"""Deterministic generators for CLI-owned project artifacts.

Generators are pure with respect to configuration: they return complete file
contents and leave directory creation, snapshots, permissions, and writes to
the orchestration layer.  Stable ordering makes preview and golden diffs useful.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

from .config import PIPELINE_CONFIG_VARIABLE, pipeline_config_json, prod_approval_environment
from .paths import CONFIG_FILE, DIST_DIR, GENERATED_ARTIFACT_DOC, GENERATED_TFVARS
from .lambda_capacity import DEFAULT_RESERVED_EXECUTIONS


def hcl_value(value: Any) -> str:
    """Serialize the limited config value types accepted by generated HCL."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(hcl_value(item) for item in value) + "]"
    return json.dumps(str(value)).replace("${", "$${").replace("%{", "%%{")


def hcl_attribute_line(key: str, value: Any, width: int) -> str:
    """Align one HCL assignment for readable deterministic output."""

    return f"{key.ljust(width)} = {hcl_value(value)}"


def cli_owned_comment(command: str) -> str:
    """Build the ownership header shared by generated text formats."""

    return "\n".join(
        [
            "# CLI-owned generated file. Do not edit directly.",
            f"# Update {CONFIG_FILE} and rerun `{command}`.",
            f"# See {GENERATED_ARTIFACT_DOC} for ownership rules.",
        ]
    )


def cli_owned_markdown_notice(command: str, artifact: str) -> str:
    """Build an inline ownership notice suitable for generated Markdown."""

    return (
        f"CLI-owned generated {artifact}. Do not edit directly; "
        f"update `{CONFIG_FILE}` and rerun `{command}`."
    )


def terraform_tfvars(cfg: dict[str, Any]) -> str:
    """Render root inputs and the per-environment map as canonical HCL."""

    top_level = [
        ("project_name", cfg["project_name"]),
        ("aws_region", cfg["aws_region"]),
        ("lambda_image_uri", cfg["lambda_image_uri"]),
        ("api_authorization_type", cfg["api_authorization_type"]),
        ("terraform_admin_role_name", cfg["terraform_admin_role_name"]),
        ("lambda_reserved_concurrent_executions", DEFAULT_RESERVED_EXECUTIONS),
    ]
    top_level_width = max(len(key) for key, _ in top_level)
    environment_width = max(len(key) for env_cfg in cfg["environments"].values() for key in env_cfg)
    lines = cli_owned_comment("devsecops render").splitlines() + [""]
    lines.extend(hcl_attribute_line(key, value, top_level_width) for key, value in top_level)
    lines.extend(["", "environment_config = {"])
    for env_name, env_cfg in cfg["environments"].items():
        lines.append(f"  {env_name} = {{")
        for key, value in env_cfg.items():
            lines.append(f"    {hcl_attribute_line(key, value, environment_width)}")
        lines.append("  }")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def backend_tf(cfg: dict[str, Any]) -> str:
    """Render a reviewable S3 backend template from local configuration.

    The output lives under ``dist`` and is not silently installed over the
    tracked backend file; operators review and copy it when ready.
    """

    backend = cfg["backend"]
    lines = cli_owned_comment("devsecops render").splitlines() + [
        "# Optional reference. CLI/workflows use ignored backend.hcl; no source edit is needed.",
        "terraform {",
        '  backend "s3" {',
        f'    bucket               = {hcl_value(backend["bucket"])}',
        f'    key                  = {hcl_value(backend["key"])}',
        f'    region               = {hcl_value(backend["region"])}',
        "    encrypt              = true",
        f'    dynamodb_table       = {hcl_value(backend["lock_table"])}',
        f'    workspace_key_prefix = {hcl_value(backend["workspace_key_prefix"])}',
        "  }",
        "}",
        "",
    ]
    return "\n".join(lines)


def backend_hcl(cfg: dict[str, Any]) -> str:
    """Partial backend config passed explicitly to Terraform, never committed."""

    backend = cfg["backend"]
    values = {
        "bucket": backend["bucket"], "key": backend["key"], "region": backend["region"],
        "encrypt": True, "dynamodb_table": backend["lock_table"],
        "workspace_key_prefix": backend["workspace_key_prefix"],
    }
    return cli_owned_comment("devsecops generate") + "\n" + "\n".join(
        hcl_attribute_line(key, value, 20) for key, value in values.items()
    ) + "\n"


def github_variables(cfg: dict[str, Any]) -> str:
    """Render the non-secret repository-variable handoff file."""

    lines = cli_owned_comment("devsecops render").splitlines() + [
        "# Repository variables to configure in GitHub.",
        "# Example with gh:",
        f'#   gh variable set PROJECT_NAME --body "{cfg["project_name"]}"',
        "",
        f'PROJECT_NAME={cfg["project_name"]}',
        f'LAMBDA_IMAGE_URI={cfg["lambda_image_uri"]}',
        f'API_AUTHORIZATION_TYPE={cfg["api_authorization_type"]}',
        f'ENABLE_SNYK_SCAN={str(cfg["enable_snyk_scan"]).lower()}',
        f'ENABLE_HTTP_VALIDATION={str(cfg["enable_http_validation"]).lower()}',
        f'ENABLE_DAST={str(cfg["enable_dast"]).lower()}',
        f"PROD_APPROVAL_ENVIRONMENT={prod_approval_environment(cfg)}",
        f"{PIPELINE_CONFIG_VARIABLE}={shell_quote(pipeline_config_json(cfg))}",
        "",
    ]
    return "\n".join(lines)


def checklist(cfg: dict[str, Any]) -> str:
    """Render the human setup checklist with posture-dependent requirements."""

    snyk_label = "`SNYK_TOKEN`" if cfg["enable_snyk_scan"] else "`SNYK_TOKEN` (optional)"
    return textwrap.dedent(
        f"""\
        # DevSecOps Pipeline Setup Checklist

        {cli_owned_markdown_notice("devsecops render", "checklist")}

        ## GitHub Secrets

        - [ ] `AWS_ROLE_TO_ASSUME_ARN` at repository or `prod` scope
        - [ ] `AWS_PLAN_ROLE_TO_ASSUME_ARN` at repository scope
        - [ ] Separate OIDC role verification passed on current `main`
        - [ ] {snyk_label}

        ## GitHub Variables

        - [ ] `PROJECT_NAME` = `{cfg["project_name"]}`
        - [ ] `LAMBDA_IMAGE_URI` = `{cfg["lambda_image_uri"] or "<immutable-image-uri>"}`
        - [ ] `API_AUTHORIZATION_TYPE` = `{cfg["api_authorization_type"]}`
        - [ ] `ENABLE_SNYK_SCAN` = `{str(cfg["enable_snyk_scan"]).lower()}`
        - [ ] `ENABLE_HTTP_VALIDATION` = `{str(cfg["enable_http_validation"]).lower()}`
        - [ ] `ENABLE_DAST` = `{str(cfg["enable_dast"]).lower()}`
        - [ ] `PROD_APPROVAL_ENVIRONMENT` = `{prod_approval_environment(cfg)}`
        - [ ] `{PIPELINE_CONFIG_VARIABLE}` synchronized with local config using `devsecops github setup --apply`
        - [ ] AWS region in pipeline configuration = `{cfg["aws_region"]}`
        - [ ] GitHub Environment `prod` has at least one required reviewer

        ## Terraform Backend

        - [ ] State bucket: `{cfg["backend"]["bucket"]}`
        - [ ] Lock table: `{cfg["backend"]["lock_table"]}`
        - [ ] Backend key: `{cfg["backend"]["key"]}`

        ## Branch Protection

        - [ ] Require pull requests before merging to `main`
        - [ ] Require `Security and Terraform Validate`
        - [ ] Require `Terraform Format and Validate`
        """
    )


def github_setup_script(cfg: dict[str, Any]) -> str:
    """Render a strict-shell helper for applying GitHub variables and secrets.

    The caller supplies an explicit destination and optional secret arguments.
    Shared CLI validation and retry behavior apply to the generated helper.
    """

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        *cli_owned_comment("devsecops render").splitlines(),
        "# Run from the project checkout with OWNER/REPO and setup options.",
        "# Example options: --deploy-role-arn <deploy-role-arn> --plan-role-arn <plan-role-arn>",
    ]
    if cfg["enable_snyk_scan"]:
        lines.append("# Include --snyk-token <snyk-token> when SNYK_TOKEN is not configured.")
    lines.extend([
        "",
        'repository="${1:?Usage: github-setup.sh OWNER/REPO [setup options]}"',
        "shift",
        'exec devsecops github setup --apply --repo "$repository" "$@"',
        "",
    ])
    return "\n".join(lines)


def shell_quote(value: str) -> str:
    """Single-quote a value for safe interpolation into POSIX shell syntax."""

    return "'" + value.replace("'", "'\"'\"'") + "'"



def render_outputs(root: Path, cfg: dict[str, Any]) -> dict[Path, str]:
    """Return the complete path-to-content manifest for generated artifacts."""

    dist = root / DIST_DIR
    return {
        root / GENERATED_TFVARS: terraform_tfvars(cfg),
        dist / "backend.tf": backend_tf(cfg),
        dist / "backend.hcl": backend_hcl(cfg),
        dist / "github-variables.env": github_variables(cfg),
        dist / "github-setup.sh": github_setup_script(cfg),
        dist / "setup-checklist.md": checklist(cfg),
    }


def generated_artifact_gaps(root: Path, cfg: dict[str, Any]) -> list[str]:
    """Compare every deterministic deployment artifact with current settings."""

    gaps = []
    for path, expected in render_outputs(root, cfg).items():
        try:
            if path.read_text(encoding="utf-8") != expected:
                gaps.append(f"{path.relative_to(root)} (outdated)")
        except FileNotFoundError:
            gaps.append(f"{path.relative_to(root)} (missing)")
    return gaps



__all__ = [
    "backend_hcl",
    "backend_tf",
    "checklist",
    "cli_owned_comment",
    "cli_owned_markdown_notice",
    "generated_artifact_gaps",
    "github_setup_script",
    "github_variables",
    "hcl_attribute_line",
    "hcl_value",
    "render_outputs",
    "shell_quote",
    "terraform_tfvars",
]
