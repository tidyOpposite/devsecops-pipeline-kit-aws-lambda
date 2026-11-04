"""Capture and restore the Lambda image in the protected production workflow."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .aws import _aws_command, _aws_json, compact_error, fetch_health_url, resolve_ecr_image_digest, resolved_lambda_image_uri
from .images import parse_ecr_image_uri
from .models import ConfigValidationError

LAMBDA_RESOURCE = "module.lambda.aws_lambda_function.workload"


class RecoveryError(Exception):
    """The workflow cannot establish or restore a verified recovery point."""


@dataclass(frozen=True)
class LambdaImage:
    digest_uri: str
    configured_uri: str
    arn: str
    revision: str
    state: str
    update_status: str


def lambda_image(root: Path, function: str, region: str) -> LambdaImage | None:
    payload, result = _aws_json(root, ["lambda", "get-function", "--function-name", function, "--region", region])
    if result.returncode != 0:
        if re.search(r"\(ResourceNotFoundException\) when calling the GetFunction operation", result.stderr or ""):
            return None
        raise RecoveryError(f"Cannot read the current Lambda image: {compact_error(result)}")
    digest = resolved_lambda_image_uri(payload)
    ref = parse_ecr_image_uri(digest)
    configuration = payload.get("Configuration") if isinstance(payload, dict) else None
    if not ref or not ref.digest or ref.region != region or not isinstance(configuration, dict):
        raise RecoveryError("Lambda did not report a valid resolved image digest and revision in the deployment region.")
    arn, revision = configuration.get("FunctionArn"), configuration.get("RevisionId")
    if not arn or not revision:
        raise RecoveryError("Lambda did not report a function ARN and revision.")
    return LambdaImage(digest, payload["Code"].get("ImageUri", ""), arn, revision,
                       configuration.get("State", ""), configuration.get("LastUpdateStatus", ""))


def terraform(root: Path, *args: str) -> str:
    directory = os.environ.get("TF_WORKING_DIR", "terraform")
    result = subprocess.run(["terraform", f"-chdir={directory}", *args], cwd=root, text=True,
                            capture_output=True, timeout=180, check=False)
    if result.returncode != 0:
        raise RecoveryError(f"Terraform {args[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def recovery_state(root: Path, function: str, function_arn: str) -> dict[str, str]:
    state = json.loads(terraform(root, "show", "-json")).get("values", {})
    modules = state.get("root_module", {}).get("child_modules", [])
    tracked = next((resource.get("values", {}) for module in modules if module.get("address") == "module.lambda"
                    for resource in module.get("resources", []) if resource.get("address") == LAMBDA_RESOURCE), {})
    outputs = state.get("outputs", {})
    tracked_name = outputs.get("lambda_function_name", {}).get("value")
    if not function_arn and not tracked and not tracked_name:
        return {}
    if not function_arn or tracked_name != function or tracked.get("arn") != function_arn:
        raise RecoveryError("The live Lambda and the selected Terraform workspace disagree. Resolve state drift before deploying.")
    health_url = outputs.get("api_gateway_health_url", {}).get("value")
    auth_type = outputs.get("api_gateway_authorization_type", {}).get("value")
    if not isinstance(health_url, str) or not health_url.startswith("https://") or auth_type not in {"AWS_IAM", "NONE"}:
        raise RecoveryError("Terraform state does not contain an HTTPS health endpoint and authorization mode for recovery.")
    return {"health_url": health_url, "auth_type": auth_type}


def restore(root: Path, function: str, function_arn: str, image_uri: str, region: str, health_url: str, auth_type: str,
            *, expected_revision: str = "") -> None:
    target = resolve_ecr_image_digest(root, image_uri, region)
    current = lambda_image(root, function, region)
    if current is None or current.arn != function_arn:
        raise RecoveryError("The original Lambda is unavailable. Image rollback requires the same function ARN.")
    if current.digest_uri != target or current.configured_uri != target:
        if expected_revision and current.revision != expected_revision:
            raise RecoveryError("Lambda changed after recovery capture. Start a new rollback with the updated state.")
        result = _aws_command(root, [
            "lambda", "update-function-code", "--function-name", function_arn, "--image-uri", target,
            "--revision-id", current.revision, "--region", region,
        ])
        if result.returncode != 0:
            raise RecoveryError(f"Lambda image update failed: {compact_error(result)}")

    result = _aws_command(root, ["lambda", "wait", "function-updated", "--function-name", function_arn,
                                 "--region", region], timeout=330)
    if result.returncode != 0:
        raise RecoveryError(f"Lambda did not finish the rollback update: {compact_error(result)}")
    active = lambda_image(root, function, region)
    if (not active or active.arn != function_arn or active.digest_uri != target or active.configured_uri != target
            or active.state != "Active" or active.update_status != "Successful"):
        raise RecoveryError("Lambda did not report the restored digest as active and successful.")

    terraform(root, "apply", "-refresh-only", f"-target={LAMBDA_RESOURCE}",
              "-auto-approve", "-input=false", "-no-color", "-lock-timeout=60s", f"-var=lambda_image_uri={target}")
    if terraform(root, "output", "-raw", "lambda_current_image_uri") != target:
        raise RecoveryError("Terraform state did not record the restored Lambda digest.")

    status, detail = fetch_health_url(health_url, aws_sigv4=auth_type == "AWS_IAM", aws_region=region, allow_redirects=False)
    if status is None or not 200 <= status < 300:
        detail = f"HTTP {status}: {detail}" if status is not None else detail
        raise RecoveryError(f"Image restored and recorded in Terraform, but /health failed: {detail}")
    print(f"Verified Lambda recovery: {target}, Terraform state matches, /health returned HTTP {status}.")


def write_actions_values(path: str, values: dict[str, str]) -> None:
    if any("\n" in value or "\r" in value for value in values.values()):
        raise RecoveryError("Recovery metadata contains a line break.")
    with open(path, "a", encoding="utf-8") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in values.items())


def main() -> int:
    root = Path.cwd()
    env = os.environ
    try:
        command = sys.argv[1]
        if command == "capture":
            function = f"{env['PROJECT_NAME']}-{env['DEPLOY_ENVIRONMENT']}-lambda"
            current = lambda_image(root, function, env["AWS_REGION"])
            if env["DEPLOY_MODE"] == "rollback" and current is None:
                raise RecoveryError("Lambda is missing. Manual rollback requires an existing function.")
            resolve_ecr_image_digest(root, env["LAMBDA_IMAGE_URI"], env["AWS_REGION"])
            previous = current.digest_uri if current else ""
            if previous and env["DEPLOY_MODE"] == "deploy":
                resolve_ecr_image_digest(root, previous, env["AWS_REGION"])
            write_actions_values(env["GITHUB_OUTPUT"], {
                "function_name": function, "function_arn": current.arn if current else "",
                "revision_id": current.revision if current else "", "previous_image_uri": previous,
            })
            print(f"Previous Lambda digest: {previous or '(first deployment)'}")
        elif command == "state":
            state = recovery_state(root, env["RECOVERY_FUNCTION_NAME"], env["RECOVERY_FUNCTION_ARN"])
            write_actions_values(env["GITHUB_OUTPUT"], state)
        elif command == "restore":
            restore(root, env["RECOVERY_FUNCTION_NAME"], env["RECOVERY_FUNCTION_ARN"], env["RECOVERY_IMAGE_URI"],
                    env["AWS_REGION"], env["RECOVERY_HEALTH_URL"], env["RECOVERY_AUTH_TYPE"],
                    expected_revision=env.get("RECOVERY_REVISION_ID", ""))
        else:
            raise RecoveryError(f"Unknown recovery operation: {command}")
    except (RecoveryError, ConfigValidationError, OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, IndexError) as exc:
        print(f"Lambda recovery: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
