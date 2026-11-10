"""AWS provider adapter and SigV4 health-check implementation.

The CLI deliberately shells out to the AWS CLI instead of requiring an AWS SDK
during initial project setup.  Public collectors translate command results into
domain-level :class:`~devsecops_cli.models.Check` objects, while injectable
callables keep provider interaction deterministic in unit tests.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import VERSION
from .images import is_immutable_image, parse_ecr_image_uri
from .models import Check, ConfigValidationError, EcrImageRef


# Keep process execution behind small adapters so collectors can be exercised
# without depending on an installed AWS CLI or live credentials.
def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run_command(command: list[str], root: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _aws_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
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
    root: Path, image_uri: str, region: str, aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]],
) -> tuple[EcrImageRef, str, dict]:
    ref = parse_ecr_image_uri(image_uri)
    if not ref or ref.region != region or not is_immutable_image(image_uri):
        raise ConfigValidationError("An immutable ECR image in the deployment region is required.")
    image_id = f"imageDigest={ref.digest.lower()}" if ref.digest else f"imageTag={ref.tag}"
    payload, result = aws_json_fn(root, [
        "ecr", "batch-get-image", "--registry-id", ref.registry_id,
        "--repository-name", ref.repository, "--image-ids", image_id, "--region", region,
    ])
    if result.returncode != 0:
        raise ConfigValidationError(f"Cannot read image from ECR: {compact_error(result)}")
    images = payload.get("images") if isinstance(payload, dict) else None
    if not isinstance(images, list) or len(images) != 1:
        raise ConfigValidationError(f"Image is unavailable in ECR: {image_uri}")
    image = images[0]
    identity = image.get("imageId") if isinstance(image, dict) else None
    digest = identity.get("imageDigest") if isinstance(identity, dict) else None
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest) or (ref.digest and ref.digest.lower() != digest):
        raise ConfigValidationError("ECR did not return the expected image digest.")
    if image.get("registryId", ref.registry_id) != ref.registry_id or image.get("repositoryName", ref.repository) != ref.repository:
        raise ConfigValidationError("ECR returned an image from a different registry or repository.")
    return ref, digest, image


def resolve_ecr_image_digest(
    root: Path, image_uri: str, region: str, *,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]] = _aws_json,
) -> str:
    """Return the exact ECR digest, using the account that owns the referenced registry."""

    ref, digest, _ = _read_ecr_image(root, image_uri, region, aws_json_fn)
    return f"{ref.registry}/{ref.repository}@{digest}"


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
        with urllib.request.build_opener(_HttpsBlobRedirectHandler()).open(request, timeout=20) as response:
            return response.read(size + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ConfigValidationError(f"Cannot read the ECR image configuration (HTTP {exc.code}).") from None
    except (OSError, ValueError, http.client.HTTPException):
        raise ConfigValidationError("Cannot read the ECR image configuration over HTTPS.") from None


def verify_ecr_lambda_image(
    root: Path, image_uri: str, region: str, *,
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
    if not isinstance(media_type, str) or media_type not in _IMAGE_CONFIG_TYPES or "manifests" in manifest:
        raise ConfigValidationError("Use a single-platform Docker V2 or OCI image. Build for linux/amd64 with provenance disabled.")
    if "sha256:" + hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() != digest:
        raise ConfigValidationError("The ECR manifest content does not match the image digest.")
    descriptor = manifest.get("config")
    if not isinstance(descriptor, dict) or descriptor.get("mediaType") != _IMAGE_CONFIG_TYPES[media_type]:
        raise ConfigValidationError("The manifest lacks a supported container image configuration.")
    config_digest, size = descriptor.get("digest"), descriptor.get("size")
    if (not isinstance(config_digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", config_digest)
            or type(size) is not int or not 0 < size <= _MAX_IMAGE_CONFIG_BYTES):
        raise ConfigValidationError("The ECR image configuration descriptor has an invalid digest or size.")
    layers = manifest.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ConfigValidationError("The ECR image manifest has no filesystem layers.")
    layer_digest = layers[0].get("digest") if isinstance(layers[0], dict) else None
    if not isinstance(layer_digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", layer_digest):
        raise ConfigValidationError("The ECR image manifest has an invalid filesystem layer digest.")

    layer, result = aws_json_fn(root, [
        "ecr", "get-download-url-for-layer", "--registry-id", ref.registry_id,
        "--repository-name", ref.repository, "--layer-digest", layer_digest, "--region", region,
    ])
    if result.returncode != 0:
        raise ConfigValidationError(f"Cannot pull image layers from ECR: {compact_error(result)}")
    if not isinstance(layer, dict) or layer.get("layerDigest") != layer_digest or not layer.get("downloadUrl"):
        raise ConfigValidationError("ECR did not grant download access to the image layer.")
    authorization, result = aws_json_fn(root, ["ecr", "get-authorization-token", "--region", region])
    entries = authorization.get("authorizationData") if isinstance(authorization, dict) else None
    entry = entries[0] if isinstance(entries, list) and entries else None
    token = entry.get("authorizationToken") if isinstance(entry, dict) else None
    if result.returncode != 0 or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", token):
        raise ConfigValidationError("Cannot obtain an ECR authorization token. Verify credentials and ecr:GetAuthorizationToken.")
    content = _read_ecr_config(ref, config_digest, size, token)
    if len(content) != size or "sha256:" + hashlib.sha256(content).hexdigest() != config_digest:
        raise ConfigValidationError("The downloaded ECR image configuration does not match its descriptor.")
    try:
        configuration = json.loads(content)
    except ValueError:
        configuration = None
    if not isinstance(configuration, dict) or (configuration.get("os"), configuration.get("architecture")) != ("linux", "amd64"):
        raise ConfigValidationError("Lambda uses x86_64. Publish a single-platform linux/amd64 image.")
    return digest_uri


# Terraform and the CLI share this naming contract.  Centralizing it prevents
# diagnostics from drifting away from the names used by the infrastructure.
def expected_name_prefix(cfg: dict[str, Any], env_name: str) -> str:
    """Return the common Terraform resource prefix for an environment."""

    return f"{cfg['project_name']}-{env_name}"


def expected_ecr_repository_name(cfg: dict[str, Any], env_name: str) -> str:
    """Return the ECR repository name produced by the Terraform stack."""

    return f"{expected_name_prefix(cfg, env_name)}-lambda-repo"


def expected_lambda_function_name(cfg: dict[str, Any], env_name: str) -> str:
    """Return the Lambda function name produced by the Terraform stack."""

    return f"{expected_name_prefix(cfg, env_name)}-lambda"


def expected_lambda_execution_role_name(cfg: dict[str, Any], env_name: str) -> str:
    """Return the Lambda execution-role name produced by Terraform."""

    return f"{expected_name_prefix(cfg, env_name)}-lambda-exec-role"


def expected_api_gateway_name(cfg: dict[str, Any], env_name: str) -> str:
    """Return the API Gateway name produced by the Terraform stack."""

    return f"{expected_name_prefix(cfg, env_name)}-http-api"


def expected_lambda_log_group_name(cfg: dict[str, Any], env_name: str) -> str:
    """Return the conventional CloudWatch log-group name for the Lambda."""

    return f"/aws/lambda/{expected_lambda_function_name(cfg, env_name)}"


def is_resource_missing(result: subprocess.CompletedProcess[str]) -> bool:
    """Distinguish an absent AWS resource from authentication or CLI errors."""

    text = f"{result.stderr}\n{result.stdout}"
    missing_markers = [
        "NotFound",
        "NotFoundException",
        "ResourceNotFoundException",
        "RepositoryNotFoundException",
        "ImageNotFoundException",
        "NoSuchBucket",
        "ResourceNotFound",
    ]
    return any(marker in text for marker in missing_markers)


def missing_or_error_detail(result: subprocess.CompletedProcess[str], missing_detail: str) -> str:
    """Use actionable absence guidance only for recognized not-found errors."""

    return missing_detail if is_resource_missing(result) else compact_error(result)


def lambda_readiness_status(configuration: dict[str, Any]) -> str:
    """API success does not establish function or update health."""

    state = configuration.get("State")
    update = configuration.get("LastUpdateStatus")
    if state == "Failed" or update == "Failed":
        return "FAIL"
    if state != "Active" or update != "Successful":
        return "WARN"
    return "OK"


LAMBDA_NOT_DEPLOYED = "Lambda function not deployed yet."


def collect_aws_checks(
    root: Path,
    cfg: dict[str, Any],
    env_name: str = "prod",
    *,
    include_workload: bool = True,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]] = _aws_json,
    aws_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _aws_command,
) -> list[Check]:
    """Inspect the expected AWS deployment and return non-throwing diagnostics.

    The checks follow deployment dependencies: tooling and identity first,
    followed by backend and the configured image. Workload inspection is
    optional for pre-deployment checks. Provider failures are reported as
    warnings so ``doctor`` can still show all locally available information.
    """

    checks: list[Check] = []
    region = str(cfg["aws_region"])
    backend = cfg["backend"]
    backend_region = str(backend["region"])
    backend_bucket = str(backend["bucket"])
    lock_table = str(backend["lock_table"])

    ecr_repository = expected_ecr_repository_name(cfg, env_name)
    lambda_function = expected_lambda_function_name(cfg, env_name)
    lambda_execution_role = expected_lambda_execution_role_name(cfg, env_name)
    api_name = expected_api_gateway_name(cfg, env_name)
    lambda_log_group = expected_lambda_log_group_name(cfg, env_name)

    if not command_exists_fn("aws"):
        return [
            Check(
                "AWS CLI",
                "WARN",
                "`aws` not found on PATH; skipped AWS identity and resource checks.",
            ),
        ]

    checks.append(Check("AWS CLI", "OK", "Installed."))

    identity_payload, identity_result = aws_json_fn(root, ["sts", "get-caller-identity"])
    if identity_result.returncode != 0:
        # Every remaining lookup needs the same credentials.  Emit explicit
        # skipped checks instead of repeating an authentication error per API.
        checks.append(Check("AWS identity", "WARN", compact_error(identity_result)))
        checks.extend(
            [
                Check("State bucket", "WARN", "Cannot inspect backend bucket without valid AWS credentials."),
                Check("Lock table", "WARN", "Cannot inspect DynamoDB lock table without valid AWS credentials."),
                Check("Configured ECR image", "WARN", "Cannot inspect configured image without valid AWS credentials."),
            ]
        )
        if include_workload:
            checks.extend([
                Check("ECR repository", "WARN", "Cannot inspect ECR repository without valid AWS credentials."),
                Check("Lambda execution role", "WARN", "Cannot inspect IAM role without valid AWS credentials."),
                Check("Lambda function", "WARN", "Cannot inspect Lambda function without valid AWS credentials."),
                Check("API Gateway", "WARN", "Cannot inspect API Gateway without valid AWS credentials."),
                Check("CloudWatch log group", "WARN", "Cannot inspect log group without valid AWS credentials."),
            ])
        return checks
    identity_detail = str(identity_payload.get("Arn") or identity_payload.get("Account") or "AWS credentials are usable.")
    checks.append(Check("AWS identity", "OK", identity_detail))

    if not backend_bucket or backend_bucket.startswith("replace-with"):
        checks.append(Check("State bucket", "WARN", "Set backend.bucket before checking remote state."))
    else:
        bucket_result = aws_command_fn(root, ["s3api", "head-bucket", "--bucket", backend_bucket, "--region", backend_region])
        checks.append(
            Check(
                "State bucket",
                "OK" if bucket_result.returncode == 0 else "WARN",
                backend_bucket if bucket_result.returncode == 0 else missing_or_error_detail(bucket_result, "Bucket not found or not accessible."),
            )
        )

    if not lock_table:
        checks.append(Check("Lock table", "WARN", "Set backend.lock_table before checking state locking."))
    else:
        table_payload, table_result = aws_json_fn(
            root,
            ["dynamodb", "describe-table", "--table-name", lock_table, "--region", backend_region],
        )
        table_status = ""
        if isinstance(table_payload, dict):
            table = table_payload.get("Table", {})
            if isinstance(table, dict):
                table_status = str(table.get("TableStatus", ""))
        checks.append(
            Check(
                "Lock table",
                "OK" if table_result.returncode == 0 and table_status == "ACTIVE" else "WARN",
                f"{lock_table} ({table_status or 'unknown status'})"
                if table_result.returncode == 0
                else missing_or_error_detail(table_result, "DynamoDB lock table not found or not accessible."),
            )
        )

    image_uri = str(cfg["lambda_image_uri"])
    if not image_uri:
        checks.append(Check("Configured ECR image", "WARN", "Set lambda_image_uri before checking image existence."))
    else:
        image_ref = parse_ecr_image_uri(image_uri)
        if image_ref is None:
            # Non-ECR registries are valid inputs, but this adapter cannot
            # prove their image existence through AWS APIs.
            checks.append(Check("Configured ECR image", "INFO", "Image URI is not an AWS ECR URI; existence check skipped.", scored=False))
        else:
            image_id = f"imageDigest={image_ref.digest.lower()}" if image_ref.digest else f"imageTag={image_ref.tag}"
            image_payload, image_result = aws_json_fn(
                root,
                [
                    "ecr",
                    "describe-images",
                    "--registry-id",
                    image_ref.registry_id,
                    "--repository-name",
                    image_ref.repository,
                    "--image-ids",
                    image_id,
                    "--region",
                    image_ref.region,
                ],
            )
            image_details = image_payload.get("imageDetails", []) if isinstance(image_payload, dict) else []
            image_found = image_result.returncode == 0 and bool(image_details)
            if image_found:
                image_detail = image_uri
            elif image_result.returncode == 0:
                image_detail = "Configured ECR image not found."
            else:
                image_detail = missing_or_error_detail(image_result, "Configured ECR image not found.")
            checks.append(
                Check(
                    "Configured ECR image",
                    "OK" if image_found else "WARN",
                    image_detail,
                )
            )

    if not include_workload:
        return checks

    _, repo_result = aws_json_fn(
        root,
        ["ecr", "describe-repositories", "--repository-names", ecr_repository, "--region", region],
    )
    checks.append(
        Check(
            "ECR repository",
            "OK" if repo_result.returncode == 0 else "WARN",
            ecr_repository if repo_result.returncode == 0 else missing_or_error_detail(repo_result, "ECR repository not deployed yet."),
        )
    )

    role_payload, role_result = aws_json_fn(root, ["iam", "get-role", "--role-name", lambda_execution_role])
    role_arn = ""
    if isinstance(role_payload, dict):
        role = role_payload.get("Role", {})
        if isinstance(role, dict):
            role_arn = str(role.get("Arn") or "")
    checks.append(
        Check(
            "Lambda execution role",
            "OK" if role_result.returncode == 0 else "WARN",
            role_arn
            if role_result.returncode == 0 and role_arn
            else lambda_execution_role
            if role_result.returncode == 0
            else missing_or_error_detail(role_result, "Lambda execution role not deployed yet."),
        )
    )

    lambda_payload, lambda_result = aws_json_fn(
        root,
        ["lambda", "get-function-configuration", "--function-name", lambda_function, "--region", region],
    )
    lambda_state = ""
    if isinstance(lambda_payload, dict):
        lambda_state = str(lambda_payload.get("State") or lambda_payload.get("LastUpdateStatus") or "")
    checks.append(
        Check(
            "Lambda function",
            lambda_readiness_status(lambda_payload) if lambda_result.returncode == 0 and isinstance(lambda_payload, dict) else "WARN",
            f"{lambda_function} (state: {lambda_state or 'unknown'}, update: {lambda_payload.get('LastUpdateStatus') or 'unknown'})"
            if lambda_result.returncode == 0
            else missing_or_error_detail(lambda_result, LAMBDA_NOT_DEPLOYED),
        )
    )

    apis_payload, apis_result = aws_json_fn(root, ["apigatewayv2", "get-apis", "--region", region])
    api_detail = "API Gateway not deployed yet."
    api_status = "WARN"
    if apis_result.returncode == 0 and isinstance(apis_payload, dict):
        items = apis_payload.get("Items", [])
        if isinstance(items, list):
            # get-apis is a collection endpoint, so an exact name match is the
            # only evidence that this project's environment is deployed.
            match = next((item for item in items if isinstance(item, dict) and item.get("Name") == api_name), None)
            if match:
                api_status = "OK"
                api_detail = str(match.get("ApiEndpoint") or api_name)
    elif apis_result.returncode != 0:
        api_detail = compact_error(apis_result)
    checks.append(Check("API Gateway", api_status, api_detail))

    logs_payload, logs_result = aws_json_fn(
        root,
        ["logs", "describe-log-groups", "--log-group-name-prefix", lambda_log_group, "--region", region],
    )
    log_detail = "Lambda log group not deployed yet."
    log_status = "WARN"
    if logs_result.returncode == 0 and isinstance(logs_payload, dict):
        groups = logs_payload.get("logGroups", [])
        if isinstance(groups, list):
            match = next((group for group in groups if isinstance(group, dict) and group.get("logGroupName") == lambda_log_group), None)
            if match:
                retention = match.get("retentionInDays")
                log_status = "OK"
                log_detail = f"{lambda_log_group} ({retention} day retention)" if retention else lambda_log_group
    elif logs_result.returncode != 0:
        log_detail = compact_error(logs_result)
    checks.append(Check("CloudWatch log group", log_status, log_detail))

    return checks



def resolve_health_url(
    root: Path,
    url: str | None = None,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    run_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
) -> tuple[str, str]:
    """Resolve a health URL from an explicit argument or Terraform output.

    The second tuple item records either provenance or an actionable error so
    callers can present the decision without reproducing resolution logic.
    """

    if url is not None:
        return url.strip(), "argument" if url.strip() else "Health URL cannot be empty. Provide an absolute HTTP(S) URL."
    if not command_exists_fn("terraform"):
        return "", "`terraform` not found on PATH and --url was not provided."
    result = run_command_fn(["terraform", "-chdir=terraform", "output", "-no-color", "-raw", "api_gateway_health_url"], root)
    if result.returncode != 0:
        return "", compact_error(result)
    return result.stdout.strip(), "terraform output api_gateway_health_url"


def aws_sigv4_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive the scoped AWS Signature Version 4 signing key."""

    # SigV4 deliberately narrows the secret through date, region, and service
    # before producing the final request-signing key.
    key_date = hmac.new(("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
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


def aws_sigv4_headers(url: str, region: str | None = None, now: dt.datetime | None = None,
                     *, method: str = "GET", payload: bytes = b"",
                     credentials: dict[str, str] | None = None) -> tuple[dict[str, str], str | None]:
    """Build SigV4 headers for an API Gateway request (GET health by default).

    Existing callers use the standard AWS environment variables. Named-profile
    callers can supply in-memory AWS CLI process credentials without changing
    the process environment or persisting secrets.
    """

    access_key = credentials.get("AccessKeyId", "") if credentials is not None else os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_key = credentials.get("SecretAccessKey", "") if credentials is not None else os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    session_token = credentials.get("SessionToken", "") if credentials is not None else os.environ.get("AWS_SESSION_TOKEN", "")
    resolved_region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not access_key or not secret_key or not resolved_region:
        return {}, "AWS SigV4 health checks require AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION/AWS_DEFAULT_REGION."

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


def health_url_error(url: str) -> str | None:
    """Validate URL input before constructing a request or signing headers."""

    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in url):
        return "Invalid health URL. Whitespace, control characters and backslashes are not allowed."
    try:
        parsed = urllib.parse.urlparse(url)
        host, port = parsed.hostname, parsed.port
        url.encode("ascii")
    except (ValueError, UnicodeError):
        return "Invalid health URL. Use an absolute HTTP(S) URL with a valid host and port; encode non-ASCII characters."
    if parsed.scheme not in {"http", "https"} or not host:
        return "Health URL must be an absolute http or https URL with a hostname."
    if parsed.username is not None or parsed.password is not None:
        return "Health URL must not contain user information."
    bracket_suffix = parsed.netloc.partition("]")[2] if parsed.netloc.startswith("[") else ""
    if (bracket_suffix and not re.fullmatch(r":\d+", bracket_suffix)) or parsed.netloc.endswith(":"):
        return "Invalid health URL. Use a valid hostname and optional numeric port."
    if port is not None and not 1 <= port <= 65535:
        return "Invalid health URL port. Use a port between 1 and 65535."
    return None


def fetch_health_url(
    url: str,
    timeout: int = 20,
    aws_sigv4: bool = False,
    aws_region: str | None = None,
    *,
    trusted_host: str | None = None,
    allow_redirects: bool = False,
) -> tuple[int | None, str]:
    """Fetch a health endpoint and return its status plus a short detail.

    Network failures use ``None`` for the status, whereas HTTP error responses
    preserve their numeric status so readiness reporting can distinguish them.
    """

    if type(timeout) is not int or timeout <= 0:
        return None, "Health timeout must be a positive number of seconds."
    stripped_url = url.strip()
    error = health_url_error(stripped_url)
    if error:
        return None, error
    parsed = urllib.parse.urlparse(stripped_url)
    if trusted_host is not None and not aws_sigv4:
        return None, "--trusted-host requires --aws-sigv4."

    try:
        request = urllib.request.Request(stripped_url, headers={"User-Agent": f"devsecops-cli/{VERSION}"})
    except (ValueError, UnicodeError, http.client.InvalidURL):
        return None, "Invalid health URL. Provide a valid absolute HTTP(S) URL."
    open_url = urllib.request.urlopen
    if aws_sigv4:
        if parsed.scheme != "https":
            return None, "AWS SigV4 health checks require HTTPS."
        host = parsed.hostname or ""
        if (
            not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z][a-z0-9-]*", host)
            or parsed.netloc.lower() not in {host, f"{host}:443"}
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in stripped_url)
        ):
            return None, "AWS SigV4 health checks require a DNS hostname on port 443 without URL user information."
        if trusted_host is not None:
            if host != trusted_host.lower():
                return None, "The health URL hostname must exactly match --trusted-host."
        elif not re.fullmatch(r"[a-z0-9-]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?", host):
            return None, "Use an API Gateway hostname or explicitly allow your custom domain with --trusted-host HOST."

        signed_headers, error = aws_sigv4_headers(stripped_url, region=aws_region)
        if error:
            return None, error
        for name, value in signed_headers.items():
            request.add_unredirected_header(name, value)
    if aws_sigv4 or not allow_redirects:
        open_url = urllib.request.build_opener(_NoRedirectResponseProcessor()).open
    try:
        with open_url(request, timeout=timeout) as response:
            # The URL is restricted to HTTP(S) above; only a small response
            # preview is retained to keep CLI output bounded.
            status = response.getcode()
            if (aws_sigv4 or not allow_redirects) and 300 <= status < 400:
                prefix = "Signed health checks" if aws_sigv4 else "Health checks"
                return status, f"{prefix} reject HTTP redirects. Use the final HTTPS endpoint."
            preview = response.read(200).decode("utf-8", errors="replace").strip()
            return status, preview or f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        with exc:
            return int(exc.code), str(exc)
    except urllib.error.URLError as exc:
        return None, str(exc.reason)
    except TimeoutError:
        return None, f"Timed out after {timeout}s."
    except (ValueError, UnicodeError, http.client.InvalidURL):
        return None, "Invalid health URL. Provide a valid absolute HTTP(S) URL."


def collect_health_checks(
    root: Path,
    cfg: dict[str, Any],
    url: str | None = None,
    timeout: int = 20,
    aws_sigv4: bool = False,
    aws_region: str | None = None,
    *,
    trusted_host: str | None = None,
    resolve_health_fn: Callable[..., tuple[str, str]] = resolve_health_url,
    fetch_health_fn: Callable[..., tuple[int | None, str]] = fetch_health_url,
) -> list[Check]:
    """Resolve and probe the workload health endpoint as readiness checks."""

    health_url, source = resolve_health_fn(root, url)
    url_error = health_url_error(health_url) if health_url else None
    checks = [
        Check(
            "Health endpoint URL",
            "OK" if health_url and not url_error else "FAIL",
            url_error or (f"{health_url} ({source})" if health_url else source),
        )
    ]
    if not health_url or url_error:
        return checks
    status, detail = fetch_health_fn(health_url, timeout=timeout, aws_sigv4=aws_sigv4, aws_region=aws_region, trusted_host=trusted_host)
    ok_status = status is not None and 200 <= status < 300
    checks.append(
        Check(
            "Health response",
            "OK" if ok_status else "FAIL",
            f"HTTP {status}: {detail}" if status is not None else detail,
        )
    )
    return checks



def inspect_aws_outputs(
    root: Path,
    cfg: dict[str, Any],
    env_name: str = "prod",
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]] = _aws_json,
) -> tuple[dict[str, str], list[Check]]:
    """Return deployed AWS values together with diagnostics for partial data.

    The output mapping always has the same keys.  Values remain empty when a
    resource cannot be inspected, allowing text and JSON presenters to consume
    partial results without branching on payload shape.
    """

    region = str(cfg["aws_region"])
    lambda_function = expected_lambda_function_name(cfg, env_name)
    api_name = expected_api_gateway_name(cfg, env_name)
    lambda_log_group = expected_lambda_log_group_name(cfg, env_name)
    outputs = {
        "environment": env_name,
        "aws_region": region,
        "lambda_function_name": lambda_function,
        "lambda_state": "",
        "lambda_last_update_status": "",
        "lambda_image_uri": "",
        "api_gateway_name": api_name,
        "api_gateway_invoke_url": "",
        "api_gateway_health_url": "",
        "cloudwatch_log_group": lambda_log_group,
        "cloudwatch_retention_days": "",
    }
    checks: list[Check] = []

    if not command_exists_fn("aws"):
        checks.append(Check("AWS CLI", "WARN", "`aws` not found on PATH."))
        checks.append(Check("AWS outputs", "WARN", "Cannot inspect deployed outputs without AWS CLI."))
        return outputs, checks

    checks.append(Check("AWS CLI", "OK", "Installed."))
    identity_payload, identity_result = aws_json_fn(root, ["sts", "get-caller-identity"])
    if identity_result.returncode != 0:
        checks.append(Check("AWS identity", "WARN", compact_error(identity_result)))
        checks.append(Check("AWS outputs", "WARN", "Cannot inspect deployed outputs without valid AWS credentials."))
        return outputs, checks
    checks.append(Check("AWS identity", "OK", str(identity_payload.get("Arn") or identity_payload.get("Account") or "AWS credentials are usable.")))

    lambda_payload, lambda_result = aws_json_fn(root, ["lambda", "get-function", "--function-name", lambda_function, "--region", region])
    if lambda_result.returncode == 0 and isinstance(lambda_payload, dict):
        configuration = lambda_payload.get("Configuration", {})
        if not isinstance(configuration, dict):
            # Some test doubles and older response shapes expose configuration
            # fields at the top level, so retain that compatible fallback.
            configuration = lambda_payload
        outputs["lambda_state"] = str(configuration.get("State") or "")
        outputs["lambda_last_update_status"] = str(configuration.get("LastUpdateStatus") or "")
        code = lambda_payload.get("Code", {})
        if isinstance(code, dict):
            outputs["lambda_image_uri"] = resolved_lambda_image_uri(lambda_payload) or str(code.get("ImageUri") or "")
        outputs["lambda_image_uri"] = outputs["lambda_image_uri"] or str(configuration.get("ImageUri") or "")
        checks.append(Check("Lambda function", lambda_readiness_status(configuration),
                            f"{lambda_function} (state: {outputs['lambda_state'] or 'unknown'}, update: {outputs['lambda_last_update_status'] or 'unknown'})"))
    else:
        checks.append(Check("Lambda function", "WARN", missing_or_error_detail(lambda_result, "Lambda function not deployed yet.")))

    apis_payload, apis_result = aws_json_fn(root, ["apigatewayv2", "get-apis", "--region", region])
    if apis_result.returncode == 0 and isinstance(apis_payload, dict):
        items = apis_payload.get("Items", [])
        match = None
        if isinstance(items, list):
            match = next((item for item in items if isinstance(item, dict) and item.get("Name") == api_name), None)
        if match:
            endpoint = str(match.get("ApiEndpoint") or "")
            outputs["api_gateway_invoke_url"] = endpoint
            outputs["api_gateway_health_url"] = endpoint.rstrip("/") + "/health" if endpoint else ""
            checks.append(Check("API Gateway", "OK", endpoint or api_name))
        else:
            checks.append(Check("API Gateway", "WARN", "API Gateway not deployed yet."))
    else:
        checks.append(Check("API Gateway", "WARN", compact_error(apis_result)))

    logs_payload, logs_result = aws_json_fn(
        root,
        ["logs", "describe-log-groups", "--log-group-name-prefix", lambda_log_group, "--region", region],
    )
    if logs_result.returncode == 0 and isinstance(logs_payload, dict):
        groups = logs_payload.get("logGroups", [])
        match = None
        if isinstance(groups, list):
            match = next((group for group in groups if isinstance(group, dict) and group.get("logGroupName") == lambda_log_group), None)
        if match:
            retention = match.get("retentionInDays")
            outputs["cloudwatch_retention_days"] = str(retention or "")
            checks.append(Check("CloudWatch log group", "OK", lambda_log_group))
        else:
            checks.append(Check("CloudWatch log group", "WARN", "Lambda log group not deployed yet."))
    else:
        checks.append(Check("CloudWatch log group", "WARN", compact_error(logs_result)))

    return outputs, checks


def resolved_lambda_image_uri(payload: Any) -> str:
    code = payload.get("Code") if isinstance(payload, dict) else None
    image_uri = code.get("ResolvedImageUri") if isinstance(code, dict) else None
    ref = parse_ecr_image_uri(image_uri)
    return image_uri if ref and ref.digest else ""


def inspect_active_lambda_image(
    root: Path,
    cfg: dict[str, Any],
    env_name: str = "prod",
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]] = _aws_json,
) -> tuple[str, str | None]:
    """Return the deployed Lambda image without making AWS credentials mandatory.

    The GitHub workflow is the deployment authority.  Local AWS inspection is
    best-effort metadata used to make a later manual rollback ergonomic.
    """

    if not command_exists_fn("aws"):
        return "", "`aws` not found on PATH; previous image cannot be recorded locally."
    function_name = expected_lambda_function_name(cfg, env_name)
    payload, result = aws_json_fn(
        root,
        ["lambda", "get-function", "--function-name", function_name, "--region", str(cfg["aws_region"])],
    )
    if result.returncode != 0:
        if is_resource_missing(result):
            return "", None
        return "", compact_error(result)
    if not isinstance(payload, dict):
        return "", "Could not parse the deployed Lambda image from AWS."
    image_uri = resolved_lambda_image_uri(payload)
    if not image_uri:
        return "", "The deployed Lambda function did not report a resolved ECR image digest."
    return image_uri, None



__all__ = [
    "aws_sigv4_headers",
    "aws_sigv4_signing_key",
    "canonical_query_string",
    "collect_aws_checks",
    "collect_health_checks",
    "expected_api_gateway_name",
    "expected_ecr_repository_name",
    "expected_lambda_execution_role_name",
    "expected_lambda_function_name",
    "expected_lambda_log_group_name",
    "expected_name_prefix",
    "fetch_health_url",
    "inspect_aws_outputs",
    "inspect_active_lambda_image",
    "is_resource_missing",
    "missing_or_error_detail",
    "parse_ecr_image_uri",
    "resolve_ecr_image_digest",
    "verify_ecr_lambda_image",
    "resolve_health_url",
]
