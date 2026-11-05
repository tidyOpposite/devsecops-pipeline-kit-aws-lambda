"""Verify the separate GitHub OIDC roles without applying infrastructure."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

from .aws import _aws_json
from .github import production_environment_check
from .models import ConfigValidationError
from .setup import iam_role_identity, is_iam_role_arn
from .workflow import decode_pipeline_config


def role_fingerprint(role_arn: str) -> str:
    return hashlib.sha256(":".join(iam_role_identity(role_arn)).encode("utf-8")).hexdigest()


def validate_role_settings(role: str, environment: dict[str, str]) -> str:
    if environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or environment.get("GITHUB_REF") != "refs/heads/main":
        raise ConfigValidationError("OIDC verification requires a manual run from main.")
    arn = environment.get("EXPECTED_ROLE_ARN", "").strip()
    if not is_iam_role_arn(arn):
        raise ConfigValidationError(f"Configure a valid IAM {role} role ARN in the workflow's secret scope.")
    if role == "deploy":
        plan = environment.get("PLAN_ROLE_FINGERPRINT", "")
        if not re.fullmatch(r"[a-f0-9]{64}", plan) or role_fingerprint(arn) == plan:
            raise ConfigValidationError("The verified plan and production deploy roles must be different.")
    return arn


def verify_identity(role_arn: str, identity: dict) -> None:
    partition, account = role_arn.split(":")[1], role_arn.split(":")[4]
    role_name = role_arn.rsplit("/", 1)[1]
    expected = rf"arn:{re.escape(partition)}:sts::{account}:assumed-role/{re.escape(role_name)}/[^/]+"
    if not isinstance(identity, dict) or identity.get("Account") != account or not re.fullmatch(expected, str(identity.get("Arn") or ""), re.IGNORECASE):
        raise ConfigValidationError("The AWS session does not match the intended OIDC role and account.")


def main() -> int:
    try:
        operation, role = sys.argv[1:]
        if operation not in {"settings", "prepare", "verify"} or role not in {"plan", "deploy"}:
            raise ConfigValidationError("Use prepare/verify with plan/deploy.")
        arn = validate_role_settings(role, os.environ)
        if operation == "settings":
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
                handle.write(f"role_fingerprint={role_fingerprint(arn)}\n")
            return 0
        if operation == "prepare":
            cfg = decode_pipeline_config(os.environ.get("PIPELINE_CONFIG_JSON", ""))
            if role == "deploy":
                protection = production_environment_check(Path.cwd(), os.environ["GITHUB_REPOSITORY"])
                if protection.status != "OK":
                    raise ConfigValidationError(protection.detail)
            with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as handle:
                handle.write(f"AWS_REGION={cfg['aws_region']}\n")
        else:
            identity, result = _aws_json(Path.cwd(), ["sts", "get-caller-identity"])
            if result.returncode != 0:
                raise ConfigValidationError("Cannot verify the assumed AWS identity.")
            verify_identity(arn, identity)
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
                handle.write(f"role_fingerprint={role_fingerprint(arn)}\n")
            print(f"Verified {role} OIDC identity and expected AWS account.")
    except (ConfigValidationError, OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
