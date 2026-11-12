"""ECR validation, account capacity and SigV4 adapters for AWS deployment."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .images import is_immutable_image, parse_ecr_image_uri
from .lambda_capacity import DEFAULT_RESERVED_EXECUTIONS, evaluate_capacity
from .models import ConfigValidationError, EcrImageRef


def _run_command(
    command: list[str], root: Path, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _aws_command(
    root: Path, args: list[str], timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    return _run_command(["aws", *args], root, timeout=timeout)


def _aws_json(
    root: Path,
    args: list[str],
    timeout: int = 30,
) -> tuple[Any, subprocess.CompletedProcess[str]]:
    """Run an AWS CLI command and retain its process result beside parsed JSON.

    Parse failures intentionally return an empty payload without hiding the
    original result; callers can still classify and report the provider error.
    """

    result = _aws_command(root, [*args, "--output", "json"], timeout=timeout)
    if result.returncode != 0:
        return {}, result
    try:
        return json.loads(result.stdout or "{}"), result
    except json.JSONDecodeError:
        return {}, result


def compact_error(result: subprocess.CompletedProcess[str]) -> str:
    """Return the most useful final output line from a failed command."""

    output = (result.stderr or result.stdout or "").strip().splitlines()
    return output[-1] if output else f"Command exited with {result.returncode}."


def _read_ecr_image(
    root: Path,
    image_uri: str,
    region: str,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]],
) -> tuple[EcrImageRef, str, dict]:
    ref = parse_ecr_image_uri(image_uri)
    if not ref or ref.region != region or not is_immutable_image(image_uri):
        raise ConfigValidationError("An immutable ECR image in the deployment region is required.")
    image_id = f"imageDigest={ref.digest.lower()}" if ref.digest else f"imageTag={ref.tag}"
    payload, result = aws_json_fn(
        root,
        [
            "ecr",
            "batch-get-image",
            "--registry-id",
            ref.registry_id,
            "--repository-name",
            ref.repository,
            "--image-ids",
            image_id,
            "--region",
            region,
        ],
    )
    if result.returncode != 0:
        raise ConfigValidationError(f"Cannot read image from ECR: {compact_error(result)}")
    images = payload.get("images") if isinstance(payload, dict) else None
    if not isinstance(images, list) or len(images) != 1:
        raise ConfigValidationError(f"Image is unavailable in ECR: {image_uri}")
    image = images[0]
    identity = image.get("imageId") if isinstance(image, dict) else None
    digest = identity.get("imageDigest") if isinstance(identity, dict) else None
    if (
        not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
        or (ref.digest and ref.digest.lower() != digest)
    ):
        raise ConfigValidationError("ECR did not return the expected image digest.")
    if (
        image.get("registryId", ref.registry_id) != ref.registry_id
        or image.get("repositoryName", ref.repository) != ref.repository
    ):
        raise ConfigValidationError(
            "ECR returned an image from a different registry or repository."
        )
    return ref, digest, image


_IMAGE_CONFIG_TYPES = {
    "application/vnd.docker.distribution.manifest.v2+json": "application/vnd.docker.container.image.v1+json",
    "application/vnd.oci.image.manifest.v1+json": "application/vnd.oci.image.config.v1+json",
}


_MAX_IMAGE_CONFIG_BYTES = 4 * 1024 * 1024


class _HttpsBlobRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ConfigValidationError("ECR redirected the image configuration outside HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_ecr_config(ref: EcrImageRef, digest: str, size: int, token: str) -> bytes:
    url = f"https://{ref.registry}/v2/{ref.repository}/blobs/{digest}"
    request = urllib.request.Request(url)
    # ECR can redirect blob downloads to presigned URLs. Keep Basic auth on
    # the original registry request, including when a redirect fails.
    request.add_unredirected_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.build_opener(_HttpsBlobRedirectHandler()).open(
            request, timeout=20
        ) as response:
            return response.read(size + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ConfigValidationError(
            f"Cannot read the ECR image configuration (HTTP {exc.code})."
        ) from None
    except (OSError, ValueError, http.client.HTTPException):
        raise ConfigValidationError("Cannot read the ECR image configuration over HTTPS.") from None


def verify_ecr_lambda_image(
    root: Path,
    image_uri: str,
    region: str,
    *,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]] = _aws_json,
) -> str:
    """Verify a pullable single-platform image for the kit's x86_64 Lambda."""

    ref, digest, image = _read_ecr_image(root, image_uri, region, aws_json_fn)
    digest_uri = f"{ref.registry}/{ref.repository}@{digest}"
    if ref.tag:
        # ECR may translate manifests requested by tag. Verify the exact
        # stored object after resolving the tag once.
        _, _, image = _read_ecr_image(root, digest_uri, region, aws_json_fn)
    manifest_text = image.get("imageManifest")
    try:
        manifest = json.loads(manifest_text)
    except (TypeError, ValueError):
        manifest = None
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
        raise ConfigValidationError("ECR did not return a version 2 image manifest.")
    media_type = manifest.get("mediaType") or image.get("imageManifestMediaType")
    if (
        not isinstance(media_type, str)
        or media_type not in _IMAGE_CONFIG_TYPES
        or "manifests" in manifest
    ):
        raise ConfigValidationError(
            "Use a single-platform Docker V2 or OCI image. Build for linux/amd64 with provenance disabled."
        )
    if "sha256:" + hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() != digest:
        raise ConfigValidationError("The ECR manifest content does not match the image digest.")
    descriptor = manifest.get("config")
    if (
        not isinstance(descriptor, dict)
        or descriptor.get("mediaType") != _IMAGE_CONFIG_TYPES[media_type]
    ):
        raise ConfigValidationError("The manifest lacks a supported container image configuration.")
    config_digest, size = descriptor.get("digest"), descriptor.get("size")
    if (
        not isinstance(config_digest, str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", config_digest)
        or type(size) is not int
        or not 0 < size <= _MAX_IMAGE_CONFIG_BYTES
    ):
        raise ConfigValidationError(
            "The ECR image configuration descriptor has an invalid digest or size."
        )
    layers = manifest.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ConfigValidationError("The ECR image manifest has no filesystem layers.")
    layer_digest = layers[0].get("digest") if isinstance(layers[0], dict) else None
    if not isinstance(layer_digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", layer_digest):
        raise ConfigValidationError(
            "The ECR image manifest has an invalid filesystem layer digest."
        )

    layer, result = aws_json_fn(
        root,
        [
            "ecr",
            "get-download-url-for-layer",
            "--registry-id",
            ref.registry_id,
            "--repository-name",
            ref.repository,
            "--layer-digest",
            layer_digest,
            "--region",
            region,
        ],
    )
    if result.returncode != 0:
        raise ConfigValidationError(f"Cannot pull image layers from ECR: {compact_error(result)}")
    if (
        not isinstance(layer, dict)
        or layer.get("layerDigest") != layer_digest
        or not layer.get("downloadUrl")
    ):
        raise ConfigValidationError("ECR did not grant download access to the image layer.")
    authorization, result = aws_json_fn(
        root, ["ecr", "get-authorization-token", "--region", region]
    )
    entries = authorization.get("authorizationData") if isinstance(authorization, dict) else None
    entry = entries[0] if isinstance(entries, list) and entries else None
    token = entry.get("authorizationToken") if isinstance(entry, dict) else None
    if (
        result.returncode != 0
        or not isinstance(token, str)
        or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", token)
    ):
        raise ConfigValidationError(
            "Cannot obtain an ECR authorization token. Verify credentials and ecr:GetAuthorizationToken."
        )
    content = _read_ecr_config(ref, config_digest, size, token)
    if len(content) != size or "sha256:" + hashlib.sha256(content).hexdigest() != config_digest:
        raise ConfigValidationError(
            "The downloaded ECR image configuration does not match its descriptor."
        )
    try:
        configuration = json.loads(content)
    except ValueError:
        configuration = None
    if not isinstance(configuration, dict) or (
        configuration.get("os"),
        configuration.get("architecture"),
    ) != ("linux", "amd64"):
        raise ConfigValidationError(
            "Lambda uses x86_64. Publish a single-platform linux/amd64 image."
        )
    return digest_uri


def get_lambda_capacity(
    root: Path,
    function: str,
    region: str,
    requested: int = DEFAULT_RESERVED_EXECUTIONS,
    *,
    allow_unreserved: bool = False,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]] = _aws_json,
) -> dict[str, Any]:
    """Read account limits and the selected function's current reservation."""
    account, result = aws_json_fn(root, ["lambda", "get-account-settings", "--region", region])
    if result.returncode:
        raise ConfigValidationError(
            "Cannot inspect Lambda account capacity (lambda:GetAccountSettings): "
            + compact_error(result)
        )
    current, result = aws_json_fn(
        root,
        ["lambda", "get-function-concurrency", "--function-name", function, "--region", region],
    )
    if result.returncode:
        if "ResourceNotFoundException" not in (result.stderr or ""):
            raise ConfigValidationError(
                "Cannot inspect function reservation (lambda:GetFunctionConcurrency): "
                + compact_error(result)
            )
        current = {}
    if not isinstance(current, dict):
        raise ConfigValidationError("AWS returned invalid function concurrency data.")
    report = evaluate_capacity(
        account.get("AccountLimit") if isinstance(account, dict) else None,
        requested,
        current.get("ReservedConcurrentExecutions", 0),
        allow_unreserved=allow_unreserved,
    )
    return {**report, "function_name": function, "region": region}


def aws_sigv4_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive the scoped AWS Signature Version 4 signing key."""

    # SigV4 deliberately narrows the secret through date, region, and service
    # before producing the final request-signing key.
    key_date = hmac.new(
        ("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256
    ).digest()
    key_region = hmac.new(key_date, region.encode("utf-8"), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def canonical_query_string(query: str) -> str:
    """Encode and sort query parameters according to SigV4 canonical rules."""

    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    encoded = [
        (
            urllib.parse.quote(key, safe="-_.~"),
            urllib.parse.quote(value, safe="-_.~"),
        )
        for key, value in pairs
    ]
    return "&".join(f"{key}={value}" for key, value in sorted(encoded))


def aws_sigv4_headers(
    url: str,
    region: str | None = None,
    now: dt.datetime | None = None,
    *,
    method: str = "GET",
    payload: bytes = b"",
    credentials: dict[str, str] | None = None,
) -> tuple[dict[str, str], str | None]:
    """Build SigV4 headers for an API Gateway request (GET health by default).

    Existing callers use the standard AWS environment variables. Named-profile
    callers can supply in-memory AWS CLI process credentials without changing
    the process environment or persisting secrets.
    """

    access_key = (
        credentials.get("AccessKeyId", "")
        if credentials is not None
        else os.environ.get("AWS_ACCESS_KEY_ID", "")
    )
    secret_key = (
        credentials.get("SecretAccessKey", "")
        if credentials is not None
        else os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    )
    session_token = (
        credentials.get("SessionToken", "")
        if credentials is not None
        else os.environ.get("AWS_SESSION_TOKEN", "")
    )
    resolved_region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not access_key or not secret_key or not resolved_region:
        return (
            {},
            "AWS SigV4 health checks require AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION/AWS_DEFAULT_REGION.",
        )

    parsed = urllib.parse.urlparse(url)
    timestamp = now or dt.datetime.now(dt.UTC)
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = timestamp.strftime("%Y%m%d")
    service = "execute-api"
    payload_hash = hashlib.sha256(payload).hexdigest()
    canonical_uri = urllib.parse.quote(parsed.path or "/", safe="/-_.~")
    canonical_query = canonical_query_string(parsed.query)
    headers = {
        "host": parsed.netloc,
        "x-amz-date": amz_date,
    }
    if session_token:
        headers["x-amz-security-token"] = session_token
    # Both header names and query parameters must be sorted before hashing;
    # changing this ordering produces a signature AWS cannot verify.
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{resolved_region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        aws_sigv4_signing_key(secret_key, date_stamp, resolved_region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    request_headers = {
        "Authorization": authorization,
        "X-Amz-Date": amz_date,
    }
    if session_token:
        request_headers["X-Amz-Security-Token"] = session_token
    return request_headers, None


class _NoRedirectResponseProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request, response):
        # Return redirects before urllib parses Location or opens another URL.
        if 300 <= response.code < 400:
            return response
        return super().http_response(request, response)

    https_response = http_response
