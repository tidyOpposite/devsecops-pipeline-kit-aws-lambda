"""Guard and prepare the explicit, isolated AWS runtime acceptance workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .aws import _aws_json, verify_ecr_lambda_image
from .config import AWS_REGION_RE
from .github import protected_environment_check
from .images import parse_ecr_image_uri
from .setup import is_iam_role_arn


def settings(environment: dict[str, str]) -> dict:
    if environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or environment.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Cloud acceptance requires manual dispatch from main.")
    if environment.get("ENABLE_CLOUD_ACCEPTANCE") != "true":
        raise ValueError("Set ENABLE_CLOUD_ACCEPTANCE=true only for the final sandbox acceptance.")
    sandbox = environment.get("ACCEPTANCE_AWS_ACCOUNT_ID", "")
    production = environment.get("PRODUCTION_AWS_ACCOUNT_ID", "")
    if not re.fullmatch(r"[0-9]{12}", sandbox) or not re.fullmatch(r"[0-9]{12}", production) or sandbox == production:
        raise ValueError("Independently confirm distinct sandbox and production AWS account IDs.")
    role = environment.get("AWS_ACCEPTANCE_ROLE_ARN", "")
    if not is_iam_role_arn(role) or role.split(":")[4] != sandbox:
        raise ValueError("The acceptance role must belong to the confirmed sandbox account.")
    region = environment.get("ACCEPTANCE_AWS_REGION", "")
    image = environment.get("ACCEPTANCE_IMAGE_URI", "")
    reference = parse_ecr_image_uri(image)
    if not AWS_REGION_RE.fullmatch(region) or not reference or not reference.digest or reference.region != region or reference.registry_id != sandbox:
        raise ValueError("Supply a Lambda-compatible digest image in the sandbox account and selected region.")
    if not environment.get("GITHUB_RUN_ID", "").isdigit() or not environment.get("GITHUB_RUN_ATTEMPT", "").isdigit():
        raise ValueError("Cloud acceptance must run in an identified GitHub Actions attempt.")
    seed = ":".join(environment.get(name, "") for name in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
    return {"expected_account_id": sandbox, "production_account_id": production, "aws_region": region,
            "lambda_image_uri": image, "project_name": "acceptance-" + hashlib.sha256(seed.encode()).hexdigest()[:21]}


def prepare(root: Path, environment: dict[str, str], *, verify_identity: bool) -> None:
    values = settings(environment)
    if verify_identity:
        identity, result = _aws_json(root, ["sts", "get-caller-identity"])
        if result.returncode or not isinstance(identity, dict) or identity.get("Account") != values["expected_account_id"]:
            raise ValueError("The active AWS session is not the confirmed sandbox account.")
        verify_ecr_lambda_image(root, values["lambda_image_uri"], values["aws_region"])
        destination = root / "terraform/acceptance/acceptance.auto.tfvars.json"
        destination.write_text(json.dumps(values, indent=2) + "\n")
    else:
        protection = protected_environment_check(root, environment["GITHUB_REPOSITORY"], "acceptance")
        if protection.status != "OK":
            raise ValueError(protection.detail)
    print(f"Validated isolated acceptance target {values['expected_account_id']} in {values['aws_region']}.")


def main() -> int:
    try:
        operation = sys.argv[1]
        if operation not in {"preflight", "prepare"}:
            raise ValueError("Use acceptance preflight or prepare.")
        prepare(Path.cwd(), os.environ, verify_identity=operation == "prepare")
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as exc:
        print(f"Cloud acceptance blocked: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
