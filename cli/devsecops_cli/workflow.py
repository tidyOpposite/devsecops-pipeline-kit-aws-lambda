"""Materialize a user's repository configuration on an ephemeral Actions runner.

No credentials belong in this payload. Repository variables carry schema-owned
settings; AWS/GitHub credentials remain in their existing secret/OIDC stores.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .config import PIPELINE_CONFIG_VARIABLE, config_shape_errors, validate_config
from .models import ConfigValidationError
from .paths import DIST_DIR, GENERATED_TFVARS
from .render import backend_hcl, terraform_tfvars


def decode_pipeline_config(payload: str) -> dict:
    if not payload:
        raise ConfigValidationError(
            f"Missing {PIPELINE_CONFIG_VARIABLE}. Run `devsecops github setup --apply` in your deployment repository."
        )
    try:
        cfg = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"Invalid {PIPELINE_CONFIG_VARIABLE}; synchronize it again with the CLI.") from exc
    errors = config_shape_errors(cfg)
    if errors:
        raise ConfigValidationError("Invalid pipeline config: " + "; ".join(errors))
    failures = [check for check in validate_config(cfg) if check.status == "FAIL"]
    if failures:
        raise ConfigValidationError("Invalid pipeline config: " + "; ".join(check.name for check in failures))
    if not cfg["backend"]["bucket"] or cfg["backend"]["bucket"].startswith("replace-with"):
        raise ConfigValidationError("Configure your Terraform backend bucket, then synchronize GitHub settings.")
    return cfg


def write_workflow_inputs(root: Path, payload: str) -> dict:
    """Validate before writing either runner input; never print payload values."""

    cfg = decode_pipeline_config(payload)
    outputs = {
        root / GENERATED_TFVARS: terraform_tfvars(cfg),
        root / DIST_DIR / "backend.hcl": backend_hcl(cfg),
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return cfg


def main() -> int:
    try:
        cfg = write_workflow_inputs(Path.cwd(), os.environ.get(PIPELINE_CONFIG_VARIABLE, ""))
        if os.environ.get("DEPLOY_MODE") in {"deploy", "rollback"} and not cfg["use_prod_approval_environment"]:
            raise ConfigValidationError("Production requires use_prod_approval_environment=true.")
        # Keep workflow gates and Terraform inputs on the same configuration.
        # All exported values are schema-validated scalars, never shell source.
        values = {
            "PROJECT_NAME": cfg["project_name"], "AWS_REGION": cfg["aws_region"],
            "API_AUTHORIZATION_TYPE": cfg["api_authorization_type"],
            "LAMBDA_IMAGE_URI": os.environ.get("DISPATCH_IMAGE_URI") or cfg["lambda_image_uri"],
            **{name.upper(): str(cfg[name]).lower() for name in ["enable_snyk_scan", "enable_http_validation", "enable_dast"]},
        }
        if any("\n" in value or "\r" in value for value in values.values()):
            raise ConfigValidationError("Workflow settings must not contain line breaks.")
        env_file = os.environ.get("GITHUB_ENV")
        if env_file:
            with open(env_file, "a", encoding="utf-8") as handle:
                handle.writelines(f"{key}={value}\n" for key, value in values.items())
    except ConfigValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("User Terraform and backend settings prepared from repository configuration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
