"""AWS provider adapter and SigV4 health-check implementation."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import VERSION
from .images import parse_ecr_image_uri
from .models import Check

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
    result = _aws_command(root, [*args, "--output", "json"], timeout=timeout)
    if result.returncode != 0:
        return {}, result
    try:
        return json.loads(result.stdout or "{}"), result
    except json.JSONDecodeError:
        return {}, result


def compact_error(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").strip().splitlines()
    return output[-1] if output else f"Command exited with {result.returncode}."


def expected_name_prefix(cfg: dict[str, Any], env_name: str) -> str:
    return f"{cfg['project_name']}-{env_name}"


def expected_ecr_repository_name(cfg: dict[str, Any], env_name: str) -> str:
    return f"{expected_name_prefix(cfg, env_name)}-lambda-repo"


def expected_lambda_function_name(cfg: dict[str, Any], env_name: str) -> str:
    return f"{expected_name_prefix(cfg, env_name)}-lambda"


def expected_lambda_execution_role_name(cfg: dict[str, Any], env_name: str) -> str:
    return f"{expected_name_prefix(cfg, env_name)}-lambda-exec-role"


def expected_api_gateway_name(cfg: dict[str, Any], env_name: str) -> str:
    return f"{expected_name_prefix(cfg, env_name)}-http-api"


def expected_lambda_log_group_name(cfg: dict[str, Any], env_name: str) -> str:
    return f"/aws/lambda/{expected_lambda_function_name(cfg, env_name)}"


def is_resource_missing(result: subprocess.CompletedProcess[str]) -> bool:
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
    return missing_detail if is_resource_missing(result) else compact_error(result)


def collect_aws_checks(
    root: Path,
    cfg: dict[str, Any],
    env_name: str = "prod",
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    aws_json_fn: Callable[..., tuple[Any, subprocess.CompletedProcess[str]]] = _aws_json,
    aws_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _aws_command,
) -> list[Check]:
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
                "`aws` not found on PATH; skipped AWS identity, backend, ECR, Lambda, API Gateway, CloudWatch, and image checks.",
            ),
        ]

    checks.append(Check("AWS CLI", "OK", "Installed."))

    identity_payload, identity_result = aws_json_fn(root, ["sts", "get-caller-identity"])
    if identity_result.returncode != 0:
        checks.append(Check("AWS identity", "WARN", compact_error(identity_result)))
        checks.extend(
            [
                Check("State bucket", "WARN", "Cannot inspect backend bucket without valid AWS credentials."),
                Check("Lock table", "WARN", "Cannot inspect DynamoDB lock table without valid AWS credentials."),
                Check("ECR repository", "WARN", "Cannot inspect ECR repository without valid AWS credentials."),
                Check("Lambda execution role", "WARN", "Cannot inspect IAM role without valid AWS credentials."),
                Check("Lambda function", "WARN", "Cannot inspect Lambda function without valid AWS credentials."),
                Check("API Gateway", "WARN", "Cannot inspect API Gateway without valid AWS credentials."),
                Check("CloudWatch log group", "WARN", "Cannot inspect log group without valid AWS credentials."),
                Check("Configured ECR image", "WARN", "Cannot inspect configured image without valid AWS credentials."),
            ]
        )
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
                "OK" if table_result.returncode == 0 else "WARN",
                f"{lock_table} ({table_status or 'found'})"
                if table_result.returncode == 0
                else missing_or_error_detail(table_result, "DynamoDB lock table not found or not accessible."),
            )
        )

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
            "OK" if lambda_result.returncode == 0 else "WARN",
            f"{lambda_function} ({lambda_state or 'found'})"
            if lambda_result.returncode == 0
            else missing_or_error_detail(lambda_result, "Lambda function not deployed yet."),
        )
    )

    apis_payload, apis_result = aws_json_fn(root, ["apigatewayv2", "get-apis", "--region", region])
    api_detail = "API Gateway not deployed yet."
    api_status = "WARN"
    if apis_result.returncode == 0 and isinstance(apis_payload, dict):
        items = apis_payload.get("Items", [])
        if isinstance(items, list):
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

    image_uri = str(cfg["lambda_image_uri"])
    if not image_uri:
        checks.append(Check("Configured ECR image", "WARN", "Set lambda_image_uri before checking image existence."))
    else:
        image_ref = parse_ecr_image_uri(image_uri)
        if image_ref is None:
            checks.append(Check("Configured ECR image", "INFO", "Image URI is not an AWS ECR URI; existence check skipped.", scored=False))
        else:
            image_id = f"imageTag={image_ref.tag}" if image_ref.tag else f"imageDigest={image_ref.digest}"
            image_payload, image_result = aws_json_fn(
                root,
                [
                    "ecr",
                    "describe-images",
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

    return checks



def resolve_health_url(
    root: Path,
    url: str | None = None,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    run_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
) -> tuple[str, str]:
    if url:
        return url.strip(), "argument"
    if not command_exists_fn("terraform"):
        return "", "`terraform` not found on PATH and --url was not provided."
    result = run_command_fn(["terraform", "-chdir=terraform", "output", "-no-color", "-raw", "api_gateway_health_url"], root)
    if result.returncode != 0:
        return "", compact_error(result)
    return result.stdout.strip(), "terraform output api_gateway_health_url"


def aws_sigv4_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    key_date = hmac.new(("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region.encode("utf-8"), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def canonical_query_string(query: str) -> str:
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    encoded = [
        (
            urllib.parse.quote(key, safe="-_.~"),
            urllib.parse.quote(value, safe="-_.~"),
        )
        for key, value in pairs
    ]
    return "&".join(f"{key}={value}" for key, value in sorted(encoded))


def aws_sigv4_headers(url: str, region: str | None = None, now: dt.datetime | None = None) -> tuple[dict[str, str], str | None]:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    session_token = os.environ.get("AWS_SESSION_TOKEN", "")
    resolved_region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not access_key or not secret_key or not resolved_region:
        return {}, "AWS SigV4 health checks require AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION/AWS_DEFAULT_REGION."

    parsed = urllib.parse.urlparse(url)
    timestamp = now or dt.datetime.now(dt.UTC)
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = timestamp.strftime("%Y%m%d")
    service = "execute-api"
    method = "GET"
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_uri = urllib.parse.quote(parsed.path or "/", safe="/-_.~")
    canonical_query = canonical_query_string(parsed.query)
    headers = {
        "host": parsed.netloc,
        "x-amz-date": amz_date,
    }
    if session_token:
        headers["x-amz-security-token"] = session_token
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


def fetch_health_url(url: str, timeout: int = 20, aws_sigv4: bool = False, aws_region: str | None = None) -> tuple[int | None, str]:
    stripped_url = url.strip()
    parsed = urllib.parse.urlparse(stripped_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, "Health URL must be an absolute http or https URL."
    headers = {"User-Agent": f"devsecops-cli/{VERSION}"}
    if aws_sigv4:
        signed_headers, error = aws_sigv4_headers(stripped_url, region=aws_region)
        if error:
            return None, error
        headers.update(signed_headers)
    request = urllib.request.Request(stripped_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            status = int(getattr(response, "status", response.getcode()))
            preview = response.read(200).decode("utf-8", errors="replace").strip()
            return status, preview or f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc)
    except urllib.error.URLError as exc:
        return None, str(exc.reason)
    except TimeoutError:
        return None, f"Timed out after {timeout}s."


def collect_health_checks(
    root: Path,
    cfg: dict[str, Any],
    url: str | None = None,
    timeout: int = 20,
    aws_sigv4: bool = False,
    aws_region: str | None = None,
    *,
    resolve_health_fn: Callable[..., tuple[str, str]] = resolve_health_url,
    fetch_health_fn: Callable[..., tuple[int | None, str]] = fetch_health_url,
) -> list[Check]:
    health_url, source = resolve_health_fn(root, url)
    checks = [
        Check(
            "Health endpoint URL",
            "OK" if health_url else "FAIL",
            f"{health_url} ({source})" if health_url else source,
        )
    ]
    if not health_url:
        return checks
    status, detail = fetch_health_fn(health_url, timeout=timeout, aws_sigv4=aws_sigv4, aws_region=aws_region)
    ok_status = status is not None and 200 <= status < 400
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
            configuration = lambda_payload
        outputs["lambda_state"] = str(configuration.get("State") or "")
        outputs["lambda_last_update_status"] = str(configuration.get("LastUpdateStatus") or "")
        code = lambda_payload.get("Code", {})
        if isinstance(code, dict):
            outputs["lambda_image_uri"] = str(code.get("ImageUri") or "")
        outputs["lambda_image_uri"] = outputs["lambda_image_uri"] or str(configuration.get("ImageUri") or "")
        checks.append(Check("Lambda function", "OK", f"{lambda_function} ({outputs['lambda_state'] or 'found'})"))
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
    "is_resource_missing",
    "missing_or_error_detail",
    "parse_ecr_image_uri",
    "resolve_health_url",
]
