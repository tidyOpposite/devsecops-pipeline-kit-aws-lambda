"""Capture production outputs only after verifying their backend and AWS context."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import load_config, validate_config
from .images import parse_ecr_image_uri


def expected_backend(cfg: dict) -> dict:
    backend = cfg["backend"]
    return {"type": "s3", "bucket": backend["bucket"], "key": backend["key"],
            "region": backend["region"], "dynamodb_table": backend["lock_table"],
            "workspace_key_prefix": backend["workspace_key_prefix"], "encrypt": True}


def validate_cloud_context(context: dict, outputs: dict, cfg: dict) -> None:
    """Reject evidence from a different account, backend, workspace or workload."""

    account = context["expected_account_id"]
    identity = context["aws_identity"]
    arn = identity["Arn"]
    if (not isinstance(account, str) or not re.fullmatch(r"[0-9]{12}", account)
            or identity["Account"] != account
            or not re.fullmatch(rf"arn:(aws|aws-us-gov|aws-cn):(?:iam|sts)::{account}:.+", arn)):
        raise ValueError("AWS identity does not match the explicitly confirmed account.")
    if context["backend"] != expected_backend(cfg) or context["workspace"] != "prod":
        raise ValueError("Initialize the configured S3 backend and select the existing prod workspace.")
    values = {name: item["value"] for name, item in outputs.items()}
    function = f"{cfg['project_name']}-prod-lambda"
    expected_arn = f"arn:{arn.split(':')[1]}:lambda:{cfg['aws_region']}:{account}:function:{function}"
    image = context["lambda_image_uri"]
    ref = parse_ecr_image_uri(image)
    captured = dt.datetime.fromisoformat(context["captured_at"].replace("Z", "+00:00"))
    if (context["schema_version"] != 1 or captured.tzinfo is None
            or context["aws_region"] != cfg["aws_region"] or context["lambda_function_arn"] != expected_arn
            or values.get("environment") != "prod" or values.get("terraform_workspace") != "prod"
            or values.get("lambda_function_name") != function
            or not ref or not ref.digest or ref.region != cfg["aws_region"]
            or values.get("lambda_current_image_uri") != image):
        raise ValueError("Terraform outputs and live Lambda do not identify the same production workload and digest.")


def capture_cloud_evidence(root: Path, directory: Path, expected_account: str) -> None:
    """Perform read-only provider calls; write only verified, noncredential evidence."""

    if not re.fullmatch(r"[0-9]{12}", expected_account):
        raise ValueError("Supply the independently confirmed 12-digit AWS account ID.")
    if os.environ.get("TF_DATA_DIR") or any(name.startswith("TF_CLI_ARGS") and value for name, value in os.environ.items()):
        raise ValueError("Unset TF_DATA_DIR and TF_CLI_ARGS overrides before collecting production evidence.")
    cfg = load_config(root)
    if any(check.status == "FAIL" for check in validate_config(cfg)):
        raise ValueError("Validate the local configuration before collecting production evidence.")
    metadata = json.loads((root / "terraform/.terraform/terraform.tfstate").read_text())["backend"]
    backend = {name: metadata["type"] if name == "type" else metadata["config"].get(name)
               for name in expected_backend(cfg)}
    if backend != expected_backend(cfg):
        raise ValueError("Initialized Terraform backend differs from the reviewed local configuration.")

    def run(command: list[str]) -> str:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=60, check=False)
        if result.returncode != 0:
            raise ValueError(f"Cannot collect evidence: {command[0]} {command[1]} failed.")
        return result.stdout.strip()

    workspace = run(["terraform", "-chdir=terraform", "workspace", "show", "-no-color"])
    if workspace != "prod":
        raise ValueError("Select the existing prod workspace before collecting outputs; no workspace was created.")
    identity = json.loads(run(["aws", "sts", "get-caller-identity", "--output", "json"]))
    if identity.get("Account") != expected_account:
        raise ValueError("AWS identity does not match the explicitly confirmed account.")
    outputs = json.loads(run(["terraform", "-chdir=terraform", "output", "-json", "-no-color"]))
    live = json.loads(run(["aws", "lambda", "get-function", "--function-name",
                          f"{cfg['project_name']}-prod-lambda", "--region", cfg["aws_region"], "--output", "json"]))
    context = {
        "schema_version": 1, "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "expected_account_id": expected_account, "aws_identity": {name: identity[name] for name in ("Account", "Arn", "UserId")},
        "aws_region": cfg["aws_region"], "backend": backend, "workspace": workspace,
        "lambda_function_arn": live["Configuration"]["FunctionArn"],
        "lambda_image_uri": live["Code"]["ResolvedImageUri"],
    }
    validate_cloud_context(context, outputs, cfg)
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in (("terraform-context.json", context), ("terraform-output.json", outputs)):
        (directory / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (directory / "active-lambda-image.txt").write_text(context["lambda_image_uri"] + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        capture_cloud_evidence(Path.cwd(), args.directory, args.expected_account_id)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
        print(f"Production evidence was not collected: {exc}", file=sys.stderr)
        return 1
    print("Captured matching production backend, workspace, AWS identity, Terraform outputs and live Lambda digest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
