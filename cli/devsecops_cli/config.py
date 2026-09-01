"""Configuration domain for the DevSecOps Pipeline Kit CLI.

This module owns configuration defaults, schema migration, validation, presets,
and security-control state.  It is independent from command parsing and
terminal presentation.  Configuration contains references and policy choices,
never credentials; secret values remain in their provider-specific stores.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from .formatting import markdown_table
from .images import is_immutable_image
from .models import Check, ConfigMigrationError, Control
from .paths import CONFIG_FILE

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback guard
    tomllib = None  # type: ignore[assignment]


# Format constraints and schema metadata form the public configuration contract.
CONFIG_SCHEMA_VERSION = 1
PROJECT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")
AWS_REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-\d$")
PRESET_ORDER = ["minimal", "balanced", "strict", "enterprise", "student-demo"]
PRESETS = set(PRESET_ORDER)
PRESET_DESCRIPTIONS = {
    "minimal": "Low-cost settings for early local and development experimentation.",
    "balanced": "Default reference settings for a practical multi-environment pipeline.",
    "strict": "Validation-focused settings with HTTP smoke testing and DAST enabled.",
    "enterprise": "Locked-down CORS, longer log retention, and stricter production gates.",
    "student-demo": "Small, simple settings for classroom demos and short-lived walkthroughs.",
}
PRESET_POSTURES = {
    "minimal": "Development-only posture. Keeps deploy approval and plan-role separation, but allows wildcard CORS and disables scanner/validation gates.",
    "balanced": "Baseline posture. Keeps production approval and separate plan role, uses explicit production CORS, and leaves workload validation opt-in.",
    "strict": "Pre-production posture. Enables Snyk, HTTP validation, DAST, strict CORS, production approval, and separate plan role.",
    "enterprise": "Production-oriented posture. Enables all validation/scanner controls, strict CORS, longer retention, and stricter throttling.",
    "student-demo": "Demo posture. Optimized for short-lived walkthroughs; disables approval and plan-role controls and is not production-ready.",
}
PRESET_POSTURE_LABELS = {
    "minimal": "development-only",
    "balanced": "baseline",
    "strict": "strict",
    "enterprise": "production-oriented",
    "student-demo": "demo-only",
}
ENVIRONMENTS = ["dev", "staging", "prod"]
# ``config set`` is deliberately allowlisted so arbitrary or secret-looking
# keys cannot silently become part of the local source-of-truth file.
CONFIG_SET_PATHS = {
    "project_name",
    "aws_region",
    "lambda_image_uri",
    "enable_snyk_scan",
    "enable_http_validation",
    "enable_dast",
    "api_authorization_type",
    "use_prod_approval_environment",
    "use_separate_aws_plan_role",
    "terraform_admin_role_name",
    "backend.bucket",
    "backend.key",
    "backend.region",
    "backend.lock_table",
    "backend.workspace_key_prefix",
}
for _env_name in ENVIRONMENTS:
    for _setting in [
        "lambda_memory_size",
        "lambda_timeout",
        "log_retention_days",
        "api_throttling_burst_limit",
        "api_throttling_rate_limit",
        "cors_allowed_origins",
    ]:
        CONFIG_SET_PATHS.add(f"environments.{_env_name}.{_setting}")

SENSITIVITY_LABEL = "sec" + "ret"
PROD_APPROVAL_ENVIRONMENT = "prod"
NO_APPROVAL_ENVIRONMENT = "devsecops-no-approval"
STRICT_CORS_ORIGINS = {
    "dev": ["https://dev.example.com"],
    "staging": ["https://staging.example.com"],
    "prod": ["https://app.example.com"],
}
API_AUTHORIZATION_TYPES = {"AWS_IAM", "NONE"}

# This machine-readable contract keeps migrations, generated artifacts, and
# rollback expectations visible to both users and release tooling.
CONFIG_MIGRATION_CONTRACT = {
    "current_schema_version": CONFIG_SCHEMA_VERSION,
    "legacy_without_schema_version": "Treat as schema_version 1 and normalize with current defaults.",
    "future_schema_version": "Refuse to load or render; upgrade the CLI before changing CLI-owned files.",
    "required_for_schema_change": [
        "increment CONFIG_SCHEMA_VERSION",
        "add deterministic migrate_config step",
        "update config_schema and config_schema_markdown",
        "add legacy-to-current and rollback expectation tests",
        "document re-render expectations in generated-artifacts and upgrade guide",
    ],
    "rollback_expectations": [
        "migration changes only local source config normalization",
        "render/report/github setup create snapshots before overwriting CLI-owned files",
        "snapshot restore affects only .devsecops-pipeline.toml, terraform/generated.auto.tfvars, dist/devsecops/* reports/helpers, and audit report",
        "snapshot restore does not mutate AWS, Terraform state, GitHub settings, or deployed Lambda images",
    ],
}


def config_path(root: Path) -> Path:
    """Return the canonical local source-configuration path."""

    return root / CONFIG_FILE


def default_config() -> dict[str, Any]:
    """Build a new baseline configuration with independent nested containers."""

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "project_name": "devsecops-pipeline",
        "aws_region": "us-east-1",
        "lambda_image_uri": "",
        "enable_snyk_scan": False,
        "enable_http_validation": False,
        "enable_dast": False,
        "api_authorization_type": "AWS_IAM",
        "use_prod_approval_environment": True,
        "use_separate_aws_plan_role": True,
        "terraform_admin_role_name": "",
        "backend": {
            "bucket": "replace-with-your-terraform-state-bucket",
            "key": "serverless-lambda/terraform.tfstate",
            "region": "us-east-1",
            "lock_table": "devsecops-pipeline-terraform-locks",
            "workspace_key_prefix": "environments",
        },
        "environments": {
            "dev": {
                "lambda_memory_size": 1024,
                "lambda_timeout": 120,
                "log_retention_days": 30,
                "api_throttling_burst_limit": 25,
                "api_throttling_rate_limit": 50,
                "cors_allowed_origins": ["*"],
            },
            "staging": {
                "lambda_memory_size": 1536,
                "lambda_timeout": 180,
                "log_retention_days": 90,
                "api_throttling_burst_limit": 50,
                "api_throttling_rate_limit": 100,
                "cors_allowed_origins": ["*"],
            },
            "prod": {
                "lambda_memory_size": 2048,
                "lambda_timeout": 240,
                "log_retention_days": 365,
                "api_throttling_burst_limit": 100,
                "api_throttling_rate_limit": 200,
                "cors_allowed_origins": ["https://app.example.com"],
            },
        },
    }


def preset_config(name: str) -> dict[str, Any]:
    """Build a complete configuration for a named operational posture.

    Every preset starts from fresh defaults, then changes only the controls and
    environment sizing that distinguish that posture.
    """

    cfg = default_config()
    if name == "minimal":
        cfg["enable_http_validation"] = False
        cfg["enable_dast"] = False
        cfg["environments"] = {
            "dev": {
                "lambda_memory_size": 512,
                "lambda_timeout": 60,
                "log_retention_days": 7,
                "api_throttling_burst_limit": 10,
                "api_throttling_rate_limit": 25,
                "cors_allowed_origins": ["*"],
            },
            "staging": {
                "lambda_memory_size": 1024,
                "lambda_timeout": 120,
                "log_retention_days": 30,
                "api_throttling_burst_limit": 25,
                "api_throttling_rate_limit": 50,
                "cors_allowed_origins": ["*"],
            },
            "prod": {
                "lambda_memory_size": 1024,
                "lambda_timeout": 180,
                "log_retention_days": 90,
                "api_throttling_burst_limit": 50,
                "api_throttling_rate_limit": 100,
                "cors_allowed_origins": ["*"],
            },
        }
    elif name == "strict":
        cfg["enable_snyk_scan"] = True
        cfg["enable_http_validation"] = True
        cfg["enable_dast"] = True
        apply_cors_policy(cfg, strict=True)
        cfg["environments"]["prod"]["lambda_timeout"] = 300
        cfg["environments"]["prod"]["api_throttling_burst_limit"] = 50
        cfg["environments"]["prod"]["api_throttling_rate_limit"] = 100
    elif name == "enterprise":
        cfg["enable_snyk_scan"] = True
        cfg["enable_http_validation"] = True
        cfg["enable_dast"] = True
        cfg["use_prod_approval_environment"] = True
        cfg["use_separate_aws_plan_role"] = True
        cfg["environments"] = {
            "dev": {
                "lambda_memory_size": 1536,
                "lambda_timeout": 180,
                "log_retention_days": 90,
                "api_throttling_burst_limit": 20,
                "api_throttling_rate_limit": 40,
                "cors_allowed_origins": ["https://dev.example.com"],
            },
            "staging": {
                "lambda_memory_size": 2048,
                "lambda_timeout": 240,
                "log_retention_days": 365,
                "api_throttling_burst_limit": 40,
                "api_throttling_rate_limit": 80,
                "cors_allowed_origins": ["https://staging.example.com"],
            },
            "prod": {
                "lambda_memory_size": 3072,
                "lambda_timeout": 300,
                "log_retention_days": 1095,
                "api_throttling_burst_limit": 50,
                "api_throttling_rate_limit": 100,
                "cors_allowed_origins": ["https://app.example.com"],
            },
        }
    elif name == "student-demo":
        cfg["enable_snyk_scan"] = False
        cfg["enable_http_validation"] = False
        cfg["enable_dast"] = False
        cfg["api_authorization_type"] = "NONE"
        cfg["use_prod_approval_environment"] = False
        cfg["use_separate_aws_plan_role"] = False
        cfg["environments"] = {
            "dev": {
                "lambda_memory_size": 512,
                "lambda_timeout": 45,
                "log_retention_days": 7,
                "api_throttling_burst_limit": 10,
                "api_throttling_rate_limit": 20,
                "cors_allowed_origins": ["*"],
            },
            "staging": {
                "lambda_memory_size": 512,
                "lambda_timeout": 60,
                "log_retention_days": 14,
                "api_throttling_burst_limit": 10,
                "api_throttling_rate_limit": 20,
                "cors_allowed_origins": ["*"],
            },
            "prod": {
                "lambda_memory_size": 1024,
                "lambda_timeout": 90,
                "log_retention_days": 30,
                "api_throttling_burst_limit": 20,
                "api_throttling_rate_limit": 40,
                "cors_allowed_origins": ["*"],
            },
        }
    elif name != "balanced":
        raise ValueError(f"Unknown preset: {name}")
    return cfg


def prod_approval_environment(cfg: dict[str, Any]) -> str:
    """Resolve the workflow environment used to express the approval policy."""

    return PROD_APPROVAL_ENVIRONMENT if cfg["use_prod_approval_environment"] else NO_APPROVAL_ENVIRONMENT


def apply_cors_policy(cfg: dict[str, Any], strict: bool) -> None:
    """Apply explicit per-environment origins or wildcard demo origins in place."""

    for env_name, env_cfg in cfg["environments"].items():
        env_cfg["cors_allowed_origins"] = list(STRICT_CORS_ORIGINS[env_name]) if strict else ["*"]


def uses_strict_cors(cfg: dict[str, Any]) -> bool:
    """Return whether every environment matches the reference strict policy."""

    return all(cfg["environments"][env_name]["cors_allowed_origins"] == STRICT_CORS_ORIGINS[env_name] for env_name in ENVIRONMENTS)


# Each catalog entry maps one control across CLI settings, Terraform, GitHub,
# AWS, scanners, and the evidence an operator should retain.
CONTROL_CATALOG = [
    Control(
        id="oidc",
        title="GitHub OIDC",
        cli_options=("devsecops github setup --deploy-role-arn", "devsecops github setup --plan-role-arn"),
        terraform=("Uses AWS provider credentials supplied by GitHub Actions OIDC-assumed roles.",),
        github=("Job permissions include id-token: write only on AWS jobs.", "aws-actions/configure-aws-credentials assumes role secrets."),
        aws=("IAM OIDC provider token.actions.githubusercontent.com.", "Separate deploy and plan IAM role trust policies."),
        scanners=("None; this is an identity and credential control.",),
        audit_evidence=("GitHub workflow permissions", "Configured AWS_ROLE_TO_ASSUME_ARN and AWS_PLAN_ROLE_TO_ASSUME_ARN secrets"),
        guidance="Avoid long-lived AWS keys in GitHub. Scope trust policy subjects to the repository, branch, and workflow usage.",
    ),
    Control(
        id="approval-gate",
        title="Production Approval Gate",
        cli_options=("use_prod_approval_environment", "devsecops compose", "devsecops preset apply"),
        terraform=("No Terraform variable; this is enforced before Terraform apply starts.",),
        github=("deploy-main uses environment: vars.PROD_APPROVAL_ENVIRONMENT || 'prod'.", "Deploy only runs on workflow_dispatch deploy/prod from main."),
        aws=("Prevents unreviewed production AWS mutations by gating the deploy job before credentials are issued.",),
        scanners=("None; this is a release authorization control.",),
        audit_evidence=("PROD_APPROVAL_ENVIRONMENT repository variable", "deploy-main environment name", "Config validation policy check"),
        guidance="Keep the value set to prod or another protected GitHub Environment with required reviewers.",
    ),
    Control(
        id="plan-role",
        title="Separate AWS Plan Role",
        cli_options=("use_separate_aws_plan_role", "devsecops github setup --plan-role-arn"),
        terraform=("Terraform plan uses backend state access and read-only refresh permissions.",),
        github=("Terraform Plan job fails when AWS_PLAN_ROLE_TO_ASSUME_ARN is missing.", "No deploy-role fallback is generated."),
        aws=("Plan role should read state, acquire locks, and refresh resources without mutating workload infrastructure.",),
        scanners=("Trivy IaC scan runs before AWS-backed planning.",),
        audit_evidence=("Require separate AWS plan role workflow step", "AWS_PLAN_ROLE_TO_ASSUME_ARN secret", "Branch protection required Terraform Plan check"),
        guidance="Use a lower-privilege plan role. Do not reuse the deploy role for pull request planning.",
    ),
    Control(
        id="state-lock",
        title="Terraform State Lock",
        cli_options=("backend.bucket", "backend.lock_table", "backend.region", "devsecops terraform bootstrap"),
        terraform=("Rendered backend.tf uses S3 with encrypt=true and DynamoDB locking.", "terraform/bootstrap creates the bucket and lock table."),
        github=("Plan and deploy jobs run terraform init against the configured backend.",),
        aws=("S3 stores encrypted Terraform state.", "DynamoDB lock table prevents concurrent state writes."),
        scanners=("Trivy scans Terraform backend-adjacent IaC for high and critical findings.",),
        audit_evidence=("dist/devsecops/backend.tf", "backend settings in audit report", "Readiness backend checks"),
        guidance="Use a dedicated state bucket and lock table with access limited to plan/deploy roles.",
    ),
    Control(
        id="immutable-image",
        title="Immutable Lambda Image",
        cli_options=("lambda_image_uri", "devsecops preflight --image-uri", "devsecops config set lambda_image_uri"),
        terraform=("lambda_image_uri validation rejects missing production values and mutable latest/bootstrap tags.", "Lambda module precondition prevents apply without an immutable image."),
        github=("Deploy job requires LAMBDA_IMAGE_URI and rejects latest/bootstrap.", "Rollback captures the previous Lambda image URI."),
        aws=("Lambda function code is updated to the configured immutable image.", "ECR image region is checked by CLI preflight."),
        scanners=("Snyk scans the configured image when ENABLE_SNYK_SCAN=true.",),
        audit_evidence=("LAMBDA_IMAGE_URI repository variable", "Terraform variable validation", "Preflight checks"),
        guidance="Use an image digest or an immutable release tag. Do not deploy latest, bootstrap, or moving tags.",
    ),
    Control(
        id="api-authorization",
        title="API Authorization",
        cli_options=("api_authorization_type", "API_AUTHORIZATION_TYPE", "devsecops health --aws-sigv4"),
        terraform=("API Gateway route authorization defaults to AWS_IAM.", "Terraform validation accepts only AWS_IAM or NONE."),
        github=("Deploy health validation signs AWS_IAM requests with SigV4.", "OWASP ZAP runs only when API_AUTHORIZATION_TYPE=NONE."),
        aws=("API Gateway requires IAM-signed requests unless explicitly configured public.",),
        scanners=("Trivy scans API Gateway route authorization.",),
        audit_evidence=("API_AUTHORIZATION_TYPE repository variable", "Terraform api_authorization_type variable", "Health validation evidence"),
        guidance="Keep AWS_IAM for production. Use NONE only for demos or intentionally public non-sensitive APIs.",
    ),
    Control(
        id="cors",
        title="Production CORS",
        cli_options=("environments.<env>.cors_allowed_origins", "devsecops compose strict CORS", "devsecops preset apply strict"),
        terraform=("environment_config passes CORS origins to the API Gateway module.", "Terraform validation rejects wildcard prod CORS."),
        github=("Generated tfvars are consumed by plan and deploy workflow Terraform runs.",),
        aws=("API Gateway HTTP API cors_configuration.allow_origins is set from Terraform.",),
        scanners=("Trivy scans API Gateway IaC for configuration findings.",),
        audit_evidence=("terraform/generated.auto.tfvars", "Audit control state", "Config validation policy check"),
        guidance="Use explicit HTTPS origins for production. Wildcard CORS is only acceptable for disposable demos.",
    ),
    Control(
        id="iac-scan",
        title="IaC Scan",
        cli_options=("Always on in the tracked workflow",),
        terraform=("Scans Terraform root and modules before plan/apply jobs.",),
        github=("Security and Terraform Validate runs aquasecurity/trivy-action with HIGH,CRITICAL severity.",),
        aws=("Blocks known high-risk IaC findings before AWS resources are changed.",),
        scanners=("Trivy config scan.",),
        audit_evidence=("Security and Terraform Validate workflow result", "Trivy action configuration"),
        guidance="Keep the validation job required in branch protection.",
    ),
    Control(
        id="snyk",
        title="Snyk Container Scan",
        cli_options=("enable_snyk_scan", "devsecops compose", "devsecops preset apply strict"),
        terraform=("No Terraform variable; scan gates deploy before Terraform apply.",),
        github=("Deploy job requires SNYK_TOKEN when ENABLE_SNYK_SCAN=true.", "Configured image is scanned before apply."),
        aws=("ECR login is used to read the configured image for scanning.",),
        scanners=("Snyk container test with high severity threshold.",),
        audit_evidence=("ENABLE_SNYK_SCAN repository variable", "SNYK_TOKEN secret readiness", "Deploy workflow Snyk steps"),
        guidance="Enable for production images and configure SNYK_TOKEN in the repository or organization.",
    ),
    Control(
        id="health-validation",
        title="HTTP Health Validation",
        cli_options=("enable_http_validation", "devsecops health --aws-sigv4", "devsecops compose"),
        terraform=("Outputs api_gateway_health_url for the deployed API Gateway endpoint.",),
        github=("Deploy job curls /health when ENABLE_HTTP_VALIDATION=true and signs AWS_IAM requests.", "Rollback runs when enabled validation fails."),
        aws=("API Gateway invokes Lambda through the deployed endpoint.",),
        scanners=("None; this is a smoke validation gate.",),
        audit_evidence=("ENABLE_HTTP_VALIDATION repository variable", "api_gateway_health_url Terraform output", "Health command output"),
        guidance="Enable once the workload implements GET /health with a non-sensitive successful response.",
    ),
    Control(
        id="dast",
        title="DAST",
        cli_options=("enable_dast", "devsecops compose", "devsecops preset apply strict"),
        terraform=("Outputs api_gateway_invoke_url for scanner target discovery.",),
        github=("Deploy job runs zaproxy/action-baseline only when ENABLE_DAST=true and API_AUTHORIZATION_TYPE=NONE.", "Rollback runs when enabled DAST fails."),
        aws=("Scans an explicitly public API Gateway invoke URL.",),
        scanners=("OWASP ZAP baseline passive scan.",),
        audit_evidence=("ENABLE_DAST repository variable", "ZAP baseline workflow step", "Scanner artifact zap-baseline-prod"),
        guidance="Enable only when the live API surface is explicitly public and safe for passive unauthenticated scanning.",
    ),
    Control(
        id="rollback",
        title="Deployment Rollback",
        cli_options=("devsecops deploy status", "devsecops deploy logs --failed", "devsecops deploy rollback"),
        terraform=("Re-applies Terraform with the previous Lambda image URI after rollback.",),
        github=("Deploy job captures the current image for automatic failure recovery; operator rollback uses the same protected workflow and environment.",),
        aws=("The protected workflow updates Lambda to the validated previous or explicitly selected immutable image.",),
        scanners=("Rollback is triggered by failed Snyk, health, or DAST gates when applicable.",),
        audit_evidence=("Deployment journal run/image metadata", "Deploy workflow rollback step", "GitHub Actions run logs", "AWS Lambda image after rollback"),
        guidance="Treat workflow rollback as cloud deployment rollback; local snapshot restore is separate.",
    ),
    Control(
        id="audit-report",
        title="Audit Evidence Report",
        cli_options=("devsecops report --format json", "devsecops report --format markdown"),
        terraform=("Includes generated Terraform variable and backend control mappings.",),
        github=("Can be attached to pull requests, workflow artifacts, or release records.",),
        aws=("Summarizes role guidance and AWS-facing control evidence.",),
        scanners=("Records scanner control states and readiness checks.",),
        audit_evidence=("dist/devsecops/audit-report.json", "dist/devsecops/readiness-report.md"),
        guidance="Generate after config/render/readiness changes and attach the JSON to review or release evidence.",
    ),
]

CONTROL_ALIASES = {
    "all": "all",
    "api-auth": "api-authorization",
    "api-authorization": "api-authorization",
    "approval": "approval-gate",
    "approval-gates": "approval-gate",
    "backend": "state-lock",
    "container-scan": "snyk",
    "health": "health-validation",
    "http-validation": "health-validation",
    "image": "immutable-image",
    "immutable-images": "immutable-image",
    "plan": "plan-role",
    "plan-role": "plan-role",
    "prod-approval": "approval-gate",
    "production-approval": "approval-gate",
    "report": "audit-report",
    "trivy": "iac-scan",
    "zap": "dast",
}


def control_catalog() -> list[Control]:
    """Return a shallow copy so callers cannot reorder the shared catalog."""

    return list(CONTROL_CATALOG)


def normalize_control_topic(topic: str) -> str:
    """Normalize user-facing control aliases into canonical identifiers."""

    normalized = topic.strip().lower().replace("_", "-")
    return CONTROL_ALIASES.get(normalized, normalized)


def control_by_id(topic: str) -> Control | None:
    """Resolve a canonical or aliased topic to its control definition."""

    normalized = normalize_control_topic(topic)
    return next((control for control in CONTROL_CATALOG if control.id == normalized), None)


def has_wildcard_cors(origins: Any) -> bool:
    """Safely detect a wildcard in an otherwise untrusted origins value."""

    return isinstance(origins, list) and any(str(origin).strip() == "*" for origin in origins)


def control_state(cfg: dict[str, Any], control_id: str) -> str:
    """Summarize one control as ON, OFF, RISK, TODO, or AVAILABLE.

    These labels describe configured posture, not live provider evidence;
    readiness collectors perform the external verification separately.
    """

    if control_id in {"oidc", "state-lock", "iac-scan", "rollback"}:
        return "ON"
    if control_id == "approval-gate":
        return "ON" if cfg["use_prod_approval_environment"] else "RISK"
    if control_id == "plan-role":
        return "ON" if cfg["use_separate_aws_plan_role"] else "RISK"
    if control_id == "immutable-image":
        image_uri = str(cfg.get("lambda_image_uri", ""))
        if image_uri and is_immutable_image(image_uri):
            return "ON"
        return "RISK" if image_uri else "TODO"
    if control_id == "api-authorization":
        return "ON" if cfg.get("api_authorization_type") == "AWS_IAM" else "RISK"
    if control_id == "cors":
        return "RISK" if has_wildcard_cors(cfg["environments"]["prod"]["cors_allowed_origins"]) else "ON"
    if control_id == "snyk":
        return "ON" if cfg["enable_snyk_scan"] else "OFF"
    if control_id == "health-validation":
        return "ON" if cfg["enable_http_validation"] else "RISK"
    if control_id == "dast":
        return "ON" if cfg["enable_dast"] else "OFF"
    if control_id == "audit-report":
        return "AVAILABLE"
    return "UNKNOWN"


def control_to_dict(control: Control, cfg: dict[str, Any]) -> dict[str, Any]:
    """Serialize a control definition with its configuration-derived state."""

    return {
        "id": control.id,
        "title": control.title,
        "state": control_state(cfg, control.id),
        "cli_options": list(control.cli_options),
        "terraform": list(control.terraform),
        "github": list(control.github),
        "aws": list(control.aws),
        "scanners": list(control.scanners),
        "audit_evidence": list(control.audit_evidence),
        "guidance": control.guidance,
    }


def compose_config(current: dict[str, Any], answers: dict[str, bool]) -> dict[str, Any]:
    """Apply interactive security answers without discarding existing settings."""

    cfg = deep_merge(default_config(), current)
    cfg["enable_snyk_scan"] = bool(answers["enable_snyk_scan"])
    cfg["enable_dast"] = bool(answers["enable_dast"])
    cfg["enable_http_validation"] = bool(answers["enable_http_validation"])
    cfg["use_prod_approval_environment"] = bool(answers["use_prod_approval_environment"])
    cfg["use_separate_aws_plan_role"] = bool(answers["use_separate_aws_plan_role"])
    apply_cors_policy(cfg, strict=bool(answers["use_strict_cors"]))
    return cfg


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively overlay mappings and return a new merged configuration.

    Dictionary branches are copied recursively; scalar and list values from
    ``override`` replace the corresponding baseline value as one unit.
    """

    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def migrate_config(raw_cfg: dict[str, Any]) -> dict[str, Any]:
    """Upgrade supported legacy config data or reject a future schema.

    Refusing future versions protects newer fields from being normalized away
    by an older CLI before it writes generated files.
    """

    cfg = dict(raw_cfg)
    version = cfg.get("schema_version", 1)
    if not isinstance(version, int):
        return cfg
    if version > CONFIG_SCHEMA_VERSION:
        raise ConfigMigrationError(
            f"{CONFIG_FILE} uses schema_version = {version}, but this CLI supports schema_version = {CONFIG_SCHEMA_VERSION}. "
            "Upgrade the devsecops CLI before rendering or changing CLI-owned files."
        )
    while version < CONFIG_SCHEMA_VERSION:
        # Future migrations should update cfg in place and increment version.
        version += 1
        cfg["schema_version"] = version
    return cfg


def normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Migrate configuration and fill missing fields from current defaults."""

    normalized = deep_merge(default_config(), migrate_config(cfg))
    normalized["schema_version"] = normalized.get("schema_version", CONFIG_SCHEMA_VERSION)
    return normalized


def load_config(root: Path) -> dict[str, Any]:
    """Load and normalize TOML, or return fresh defaults when it is absent."""

    path = config_path(root)
    if not path.exists():
        return default_config()
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required to read TOML config files.")
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return normalize_config(loaded)


def toml_value(value: Any) -> str:
    """Serialize the limited scalar/list value types used by this schema."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_config_toml(cfg: dict[str, Any]) -> str:
    """Serialize normalized configuration in a stable, human-readable order.

    Deterministic ordering keeps diffs, snapshots, and generated-file tests
    meaningful even though input dictionaries may have different insertion
    histories.
    """

    normalized = normalize_config(cfg)
    lines = [
        "# DevSecOps Pipeline Kit local source configuration",
        "# Managed by: devsecops CLI. Do not commit this file.",
        "",
    ]
    for key in [
        "schema_version",
        "project_name",
        "aws_region",
        "lambda_image_uri",
        "enable_snyk_scan",
        "enable_http_validation",
        "enable_dast",
        "api_authorization_type",
        "use_prod_approval_environment",
        "use_separate_aws_plan_role",
        "terraform_admin_role_name",
    ]:
        lines.append(f"{key} = {toml_value(normalized[key])}")

    lines.append("")
    lines.append("[backend]")
    for key, value in normalized["backend"].items():
        lines.append(f"{key} = {toml_value(value)}")

    for env_name, env_cfg in normalized["environments"].items():
        lines.append("")
        lines.append(f"[environments.{env_name}]")
        for key, value in env_cfg.items():
            lines.append(f"{key} = {toml_value(value)}")

    lines.append("")
    return "\n".join(lines)


def write_config(root: Path, cfg: dict[str, Any]) -> None:
    """Write normalized configuration to its canonical local path."""

    config_path(root).write_text(dump_config_toml(cfg), encoding="utf-8")


def clean_config(preset_name: str = "balanced") -> dict[str, Any]:
    """Return a normalized config containing only a known preset's values."""

    if preset_name not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_name}")
    return normalize_config(preset_config(preset_name))


def config_schema() -> dict[str, Any]:
    """Return the machine-readable schema and migration contract."""

    environment_fields = {
        "lambda_memory_size": {"type": "integer", "minimum": 128, "maximum": 10240},
        "lambda_timeout": {"type": "integer", "minimum": 1, "maximum": 900},
        "log_retention_days": {"type": "integer", "minimum": 1, "maximum": 3653},
        "api_throttling_burst_limit": {"type": "integer", "minimum": 1, "maximum": 5000},
        "api_throttling_rate_limit": {"type": "integer", "minimum": 1, "maximum": 10000},
        "cors_allowed_origins": {"type": "array", "items": "string"},
    }
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "config_file": CONFIG_FILE,
        "secrets_allowed": False,
        "presets": PRESET_ORDER,
        "migration": CONFIG_MIGRATION_CONTRACT,
        "fields": {
            "schema_version": {"type": "integer", "current": CONFIG_SCHEMA_VERSION},
            "project_name": {"type": "string", "pattern": PROJECT_NAME_RE.pattern},
            "aws_region": {"type": "string", "pattern": AWS_REGION_RE.pattern},
            "lambda_image_uri": {"type": "string", SENSITIVITY_LABEL: False},
            "enable_snyk_scan": {"type": "boolean"},
            "enable_http_validation": {"type": "boolean"},
            "enable_dast": {"type": "boolean"},
            "api_authorization_type": {"type": "string", "enum": sorted(API_AUTHORIZATION_TYPES)},
            "use_prod_approval_environment": {"type": "boolean"},
            "use_separate_aws_plan_role": {"type": "boolean"},
            "terraform_admin_role_name": {"type": "string", SENSITIVITY_LABEL: False},
            "backend": {
                "type": "object",
                "fields": {
                    "bucket": {"type": "string"},
                    "key": {"type": "string"},
                    "region": {"type": "string", "pattern": AWS_REGION_RE.pattern},
                    "lock_table": {"type": "string"},
                    "workspace_key_prefix": {"type": "string"},
                },
            },
            "environments": {
                "type": "object",
                "required": ENVIRONMENTS,
                "fields": {env_name: environment_fields for env_name in ENVIRONMENTS},
            },
        },
    }


def config_schema_markdown() -> str:
    """Render the public configuration schema for human review."""

    rows = [
        ["schema_version", "integer", str(CONFIG_SCHEMA_VERSION)],
        ["project_name", "string", PROJECT_NAME_RE.pattern],
        ["aws_region", "string", AWS_REGION_RE.pattern],
        ["lambda_image_uri", "string", "Immutable image URI; not a secret."],
        ["enable_snyk_scan", "boolean", ""],
        ["enable_http_validation", "boolean", ""],
        ["enable_dast", "boolean", ""],
        ["api_authorization_type", "string", "AWS_IAM or NONE. Defaults to AWS_IAM."],
        ["use_prod_approval_environment", "boolean", ""],
        ["use_separate_aws_plan_role", "boolean", ""],
        ["terraform_admin_role_name", "string", "Optional role name; not a secret."],
        ["backend.*", "object", "S3 backend names and region."],
        ["environments.<env>.*", "object", "dev, staging, and prod settings."],
    ]
    return "\n\n".join(
        [
            "# DevSecOps Config Schema",
            f"Current schema version: `{CONFIG_SCHEMA_VERSION}`",
            "Secrets are not allowed in `.devsecops-pipeline.toml`.",
            markdown_table(["Field", "Type", "Notes"], rows),
            "## Migration Contract",
            "Legacy files without `schema_version` are treated as schema version `1` and migrated to the current version.",
            "Configs with a future `schema_version` are refused until the CLI is upgraded.",
            "Schema-changing releases must update `migrate_config`, tests, release notes, generated-artifact compatibility notes, and this schema output before shipping.",
            "Snapshot restore can recover only local CLI-owned files; it never mutates AWS, Terraform state, GitHub settings, or deployed Lambda images.",
            "",
        ]
    )


def canonical_config_text(cfg: dict[str, Any]) -> str:
    """Return canonical TOML text used for comparisons and snapshots."""

    return dump_config_toml(cfg)


def unified_text_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
    """Build a newline-terminated unified diff, or an empty string if equal."""

    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    return "\n".join(diff_lines) + ("\n" if diff_lines else "")


def config_file_diff(root: Path) -> str:
    """Compare the on-disk config with its normalized canonical form."""

    path = config_path(root)
    current_text = path.read_text(encoding="utf-8") if path.exists() else ""
    clean_text = canonical_config_text(load_config(root))
    return unified_text_diff(current_text, clean_text, str(path), f"{CONFIG_FILE} (canonical)")


def config_preset_diff(root: Path, preset_name: str) -> str:
    """Compare current normalized configuration with a named clean preset."""

    current_text = canonical_config_text(load_config(root))
    preset_text = canonical_config_text(clean_config(preset_name))
    return unified_text_diff(current_text, preset_text, CONFIG_FILE, f"preset:{preset_name}")


def parse_config_value(raw_value: str, current_value: Any) -> Any:
    """Parse CLI text according to the existing setting's schema-like type."""

    if isinstance(current_value, bool):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        raise ValueError("Expected boolean: true/false.")
    if isinstance(current_value, int):
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError("Expected integer.") from exc
    if isinstance(current_value, list):
        if not raw_value.strip():
            return []
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    return raw_value


def nested_get(cfg: dict[str, Any], dotted_path: str) -> Any:
    """Read an existing nested setting addressed by a dotted path."""

    cursor: Any = cfg
    for part in dotted_path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(dotted_path)
        cursor = cursor[part]
    return cursor


def nested_set(cfg: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Replace an existing dotted-path setting without creating unknown keys."""

    cursor: Any = cfg
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(dotted_path)
        cursor = cursor[part]
    if not isinstance(cursor, dict) or parts[-1] not in cursor:
        raise KeyError(dotted_path)
    cursor[parts[-1]] = value


def validate_config(cfg: dict[str, Any]) -> list[Check]:
    """Validate schema values and production policy as structured checks.

    Malformed or out-of-range values are failures.  Valid settings that weaken
    the recommended production posture remain warnings so demo configurations
    can still be represented and inspected explicitly.
    """

    checks: list[Check] = []
    schema_version = cfg.get("schema_version")
    checks.append(
        Check(
            "Config schema version",
            "OK" if schema_version == CONFIG_SCHEMA_VERSION else "FAIL",
            str(schema_version)
            if schema_version == CONFIG_SCHEMA_VERSION
            else f"Expected schema_version = {CONFIG_SCHEMA_VERSION}.",
        )
    )
    checks.append(
        Check(
            "Config project name",
            "OK" if PROJECT_NAME_RE.match(cfg["project_name"]) else "FAIL",
            cfg["project_name"],
        )
    )
    checks.append(
        Check(
            "Config AWS region",
            "OK" if AWS_REGION_RE.match(cfg["aws_region"]) else "WARN",
            cfg["aws_region"],
        )
    )
    for key in [
        "enable_snyk_scan",
        "enable_http_validation",
        "enable_dast",
        "use_prod_approval_environment",
        "use_separate_aws_plan_role",
    ]:
        checks.append(
            Check(
                f"Config {key}",
                "OK" if isinstance(cfg.get(key), bool) else "FAIL",
                str(cfg.get(key)) if isinstance(cfg.get(key), bool) else "Expected boolean.",
            )
        )
    image_uri = str(cfg.get("lambda_image_uri", ""))
    if image_uri:
        checks.append(
            Check(
                "Lambda image immutability policy",
                "OK" if is_immutable_image(image_uri) else "FAIL",
                image_uri if is_immutable_image(image_uri) else "Use an immutable tag or digest; latest/bootstrap are not allowed.",
            )
        )
    else:
        checks.append(Check("Lambda image immutability policy", "WARN", "Required before production deploy."))
    for env_name, env_cfg in cfg["environments"].items():
        numeric_rules = {
            "lambda_memory_size": (128, 10240),
            "lambda_timeout": (1, 900),
            "log_retention_days": (1, 3653),
            "api_throttling_burst_limit": (1, 5000),
            "api_throttling_rate_limit": (1, 10000),
        }
        for setting, limits in numeric_rules.items():
            value = env_cfg[setting]
            lower, upper = limits
            status = "OK" if isinstance(value, int) and lower <= value <= upper else "FAIL"
            checks.append(
                Check(
                    f"{env_name}.{setting}",
                    status,
                    str(value) if status == "OK" else f"{value} outside {lower}-{upper}.",
                )
            )
        origins = env_cfg["cors_allowed_origins"]
        valid_origins = isinstance(origins, list) and all(isinstance(item, str) and item for item in origins)
        checks.append(
            Check(
                f"{env_name}.cors_allowed_origins",
                "OK" if valid_origins else "FAIL",
                ",".join(origins) if valid_origins else "Expected non-empty list of strings.",
            )
        )
    prod_origins = cfg["environments"].get("prod", {}).get("cors_allowed_origins", [])
    prod_origins_detail = ",".join(prod_origins) if isinstance(prod_origins, list) and all(isinstance(item, str) for item in prod_origins) else "Expected non-empty list of strings."
    checks.append(
        Check(
            "Production CORS policy",
            "WARN" if has_wildcard_cors(prod_origins) else "OK",
            "Wildcard CORS is not production-safe. Use explicit HTTPS origins."
            if has_wildcard_cors(prod_origins)
            else prod_origins_detail,
        )
    )
    api_authorization_type = str(cfg.get("api_authorization_type", "AWS_IAM"))
    if api_authorization_type not in API_AUTHORIZATION_TYPES:
        checks.append(
            Check(
                "API authorization policy",
                "FAIL",
                f"Expected one of {', '.join(sorted(API_AUTHORIZATION_TYPES))}.",
            )
        )
    else:
        checks.append(
            Check(
                "API authorization policy",
                "OK" if api_authorization_type == "AWS_IAM" else "WARN",
                "API Gateway routes require AWS_IAM signed requests."
                if api_authorization_type == "AWS_IAM"
                else "API Gateway routes are public; use only for demo or non-sensitive workloads.",
            )
        )
    checks.append(
        Check(
            "Production approval gate policy",
            "OK" if cfg["use_prod_approval_environment"] else "WARN",
            f"GitHub environment: {prod_approval_environment(cfg)}"
            if cfg["use_prod_approval_environment"]
            else "Production deploy approval is disabled in local config.",
        )
    )
    checks.append(
        Check(
            "Separate plan role policy",
            "OK" if cfg["use_separate_aws_plan_role"] else "WARN",
            "AWS_PLAN_ROLE_TO_ASSUME_ARN is required and deploy-role fallback is disabled."
            if cfg["use_separate_aws_plan_role"]
            else "Local config disables the separate plan-role posture; workflow still requires AWS_PLAN_ROLE_TO_ASSUME_ARN.",
        )
    )
    checks.append(
        Check(
            "Deployment validation policy",
            "OK" if cfg["enable_http_validation"] else "WARN",
            "HTTP /health validation is enabled."
            if cfg["enable_http_validation"]
            else "ENABLE_HTTP_VALIDATION is false; strict production validation requires a post-deploy health gate.",
        )
    )
    return checks

__all__ = [
    "API_AUTHORIZATION_TYPES",
    "AWS_REGION_RE",
    "CONFIG_SCHEMA_VERSION",
    "CONFIG_SET_PATHS",
    "CONTROL_ALIASES",
    "CONTROL_CATALOG",
    "ENVIRONMENTS",
    "NO_APPROVAL_ENVIRONMENT",
    "PRESETS",
    "PRESET_DESCRIPTIONS",
    "PRESET_ORDER",
    "PRESET_POSTURES",
    "PRESET_POSTURE_LABELS",
    "PROD_APPROVAL_ENVIRONMENT",
    "PROJECT_NAME_RE",
    "STRICT_CORS_ORIGINS",
    "apply_cors_policy",
    "canonical_config_text",
    "clean_config",
    "compose_config",
    "config_file_diff",
    "config_path",
    "config_preset_diff",
    "config_schema",
    "config_schema_markdown",
    "control_by_id",
    "control_catalog",
    "control_state",
    "control_to_dict",
    "deep_merge",
    "default_config",
    "dump_config_toml",
    "has_wildcard_cors",
    "load_config",
    "migrate_config",
    "nested_get",
    "nested_set",
    "normalize_config",
    "normalize_control_topic",
    "parse_config_value",
    "preset_config",
    "prod_approval_environment",
    "toml_value",
    "unified_text_diff",
    "uses_strict_cors",
    "validate_config",
    "write_config",
]
