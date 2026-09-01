"""Pure readiness scoring, categorization, remediation, and serialization.

This module has no filesystem or provider access.  It converts already-observed
checks into scores, gates, actionable guidance, JSON contracts, and stable exit
codes that can be shared by every CLI presentation.
"""

from __future__ import annotations

from typing import Any

from .models import Check


CONTRACT_SCHEMA_VERSION = 1
EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_MISSING_EXTERNAL_TOOL = 2
EXIT_AUTH_FAILED = 3
READINESS_CATEGORIES = ["Local", "Terraform", "GitHub", "AWS", "Security", "Deployment"]


def readiness_score(checks: list[Check]) -> int:
    """Return a weighted score over checks explicitly included in scoring.

    ``OK`` earns full credit, ``WARN``/``INFO`` half credit, and ``FAIL`` no
    credit.  An empty scored set is treated as complete rather than undefined.
    """

    scored = [check for check in checks if check.scored]
    if not scored:
        return 100
    points = 0
    for check in scored:
        if check.status == "OK":
            points += 2
        elif check.status in {"WARN", "INFO"}:
            points += 1
    return round(points / (len(scored) * 2) * 100)


def readiness_action_detail_for_check(check: Check) -> str:
    """Map a known check name to its most direct remediation command.

    The fallback preserves provider detail for new checks until a dedicated
    action is added, so unknown observations still remain useful.
    """

    if check.name == "Local config":
        return "Run `devsecops config new --preset balanced` or open `devsecops menu`."
    if check.name == "Project name":
        return "Set a lowercase 3-32 character project name with `devsecops set project_name <name>`."
    if check.name == "Project files":
        return "Restore the required Terraform and GitHub workflow files."
    if check.name == "`git` CLI":
        return "Install Git and make sure it is available on PATH."
    if check.name == "`terraform` CLI":
        return "Install Terraform and make sure it is available on PATH."
    if check.name == "`aws` CLI":
        return "Install AWS CLI before cloud bootstrap or AWS identity checks."
    if check.name == "AWS CLI":
        return "Install AWS CLI and make sure `aws` is available on PATH."
    if check.name == "State bucket":
        return "Set `backend.bucket`, run `devsecops render`, then `devsecops bootstrap --apply`."
    if check.name == "Lock table":
        return "Set `backend.lock_table`, run `devsecops render`, then `devsecops bootstrap --apply`."
    if check.name == "ECR repository":
        return "Run a Terraform plan/apply path that creates the ECR repository before publishing images."
    if check.name == "Lambda execution role":
        return "Run a Terraform apply path that creates the Lambda execution role, then re-run `devsecops aws-doctor`."
    if check.name == "Lambda function":
        return "Run `devsecops deploy prod` after setting an immutable `lambda_image_uri`."
    if check.name == "API Gateway":
        return "Run a successful workload deploy, then inspect Terraform output `api_gateway_invoke_url`."
    if check.name == "CloudWatch log group":
        return "Deploy the Lambda function; Terraform creates the log group before Lambda creation."
    if check.name == "Configured ECR image":
        return "Publish the configured ECR image or update `lambda_image_uri` to an existing immutable image."
    if check.name == "Lambda image URI":
        return "Set `LAMBDA_IMAGE_URI` to an immutable image with `devsecops set lambda_image_uri <image-uri> --render`."
    if check.name == "Lambda image immutability policy":
        return "Set `lambda_image_uri` to an immutable image tag or digest and rerun `devsecops config validate --strict`."
    if check.name == "Lambda image shape":
        return "Use an ECR Lambda image URI such as `123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-abc123`."
    if check.name == "Lambda image immutability":
        return "Use an immutable tag or digest, then run `devsecops preflight --image-uri <image-uri>`."
    if check.name == "Lambda image region":
        return "Publish or select an image in the same region as `aws_region`, then rerun `devsecops preflight`."
    if check.name == "Backend bucket":
        return "Set `backend.bucket` to a real S3 state bucket and run `devsecops render`."
    if check.name == "Config schema":
        return "Run `devsecops validate-config`, fix invalid values, then run `devsecops render`."
    if check.name == "Security policy posture":
        return "Run `devsecops config validate --strict` and fix the listed production policy gaps."
    if check.name == "Production CORS policy":
        return "Set `environments.prod.cors_allowed_origins` to explicit HTTPS origins and run `devsecops render`."
    if check.name == "Production approval gate policy":
        return "Set `use_prod_approval_environment` to true and protect the `prod` GitHub Environment."
    if check.name == "Separate plan role policy":
        return "Set `use_separate_aws_plan_role` to true and configure `AWS_PLAN_ROLE_TO_ASSUME_ARN`."
    if check.name == "Deployment validation policy":
        return "Set `enable_http_validation` to true after the workload implements `GET /health`."
    if check.name == "Rendered tfvars":
        return "Run `devsecops render`."
    if check.name == "Git branch":
        return "Switch to `main` when checking production deploy readiness."
    if check.name in {"Terraform validate", "Bootstrap validate"}:
        return "Run `terraform validate` in the reported module and fix the Terraform error."
    if check.name == "AWS identity":
        return "Configure AWS credentials and verify with `aws sts get-caller-identity`."
    if check.name == "AWS outputs":
        return "Install/configure AWS CLI, then run `devsecops aws outputs --environment prod` again."
    if check.name == "Health endpoint URL":
        return "Pass `--url <health-url>` or deploy once so Terraform output `api_gateway_health_url` exists."
    if check.name == "Health response":
        return "Inspect Lambda logs and workload `/health` behavior, then rerun `devsecops health`."
    if check.name == "Concurrent production run":
        return "Run `devsecops deploy status --watch` and wait for the active production workflow to finish."
    if check.name == "Rollback changes image":
        return "Inspect `devsecops aws outputs --environment prod`; choose a different known-good immutable image only if a change is required."
    if check.name == "Protected deployment workflow":
        return "Restore `.github/workflows/deploy.yml` from the project template before dispatching a rollback."
    return check.detail


def troubleshooting_anchor_for_check(check: Check) -> str:
    """Map a check to the closest troubleshooting section anchor."""

    name = check.name
    if name == "Local config":
        return "#local-config-is-missing"
    if name in {
        "Project name",
        "Config schema",
        "Security policy posture",
        "Lambda image immutability policy",
        "Production CORS policy",
        "Production approval gate policy",
        "Separate plan role policy",
        "Deployment validation policy",
    } or name.startswith("Config ") or "." in name:
        return "#config-validation-fails"
    if name == "Project files":
        return "#project-files-are-missing"
    if name == "`terraform` CLI":
        return "#terraform-cli-is-not-found"
    if name in {"`aws` CLI", "AWS CLI", "AWS identity"}:
        return "#aws-doctor-cannot-inspect-resources"
    if name == "AWS outputs":
        return "#check-aws-account-and-deployed-resources"
    if name.startswith("Health "):
        return "#health-check-returns-500"
    if name in {"Backend bucket", "State bucket", "Lock table", "Backend lock table"}:
        return "#readiness-says-backend-bucket-is-missing"
    if name in {
        "Lambda image URI",
        "Lambda image shape",
        "Lambda image immutability",
        "Lambda image region",
        "Configured ECR image",
    }:
        return "#lambda-image-uri-is-missing-or-invalid"
    if name == "`git` CLI" or name == "Git branch":
        return "#git-or-branch-readiness-fails"
    if name.startswith("GitHub") or name.endswith("secret") or name.endswith("variable"):
        return "#github-repository-variables-or-secrets-are-missing"
    if name.startswith("Branch `") or name.startswith("Required check") or name == "Protection details":
        return "#branch-protection-doctor-reports-missing-checks"
    if name in {"Terraform validate", "Bootstrap validate"}:
        return "#terraform-validation-fails"
    if name == "Concurrent production run":
        return "#deployment-command-reports-an-active-production-run"
    if name in {"Rollback changes image", "Protected deployment workflow"}:
        return "#deployment-command-cannot-find-a-run-or-rollback-target"
    return "#start-here"


def readiness_action_for_check(check: Check) -> str:
    """Combine direct remediation with its stable troubleshooting link."""

    action = readiness_action_detail_for_check(check)
    anchor = troubleshooting_anchor_for_check(check)
    return f"{action} See `docs/troubleshooting.md{anchor}`."


def readiness_gap_rows(checks: list[Check]) -> list[list[str]]:
    """Return actionable rows for non-OK checks that affect readiness."""

    return [
        [check.name, check.status, check.detail, readiness_action_for_check(check)]
        for check in checks
        if check.scored and check.status != "OK"
    ]


def readiness_category_for_check(check: Check) -> str:
    """Assign a check to one stable dashboard category by its contract name.

    New or purely local checks fall back to ``Local`` until explicitly mapped.
    """

    name = check.name
    if name.startswith("GitHub") or name.startswith("Branch `") or name.startswith("Required check"):
        return "GitHub"
    if name == "Protection details":
        return "GitHub"
    if name in {
        "`terraform` CLI",
        "Terraform validate",
        "Bootstrap validate",
        "Backend bucket",
        "Backend lock table",
        "Rendered tfvars",
        "State bucket",
        "Lock table",
    }:
        return "Terraform"
    if name in {
        "`aws` CLI",
        "AWS CLI",
        "AWS identity",
        "ECR repository",
        "Lambda execution role",
        "API Gateway",
        "CloudWatch log group",
    }:
        return "AWS"
    if name in {
        "Snyk container scan",
        "HTTP validation",
        "DAST",
        "Separate AWS plan role",
    }:
        return "Security"
    if name in {
        "Lambda image URI",
        "Configured ECR image",
        "Lambda function",
        "Prod approval environment",
        "Concurrent production run",
        "Rollback changes image",
        "Protected deployment workflow",
        "Production config policy",
        "Generated deployment helpers",
        "Project deployment files",
        "Current Lambda image",
    }:
        return "Deployment"
    return "Local"


def grouped_readiness_checks(checks: list[Check]) -> dict[str, list[Check]]:
    """Group checks while preserving category and input order."""

    grouped = {category: [] for category in READINESS_CATEGORIES}
    for check in checks:
        grouped[readiness_category_for_check(check)].append(check)
    return grouped


def readiness_score_for_category(checks: list[Check]) -> int | None:
    """Score all visible checks in one category, or return ``None`` if empty.

    Category summaries intentionally include informational, unscored checks;
    strict exits and the direct readiness score continue to honor ``scored``.
    """

    if not checks:
        return None
    points = 0
    for check in checks:
        if check.status == "OK":
            points += 2
        elif check.status in {"WARN", "INFO"}:
            points += 1
    return round(points / (len(checks) * 2) * 100)


def readiness_breakdown_rows(checks: list[Check], compact: bool = False) -> list[list[str]]:
    """Build compact gap counts or full status counts for each category."""

    grouped = grouped_readiness_checks(checks)
    rows: list[list[str]] = []
    for category in READINESS_CATEGORIES:
        category_checks = grouped[category]
        score = readiness_score_for_category(category_checks)
        score_text = "n/a" if score is None else f"{score}%"
        if compact:
            gaps = sum(1 for check in category_checks if check.status != "OK")
            rows.append([category, score_text, str(gaps)])
        else:
            status_counts = {
                "OK": sum(1 for check in category_checks if check.status == "OK"),
                "WARN": sum(1 for check in category_checks if check.status == "WARN"),
                "FAIL": sum(1 for check in category_checks if check.status == "FAIL"),
                "INFO": sum(1 for check in category_checks if check.status == "INFO"),
            }
            rows.append(
                [
                    category,
                    score_text,
                    str(status_counts["OK"]),
                    str(status_counts["WARN"]),
                    str(status_counts["FAIL"]),
                    str(status_counts["INFO"]),
                ]
            )
    return rows


def overall_breakdown_score(checks: list[Check]) -> int:
    """Return the macro-average of non-empty category scores."""

    scores = [score for score in (readiness_score_for_category(group) for group in grouped_readiness_checks(checks).values()) if score is not None]
    return round(sum(scores) / len(scores)) if scores else 100



def check_to_dict(check: Check) -> dict[str, Any]:
    """Serialize one check without losing its scoring participation flag."""

    return {
        "name": check.name,
        "status": check.status,
        "detail": check.detail,
        "scored": check.scored,
    }


def readiness_breakdown_dicts(checks: list[Check]) -> list[dict[str, Any]]:
    """Serialize category breakdown rows with numeric values."""

    rows = readiness_breakdown_rows(checks, compact=False)
    return [
        {
            "area": row[0],
            "score": int(row[1].rstrip("%")) if row[1].endswith("%") else None,
            "ok": int(row[2]),
            "warn": int(row[3]),
            "fail": int(row[4]),
            "info": int(row[5]),
        }
        for row in rows
    ]


def readiness_gap_dicts(checks: list[Check]) -> list[dict[str, str]]:
    """Serialize actionable readiness gaps for machine-readable output."""

    return [
        {"name": name, "status": status, "detail": detail, "action": action}
        for name, status, detail, action in readiness_gap_rows(checks)
    ]


def checks_payload(kind: str, checks: list[Check], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the shared versioned JSON envelope for check-based commands.

    ``score`` is weighted across scored checks, whereas
    ``overall_breakdown_score`` is the macro-average used by area dashboards.
    """

    payload: dict[str, Any] = {
        "kind": kind,
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "score": readiness_score(checks),
        "overall_breakdown_score": overall_breakdown_score(checks),
        "gates": readiness_gate_dicts(checks),
        "breakdown": readiness_breakdown_dicts(checks),
        "gaps": readiness_gap_dicts(checks),
        "checks": [check_to_dict(check) for check in checks],
    }
    if context:
        payload["context"] = context
    return payload


def check_status_by_name(checks: list[Check], name: str) -> str | None:
    """Return the first status for a named contract check, if present."""

    match = next((check for check in checks if check.name == name), None)
    return match.status if match else None


def readiness_gate_rows(checks: list[Check]) -> list[list[str]]:
    """Summarize local, source, production, and evidence readiness gates."""

    local_config_ok = check_status_by_name(checks, "Local config") == "OK" and check_status_by_name(checks, "Config schema") != "FAIL"
    project_files_ok = check_status_by_name(checks, "Project files") == "OK"
    production_gaps = [check for check in checks if check.scored and check.status != "OK"]
    release_ready = not production_gaps
    return [
        [
            "Local config",
            "OK" if local_config_ok else "Blocked",
            "Config exists and schema checks pass." if local_config_ok else "Create or fix local source config.",
        ],
        [
            "Project files",
            "OK" if project_files_ok else "Blocked",
            "Terraform and GitHub workflow files are present."
            if project_files_ok
            else "Run inside the DevSecOps pipeline repo/template or restore required files.",
        ],
        [
            "Production readiness",
            "OK" if not production_gaps else "Blocked",
            "No scored readiness gaps."
            if not production_gaps
            else f"{len(production_gaps)} scored gap(s) remain before production deploy.",
        ],
        [
            "Release evidence",
            "Ready" if release_ready else "Blocked",
            "Run `devsecops evidence collect --rc`."
            if release_ready
            else "Collect RC evidence only after production readiness is unblocked.",
        ],
    ]


def readiness_gate_dicts(checks: list[Check]) -> list[dict[str, str]]:
    """Serialize readiness gates without duplicating gate evaluation."""

    return [{"gate": gate, "status": status, "detail": detail} for gate, status, detail in readiness_gate_rows(checks)]



def strict_exit_code(checks: list[Check], strict: bool = False, fail_on_warn: bool = False) -> int:
    """Translate scored gaps into the stable strict-mode exit-code contract.

    Missing tools and authentication receive dedicated codes so automation can
    distinguish environmental prerequisites from configuration validation.
    """

    if not strict:
        return EXIT_OK
    scored_gaps = [
        check
        for check in checks
        if check.scored and (check.status != "OK" if fail_on_warn else check.status == "FAIL")
    ]
    if not scored_gaps:
        return EXIT_OK
    gap_text = "\n".join(f"{check.name} {check.detail}".lower() for check in scored_gaps)
    if "not found on path" in gap_text:
        return EXIT_MISSING_EXTERNAL_TOOL
    if "auth" in gap_text or "authenticated" in gap_text or "login" in gap_text:
        return EXIT_AUTH_FAILED
    return EXIT_VALIDATION_FAILED



__all__ = [
    "check_status_by_name",
    "check_to_dict",
    "checks_payload",
    "grouped_readiness_checks",
    "overall_breakdown_score",
    "readiness_action_detail_for_check",
    "readiness_action_for_check",
    "readiness_breakdown_dicts",
    "readiness_breakdown_rows",
    "readiness_category_for_check",
    "readiness_gap_dicts",
    "readiness_gap_rows",
    "readiness_gate_dicts",
    "readiness_gate_rows",
    "readiness_score",
    "readiness_score_for_category",
    "strict_exit_code",
    "troubleshooting_anchor_for_check",
]
