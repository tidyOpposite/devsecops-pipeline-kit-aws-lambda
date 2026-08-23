"""Deterministic generators for CLI-owned project artifacts."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from .config import prod_approval_environment
from .paths import CONFIG_FILE, DIST_DIR, GENERATED_ARTIFACT_DOC, GENERATED_TFVARS


def hcl_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(hcl_value(item) for item in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def hcl_attribute_line(key: str, value: Any, width: int) -> str:
    return f"{key.ljust(width)} = {hcl_value(value)}"


def cli_owned_comment(command: str) -> str:
    return "\n".join(
        [
            "# CLI-owned generated file. Do not edit directly.",
            f"# Update {CONFIG_FILE} and rerun `{command}`.",
            f"# See {GENERATED_ARTIFACT_DOC} for ownership rules.",
        ]
    )


def cli_owned_markdown_notice(command: str, artifact: str) -> str:
    return (
        f"CLI-owned generated {artifact}. Do not edit directly; "
        f"update `{CONFIG_FILE}` and rerun `{command}`."
    )


def terraform_tfvars(cfg: dict[str, Any]) -> str:
    top_level = [
        ("project_name", cfg["project_name"]),
        ("aws_region", cfg["aws_region"]),
        ("lambda_image_uri", cfg["lambda_image_uri"]),
        ("api_authorization_type", cfg["api_authorization_type"]),
        ("terraform_admin_role_name", cfg["terraform_admin_role_name"]),
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
    backend = cfg["backend"]
    lines = cli_owned_comment("devsecops render").splitlines() + [
        "# Review and copy into terraform/backend.tf when ready.",
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


def github_variables(cfg: dict[str, Any]) -> str:
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
        "",
    ]
    return "\n".join(lines)


def checklist(cfg: dict[str, Any]) -> str:
    snyk_label = "`SNYK_TOKEN`" if cfg["enable_snyk_scan"] else "`SNYK_TOKEN` (optional)"
    return textwrap.dedent(
        f"""\
        # DevSecOps Pipeline Setup Checklist

        {cli_owned_markdown_notice("devsecops render", "checklist")}

        ## GitHub Secrets

        - [ ] `AWS_ROLE_TO_ASSUME_ARN`
        - [ ] `AWS_PLAN_ROLE_TO_ASSUME_ARN`
        - [ ] `AWS_REGION` = `{cfg["aws_region"]}`
        - [ ] {snyk_label}

        ## GitHub Variables

        - [ ] `PROJECT_NAME` = `{cfg["project_name"]}`
        - [ ] `LAMBDA_IMAGE_URI` = `{cfg["lambda_image_uri"] or "<immutable-image-uri>"}`
        - [ ] `API_AUTHORIZATION_TYPE` = `{cfg["api_authorization_type"]}`
        - [ ] `ENABLE_SNYK_SCAN` = `{str(cfg["enable_snyk_scan"]).lower()}`
        - [ ] `ENABLE_HTTP_VALIDATION` = `{str(cfg["enable_http_validation"]).lower()}`
        - [ ] `ENABLE_DAST` = `{str(cfg["enable_dast"]).lower()}`
        - [ ] `PROD_APPROVAL_ENVIRONMENT` = `{prod_approval_environment(cfg)}`

        ## Terraform Backend

        - [ ] State bucket: `{cfg["backend"]["bucket"]}`
        - [ ] Lock table: `{cfg["backend"]["lock_table"]}`
        - [ ] Backend key: `{cfg["backend"]["key"]}`

        ## Branch Protection

        - [ ] Require pull requests before merging to `main`
        - [ ] Require `Security and Terraform Validate`
        - [ ] Require `Terraform Plan`
        """
    )


def github_setup_script(cfg: dict[str, Any]) -> str:
    snyk_token_command = (
        'gh secret set SNYK_TOKEN --body "<snyk-token>"'
        if cfg["enable_snyk_scan"]
        else '# Optional: gh secret set SNYK_TOKEN --body "<snyk-token>"'
    )
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        *cli_owned_comment("devsecops render").splitlines(),
        "# Review placeholder values before running.",
        "",
        f'gh variable set PROJECT_NAME --body {shell_quote(cfg["project_name"])}',
        f'gh variable set LAMBDA_IMAGE_URI --body {shell_quote(cfg["lambda_image_uri"] or "<immutable-image-uri>")}',
        f'gh variable set API_AUTHORIZATION_TYPE --body {shell_quote(cfg["api_authorization_type"])}',
        f'gh variable set ENABLE_SNYK_SCAN --body {shell_quote(str(cfg["enable_snyk_scan"]).lower())}',
        f'gh variable set ENABLE_HTTP_VALIDATION --body {shell_quote(str(cfg["enable_http_validation"]).lower())}',
        f'gh variable set ENABLE_DAST --body {shell_quote(str(cfg["enable_dast"]).lower())}',
        f"gh variable set PROD_APPROVAL_ENVIRONMENT --body {shell_quote(prod_approval_environment(cfg))}",
        "",
        f'gh secret set AWS_REGION --body {shell_quote(cfg["aws_region"])}',
        'gh secret set AWS_ROLE_TO_ASSUME_ARN --body "<deploy-role-arn>"',
        'gh secret set AWS_PLAN_ROLE_TO_ASSUME_ARN --body "<plan-role-arn>"',
        snyk_token_command,
        "",
    ]
    return "\n".join(lines)


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"



def render_outputs(root: Path, cfg: dict[str, Any]) -> dict[Path, str]:
    dist = root / DIST_DIR
    return {
        root / GENERATED_TFVARS: terraform_tfvars(cfg),
        dist / "backend.tf": backend_tf(cfg),
        dist / "github-variables.env": github_variables(cfg),
        dist / "github-setup.sh": github_setup_script(cfg),
        dist / "setup-checklist.md": checklist(cfg),
    }



__all__ = [
    "backend_tf",
    "checklist",
    "cli_owned_comment",
    "cli_owned_markdown_notice",
    "github_setup_script",
    "github_variables",
    "hcl_attribute_line",
    "hcl_value",
    "render_outputs",
    "shell_quote",
    "terraform_tfvars",
]
