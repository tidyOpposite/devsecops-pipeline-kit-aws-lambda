"""Readiness and audit report generation."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from . import VERSION
from .config import (
    PRESET_DESCRIPTIONS,
    PRESET_ORDER,
    PRESET_POSTURES,
    PRESET_POSTURE_LABELS,
    SENSITIVITY_LABEL,
    control_catalog,
    control_to_dict,
    has_wildcard_cors,
    preset_config,
    prod_approval_environment,
    validate_config,
)
from .formatting import markdown_table
from .models import Check
from .paths import AUDIT_REPORT, DIST_DIR, GENERATED_TFVARS
from .readiness import (
    check_to_dict,
    checks_payload,
    readiness_breakdown_rows,
    readiness_gap_rows,
    readiness_score,
)
from .render import cli_owned_markdown_notice
from .views import control_rows, env_rows

PLAN_ROLE_ENV_NAME = "AWS_PLAN_ROLE_TO_ASSUME_ARN"
DEPLOY_ROLE_ENV_NAME = "AWS_ROLE_TO_ASSUME_ARN"


def markdown_report(cfg: dict[str, Any], checks: list[Check]) -> str:
    score = readiness_score(checks)
    check_rows = [[check.name, check.status, check.detail] for check in checks]
    breakdown_rows = readiness_breakdown_rows(checks, compact=True)
    control_report_rows = control_rows(cfg)
    env_report_rows = env_rows(cfg)
    generated_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return "\n\n".join(
        [
            "# DevSecOps Pipeline Readiness Report",
            cli_owned_markdown_notice("devsecops report", "report"),
            f"Generated: {generated_at}",
            f"Project: `{cfg['project_name']}`",
            f"Region: `{cfg['aws_region']}`",
            f"Readiness: `{score}%`",
            "## Score Breakdown\n\n" + markdown_table(["Area", "Score", "Gaps"], breakdown_rows),
            "## Checks\n\n" + markdown_table(["Check", "Status", "Detail"], check_rows),
            "## Environments\n\n"
            + markdown_table(["Env", "Memory", "Timeout", "Logs", "Burst/Rate", "CORS"], env_report_rows),
            "## Controls\n\n" + markdown_table(["Control", "State", "CLI", "Generated Behavior"], control_report_rows),
            "## Next Actions\n\n" + "\n".join(next_actions(cfg, checks)),
            "",
        ]
    )


def preset_dict(name: str) -> dict[str, Any]:
    cfg = preset_config(name)
    return {
        "name": name,
        "posture": PRESET_POSTURE_LABELS[name],
        "description": PRESET_DESCRIPTIONS[name],
        "security_posture": PRESET_POSTURES[name],
        "enable_snyk_scan": cfg["enable_snyk_scan"],
        "enable_http_validation": cfg["enable_http_validation"],
        "enable_dast": cfg["enable_dast"],
        "use_prod_approval_environment": cfg["use_prod_approval_environment"],
        "use_separate_aws_plan_role": cfg["use_separate_aws_plan_role"],
        "prod_cors_allowed_origins": cfg["environments"]["prod"]["cors_allowed_origins"],
        "strict_policy_gaps": [
            check_to_dict(check)
            for check in validate_config(cfg)
            if check.status in {"WARN", "FAIL"}
            and check.name
            in {
                "Lambda image immutability policy",
                "Production CORS policy",
                "Production approval gate policy",
                "Separate plan role policy",
                "Deployment validation policy",
            }
        ],
    }


def least_privilege_guidance() -> dict[str, Any]:
    return {
        "plan_role": {
            SENSITIVITY_LABEL: PLAN_ROLE_ENV_NAME,
            "purpose": "Pull request and manual Terraform plans.",
            "allow": [
                "Read Terraform state from the dedicated S3 backend bucket.",
                "Acquire and release DynamoDB state locks.",
                "Read/describe AWS resources needed by Terraform refresh.",
                "Read the configured ECR image metadata when planning image-dependent resources.",
            ],
            "avoid": [
                "Do not grant broad create/update/delete permissions for workload resources.",
                "Do not reuse AWS_ROLE_TO_ASSUME_ARN for pull request planning.",
                "Do not allow forked pull requests to assume AWS roles.",
            ],
        },
        "deploy_role": {
            SENSITIVITY_LABEL: DEPLOY_ROLE_ENV_NAME,
            "purpose": "Manual production deploy workflow from main after approval.",
            "allow": [
                "Apply Terraform-managed KMS, S3, ECR, Lambda, API Gateway, CloudWatch Logs, SQS, and IAM resources.",
                "Pass only the Terraform-managed Lambda execution role.",
                "Read and update the configured Lambda function image for rollback.",
                "Read the configured ECR image for optional container scanning.",
            ],
            "avoid": [
                "Do not grant access outside the project/environment resource naming boundary once names are stable.",
                "Do not use the deploy role for PR plans.",
                "Do not store static AWS access keys in GitHub secrets.",
            ],
        },
        "reference": "AWS_policy.md",
    }


def audit_report_payload(cfg: dict[str, Any], checks: list[Check], deep: bool = False) -> dict[str, Any]:
    validation_checks = validate_config(cfg)
    return {
        "kind": "audit-evidence",
        "schema_version": 1,
        "cli_version": VERSION,
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "project": {
            "name": cfg["project_name"],
            "aws_region": cfg["aws_region"],
            "config_schema_version": cfg.get("schema_version"),
        },
        "readiness": checks_payload("readiness", checks, context={"deep": deep}),
        "config_validation": {
            "strict_pass": not any(check.status in {"WARN", "FAIL"} for check in validation_checks),
            "checks": [check_to_dict(check) for check in validation_checks],
        },
        "controls": [control_to_dict(control, cfg) for control in control_catalog()],
        "policy_presets": [preset_dict(name) for name in PRESET_ORDER],
        "least_privilege": least_privilege_guidance(),
        "attachable_evidence": [
            str(AUDIT_REPORT),
            str(DIST_DIR / "readiness-report.md"),
            str(GENERATED_TFVARS),
            str(DIST_DIR / "github-setup.sh"),
        ],
    }


def audit_report_json(cfg: dict[str, Any], checks: list[Check], deep: bool = False) -> str:
    return json.dumps(audit_report_payload(cfg, checks, deep=deep), indent=2, sort_keys=True) + "\n"


def next_actions(cfg: dict[str, Any], checks: list[Check]) -> list[str]:
    actions: list[str] = []
    for check_name, status, _detail, action in readiness_gap_rows(checks):
        actions.append(f"- {check_name} ({status}): {action}")
    if actions:
        return actions
    if not cfg["lambda_image_uri"]:
        actions.append("- Set `LAMBDA_IMAGE_URI` to an immutable Lambda container image.")
    if cfg["backend"]["bucket"].startswith("replace-with"):
        actions.append("- Set a real Terraform backend S3 bucket and run `devsecops render`.")
    if any(check.name == "`aws` CLI" and check.status != "OK" for check in checks):
        actions.append("- Install or configure AWS CLI before running cloud bootstrap checks.")
    if cfg["enable_snyk_scan"]:
        actions.append("- Configure `SNYK_TOKEN` so the enabled container scan can run.")
    if cfg["use_separate_aws_plan_role"]:
        actions.append("- Configure `AWS_PLAN_ROLE_TO_ASSUME_ARN`; Terraform plan workflows do not fall back to the deploy role.")
    else:
        actions.append("- Enable separate AWS plan role and configure `AWS_PLAN_ROLE_TO_ASSUME_ARN`; deploy-role fallback is disabled.")
    if not cfg["enable_http_validation"]:
        actions.append("- Enable `/health` validation after the workload implements that route.")
    if not cfg["enable_dast"]:
        actions.append("- Enable DAST only after the API surface is safe for passive scanning.")
    if not actions:
        actions.append("- No immediate configuration gaps detected.")
    return actions



__all__ = [
    "audit_report_json",
    "audit_report_payload",
    "least_privilege_guidance",
    "markdown_report",
    "next_actions",
    "preset_dict",
]
