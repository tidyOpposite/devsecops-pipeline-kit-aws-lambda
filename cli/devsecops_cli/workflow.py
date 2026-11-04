"""Materialize a user's repository configuration on an ephemeral Actions runner.

No credentials belong in this payload. Repository variables carry schema-owned
settings; AWS/GitHub credentials remain in their existing secret/OIDC stores.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import PIPELINE_CONFIG_VARIABLE, config_shape_errors, deployment_config_sha256, production_policy_blockers, validate_config
from .deploy import DEPLOYMENT_OPERATIONS, DeploymentIntent, is_commit_sha
from .github import production_environment_check
from .images import collect_image_preflight_checks, parse_ecr_image_uri
from .models import ConfigValidationError
from .paths import DIST_DIR, GENERATED_TFVARS
from .render import backend_hcl, terraform_tfvars


def decode_pipeline_config(payload: str, *, production: bool = False, image_uri: str = "") -> dict:
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
    if production and image_uri:
        cfg["lambda_image_uri"] = image_uri
    checks = validate_config(cfg)
    if production:
        blockers = production_policy_blockers(checks)
        if not blockers:
            blockers = [check for check in collect_image_preflight_checks(cfg) if check.status == "FAIL"]
        if blockers:
            detail = "; ".join(
                f"{check.name}: {check.detail}" if check.status == "WARN" else check.name
                for check in blockers
            )
            raise ConfigValidationError(f"Production config policy blocked: {detail}. Check the config and synchronize GitHub settings.")
    else:
        failures = [check for check in checks if check.status == "FAIL"]
        if failures:
            raise ConfigValidationError("Invalid pipeline config: " + "; ".join(check.name for check in failures))
    if not cfg["backend"]["bucket"] or cfg["backend"]["bucket"].startswith("replace-with"):
        raise ConfigValidationError("Configure your Terraform backend bucket, then synchronize GitHub settings.")
    return cfg


def write_workflow_inputs(
    root: Path, payload: str, *, intent: DeploymentIntent | None = None, actual_commit: str = "",
    verify_only: bool = False,
) -> dict:
    """Validate the config and any required production protections before writing runner inputs."""

    if intent is None:
        cfg = decode_pipeline_config(payload)
    else:
        cfg = verify_production_intent(payload, intent, actual_commit)
        if verify_only:
            return cfg
        approval = production_environment_check(root, intent.repository)
        if approval.status != "OK":
            raise ConfigValidationError(f"{approval.name}: {approval.detail}")
    outputs = {
        root / GENERATED_TFVARS: terraform_tfvars(cfg),
        root / DIST_DIR / "backend.hcl": backend_hcl(cfg),
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return cfg


def verify_production_intent(payload: str, intent: DeploymentIntent, actual_commit: str) -> dict:
    if intent.request_id and not re.fullmatch(r"[a-f0-9]{32}", intent.request_id):
        raise ConfigValidationError("The deployment request ID must be 32 lowercase hexadecimal characters.")
    image = parse_ecr_image_uri(intent.image_uri)
    if not image or not image.digest or image.digest != image.digest.lower():
        raise ConfigValidationError("Production requires an explicit ECR image @sha256 digest from the deployment preview.")
    if not is_commit_sha(intent.commit_sha) or intent.commit_sha != actual_commit:
        raise ConfigValidationError("The dispatch commit_sha does not match this workflow commit. Review the deployment again.")
    cfg = decode_pipeline_config(payload, production=True, image_uri=intent.image_uri)
    if intent.config_sha256 != deployment_config_sha256(cfg, intent.image_uri):
        raise ConfigValidationError("The dispatch config_sha256 does not match the effective configuration. Synchronize settings and review the deployment again.")
    return cfg


def main() -> int:
    try:
        mode = os.environ.get("DEPLOY_MODE", "")
        production = mode in DEPLOYMENT_OPERATIONS
        verify_only = "--verify-intent" in sys.argv[1:]
        image_uri = os.environ.get("DISPATCH_IMAGE_URI", "")
        intent = None
        if production:
            intent = DeploymentIntent(
                os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("DISPATCH_COMMIT_SHA", ""),
                os.environ.get("DISPATCH_CONFIG_SHA256", ""), image_uri, os.environ.get("DISPATCH_REQUEST_ID", ""),
            )
        if verify_only and intent is None:
            raise ConfigValidationError("Intent verification requires a production deploy or rollback.")
        cfg = write_workflow_inputs(
            Path.cwd(), os.environ.get(PIPELINE_CONFIG_VARIABLE, ""),
            intent=intent, actual_commit=os.environ.get("GITHUB_SHA", ""), verify_only=verify_only,
        )
        if verify_only and intent is not None:
            summary = (
                f"## Reviewed production {mode}\n\n"
                f"- Commit: `{intent.commit_sha}`\n"
                f"- Configuration SHA-256: `{intent.config_sha256}`\n"
                f"- Image: `{intent.image_uri}`\n"
            )
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary_path:
                with open(summary_path, "a", encoding="utf-8") as handle:
                    handle.write(summary)
            print(summary)
            return 0
        # Keep workflow gates and Terraform inputs on the same configuration.
        # All exported values are schema-validated scalars, never shell source.
        values = {
            "PROJECT_NAME": cfg["project_name"], "AWS_REGION": cfg["aws_region"],
            "API_AUTHORIZATION_TYPE": cfg["api_authorization_type"],
            "LAMBDA_IMAGE_URI": image_uri or cfg["lambda_image_uri"],
            **{name.upper(): str(cfg[name]).lower() for name in ["enable_snyk_scan", "enable_http_validation", "enable_dast"]},
        }
        if any("\n" in value or "\r" in value for value in values.values()):
            raise ConfigValidationError("Workflow settings must not contain line breaks.")
        env_file = os.environ.get("GITHUB_ENV")
        if env_file:
            with open(env_file, "a", encoding="utf-8") as handle:
                handle.writelines(f"{key}={value}\n" for key, value in values.items())
    except (ConfigValidationError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("User Terraform and backend settings prepared from repository configuration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
