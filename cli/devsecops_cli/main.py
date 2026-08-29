#!/usr/bin/env python3
"""DevSecOps Pipeline Kit CLI.

This CLI is intentionally dependency-free so it can run before the project has
any Python environment configured. It uses a local TOML config and generates
ignored Terraform/GitHub helper artifacts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

from . import VERSION
from . import aws as _aws_adapter
from . import doctor as _doctor_service
from . import github as _github_adapter
from . import parser as _parser_builder
from . import context as _project_context_service
from . import snapshots as _snapshot_store
from .context import PRODUCTION_DEPLOY_COMMAND, missing_project_files, project_context
from .aws import (
    aws_sigv4_headers,
    aws_sigv4_signing_key,
    canonical_query_string,
    expected_api_gateway_name,
    expected_ecr_repository_name,
    expected_lambda_execution_role_name,
    expected_lambda_function_name,
    expected_lambda_log_group_name,
    expected_name_prefix,
    fetch_health_url,
    is_resource_missing,
    missing_or_error_detail,
)
from .config import (
    AWS_REGION_RE,
    CONFIG_MIGRATION_CONTRACT,
    CONFIG_SCHEMA_VERSION,
    CONFIG_SET_PATHS,
    ENVIRONMENTS,
    NO_APPROVAL_ENVIRONMENT,
    PRESETS,
    PRESET_DESCRIPTIONS,
    PRESET_ORDER,
    PRESET_POSTURES,
    PRESET_POSTURE_LABELS,
    PROJECT_NAME_RE,
    SENSITIVITY_LABEL,
    apply_cors_policy,
    canonical_config_text,
    clean_config,
    compose_config,
    config_file_diff,
    config_path,
    config_preset_diff,
    config_schema,
    config_schema_markdown,
    control_by_id,
    control_catalog,
    control_state,
    control_to_dict,
    deep_merge,
    default_config,
    dump_config_toml,
    has_wildcard_cors,
    load_config,
    nested_get,
    nested_set,
    normalize_config,
    normalize_control_topic,
    parse_config_value,
    preset_config,
    prod_approval_environment,
    uses_strict_cors,
    validate_config,
    toml_value,
    write_config,
)
from .completion import (
    COMPLETION_COMMANDS,
    COMPLETION_OPTIONS,
    COMPLETION_SHELLS,
    COMPLETION_SUBCOMMANDS,
    bash_completion_script,
    completion_function_name,
    completion_script,
    fish_completion_script,
    indent_lines,
    shell_words,
    zsh_completion_script,
)
from .contracts import (
    COMMAND_CONTRACTS,
    CONTRACT_SCHEMA_VERSION,
    DEPRECATION_POLICY,
    GENERATED_ARTIFACT_CONTRACTS,
    JSON_OUTPUT_CONTRACTS,
    command_contract_rows,
    command_contracts,
    command_inventory_markdown,
    inventory_payload,
)
from .formatting import markdown_table
from .github import (
    DEFAULT_BRANCH,
    DEPLOY_ROLE_ENV_NAME,
    PLAN_ROLE_ENV_NAME,
    REQUIRED_BRANCH_CHECKS,
    RUNBOOK_FAILED_APPLY,
    RUNBOOK_FAILED_PLAN,
    RUNBOOK_FAILED_ROLLBACK,
    RUNBOOK_FAILED_VALIDATION,
    RUNBOOK_MISSING_IMAGE,
    SNYK_ENV_NAME,
    actions_next_actions,
    actions_run_rows,
    branch_protection_checks,
    failed_job_rows,
    failed_step_rows,
    github_expected_variables,
    github_secret_checks,
    github_variable_checks,
    optional_github_secrets,
    parse_gh_items,
    parse_gh_plain_table,
    parse_gh_runs,
    parse_json_object,
    required_github_secrets,
    required_status_check_names,
    runbook_for_failure,
)
from .images import (
    collect_image_preflight_checks,
    image_uri_from_config_or_override,
    is_immutable_image,
    parse_ecr_image_uri,
)
from .models import ActionsStatus, Check, ConfigMigrationError, Control, EcrImageRef, InputCancelled
from .paths import (
    AUDIT_REPORT,
    CONFIG_FILE,
    DIST_DIR,
    GENERATED_ARTIFACT_DOC,
    GENERATED_TFVARS,
    PRODUCTION_EVIDENCE_DIR,
    RC_EVIDENCE_DIR,
    REQUIRED_PROJECT_FILES,
    SNAPSHOT_DIR,
    SNAPSHOT_FILES,
    SNAPSHOT_FILE_PATHS,
)
from .render import (
    backend_tf,
    checklist,
    cli_owned_comment,
    cli_owned_markdown_notice,
    github_setup_script,
    github_variables,
    hcl_attribute_line,
    hcl_value,
    render_outputs,
    shell_quote,
    terraform_tfvars,
)
from .reports import (
    audit_report_json,
    audit_report_payload,
    least_privilege_guidance,
    markdown_report,
    next_actions,
    preset_dict,
)
from .readiness import (
    check_status_by_name,
    check_to_dict,
    checks_payload,
    grouped_readiness_checks,
    overall_breakdown_score,
    readiness_action_detail_for_check,
    readiness_action_for_check,
    readiness_breakdown_dicts,
    readiness_breakdown_rows,
    readiness_category_for_check,
    readiness_gap_dicts,
    readiness_gap_rows,
    readiness_gate_dicts,
    readiness_gate_rows,
    readiness_score,
    readiness_score_for_category,
    strict_exit_code,
    troubleshooting_anchor_for_check,
)
from .snapshots import (
    file_line_counts,
    list_snapshots,
    read_snapshot_manifest,
    resolve_snapshot,
    resolve_snapshot_selection,
    restore_snapshot,
    snapshot_base,
    snapshot_changes,
    snapshot_entry_relative_path,
    snapshot_id,
    snapshot_rows,
)
from .setup import (
    SETUP_STATE_FILE,
    SetupStage,
    SetupStateError,
    completed_stage_count,
    demo_image_uri,
    first_pending_stage,
    github_setup_ready,
    is_backend_bucket_configured,
    is_iam_role_arn,
    load_setup_state,
    mark_setup_step,
    mode_for_preset,
    new_setup_state,
    save_setup_state,
    setup_config_blockers,
    setup_config_fingerprint,
    setup_next_command,
    setup_profile,
    setup_stages,
    switch_setup_mode,
)
from .views import (
    compact_join,
    control_rows,
    env_rows,
    generated_behavior_summary,
    preset_detail_rows,
    preset_rows,
)

EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_MISSING_EXTERNAL_TOOL = 2
EXIT_AUTH_FAILED = 3
EXIT_UNEXPECTED_ERROR = 70
EXIT_INTERRUPTED = 130
READINESS_CATEGORIES = ["Local", "Terraform", "GitHub", "AWS", "Security", "Deployment"]
CANCEL_INPUTS = {"b", "back", "cancel", "q", "quit"}
MENU_CANCEL_INPUTS = CANCEL_INPUTS | {"0"}
PRODUCTION_EVIDENCE_REQUIRED_FILES = [
    "release-install.txt",
    "release-checksums.txt",
    "config.json",
    "config-validate.json",
    "readiness.json",
    "readiness-report.md",
    "audit-report.json",
    "terraform-generated.auto.tfvars",
    "github-setup.sh",
    "github-variables.env",
    "setup-checklist.md",
    "github-doctor.json",
    "branch-doctor.json",
    "github-status.json",
    "workflow-run.json",
    "terraform-output.json",
    "aws-outputs.json",
    "aws-doctor.json",
    "health.json",
    "health-response.txt",
    "cloudwatch-log-groups.json",
    "cloudwatch-tail.txt",
    "active-lambda-image.txt",
    "notes.md",
]
WSL2_EVIDENCE_REQUIRED_FILES = [
    "wsl2-transcript.txt",
]
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    BLUE = "\033[34m"


def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def color(text: str, code: str) -> str:
    if not supports_color():
        return text
    return f"{code}{text}{Style.RESET}"


def ok(text: str = "OK") -> str:
    return color(text, Style.GREEN)


def warn(text: str = "WARN") -> str:
    return color(text, Style.YELLOW)


def fail(text: str = "FAIL") -> str:
    return color(text, Style.RED)


def info(text: str) -> str:
    return color(text, Style.CYAN)


def repo_root() -> Path:
    return Path.cwd()


def create_snapshot(root: Path, operation: str, description: str) -> Path:
    """Compatibility boundary that keeps snapshot-id injection patchable."""

    return _snapshot_store.create_snapshot(root, operation, description, id_factory=snapshot_id)


def print_snapshot_detail(root: Path, snapshot: dict[str, Any]) -> None:
    draw_box(
        "Snapshot Detail",
        [
            f"ID: {snapshot.get('id', '')}",
            f"Created: {snapshot.get('created_at', '')}",
            f"Operation: {snapshot.get('operation', '')}",
            f"Description: {snapshot.get('description', '')}",
        ],
    )
    changes = snapshot_changes(root, snapshot)
    print()
    if changes:
        draw_table(["File", "Change since snapshot"], [[item["path"], item["detail"]] for item in changes])
    else:
        print(ok("No changes detected since this snapshot."))


def print_snapshot_list(root: Path) -> list[dict[str, Any]]:
    snapshots = list_snapshots(root)
    if not snapshots:
        print(warn("No snapshots found."))
        return []
    draw_table(["#", "Snapshot", "Created", "Operation"], snapshot_rows(snapshots), title="Snapshots")
    return snapshots


def snapshot_before_change(root: Path, operation: str, description: str) -> None:
    path = create_snapshot(root, operation, description)
    print(info("Snapshot created: ") + path.name)


def rollback_boundary_lines() -> list[str]:
    return [
        "Local snapshot restore only: restores CLI-owned files from `.devsecops/snapshots/`.",
        "It does not change AWS Lambda, Terraform state, GitHub Actions, or deployed traffic.",
        f"For deployment rollback diagnostics, use `{RUNBOOK_FAILED_ROLLBACK}` and GitHub Actions logs.",
    ]


def draw_box(title: str, lines: list[str], width: int = 74) -> None:
    print("+" + "-" * (width - 2) + "+")
    title_text = f" {title} "
    print("|" + title_text.ljust(width - 2) + "|")
    print("+" + "-" * (width - 2) + "+")
    for line in lines:
        for wrapped in textwrap.wrap(line, width=width - 4) or [""]:
            print("| " + wrapped.ljust(width - 4) + " |")
    print("+" + "-" * (width - 2) + "+")


def draw_table(headers: list[str], rows: list[list[str]], title: str | None = None) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    if title:
        print(info(title))
    print(border)
    print("|" + "|".join(f" {headers[index].ljust(widths[index])} " for index in range(len(headers))) + "|")
    print(border)
    for row in rows:
        print("|" + "|".join(f" {row[index].ljust(widths[index])} " for index in range(len(headers))) + "|")
    print(border)


def progress_bar(score: int, width: int = 28) -> str:
    filled = max(0, min(width, round(width * score / 100)))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {score:3d}%"


def is_cancel_input(value: str, include_zero: bool = True) -> bool:
    normalized = value.strip().lower()
    cancel_inputs = MENU_CANCEL_INPUTS if include_zero else CANCEL_INPUTS
    return normalized in cancel_inputs


def cancel_hint(allow_cancel: bool) -> str:
    return ", b/back/0 to cancel" if allow_cancel else ""


def prompt_text(label: str, default: str = "", allow_cancel: bool = False) -> str:
    options = []
    if default:
        options.append(default)
    if allow_cancel:
        options.append("b/back/0 to cancel")
    suffix = f" [{', '.join(options)}]" if options else ""
    value = input(f"{label}{suffix}: ").strip()
    if allow_cancel and is_cancel_input(value):
        raise InputCancelled
    return value or default


def prompt_bool(label: str, default: bool = False, allow_cancel: bool = False) -> bool:
    default_text = "y" if default else "n"
    while True:
        value = input(f"{label} [y/n, default {default_text}{cancel_hint(allow_cancel)}]: ").strip().lower()
        if allow_cancel and is_cancel_input(value):
            raise InputCancelled
        if not value:
            return default
        if value in {"y", "yes", "true", "1"}:
            return True
        if value in {"n", "no", "false", "0"}:
            return False
        print(warn("Use y or n."))


def prompt_int(label: str, default: int, allow_cancel: bool = False) -> int:
    while True:
        value = input(f"{label} [{default}{cancel_hint(allow_cancel)}]: ").strip()
        if allow_cancel and is_cancel_input(value):
            raise InputCancelled
        if not value:
            return default
        try:
            return int(value)
        except ValueError:
            print(warn("Use a number."))


def header(cfg: dict[str, Any] | None = None) -> None:
    lines = [
        "DevSecOps Pipeline Kit",
        "AWS Lambda CI/CD reference pipeline configurator",
    ]
    if cfg:
        lines.extend(
            [
                f"Project: {cfg['project_name']}",
                f"Region: {cfg['aws_region']}",
            ]
        )
    draw_box("Main", lines)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(command: list[str], root: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def gh_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run_command(["gh", *args], root, timeout=timeout)


def aws_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run_command(["aws", *args], root, timeout=timeout)


def aws_json(root: Path, args: list[str], timeout: int = 30) -> tuple[Any, subprocess.CompletedProcess[str]]:
    result = aws_command(root, [*args, "--output", "json"], timeout=timeout)
    if result.returncode != 0:
        return {}, result
    try:
        return json.loads(result.stdout or "{}"), result
    except json.JSONDecodeError:
        return {}, result


def collect_aws_checks(root: Path, cfg: dict[str, Any], env_name: str = "prod") -> list[Check]:
    """Collect AWS checks through the provider adapter using current CLI dependencies."""

    return _aws_adapter.collect_aws_checks(
        root,
        cfg,
        env_name,
        command_exists_fn=command_exists,
        aws_json_fn=aws_json,
        aws_command_fn=aws_command,
    )


def resolve_health_url(root: Path, url: str | None = None) -> tuple[str, str]:
    return _aws_adapter.resolve_health_url(
        root,
        url,
        command_exists_fn=command_exists,
        run_command_fn=run_command,
    )


def collect_health_checks(
    root: Path,
    cfg: dict[str, Any],
    url: str | None = None,
    timeout: int = 20,
    aws_sigv4: bool = False,
    aws_region: str | None = None,
) -> list[Check]:
    return _aws_adapter.collect_health_checks(
        root,
        cfg,
        url=url,
        timeout=timeout,
        aws_sigv4=aws_sigv4,
        aws_region=aws_region,
        resolve_health_fn=resolve_health_url,
        fetch_health_fn=fetch_health_url,
    )


def inspect_aws_outputs(
    root: Path,
    cfg: dict[str, Any],
    env_name: str = "prod",
) -> tuple[dict[str, str], list[Check]]:
    return _aws_adapter.inspect_aws_outputs(
        root,
        cfg,
        env_name,
        command_exists_fn=command_exists,
        aws_json_fn=aws_json,
    )



def collect_github_checks(root: Path, cfg: dict[str, Any]) -> list[Check]:
    return _github_adapter.collect_github_checks(
        root,
        cfg,
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )


def collect_branch_checks(root: Path, branch: str = DEFAULT_BRANCH) -> list[Check]:
    return _github_adapter.collect_branch_checks(
        root,
        branch,
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )


def github_status_rows(root: Path, limit: int = 5) -> tuple[list[list[str]], str | None]:
    return _github_adapter.github_status_rows(
        root,
        limit,
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )


def collect_github_actions_status(
    root: Path,
    limit: int = 8,
    failed_jobs_limit: int = 3,
) -> ActionsStatus:
    return _github_adapter.collect_github_actions_status(
        root,
        limit,
        failed_jobs_limit,
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )


def github_actions_status(
    root: Path,
    limit: int = 8,
    failed_jobs_limit: int = 3,
) -> tuple[list[list[str]], list[list[str]], str | None]:
    status = collect_github_actions_status(root, limit=limit, failed_jobs_limit=failed_jobs_limit)
    return status.runs, status.failed_jobs, status.error



def apply_github_setup(root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> int:
    if not command_exists("gh"):
        print(fail("`gh` not found on PATH."))
        return 1
    auth = gh_command(root, ["auth", "status"])
    if auth.returncode != 0:
        print(fail("GitHub CLI is not authenticated: ") + compact_error(auth))
        return auth.returncode

    expected_vars = github_expected_variables(cfg)
    if not expected_vars["LAMBDA_IMAGE_URI"]:
        print(warn("Skipping LAMBDA_IMAGE_URI because local config is empty."))
        expected_vars.pop("LAMBDA_IMAGE_URI")

    for name, value in expected_vars.items():
        command = ["variable", "set", name, "--body", value]
        print(info("$ gh " + " ".join(command[:3]) + " --body <value>"))
        result = gh_command(root, command)
        if result.returncode != 0:
            print(fail(compact_error(result)))
            return result.returncode

    secrets = {"AWS_REGION": cfg["aws_region"]}
    if args.deploy_role_arn:
        secrets["AWS_ROLE_TO_ASSUME_ARN"] = args.deploy_role_arn
    else:
        print(warn("Skipping AWS_ROLE_TO_ASSUME_ARN; pass --deploy-role-arn to set it."))
    if args.plan_role_arn:
        secrets["AWS_PLAN_ROLE_TO_ASSUME_ARN"] = args.plan_role_arn
    else:
        print(warn("Skipping AWS_PLAN_ROLE_TO_ASSUME_ARN; pass --plan-role-arn because Terraform plan no longer falls back to the deploy role."))
    if args.snyk_token:
        secrets["SNYK_TOKEN"] = args.snyk_token
    elif cfg["enable_snyk_scan"]:
        print(warn("Skipping SNYK_TOKEN; pass --snyk-token because enable_snyk_scan is true."))

    for name, value in secrets.items():
        command = ["secret", "set", name, "--body", value]
        print(info("$ gh " + " ".join(command[:3]) + " --body <value>"))
        result = gh_command(root, command)
        if result.returncode != 0:
            print(fail(compact_error(result)))
            return result.returncode

    print(ok("Applied GitHub repository variables/secrets available from config and arguments."))
    return 0


def github_setup_precheck(root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> list[Check]:
    return _github_adapter.github_setup_precheck(
        root,
        cfg,
        args,
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )



def collect_checks(root: Path, cfg: dict[str, Any], deep: bool = False) -> list[Check]:
    return _doctor_service.collect_checks(
        root,
        cfg,
        deep,
        command_exists_fn=command_exists,
        run_command_fn=run_command,
        image_preflight_fn=collect_image_preflight_checks,
        aws_checks_fn=collect_aws_checks,
    )



def next_action(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return _project_context_service.next_action(
        root,
        cfg,
        command_exists_fn=command_exists,
        github_checks_fn=collect_github_checks,
        aws_checks_fn=collect_aws_checks,
    )


def next_action_lines(action: dict[str, Any]) -> list[str]:
    state_label = "What is not ready" if action.get("blocked", True) else "Current state"
    return [
        f"{state_label}: {action['title']}",
        f"Why it matters: {action['why']}",
        f"What will change: {action['changes']}",
        f"Next command: {action['command']}",
        f"Docs: {action['docs']}",
    ]


def print_next_action(action: dict[str, Any], title: str = "Next Action") -> None:
    lines = next_action_lines(action)
    draw_box(title, lines[:3])
    print(lines[3])
    print(lines[4])



def compact_error(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").strip().splitlines()
    return output[-1] if output else f"Command exited with {result.returncode}."


def score_status(score: int | None) -> str:
    if score is None:
        return info("n/a")
    if score >= 90:
        return ok(f"{score}%")
    if score >= 60:
        return warn(f"{score}%")
    return fail(f"{score}%")


def print_readiness_breakdown(checks: list[Check], compact: bool = False) -> None:
    print_readiness_gates(checks)
    print()
    grouped = grouped_readiness_checks(checks)
    rows: list[list[str]] = []
    for raw_row in readiness_breakdown_rows(checks, compact=compact):
        score = readiness_score_for_category(grouped[raw_row[0]])
        row = [raw_row[0], score_status(score), *raw_row[2:]]
        rows.append(row)
    headers = ["Area", "Score", "Gaps"] if compact else ["Area", "Score", "OK", "WARN", "FAIL", "INFO"]
    draw_table(headers, rows, title="Readiness")
    print()
    print(f"Overall: {score_status(overall_breakdown_score(checks))}")


def print_gap_summary(checks: list[Check], limit: int = 3) -> None:
    rows = readiness_gap_rows(checks)[:limit]
    if not rows:
        print(ok("Readiness gaps: none."))
        return
    print(info("Readiness gaps ([i] details):"))
    for check_name, status, detail, action in rows:
        label = fail(status) if status == "FAIL" else warn(status)
        print(f"  {label} {check_name}: {detail}")
        print(f"    Fix: {action}")


def collect_dashboard_checks(root: Path, cfg: dict[str, Any], mode: str = "full") -> list[Check]:
    return _doctor_service.collect_dashboard_checks(
        root,
        cfg,
        mode,
        collect_checks_fn=collect_checks,
        github_checks_fn=collect_github_checks,
        branch_checks_fn=collect_branch_checks,
    )



def print_readiness_details(root: Path, deep: bool = False) -> None:
    cfg = load_config(root)
    checks = collect_checks(root, cfg, deep=deep)
    score = readiness_score(checks)
    draw_box(
        "Readiness Details",
        [
            f"Current readiness: {score}%",
            "Only scored checks below 100% are listed here.",
            "Use `devsecops doctor` for the full check list.",
        ],
    )
    print()
    print_readiness_gates(checks)
    rows = readiness_gap_rows(checks)
    print()
    if rows:
        for check_name, status, detail, action in rows:
            label = fail(status) if status == "FAIL" else warn(status)
            print(f"{label} {check_name}")
            print(f"  Current: {detail}")
            print(f"  Fix: {action}")
            print()
    else:
        print(ok("All scored readiness checks are OK."))


def print_checks(checks: list[Check]) -> None:
    score = readiness_score(checks)
    print(info("Readiness: ") + progress_bar(score))
    print()
    name_width = max(len(check.name) for check in checks) + 2
    for check in checks:
        if check.status == "OK":
            label = ok("OK")
        elif check.status == "FAIL":
            label = fail("FAIL")
        elif check.status == "INFO":
            label = info("INFO")
        else:
            label = warn("WARN")
        print(f"{check.name.ljust(name_width)} {label.ljust(12)} {check.detail}")
        if check.scored and check.status != "OK":
            print(f"{''.ljust(name_width)} {'Fix'.ljust(12)} {readiness_action_for_check(check)}")


def print_readiness_gates(checks: list[Check]) -> None:
    draw_table(["Gate", "Status", "Detail"], readiness_gate_rows(checks), title="Readiness Gates")


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_compact_checks(checks: list[Check], title: str | None = None) -> None:
    if title:
        print(info(title))
    print(f"Score: {readiness_score(checks)}%")
    gaps = [check for check in checks if check.scored and check.status in {"WARN", "FAIL"}]
    if not gaps:
        print(ok("No scored gaps."))
        return
    for check in gaps:
        label = fail(check.status) if check.status == "FAIL" else warn(check.status)
        print(f"{label} {check.name}: {check.detail}")
        print(f"  Fix: {readiness_action_for_check(check)}")


def print_strict_validation_summary(checks: list[Check]) -> None:
    blockers = [check for check in checks if check.scored and check.status == "FAIL"]
    promoted = [check for check in checks if check.scored and check.status == "WARN"]
    if not blockers and not promoted:
        print(ok("Production blockers: none."))
        return
    print()
    draw_box(
        "Production Blockers",
        [
            f"Failures: {len(blockers)}",
            f"Warnings promoted to failures by --strict: {len(promoted)}",
            "Fix these before treating the pipeline as production-ready.",
        ],
    )
    for check in [*blockers, *promoted]:
        label = fail(check.status) if check.status == "FAIL" else warn(check.status)
        print(f"{label} {check.name}: {check.detail}")
        print(f"  Next command: {readiness_action_detail_for_check(check)}")


def emit_check_output(
    title: str,
    checks: list[Check],
    output_format: str = "human",
    context: dict[str, Any] | None = None,
) -> None:
    if output_format == "json":
        emit_json(checks_payload(title.lower().replace(" ", "-"), checks, context=context))
    elif output_format == "compact":
        print_compact_checks(checks, title=title)
    else:
        if context:
            lines = [f"{key}: {value}" for key, value in context.items()]
            draw_box(title, lines)
        else:
            draw_box(title, [])
        print_checks(checks)


def print_preset_list() -> None:
    draw_table(
        ["Preset", "Posture", "Scanners", "Validation", "Prod CORS", "Approval", "Plan Role"],
        preset_rows(),
        title="Policy Preset Comparison",
    )


def print_preset_detail(name: str) -> int:
    if name not in PRESETS:
        print(fail("Unknown preset: ") + name)
        print("Available presets: " + ", ".join(PRESET_ORDER))
        return 1
    cfg = preset_config(name)
    draw_box(f"Preset: {name}", [PRESET_DESCRIPTIONS[name], PRESET_POSTURES[name]])
    print()
    draw_table(["Setting", "Value"], preset_detail_rows(cfg))
    return 0


def cmd_completion(args: argparse.Namespace) -> int:
    print(completion_script(args.shell, args.program), end="")
    return EXIT_OK


def cmd_envs(args: argparse.Namespace) -> int:
    cfg = load_config(repo_root())
    draw_table(
        ["Env", "Memory", "Timeout", "Logs", "Burst/Rate", "CORS"],
        env_rows(cfg),
        title="Environment Configuration",
    )
    return 0


def cmd_controls(args: argparse.Namespace) -> int:
    cfg = load_config(repo_root())
    if getattr(args, "format", "human") == "json":
        emit_json(
            {
                "kind": "control-catalog",
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "controls": [control_to_dict(control, cfg) for control in control_catalog()],
            }
        )
    else:
        draw_table(["Control", "State", "CLI", "Generated Behavior"], control_rows(cfg), title="Pipeline Controls")
    return 0


def architecture_lines() -> list[str]:
    return [
        "GitHub Actions",
        "|-- OIDC -> AWS STS -> deploy role",
        "|-- Terraform validate + Trivy IaC scan",
        "|-- Terraform plan comment on pull requests",
        "|-- Manual production apply via workflow_dispatch",
        "AWS",
        "|-- S3 backend + DynamoDB lock",
        "|-- KMS key",
        "|-- ECR repository",
        "|-- Lambda container workload",
        "|-- API Gateway HTTP API",
        "|-- S3 workload data bucket",
        "|-- CloudWatch Logs + X-Ray + SQS DLQ",
    ]


def cmd_architecture(args: argparse.Namespace) -> int:
    draw_box("Architecture", architecture_lines())
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    status = getattr(args, "status", "all")
    output_format = getattr(args, "format", "human")
    if output_format == "json":
        emit_json(inventory_payload(status))
    elif output_format == "markdown":
        print(command_inventory_markdown(status))
    else:
        draw_table(["Command", "Status", "Scope", "Stable Flags", "Alias/JSON"], command_contract_rows(status), title="Command Inventory")
        print()
        draw_box(
            "Stability Contract",
            [
                "Stable commands and flags are safe for scripts within normal semver expectations.",
                "Aliases remain callable through at least v1.0, but new scripts should use grouped commands.",
                "Experimental commands are excluded from first-success docs and may change in 0.x releases.",
                "Use `devsecops inventory --format json` for a machine-readable contract.",
            ],
        )
    return EXIT_OK


def render_dashboard(root: Path, mode: str = "full", clear: bool = False) -> None:
    if clear:
        clear_screen()
    mode = mode if mode in {"compact", "full"} else "full"
    full = mode == "full"
    cfg = load_config(root)
    checks = collect_dashboard_checks(root, cfg, mode=mode)
    action = next_action(root, cfg)
    header(cfg)
    print()
    for line in menu_status(root, cfg, checks=checks):
        print(line)
    print()
    print_readiness_breakdown(checks, compact=not full)
    print()
    print_next_action(action)
    if not full:
        print()
        print(info("Run `devsecops status --deep` for GitHub, AWS, and deep Terraform checks."))
        return
    print()
    draw_table(
        ["Env", "Memory", "Timeout", "Logs", "Burst/Rate", "CORS"],
        env_rows(cfg),
        title="Environment Configuration",
    )
    print()
    draw_table(["Control", "State", "CLI", "Generated Behavior"], control_rows(cfg), title="Pipeline Controls")
    print()
    draw_box("Architecture", architecture_lines())


def cmd_dashboard(args: argparse.Namespace) -> int:
    root = repo_root()
    interval = max(1, int(args.interval))
    while True:
        render_dashboard(root, mode=args.mode, clear=bool(args.watch))
        if not args.watch:
            return 0
        print()
        print(info(f"Watching dashboard every {interval}s. Press Ctrl-C to stop."))
        time.sleep(interval)


def status_payload(checks: list[Check], action: dict[str, Any], deep: bool) -> dict[str, Any]:
    """Return the preferred status contract with one unambiguous score."""

    payload = checks_payload("status", checks, context={"deep": deep})
    payload["score"] = overall_breakdown_score(checks)
    payload.pop("overall_breakdown_score", None)
    payload["next_action"] = {
        "action": action["id"],
        "title": action["title"],
        "detail": action["detail"],
        "why": action["why"],
        "changes": action["changes"],
        "command": action["command"],
        "docs": action["docs"],
        "blocked": action["blocked"],
    }
    return payload


def cmd_status(args: argparse.Namespace) -> int:
    """Show one status surface: current state, blockers, and next action."""

    root = repo_root()
    deep = bool(getattr(args, "deep", False))
    output_format = getattr(args, "format", "human")
    watch = bool(getattr(args, "watch", False))
    if watch and output_format != "human":
        print(fail("--watch is available only with human output."))
        return EXIT_VALIDATION_FAILED

    interval = max(1, int(getattr(args, "interval", 5)))
    while True:
        cfg = load_config(root)
        checks = collect_dashboard_checks(root, cfg, mode="full" if deep else "compact")
        action = next_action(root, cfg)
        if output_format == "json":
            emit_json(status_payload(checks, action, deep))
        elif output_format == "compact":
            print_readiness_breakdown(checks, compact=True)
            print()
            print_next_action(action)
        else:
            render_dashboard(root, mode="full" if deep else "compact", clear=watch)

        result = strict_exit_code(checks, strict=bool(getattr(args, "strict", False)), fail_on_warn=True)
        if not watch:
            return result
        print()
        print(info(f"Watching status every {interval}s. Press Ctrl-C to stop."))
        time.sleep(interval)


def cmd_overview(args: argparse.Namespace) -> int:
    """Show compact status and the single recommended next action."""

    render_dashboard(repo_root(), mode="compact", clear=False)
    return EXIT_OK


def render_rich_tui(root: Path) -> bool:
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        return False

    cfg = load_config(root)
    checks = collect_dashboard_checks(root, cfg, mode="compact")
    action = next_action(root, cfg)
    console = Console()
    console.print(
        Panel(
            f"Project: {cfg['project_name']}\nRegion: {cfg['aws_region']}\nOverall: {overall_breakdown_score(checks)}%",
            title="DevSecOps Pipeline Kit",
        )
    )

    table = Table(title="Readiness")
    table.add_column("Area")
    table.add_column("Score", justify="right")
    table.add_column("Gaps", justify="right")
    for area, score, gaps in readiness_breakdown_rows(checks, compact=True):
        table.add_row(area, score, gaps)
    console.print(table)

    gap_table = Table(title="[i] Readiness Details")
    gap_table.add_column("Check")
    gap_table.add_column("Status")
    gap_table.add_column("Fix")
    for check_name, status, _detail, action in readiness_gap_rows(checks)[:5]:
        gap_table.add_row(check_name, status, action)
    if gap_table.row_count:
        console.print(gap_table)
    else:
        console.print(Panel("All scored readiness checks are OK.", title="Readiness Details"))
    console.print(Panel("\n".join(next_action_lines(action)), title="Next Action"))
    console.print("[dim]Full Textual mode is intentionally deferred until doctor workflows stabilize.[/dim]")
    return True


def cmd_tui(args: argparse.Namespace) -> int:
    root = repo_root()
    if render_rich_tui(root):
        return 0
    print(warn("Rich/Textual UI is optional and not installed. Falling back to compact dashboard."))
    print(info('Install optional UI dependencies with `pipx install ".[tui]"` or `python3 -m pip install -e ".[tui]"`.'))
    print()
    render_dashboard(root, mode="compact", clear=False)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    action = next_action(root, cfg)
    if getattr(args, "format", "human") == "json":
        emit_json(
            {
                "kind": "next-action",
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "context": action["context"],
                "action": action["id"],
                "title": action["title"],
                "detail": action["detail"],
                "why": action["why"],
                "changes": action["changes"],
                "command": action["command"],
                "docs": action["docs"],
                "blocked": action["blocked"],
            }
        )
        return EXIT_OK
    print_next_action(action)
    return EXIT_OK


def choose_setup_mode(args: argparse.Namespace, state: dict[str, Any] | None) -> tuple[str, str]:
    requested_mode = getattr(args, "mode", None)
    requested_preset = getattr(args, "preset", None)
    if requested_mode:
        return requested_mode, requested_preset or str(setup_profile(requested_mode)["preset"])
    if requested_preset:
        return mode_for_preset(requested_preset), requested_preset
    if state is not None:
        return str(state["mode"]), str(state.get("preset") or setup_profile(str(state["mode"]))["preset"])
    if bool(getattr(args, "yes", False)):
        return "standard", "balanced"

    draw_box(
        "Setup Mode",
        [
            "Choose how far this guided setup should take the project.",
            "The mode controls required checks; it never grants permission for cloud changes.",
        ],
    )
    print()
    draw_table(
        ["#", "Mode", "Use when"],
        [
            ["1", "Demo", str(setup_profile("demo")["description"])],
            ["2", "Standard", str(setup_profile("standard")["description"])],
            ["3", "Production", str(setup_profile("production")["description"])],
        ],
    )
    choices = {
        "1": "demo",
        "demo": "demo",
        "2": "standard",
        "standard": "standard",
        "3": "production",
        "production": "production",
    }
    while True:
        value = input("\nChoose mode [2, b/back/0 to pause]: ").strip().lower()
        if not value:
            value = "2"
        if is_cancel_input(value):
            raise InputCancelled
        if value in choices:
            mode = choices[value]
            return mode, str(setup_profile(mode)["preset"])
        print(warn("Choose 1, 2, or 3."))


def begin_setup_step(root: Path, state: dict[str, Any], step: str, detail: str = "") -> None:
    mark_setup_step(state, step, "pending", detail)
    save_setup_state(root, state)


def setup_argument_error(args: argparse.Namespace, mode: str) -> str | None:
    github_values = [
        getattr(args, "deploy_role_arn", None),
        getattr(args, "plan_role_arn", None),
        getattr(args, "snyk_token", None),
    ]
    if any(github_values) and not bool(getattr(args, "apply_github", False)):
        return "Role ARN and Snyk token options require --apply-github."
    cloud_options = [
        getattr(args, "backend_bucket", None),
        getattr(args, "backend_region", None),
        getattr(args, "backend_lock_table", None),
        bool(getattr(args, "apply_github", False)),
    ]
    if mode == "demo" and any(cloud_options):
        return "Backend and GitHub apply options require --mode standard or --mode production."
    return None


def prompt_matching_text(label: str, default: str, pattern: Any, guidance: str) -> str:
    while True:
        value = prompt_text(label, default, allow_cancel=True)
        if pattern.fullmatch(value):
            return value
        print(warn(guidance))


def prompt_secret(label: str) -> str:
    value = getpass.getpass(f"{label} [hidden, b/back/0 to pause]: ").strip()
    if is_cancel_input(value):
        raise InputCancelled
    return value


def setup_dependency_status() -> dict[str, bool]:
    return {tool: command_exists(tool) for tool in ("git", "terraform", "aws", "gh")}


def print_setup_dependencies(mode: str, statuses: dict[str, bool]) -> None:
    profile = setup_profile(mode)
    required = set(profile["required_tools"])
    recommended = set(profile["recommended_tools"])
    rows = []
    for tool in ("git", "terraform", "aws", "gh"):
        if tool in required:
            need = "required"
        elif tool in recommended:
            need = "recommended"
        else:
            need = "later"
        rows.append([tool, need, "available" if statuses[tool] else "missing"])
    draw_table(["Tool", "For this mode", "Status"], rows, title="Step 2/9 - Dependencies")
    missing = [tool for tool in required if not statuses[tool]]
    if missing:
        print()
        print(
            warn("Setup can prepare local inputs, but these stages remain incomplete: ")
            + ", ".join(sorted(missing))
        )
        print("Install guidance: docs/distribution.md and docs/first-successful-pipeline.md")


def write_setup_config_change(root: Path, cfg: dict[str, Any], description: str) -> None:
    if config_path(root).exists():
        snapshot_before_change(root, "setup", description)
    write_config(root, cfg)
    print(ok("Updated ") + str(config_path(root)))


def create_setup_config(root: Path, state: dict[str, Any], interactive: bool) -> dict[str, Any] | None:
    if config_path(root).exists():
        return load_config(root)
    preset_name = str(state["preset"])
    should_create = True
    if interactive:
        should_create = prompt_bool(
            f"Create {CONFIG_FILE} with the `{preset_name}` preset",
            True,
            allow_cancel=True,
        )
    if not should_create:
        print(info("Config creation deferred. Rerun `devsecops setup` to continue."))
        return None

    cfg = clean_config(preset_name)
    if interactive:
        cfg["project_name"] = prompt_matching_text(
            "Project name",
            str(cfg["project_name"]),
            PROJECT_NAME_RE,
            "Use 3-32 lowercase letters, digits, or hyphens; start with a letter.",
        )
        cfg["aws_region"] = prompt_matching_text(
            "AWS region",
            str(cfg["aws_region"]),
            AWS_REGION_RE,
            "Use an AWS region such as us-east-1 or eu-central-1.",
        )
        cfg["backend"]["region"] = cfg["aws_region"]
        cfg["backend"]["lock_table"] = f"{cfg['project_name']}-terraform-locks"
    write_config(root, cfg)
    print(ok("Created clean config ") + str(config_path(root)))
    return cfg


def validate_setup_image(cfg: dict[str, Any], image_uri: str) -> list[Check]:
    return collect_image_preflight_checks(cfg, image_uri=image_uri, env_name="prod")


def configure_setup_image(
    root: Path,
    cfg: dict[str, Any],
    image_uri: str | None,
    interactive: bool,
) -> tuple[dict[str, Any], bool]:
    current = str(cfg.get("lambda_image_uri", ""))
    if current and is_immutable_image(current) and not image_uri:
        print(ok("Immutable image already configured: ") + current)
        return cfg, False

    candidate = image_uri
    while not candidate and interactive:
        draw_box(
            "Step 4/9 - Lambda Image",
            [
                "The CLI does not build or push the Lambda application image.",
                "Use an existing ECR URI with an immutable release tag or sha256 digest.",
            ],
        )
        print("[1] Enter an existing image URI")
        print("[2] Show the image guide and continue later")
        print("[0] Pause setup")
        choice = input("\nChoose: ").strip().lower()
        if is_cancel_input(choice):
            raise InputCancelled
        if choice == "2":
            print(info("Image guide: docs/bring-your-own-image.md"))
            print("Resume with `devsecops setup --image-uri <immutable-ecr-image-uri>`.")
            return cfg, False
        if choice == "1":
            candidate = prompt_text("Immutable ECR image URI", allow_cancel=True)
        else:
            print(warn("Choose 1, 2, or 0."))

    if not candidate:
        print(warn("Lambda image is not configured."))
        print("Guide: docs/bring-your-own-image.md")
        return cfg, False

    checks = validate_setup_image(cfg, candidate)
    if any(check.status == "FAIL" for check in checks):
        emit_check_output("Lambda Image", checks)
        print(fail("The image URI was not saved. Fix it and rerun setup."))
        return cfg, True
    cfg["lambda_image_uri"] = candidate
    write_setup_config_change(root, cfg, "Before configuring the guided-setup Lambda image.")
    print(ok("Configured immutable Lambda image."))
    return load_config(root), False


def configure_setup_backend(
    root: Path,
    cfg: dict[str, Any],
    args: argparse.Namespace,
    interactive: bool,
) -> tuple[dict[str, Any], bool]:
    current_bucket = str(cfg["backend"]["bucket"])
    requested_bucket = getattr(args, "backend_bucket", None)
    requested_region = getattr(args, "backend_region", None)
    requested_lock_table = getattr(args, "backend_lock_table", None)
    if (
        is_backend_bucket_configured(current_bucket)
        and not requested_bucket
        and not requested_region
        and not requested_lock_table
    ):
        print(ok("Terraform backend configured: ") + current_bucket)
        return cfg, False

    bucket = requested_bucket or (
        current_bucket if is_backend_bucket_configured(current_bucket) else None
    )
    if not bucket and interactive:
        draw_box(
            "Step 5/9 - Terraform Backend",
            [
                "Shared deployments need an S3 state bucket and DynamoDB lock table.",
                "This step saves names in local config; it does not create AWS resources.",
            ],
        )
        if not prompt_bool("Configure backend names now", True, allow_cancel=True):
            print(info("Backend configuration deferred."))
            return cfg, False
        bucket = prompt_text("Existing or planned S3 state bucket", allow_cancel=True)

    if not bucket:
        print(warn("Terraform backend is not configured."))
        return cfg, False
    if not is_backend_bucket_configured(bucket):
        print(fail("Invalid S3 bucket name; use 3-63 lowercase letters, digits, dots, or hyphens."))
        return cfg, True

    region = requested_region or str(cfg["backend"].get("region") or cfg["aws_region"])
    lock_table = requested_lock_table or str(
        cfg["backend"].get("lock_table") or f"{cfg['project_name']}-terraform-locks"
    )
    if interactive:
        region = prompt_matching_text(
            "Backend AWS region",
            region,
            AWS_REGION_RE,
            "Use an AWS region such as us-east-1 or eu-central-1.",
        )
        lock_table = prompt_text("DynamoDB lock table", lock_table, allow_cancel=True)
    if not AWS_REGION_RE.fullmatch(region):
        print(fail("Invalid backend region; use an AWS region such as us-east-1."))
        return cfg, True
    if not lock_table.strip():
        print(fail("DynamoDB lock table name cannot be empty."))
        return cfg, True

    cfg["backend"]["bucket"] = bucket
    cfg["backend"]["region"] = region
    cfg["backend"]["lock_table"] = lock_table
    write_setup_config_change(root, cfg, "Before configuring the guided-setup Terraform backend.")
    print("No AWS resources were created. Preview them with `devsecops terraform bootstrap`.")
    return load_config(root), False


def setup_aws_identity(root: Path, mode: str) -> Check | None:
    if not setup_profile(mode)["cloud_required"]:
        return None
    if not command_exists("aws"):
        return Check("AWS identity", "WARN", "`aws` is not available on PATH.")
    payload, result = aws_json(root, ["sts", "get-caller-identity"])
    if result.returncode != 0:
        return Check("AWS identity", "WARN", compact_error(result))
    detail = (
        str(payload.get("Arn") or payload.get("Account") or "AWS credentials are usable.")
        if isinstance(payload, dict)
        else "AWS credentials are usable."
    )
    return Check("AWS identity", "OK", detail)


def setup_backend_resource_checks(
    root: Path,
    cfg: dict[str, Any],
    mode: str,
    identity: Check | None,
) -> list[Check]:
    if not setup_profile(mode)["cloud_required"]:
        return []
    bucket = str(cfg["backend"]["bucket"])
    lock_table = str(cfg["backend"]["lock_table"])
    if not is_backend_bucket_configured(bucket):
        return []
    if identity is None or identity.status != "OK":
        return [
            Check("State bucket", "WARN", "Waiting for a valid AWS identity."),
            Check("Lock table", "WARN", "Waiting for a valid AWS identity."),
        ]

    region = str(cfg["backend"]["region"])
    bucket_result = aws_command(
        root,
        ["s3api", "head-bucket", "--bucket", bucket, "--region", region],
    )
    _, table_result = aws_json(
        root,
        ["dynamodb", "describe-table", "--table-name", lock_table, "--region", region],
    )
    return [
        Check(
            "State bucket",
            "OK" if bucket_result.returncode == 0 else "WARN",
            bucket
            if bucket_result.returncode == 0
            else missing_or_error_detail(bucket_result, "Bucket not found or not accessible."),
        ),
        Check(
            "Lock table",
            "OK" if table_result.returncode == 0 else "WARN",
            lock_table
            if table_result.returncode == 0
            else missing_or_error_detail(table_result, "DynamoDB lock table not found or not accessible."),
        ),
    ]


def print_setup_aws_identity(check: Check | None, mode: str) -> None:
    if not setup_profile(mode)["cloud_required"]:
        print(info("Step 6/9 - AWS identity: not required in demo mode."))
        return
    if check is None:
        print(warn("Step 6/9 - AWS identity: waiting for a valid local config."))
        return
    label = ok(check.status) if check.status == "OK" else warn(check.status)
    print(f"Step 6/9 - AWS identity: {label} {check.detail}")
    if check.status != "OK":
        print("Configure credentials, then verify with `aws sts get-caller-identity`.")


def setup_github_connection(
    root: Path,
    cfg: dict[str, Any],
    args: argparse.Namespace,
    interactive: bool,
    mode: str,
) -> tuple[list[Check], bool]:
    if not setup_profile(mode)["cloud_required"]:
        print(info("Step 7/9 - GitHub repository / OIDC: not required in demo mode."))
        return [], False

    checks = collect_github_checks(root, cfg)
    if github_setup_ready(checks):
        print(ok("Step 7/9 - GitHub repository variables and OIDC role secrets are ready."))
        return checks, False

    emit_check_output("Step 7/9 - GitHub Repository / OIDC", checks, output_format="compact")
    apply_requested = bool(getattr(args, "apply_github", False))
    if interactive and not apply_requested:
        print()
        draw_box(
            "GitHub Change Boundary",
            [
                "Applying setup writes variables and encrypted secrets to the current GitHub repository.",
                "It does not run a workflow or change AWS resources.",
            ],
        )
        apply_requested = prompt_bool("Apply GitHub repository setup now", False, allow_cancel=True)
    if not apply_requested:
        print(
            "Resume here with `devsecops setup --apply-github "
            "--deploy-role-arn <arn> --plan-role-arn <arn>`."
        )
        return checks, False

    deploy_role_arn = getattr(args, "deploy_role_arn", None)
    plan_role_arn = getattr(args, "plan_role_arn", None)
    snyk_token = getattr(args, "snyk_token", None)
    if interactive:
        deploy_role_arn = deploy_role_arn or prompt_text("AWS deploy role ARN", allow_cancel=True)
        plan_role_arn = plan_role_arn or prompt_text("AWS plan role ARN", allow_cancel=True)
        if cfg["enable_snyk_scan"] and not snyk_token:
            snyk_token = prompt_secret("Snyk token")
    invalid_roles = [
        label
        for label, value in (("deploy", deploy_role_arn), ("plan", plan_role_arn))
        if not value or not is_iam_role_arn(value)
    ]
    if invalid_roles:
        print(fail("Valid IAM role ARNs are required for: ") + ", ".join(invalid_roles))
        return checks, True
    if cfg["enable_snyk_scan"] and not snyk_token:
        print(fail("SNYK_TOKEN is required because this setup mode enables Snyk scanning."))
        return checks, True

    apply_args = argparse.Namespace(
        deploy_role_arn=deploy_role_arn,
        plan_role_arn=plan_role_arn,
        snyk_token=snyk_token,
    )
    precheck = github_setup_precheck(root, cfg, apply_args)
    emit_check_output("GitHub Setup Precheck", precheck)
    print()
    result = apply_github_setup(root, cfg, apply_args)
    if result != EXIT_OK:
        return checks, True
    return collect_github_checks(root, cfg), False


def save_reconciled_setup(root: Path, state: dict[str, Any], stages: list[SetupStage]) -> None:
    for stage in stages:
        mark_setup_step(state, stage.id, stage.status, stage.detail)
    pending = first_pending_stage(stages)
    state["last_step"] = pending.id if pending else "summary"
    save_setup_state(root, state)


def print_setup_summary(state: dict[str, Any], stages: list[SetupStage]) -> None:
    labels = {"complete": "Complete", "pending": "Action needed", "not-required": "Not required"}
    rows = [
        [f"{index}/9", stage.title, labels[stage.status], stage.detail]
        for index, stage in enumerate(stages, start=1)
    ]
    draw_table(["Step", "Stage", "Status", "Detail"], rows, title="Guided Setup Summary")
    complete, required = completed_stage_count(stages)
    pending = first_pending_stage(stages)
    print()
    print(f"Progress: {complete}/{required} required stages complete")
    print(f"Saved progress: {SETUP_STATE_FILE}")
    next_command = setup_next_command(pending, str(state["mode"]))
    print(f"Next command: {next_command}")
    if pending:
        print(f"Resume point: {pending.title} - {pending.detail}")
    else:
        print(ok("Guided setup complete. No deployment was started."))
    print()
    draw_box(
        "Next Action",
        [
            pending.title if pending else "Validate the resulting project status",
            pending.detail if pending else "Guided setup is complete; review the unified status before deployment.",
            "Rerunning setup rechecks observable state and resumes without repeating completed work.",
        ],
    )
    print(f"Next command: {next_command}")


def cmd_setup(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    context = project_context(root, cfg)
    draw_box(
        "Guided Project Setup",
        [
            "Resumable onboarding for the first successful pipeline path.",
            f"Project context: {context['stage']}",
            "AWS checks are read-only. GitHub changes require confirmation or --apply-github.",
            f"Progress is stored locally in {SETUP_STATE_FILE}; secrets are never stored there.",
        ],
    )
    if context["missing_project_files"]:
        print()
        print_next = argparse.Namespace(format="human")
        return cmd_next(print_next)

    state = load_setup_state(root)
    try:
        mode, preset_name = choose_setup_mode(args, state)
        if state is None:
            state = new_setup_state(mode, preset=preset_name)
            print(info(f"Starting {mode} setup with the `{preset_name}` preset."))
        else:
            previous_mode = str(state["mode"])
            previous_preset = str(state.get("preset", ""))
            if previous_mode != mode or previous_preset != preset_name:
                state = switch_setup_mode(state, mode, preset=preset_name)
                print(info(f"Switched saved setup from {previous_mode} to {mode} mode."))
            else:
                print(
                    info(
                        f"Resuming saved {mode} setup from step "
                        f"`{state.get('last_step', 'mode')}`."
                    )
                )
        mark_setup_step(state, "mode", "complete", f"Mode: {mode}; preset: {preset_name}")
        save_setup_state(root, state)

        argument_error = setup_argument_error(args, mode)
        if argument_error:
            print(fail(argument_error))
            return EXIT_VALIDATION_FAILED

        interactive = not bool(getattr(args, "yes", False))
        input_error = False

        begin_setup_step(root, state, "dependencies")
        dependency_status = setup_dependency_status()
        print()
        print_setup_dependencies(mode, dependency_status)

        begin_setup_step(root, state, "config")
        cfg = create_setup_config(root, state, interactive) or load_config(root)

        config_exists = config_path(root).exists()
        config_blockers = setup_config_blockers(cfg, mode) if config_exists else []
        config_valid = config_exists and not config_blockers
        repairable_mode_posture = (
            config_exists
            and config_blockers
            and not any(check.status == "FAIL" for check in config_blockers)
        )
        should_apply_mode_preset = False
        if repairable_mode_posture:
            print()
            emit_check_output("Step 3/9 - Mode Posture", config_blockers, output_format="compact")
            if interactive:
                should_apply_mode_preset = prompt_bool(
                    f"Apply the `{preset_name}` mode preset while preserving "
                    "project, region, image, and backend values",
                    True,
                    allow_cancel=True,
                )
            elif getattr(args, "mode", None) or getattr(args, "preset", None):
                should_apply_mode_preset = True
                print(info(f"Applying the explicitly selected `{preset_name}` mode preset."))
            if should_apply_mode_preset:
                apply_result = apply_preset(root, preset_name, render=False)
                if apply_result != EXIT_OK:
                    return apply_result
                cfg = load_config(root)
                config_blockers = setup_config_blockers(cfg, mode)
                config_valid = not config_blockers
        if config_exists and not config_valid:
            print()
            emit_check_output("Step 3/9 - Config", config_blockers, output_format="compact")

        if config_valid:
            begin_setup_step(root, state, "image")
            if (
                mode == "demo"
                and not getattr(args, "image_uri", None)
                and not is_immutable_image(str(cfg.get("lambda_image_uri", "")))
            ):
                print()
                print(info("Step 4/9 - Lambda image: demo mode will use a sample URI only for dry-run."))
                print("Bring-your-own-image guide: docs/bring-your-own-image.md")
            else:
                print()
                cfg, image_error = configure_setup_image(
                    root,
                    cfg,
                    getattr(args, "image_uri", None),
                    interactive,
                )
                input_error = input_error or image_error

            begin_setup_step(root, state, "backend")
            if setup_profile(mode)["cloud_required"]:
                print()
                cfg, backend_error = configure_setup_backend(root, cfg, args, interactive)
                input_error = input_error or backend_error
            else:
                print(info("Step 5/9 - Terraform backend: not required in demo mode."))

        if bool(getattr(args, "render", False)) and config_exists:
            print()
            render_result = run_render(root, snapshot=True)
            if render_result != EXIT_OK:
                return render_result

        begin_setup_step(root, state, "aws")
        aws_identity = setup_aws_identity(root, mode) if config_exists else None
        backend_checks = setup_backend_resource_checks(root, cfg, mode, aws_identity) if config_exists else []
        print()
        print_setup_aws_identity(aws_identity, mode)
        for check in backend_checks:
            label = ok(check.status) if check.status == "OK" else warn(check.status)
            print(f"  Terraform backend {check.name}: {label} {check.detail}")
        if any(check.status != "OK" for check in backend_checks):
            print(
                "  Next: preview with `devsecops terraform bootstrap`, then apply "
                "after reviewing the AWS account and names."
            )

        begin_setup_step(root, state, "github")
        github_checks: list[Check] = []
        if config_valid:
            print()
            github_checks, github_error = setup_github_connection(root, cfg, args, interactive, mode)
            input_error = input_error or github_error

        begin_setup_step(root, state, "dry_run")
        effective_image = None
        if mode == "demo" and not is_immutable_image(str(cfg.get("lambda_image_uri", ""))):
            effective_image = demo_image_uri(cfg)
        dry_run_can_run = config_valid and bool(
            effective_image or is_immutable_image(str(cfg.get("lambda_image_uri", "")))
        )
        current_fingerprint = setup_config_fingerprint(cfg, image_override=effective_image)
        if dry_run_can_run and state.get("dry_run_fingerprint") != current_fingerprint:
            print()
            dry_run_result = cmd_dry_run(
                argparse.Namespace(
                    preset=preset_name,
                    image_uri=effective_image,
                    environment="prod",
                )
            )
            if dry_run_result == EXIT_OK:
                state["dry_run_fingerprint"] = current_fingerprint
                save_setup_state(root, state)
            else:
                input_error = True
        elif dry_run_can_run:
            print(ok("Step 8/9 - Dry-run is already current; no need to repeat it."))
        else:
            print(warn("Step 8/9 - Dry-run is waiting for a valid config and immutable image."))

        cfg = load_config(root)
        dependency_status = setup_dependency_status()
        stages = setup_stages(
            root,
            cfg,
            state,
            dependency_status=dependency_status,
            backend_checks=backend_checks,
            aws_identity=aws_identity,
            github_checks=github_checks,
        )
        save_reconciled_setup(root, state, stages)
        print()
        print_setup_summary(state, stages)
        pending = first_pending_stage(stages)
        if input_error:
            return EXIT_VALIDATION_FAILED
        if bool(getattr(args, "strict", False)) and pending is not None:
            required_tools = set(setup_profile(mode)["required_tools"])
            if any(not dependency_status.get(tool, False) for tool in required_tools):
                return EXIT_MISSING_EXTERNAL_TOOL
            github_auth = next(
                (check for check in github_checks if check.name == "GitHub auth"),
                None,
            )
            if pending.id == "aws" and (aws_identity is None or aws_identity.status != "OK"):
                return EXIT_AUTH_FAILED
            if pending.id == "github" and (github_auth is None or github_auth.status != "OK"):
                return EXIT_AUTH_FAILED
            return EXIT_VALIDATION_FAILED
        return EXIT_OK
    except InputCancelled:
        if state is not None:
            save_setup_state(root, state)
            print(
                info(
                    f"Setup paused at step `{state.get('last_step', 'mode')}`. "
                    "Rerun `devsecops setup` to resume."
                )
            )
        else:
            print(info("Setup paused before progress was created."))
        return EXIT_OK


def cmd_start(args: argparse.Namespace) -> int:
    """Compatibility handler for the previous public command name."""

    return cmd_setup(args)


def file_exists_check(root: Path, label: str, path: str) -> dict[str, str]:
    full_path = root / path
    return {
        "name": label,
        "status": "OK" if full_path.exists() else "BLOCKED",
        "detail": path if full_path.exists() else f"Missing {path}.",
    }


def file_contains_check(root: Path, label: str, path: str, snippets: list[str]) -> dict[str, str]:
    full_path = root / path
    if not full_path.exists():
        return {"name": label, "status": "BLOCKED", "detail": f"Missing {path}."}
    text = full_path.read_text(encoding="utf-8")
    missing = [snippet for snippet in snippets if snippet not in text]
    return {
        "name": label,
        "status": "OK" if not missing else "BLOCKED",
        "detail": path if not missing else f"{path} is missing: " + ", ".join(missing),
    }


def test_contains_check(root: Path, label: str, snippets: list[str]) -> dict[str, str]:
    return file_contains_check(root, label, "cli/tests/test_devsecops_cli.py", snippets)


def make_criterion(
    criterion_id: str,
    title: str,
    evidence: list[str],
    checks: list[dict[str, str]],
    next_action: str,
) -> dict[str, Any]:
    blocked = [check for check in checks if check["status"] != "OK"]
    return {
        "id": criterion_id,
        "title": title,
        "status": "OK" if not blocked else "BLOCKED",
        "evidence": evidence,
        "checks": checks,
        "next_action": "No action required." if not blocked else next_action,
    }


def evidence_file_checks(evidence_dir: Path, required_files: list[str]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for relative in required_files:
        path = evidence_dir / relative
        if not path.exists():
            checks.append({"name": relative, "status": "BLOCKED", "detail": f"Missing {path}."})
            continue
        if path.is_file() and path.stat().st_size == 0:
            checks.append({"name": relative, "status": "BLOCKED", "detail": f"{path} is empty."})
            continue
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                checks.append({"name": relative, "status": "BLOCKED", "detail": f"{path} is not valid JSON: {exc.msg}."})
                continue
        checks.append(
            {
                "name": relative,
                "status": "OK",
                "detail": str(path),
            }
        )
    return checks


def v1_criteria_payload(root: Path, evidence_dir: Path | None = None) -> dict[str, Any]:
    if evidence_dir is None:
        evidence_dir = root / PRODUCTION_EVIDENCE_DIR / f"v{VERSION}"
    elif not evidence_dir.is_absolute():
        evidence_dir = root / evidence_dir
    evidence_dir_display = str(evidence_dir.relative_to(root)) if evidence_dir.is_relative_to(root) else str(evidence_dir)

    criteria = [
        make_criterion(
            "cli-command-stability",
            "CLI command groups and core flags are stable.",
            [
                "devsecops inventory --format json",
                "docs/stability-contract.md",
                "docs/command-inventory.md",
                "test_command_inventory_json_exposes_stability_contract",
            ],
            [
                file_exists_check(root, "Stability contract doc", "docs/stability-contract.md"),
                file_exists_check(root, "Command inventory doc", "docs/command-inventory.md"),
                test_contains_check(root, "Inventory regression tests", ["test_command_inventory_json_exposes_stability_contract"]),
                {
                    "name": "Stable command inventory",
                    "status": "OK" if any(item["command"] == "devsecops criteria" and item["status"] == "stable" for item in COMMAND_CONTRACTS) else "BLOCKED",
                    "detail": "`devsecops criteria` is listed as a stable release command.",
                },
            ],
            "Run `devsecops inventory --format json` and update docs/stability-contract.md or command contracts.",
        ),
        make_criterion(
            "config-schema-migration",
            "Config schema versioning and migration behavior are implemented.",
            [
                "devsecops config schema --format json",
                "docs/upgrade-guide.md",
                "test_future_config_schema_version_fails_closed_before_rendering",
            ],
            [
                {"name": "Current config schema version", "status": "OK", "detail": str(CONFIG_SCHEMA_VERSION)},
                file_exists_check(root, "Upgrade guide", "docs/upgrade-guide.md"),
                test_contains_check(
                    root,
                    "Config migration regression tests",
                    [
                        "test_load_legacy_config_without_schema_version_migrates_to_current_schema",
                        "test_future_config_schema_version_fails_closed_before_rendering",
                        "test_config_schema_documents_migration_and_rollback_contract",
                    ],
                ),
            ],
            "Update config migration tests, docs/upgrade-guide.md, and `devsecops config schema` output.",
        ),
        make_criterion(
            "clean-config-e2e",
            "Clean config generation, validation, rendering, and readiness are covered by end-to-end tests.",
            [
                "test_config_new_show_schema_diff_and_reset_workflow",
                "test_e2e_config_validate_render_report_in_temp_repo",
                ".github/workflows/ci.yml",
            ],
            [
                file_exists_check(root, "CI workflow", ".github/workflows/ci.yml"),
                test_contains_check(
                    root,
                    "Clean config and E2E tests",
                    [
                        "test_config_new_show_schema_diff_and_reset_workflow",
                        "test_e2e_config_validate_render_report_in_temp_repo",
                    ],
                ),
            ],
            "Add or restore clean-config/E2E coverage before marking v1.0 stable.",
        ),
        make_criterion(
            "generated-artifacts-deterministic",
            "Generated Terraform and GitHub artifacts are deterministic and documented.",
            [
                "docs/generated-artifacts.md",
                "cli/tests/golden/",
                "test_rendered_artifacts_have_stable_diffs_across_repeated_runs",
            ],
            [
                file_exists_check(root, "Generated artifacts doc", "docs/generated-artifacts.md"),
                file_exists_check(root, "Golden artifact fixtures", "cli/tests/golden"),
                test_contains_check(
                    root,
                    "Generated artifact regression tests",
                    [
                        "test_rendered_artifacts_have_stable_diffs_across_repeated_runs",
                        "test_generated_github_artifacts_match_golden_fixtures",
                    ],
                ),
            ],
            "Update generated artifact docs and golden tests before releasing stable.",
        ),
        make_criterion(
            "production-walkthrough-documented",
            "At least one full AWS/GitHub production deployment walkthrough is documented.",
            [
                "docs/production-deployment-evidence.md",
                "docs/first-successful-pipeline.md",
                "README.md production deployment flow",
            ],
            [
                file_contains_check(
                    root,
                    "Production evidence walkthrough",
                    "docs/production-deployment-evidence.md",
                    [
                        "workflow-run.json",
                        "terraform-output.json",
                        "aws-outputs.json",
                        "health.json",
                        "cloudwatch-tail.txt",
                        "active-lambda-image.txt",
                    ],
                ),
                test_contains_check(root, "Production evidence docs test", ["test_production_evidence_docs_cover_milestone_eight_contract"]),
            ],
            "Update docs/production-deployment-evidence.md with the full AWS/GitHub walkthrough.",
        ),
        make_criterion(
            "local-rollback-safe",
            "Local rollback cannot overwrite files outside the CLI-owned file set.",
            [
                "SNAPSHOT_FILES allowlist",
                "docs/generated-artifacts.md",
                "test_snapshot_restore_does_not_overwrite_user_owned_file",
            ],
            [
                {"name": "Snapshot allowlist", "status": "OK" if SNAPSHOT_FILE_PATHS else "BLOCKED", "detail": ", ".join(sorted(SNAPSHOT_FILE_PATHS))},
                file_exists_check(root, "Generated artifacts doc", "docs/generated-artifacts.md"),
                test_contains_check(
                    root,
                    "Rollback allowlist tests",
                    [
                        "test_snapshot_restore_does_not_overwrite_user_owned_file",
                        "test_snapshot_restore_ignores_paths_outside_cli_allowlist",
                    ],
                ),
            ],
            "Restore rollback allowlist tests and generated-artifact rollback documentation.",
        ),
        make_criterion(
            "security-controls-regression",
            "Security controls have documented behavior and regression tests.",
            [
                "docs/security-controls.md",
                "AWS_policy.md",
                "test_workflow_security_hardening_contract",
                "test_terraform_security_hardening_contract",
            ],
            [
                file_exists_check(root, "Security controls doc", "docs/security-controls.md"),
                file_exists_check(root, "AWS OIDC/IAM guidance", "AWS_policy.md"),
                test_contains_check(
                    root,
                    "Security regression tests",
                    [
                        "test_workflow_security_hardening_contract",
                        "test_terraform_security_hardening_contract",
                    ],
                ),
            ],
            "Update security docs and workflow/Terraform regression tests.",
        ),
        make_criterion(
            "release-upgrade-documented",
            "Release and upgrade flows are documented.",
            [
                "docs/distribution.md",
                "docs/release-checklist.md",
                "docs/upgrade-guide.md",
                "docs/release-v0.13.1.md",
            ],
            [
                file_exists_check(root, "Distribution guide", "docs/distribution.md"),
                file_exists_check(root, "Release checklist", "docs/release-checklist.md"),
                file_exists_check(root, "Upgrade guide", "docs/upgrade-guide.md"),
                file_exists_check(root, "Latest release notes", "docs/release-v0.13.1.md"),
            ],
            "Update distribution, release, upgrade, and latest release-note docs.",
        ),
        make_criterion(
            "known-limitations-explicit",
            "Known limitations are explicit rather than hidden in implementation details.",
            [
                "docs/known-limitations.md",
                "README.md Current Limitations",
                "docs/v1.0.0-release-candidate-checklist.md blocker register",
            ],
            [
                file_contains_check(root, "Known limitations register", "docs/known-limitations.md", ["Accepted Limitations", "Blockers Before v1.0.0 Stable"]),
                file_contains_check(root, "README limitations section", "README.md", ["## Current Limitations"]),
                file_contains_check(root, "RC blocker register", "docs/v1.0.0-release-candidate-checklist.md", ["Blocker Register For v1.0.0 Stable"]),
            ],
            "Keep accepted limitations and stable-release blockers explicit in docs.",
        ),
    ]

    stable_release_gates = [
        make_criterion(
            "production-evidence-bundle-attached",
            "Full AWS/GitHub production evidence bundle is attached.",
            [str(evidence_dir), "docs/production-deployment-evidence.md"],
            evidence_file_checks(evidence_dir, PRODUCTION_EVIDENCE_REQUIRED_FILES),
            f"Run docs/production-deployment-evidence.md and store the required files under {evidence_dir_display}.",
        ),
        make_criterion(
            "wsl2-compatibility-transcript-attached",
            "WSL2 compatibility transcript is attached.",
            [str(evidence_dir / WSL2_EVIDENCE_REQUIRED_FILES[0]), "docs/distribution.md"],
            evidence_file_checks(evidence_dir, WSL2_EVIDENCE_REQUIRED_FILES),
            f"Capture WSL2 install, dry-run, completion, and test transcript in {evidence_dir_display}/{WSL2_EVIDENCE_REQUIRED_FILES[0]}.",
        ),
    ]

    next_actions = [
        item["next_action"]
        for item in [*criteria, *stable_release_gates]
        if item["status"] != "OK"
    ]
    return {
        "kind": "v1-criteria",
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "cli_version": VERSION,
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "evidence_dir": evidence_dir_display,
        "stable_ready": not next_actions,
        "criteria": criteria,
        "stable_release_gates": stable_release_gates,
        "next_actions": next_actions or ["No action required."],
    }


def print_v1_criteria(payload: dict[str, Any]) -> None:
    draw_table(
        ["Criterion", "Status", "Next Action"],
        [[item["title"], item["status"], item["next_action"]] for item in payload["criteria"]],
        title="Version 1.0 Criteria",
    )
    print()
    draw_table(
        ["Stable Release Gate", "Status", "Next Action"],
        [[item["title"], item["status"], item["next_action"]] for item in payload["stable_release_gates"]],
        title="Stable Release Gates",
    )
    print()
    draw_box(
        "Stable Readiness",
        [
            f"Stable ready: {str(payload['stable_ready']).lower()}",
            f"Evidence dir: {payload['evidence_dir']}",
            f"Next: {payload['next_actions'][0]}",
        ],
    )


def cmd_criteria(args: argparse.Namespace) -> int:
    root = repo_root()
    evidence_arg = getattr(args, "evidence_dir", None)
    payload = v1_criteria_payload(root, Path(evidence_arg) if evidence_arg else None)
    if getattr(args, "format", "human") == "json":
        emit_json(payload)
    else:
        print_v1_criteria(payload)
    if getattr(args, "strict", False) and not payload["stable_ready"]:
        return EXIT_VALIDATION_FAILED
    return EXIT_OK


def terraform_validate_evidence(root: Path) -> dict[str, Any]:
    if not command_exists("terraform"):
        return {"available": False, "returncode": None, "detail": "`terraform` not found on PATH."}
    if missing_project_files(root):
        return {"available": False, "returncode": None, "detail": "Required project files are missing."}
    result = run_command(["terraform", "-chdir=terraform", "validate", "-no-color"], root, timeout=60)
    return {
        "available": True,
        "returncode": result.returncode,
        "detail": (result.stdout or result.stderr or "").strip() or "Terraform validate completed.",
    }


def collect_rc_evidence(root: Path, output_dir: Path) -> dict[str, Any]:
    cfg = load_config(root)
    checks = collect_checks(root, cfg, deep=False)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    terraform_validate = terraform_validate_evidence(root)
    files: dict[str, str] = {
        "version.txt": f"devsecops {VERSION}\n",
        "inventory.json": json.dumps(inventory_payload(), indent=2, sort_keys=True) + "\n",
        "config-schema.json": json.dumps(config_schema(), indent=2, sort_keys=True) + "\n",
        "config-schema.md": config_schema_markdown() + "\n",
        "readiness.json": json.dumps(checks_payload("readiness", checks, context={"deep": False}), indent=2, sort_keys=True) + "\n",
        "audit-report.json": audit_report_json(cfg, checks, deep=False),
        "criteria.json": json.dumps(v1_criteria_payload(root), indent=2, sort_keys=True) + "\n",
        "terraform-validate.txt": terraform_validate["detail"] + "\n",
    }
    written: list[str] = []
    for name, content in files.items():
        path = output_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(str(path.relative_to(root)) if path.is_relative_to(root) else str(path))

    manifest = {
        "kind": "release-candidate-evidence",
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "output_dir": str(output_dir.relative_to(root)) if output_dir.is_relative_to(root) else str(output_dir),
        "files": written,
        "terraform_validate": terraform_validate,
    }
    manifest_path = output_dir / "manifest.json"
    manifest["files"].append(str(manifest_path.relative_to(root)) if manifest_path.is_relative_to(root) else str(manifest_path))
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def cmd_evidence(args: argparse.Namespace) -> int:
    command = getattr(args, "evidence_command", None)
    if command != "collect":
        print(fail("Usage: devsecops evidence collect --rc"))
        return EXIT_VALIDATION_FAILED
    if not getattr(args, "rc", False):
        print(fail("Pass --rc to collect release-candidate evidence."))
        return EXIT_VALIDATION_FAILED
    manifest = collect_rc_evidence(repo_root(), Path(getattr(args, "output", None) or RC_EVIDENCE_DIR))
    draw_box(
        "Release Candidate Evidence",
        [
            f"Output: {manifest['output_dir']}",
            f"Files: {len(manifest['files'])}",
            f"Terraform validate: {manifest['terraform_validate']['detail']}",
        ],
    )
    return EXIT_OK


def cmd_validate_config(args: argparse.Namespace) -> int:
    cfg = load_config(repo_root())
    checks = validate_config(cfg)
    output_format = getattr(args, "format", "human")
    emit_check_output("Config", checks, output_format=output_format)
    if getattr(args, "strict", False):
        if output_format != "json":
            print_strict_validation_summary(checks)
        return strict_exit_code(checks, strict=True, fail_on_warn=True)
    return EXIT_VALIDATION_FAILED if any(check.status == "FAIL" for check in checks) else EXIT_OK


def cmd_set(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    if args.key not in CONFIG_SET_PATHS:
        print(fail("Unknown config key: ") + args.key)
        print("Allowed keys:")
        for key in sorted(CONFIG_SET_PATHS):
            print(f"  {key}")
        return 1
    try:
        current = nested_get(cfg, args.key)
        value = parse_config_value(args.value, current)
        nested_set(cfg, args.key, value)
    except (KeyError, ValueError) as exc:
        print(fail(str(exc)))
        return 1
    snapshot_before_change(root, "set", f"Before setting {args.key} to {args.value}.")
    write_config(root, cfg)
    print(ok("Updated ") + f"{CONFIG_FILE}: {args.key} = {toml_value(value)}")
    if args.render:
        return run_render(root, snapshot=False)
    return 0


def apply_preset(root: Path, name: str, render: bool = False) -> int:
    if name not in PRESETS:
        print(fail("Unknown preset: ") + name)
        print("Available presets: " + ", ".join(PRESET_ORDER))
        return 1
    current = load_config(root)
    cfg = preset_config(name)
    for key in ["project_name", "aws_region", "lambda_image_uri", "terraform_admin_role_name", "backend"]:
        cfg[key] = current[key]
    snapshot_before_change(root, "preset", f"Before applying `{name}` preset.")
    write_config(root, cfg)
    print(ok("Applied preset ") + name)
    if render:
        return run_render(root, snapshot=False)
    return 0


def cmd_preset(args: argparse.Namespace) -> int:
    command = args.command
    name = args.name
    if command is None:
        print_preset_list()
        return 0
    if command == "list":
        if name:
            print(fail("`preset list` does not take a preset name."))
            return 1
        print_preset_list()
        return 0
    if command == "show":
        if not name:
            print(fail("Usage: devsecops preset show <name>"))
            return 1
        return print_preset_detail(name)
    if command == "apply":
        if not name:
            print(fail("Usage: devsecops preset apply <name> [--render]"))
            return 1
        return apply_preset(repo_root(), name, render=args.render)
    if command in PRESETS and name is None:
        return apply_preset(repo_root(), command, render=args.render)
    print(fail("Unknown preset command: ") + command)
    print("Usage: devsecops preset list | show <name> | apply <name> [--render]")
    return 1


def compose_summary_rows(cfg: dict[str, Any]) -> list[list[str]]:
    return [
        ["Snyk container scan", "yes" if cfg["enable_snyk_scan"] else "no"],
        ["DAST", "yes" if cfg["enable_dast"] else "no"],
        ["Health check", "yes" if cfg["enable_http_validation"] else "no"],
        ["Strict CORS", "yes" if uses_strict_cors(cfg) else "no"],
        ["Prod approval environment", "yes" if cfg["use_prod_approval_environment"] else "no"],
        ["Separate AWS plan role", "yes" if cfg["use_separate_aws_plan_role"] else "no"],
    ]


def cmd_compose(args: argparse.Namespace) -> int:
    root = repo_root()
    current = load_config(root)
    draw_box(
        "Pipeline Composer",
        [
            "Choose controls for the generated local config, Terraform/GitHub helper artifacts, and readiness report.",
            "Type `b`, `back`, `0`, or `cancel` at any prompt to stop without writing files.",
        ],
    )
    try:
        answers = {
            "enable_snyk_scan": prompt_bool("Enable Snyk container scan", bool(current["enable_snyk_scan"]), allow_cancel=True),
            "enable_dast": prompt_bool("Enable DAST", bool(current["enable_dast"]), allow_cancel=True),
            "enable_http_validation": prompt_bool("Enable health check", bool(current["enable_http_validation"]), allow_cancel=True),
            "use_strict_cors": prompt_bool("Use strict CORS", uses_strict_cors(current), allow_cancel=True),
            "use_prod_approval_environment": prompt_bool(
                "Use prod approval environment",
                bool(current["use_prod_approval_environment"]),
                allow_cancel=True,
            ),
            "use_separate_aws_plan_role": prompt_bool(
                "Use separate AWS plan role",
                bool(current["use_separate_aws_plan_role"]),
                allow_cancel=True,
            ),
        }
    except InputCancelled:
        print(info("Compose cancelled. No files changed."))
        return 0

    cfg = compose_config(current, answers)
    snapshot_before_change(root, "compose", "Before composing pipeline controls.")
    write_config(root, cfg)
    print(ok("Updated ") + str(config_path(root)))
    draw_table(["Control", "Enabled"], compose_summary_rows(cfg), title="Composed Pipeline")

    render_result = run_render(root, snapshot=False)
    if render_result != 0:
        return render_result

    report_path = root / DIST_DIR / "readiness-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    checks = collect_checks(root, load_config(root), deep=False)
    report_path.write_text(markdown_report(cfg, checks), encoding="utf-8")
    print(ok("Wrote ") + str(report_path))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    checks = collect_checks(root, cfg, deep=args.deep)
    output_format = getattr(args, "format", "markdown")
    report = audit_report_json(cfg, checks, deep=args.deep) if output_format == "json" else markdown_report(cfg, checks)
    if args.output:
        path = Path(args.output)
    else:
        path = root / (AUDIT_REPORT if output_format == "json" else DIST_DIR / "readiness-report.md")
    if not path.is_absolute():
        path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_before_change(root, "report", f"Before writing report to {path.relative_to(root) if path.is_relative_to(root) else path}.")
    path.write_text(report, encoding="utf-8")
    print(ok("Wrote ") + str(path))
    if args.print:
        print()
        print(report)
    return 0


def cmd_github_setup(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    if args.apply:
        precheck = github_setup_precheck(root, cfg, args)
        emit_check_output("GitHub Setup Precheck", precheck)
        print()
        return apply_github_setup(root, cfg, args)
    script = github_setup_script(cfg)
    if args.write:
        path = root / DIST_DIR / "github-setup.sh"
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_before_change(root, "github-setup", "Before writing GitHub setup script.")
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
        print(ok("Wrote ") + str(path))
    else:
        print(script)
    return 0


def cmd_snapshots(args: argparse.Namespace) -> int:
    root = repo_root()
    snapshots = print_snapshot_list(root)
    if args.show:
        snapshot = resolve_snapshot_selection(root, args.show)
        if not snapshot:
            print(fail("Snapshot not found: ") + args.show)
            return 1
        print()
        print_snapshot_detail(root, snapshot)
    elif snapshots:
        print()
        print(info("Use `devsecops snapshots --show <number-or-id>` to inspect changes."))
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    root = repo_root()
    target = args.to
    if args.last or not target:
        snapshot = resolve_snapshot(root, last=True)
    else:
        snapshot = resolve_snapshot_selection(root, target)
    if not snapshot:
        print(fail("No matching snapshot found."))
        return 1
    draw_box("Local Snapshot Restore", rollback_boundary_lines())
    print()
    print_snapshot_detail(root, snapshot)
    changes = snapshot_changes(root, snapshot)
    if args.dry_run:
        print()
        print(info("Dry run only. No files changed."))
        return 0
    if not changes:
        print(info("Snapshot matches current files. Nothing to roll back."))
        return 0
    if not args.yes:
        confirmation = input(f"\nRollback to {snapshot.get('id')}? Type yes to continue: ").strip().lower()
        if confirmation != "yes":
            print(info("Rollback cancelled."))
            return 0
    snapshot_before_change(root, "rollback", f"Before rolling back to {snapshot.get('id')}.")
    restore_snapshot(root, snapshot)
    print(ok("Rolled back to snapshot ") + str(snapshot.get("id")))
    return 0


def cmd_gh_doctor(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    checks = collect_github_checks(root, cfg)
    emit_check_output(
        "GitHub",
        checks,
        output_format=getattr(args, "format", "human"),
        context={"scope": "repository readiness checks through GitHub CLI"},
    )
    return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)


def cmd_gh_status(args: argparse.Namespace) -> int:
    status = collect_github_actions_status(repo_root(), limit=args.limit)
    output_format = getattr(args, "format", "human")
    if status.error:
        if output_format == "json":
            emit_json(
                {
                    "kind": "github-actions-status",
                    "schema_version": CONTRACT_SCHEMA_VERSION,
                    "error": status.error,
                    "runs": [],
                    "failed_jobs": [],
                    "failed_steps": [],
                    "next_actions": [],
                }
            )
        else:
            print(warn(status.error))
        if not getattr(args, "strict", False):
            return EXIT_OK
        if "not found on PATH" in status.error:
            return EXIT_MISSING_EXTERNAL_TOOL
        if "auth" in status.error.lower() or "login" in status.error.lower():
            return EXIT_AUTH_FAILED
        return EXIT_VALIDATION_FAILED
    if output_format == "json":
        emit_json(
            {
                "kind": "github-actions-status",
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "error": None,
                "runs": status.runs,
                "failed_jobs": status.failed_jobs,
                "failed_steps": status.failed_steps,
                "next_actions": status.next_actions,
            }
        )
        return EXIT_VALIDATION_FAILED if getattr(args, "strict", False) and status.failed_jobs else EXIT_OK
    if not status.runs:
        print(warn("No GitHub Actions runs found."))
        return EXIT_OK
    if output_format == "compact":
        print(info("Recent GitHub Actions Runs"))
        for row in status.runs:
            print(" | ".join(row[:4]))
        if status.failed_jobs:
            print(warn(f"Failed jobs: {len(status.failed_jobs)}"))
        for action in status.next_actions:
            print("Fix: " + action)
    else:
        draw_table(["Workflow", "Branch", "Status", "Conclusion", "Created"], status.runs, title="Recent GitHub Actions Runs")
        if status.failed_jobs:
            print()
            draw_table(["Workflow", "Job", "Status", "Conclusion"], status.failed_jobs, title="Failed Jobs")
        if status.failed_steps:
            print()
            draw_table(["Workflow", "Job", "Step", "Conclusion", "Runbook"], status.failed_steps, title="Failed Steps")
        if status.next_actions:
            print()
            draw_box("Next Actions", status.next_actions)
        if not status.failed_jobs:
            print(ok("No failed jobs found in inspected runs."))
    return EXIT_VALIDATION_FAILED if getattr(args, "strict", False) and status.failed_jobs else EXIT_OK


def cmd_branch_doctor(args: argparse.Namespace) -> int:
    checks = collect_branch_checks(repo_root(), branch=args.branch)
    emit_check_output(
        "Branch Protection",
        checks,
        output_format=getattr(args, "format", "human"),
        context={"branch": args.branch},
    )
    return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)


def cmd_doctor(args: argparse.Namespace) -> int:
    command = getattr(args, "doctor_command", None) or "local"
    if command == "github":
        return cmd_gh_doctor(args)
    if command == "aws":
        return cmd_aws_doctor(args)
    if command == "branch":
        return cmd_branch_doctor(args)
    if command == "actions":
        return cmd_gh_status(args)
    if command == "all":
        root = repo_root()
        cfg = load_config(root)
        checks = collect_checks(root, cfg, deep=getattr(args, "deep", False))
        checks.extend(collect_github_checks(root, cfg))
        checks.extend(collect_branch_checks(root, branch=getattr(args, "branch", DEFAULT_BRANCH)))
        checks.extend(collect_aws_checks(root, cfg, env_name=getattr(args, "environment", "prod")))
        emit_check_output(
            "Doctor All",
            checks,
            output_format=getattr(args, "format", "human"),
            context={"environment": getattr(args, "environment", "prod"), "branch": getattr(args, "branch", DEFAULT_BRANCH)},
        )
        return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)
    else:
        root = repo_root()
        cfg = load_config(root)
        checks = collect_checks(root, cfg, deep=getattr(args, "deep", False))
        emit_check_output(
            "Doctor Local",
            checks,
            output_format=getattr(args, "format", "human"),
            context={"deep": getattr(args, "deep", False)},
        )
        return strict_exit_code(checks, strict=getattr(args, "strict", False))


def run_init(root: Path, force: bool = False, defaults: bool = False, allow_cancel: bool = False) -> int:
    current = load_config(root)
    path = config_path(root)
    try:
        if path.exists() and not force:
            replace = prompt_bool(f"{CONFIG_FILE} exists. Replace it", False, allow_cancel=allow_cancel)
            if not replace:
                print(info("Kept existing config."))
                return 0

        cfg = default_config()
        if not defaults:
            if not allow_cancel:
                header(current)
            cfg["project_name"] = prompt_text("Project name", current["project_name"], allow_cancel=allow_cancel)
            cfg["aws_region"] = prompt_text("AWS region", current["aws_region"], allow_cancel=allow_cancel)
            cfg["lambda_image_uri"] = prompt_text(
                "Immutable Lambda image URI",
                current["lambda_image_uri"],
                allow_cancel=allow_cancel,
            )
            cfg["enable_snyk_scan"] = prompt_bool(
                "Enable Snyk container scan",
                bool(current["enable_snyk_scan"]),
                allow_cancel=allow_cancel,
            )
            cfg["enable_http_validation"] = prompt_bool(
                "Enable /health smoke test",
                bool(current["enable_http_validation"]),
                allow_cancel=allow_cancel,
            )
            cfg["enable_dast"] = prompt_bool(
                "Enable OWASP ZAP DAST",
                bool(current["enable_dast"]),
                allow_cancel=allow_cancel,
            )
            cfg["use_prod_approval_environment"] = prompt_bool(
                "Use prod approval environment",
                bool(current["use_prod_approval_environment"]),
                allow_cancel=allow_cancel,
            )
            cfg["use_separate_aws_plan_role"] = prompt_bool(
                "Use separate AWS plan role",
                bool(current["use_separate_aws_plan_role"]),
                allow_cancel=allow_cancel,
            )
            cfg["backend"]["bucket"] = prompt_text(
                "Terraform state bucket",
                current["backend"]["bucket"],
                allow_cancel=allow_cancel,
            )
            cfg["backend"]["lock_table"] = prompt_text(
                "DynamoDB lock table",
                current["backend"]["lock_table"],
                allow_cancel=allow_cancel,
            )
            cfg["backend"]["region"] = prompt_text(
                "Backend AWS region",
                current["backend"]["region"],
                allow_cancel=allow_cancel,
            )

            for env_name, env_cfg in cfg["environments"].items():
                print()
                print(info(f"{env_name} environment"))
                current_env = current["environments"][env_name]
                env_cfg["lambda_memory_size"] = prompt_int(
                    f"{env_name} Lambda memory MB",
                    int(current_env["lambda_memory_size"]),
                    allow_cancel=allow_cancel,
                )
                env_cfg["lambda_timeout"] = prompt_int(
                    f"{env_name} Lambda timeout seconds",
                    int(current_env["lambda_timeout"]),
                    allow_cancel=allow_cancel,
                )
                env_cfg["log_retention_days"] = prompt_int(
                    f"{env_name} log retention days",
                    int(current_env["log_retention_days"]),
                    allow_cancel=allow_cancel,
                )
                env_cfg["api_throttling_burst_limit"] = prompt_int(
                    f"{env_name} API burst limit",
                    int(current_env["api_throttling_burst_limit"]),
                    allow_cancel=allow_cancel,
                )
                env_cfg["api_throttling_rate_limit"] = prompt_int(
                    f"{env_name} API rate limit",
                    int(current_env["api_throttling_rate_limit"]),
                    allow_cancel=allow_cancel,
                )
    except InputCancelled:
        print(info("Configuration cancelled. No files changed."))
        return 0

    snapshot_before_change(root, "init", "Before creating or replacing local pipeline config.")
    path.write_text(dump_config_toml(cfg), encoding="utf-8")
    print(ok("Created ") + str(path))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    return run_init(repo_root(), force=args.force, defaults=args.defaults)


def cmd_preflight(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    checks = collect_image_preflight_checks(
        cfg,
        image_uri=getattr(args, "image_uri", None),
        env_name=getattr(args, "environment", "prod"),
    )
    output_format = getattr(args, "format", "human")
    context = {"environment": getattr(args, "environment", "prod"), "aws_region": cfg["aws_region"]}
    if output_format == "json":
        kind = "image-validation" if getattr(args, "command", None) == "image" else "preflight"
        payload = checks_payload(kind, checks, context=context)
        if kind == "image-validation":
            payload.pop("overall_breakdown_score", None)
        emit_json(payload)
    else:
        emit_check_output("Validate Image", checks, output_format=output_format, context=context)
    return EXIT_VALIDATION_FAILED if any(check.status == "FAIL" for check in checks) else EXIT_OK


def dry_run_config(root: Path, preset_name: str, image_uri: str | None = None) -> tuple[dict[str, Any], str]:
    if config_path(root).exists():
        cfg = load_config(root)
        source = str(CONFIG_FILE)
    else:
        cfg = clean_config(preset_name)
        source = f"clean `{preset_name}` preset (not written)"
    if image_uri:
        cfg["lambda_image_uri"] = image_uri
    return cfg, source


def cmd_dry_run(args: argparse.Namespace) -> int:
    root = repo_root()
    env_name = getattr(args, "environment", "prod")
    cfg, source = dry_run_config(root, getattr(args, "preset", "balanced"), getattr(args, "image_uri", None))
    outputs = render_outputs(root, cfg)
    image_checks = collect_image_preflight_checks(cfg, env_name=env_name)
    readiness_checks = collect_checks(root, cfg, deep=False)

    draw_box(
        "First Successful Pipeline Dry Run",
        [
            "No files changed.",
            "AWS credentials are not required for this dry run.",
            f"Config source: {source}",
            f"Environment target: {env_name}",
        ],
    )
    print_render_plan(root, outputs, title="Files that would be generated")
    print()
    print_checks(image_checks)
    print()
    print_gap_summary(readiness_checks, limit=8)
    print()
    print(info("Next documented path: docs/first-successful-pipeline.md"))
    return EXIT_OK


def display_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def render_plan_rows(root: Path, outputs: dict[Path, str]) -> list[list[str]]:
    rows = []
    for path, content in outputs.items():
        if not path.exists():
            state = "create"
        elif path.read_text(encoding="utf-8") == content:
            state = "no change"
        else:
            state = "update"
        rows.append([display_path(root, path), state, f"{len(content.splitlines())} lines"])
    return rows


def print_render_plan(root: Path, outputs: dict[Path, str], title: str = "Deployment File Plan") -> None:
    draw_table(["File", "Action", "Size"], render_plan_rows(root, outputs), title=title)


def run_render(root: Path, snapshot: bool = True, dry_run: bool = False) -> int:
    cfg = load_config(root)
    outputs = render_outputs(root, cfg)
    if dry_run:
        print(info("Dry run only. No files changed."))
        print_render_plan(root, outputs)
        return 0

    dist = root / DIST_DIR
    dist.mkdir(parents=True, exist_ok=True)
    if snapshot:
        snapshot_before_change(root, "generate", "Before generating Terraform and GitHub deployment files.")

    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if path.name.endswith(".sh"):
            path.chmod(0o755)
        print(ok("Generated ") + str(path))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    return run_render(repo_root(), dry_run=getattr(args, "dry_run", False))


def cmd_readiness(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    checks = collect_checks(root, cfg, deep=getattr(args, "deep", False))
    output_format = getattr(args, "format", "human")
    if output_format == "json":
        emit_json(checks_payload("readiness", checks, context={"deep": getattr(args, "deep", False)}))
    elif output_format == "compact":
        print_readiness_breakdown(checks, compact=True)
        print()
        print_gap_summary(checks, limit=5)
    else:
        print_readiness_details(root, deep=getattr(args, "deep", False))
    return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)


def cmd_health(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    checks = collect_health_checks(
        root,
        cfg,
        url=getattr(args, "url", None),
        timeout=getattr(args, "timeout", 20),
        aws_sigv4=getattr(args, "aws_sigv4", False),
        aws_region=getattr(args, "aws_region", None),
    )
    emit_check_output(
        "Health",
        checks,
        output_format=getattr(args, "format", "human"),
        context={
            "source": "url" if getattr(args, "url", None) else "terraform output",
            "timeout_seconds": getattr(args, "timeout", 20),
            "aws_sigv4": bool(getattr(args, "aws_sigv4", False)),
        },
    )
    return EXIT_VALIDATION_FAILED if any(check.status == "FAIL" for check in checks) else EXIT_OK


def cmd_aws_doctor(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    checks = collect_aws_checks(root, cfg, env_name=args.environment)
    emit_check_output(
        "AWS",
        checks,
        output_format=getattr(args, "format", "human"),
        context={"environment": args.environment},
    )
    return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)


def cmd_aws_outputs(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    outputs, checks = inspect_aws_outputs(root, cfg, env_name=getattr(args, "environment", "prod"))
    output_format = getattr(args, "format", "human")
    if output_format == "json":
        emit_json(
            {
                "kind": "aws-outputs",
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "environment": getattr(args, "environment", "prod"),
                "outputs": outputs,
                "checks": [check_to_dict(check) for check in checks],
                "next_actions": [readiness_action_for_check(check) for check in checks if check.scored and check.status != "OK"],
            }
        )
    else:
        draw_box(
            "AWS Deployed Outputs",
            [
                "Read-only inspection of deployed Lambda, API Gateway, and log resources.",
                f"Environment: {outputs['environment']}",
                f"Region: {outputs['aws_region']}",
            ],
        )
        print()
        draw_table(["Output", "Value"], [[key, value or "(not found)"] for key, value in outputs.items()])
        print()
        print_compact_checks(checks, title="AWS Output Checks")
    return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)


def cmd_aws(args: argparse.Namespace) -> int:
    command = getattr(args, "aws_command", None) or "outputs"
    if command == "doctor":
        return cmd_aws_doctor(args)
    if command == "outputs":
        return cmd_aws_outputs(args)
    print(fail("Unknown AWS command: ") + str(command))
    print("Usage: devsecops aws [doctor|outputs]")
    return EXIT_VALIDATION_FAILED


def cmd_github(args: argparse.Namespace) -> int:
    command = getattr(args, "github_command", None) or "status"
    if command == "setup":
        return cmd_github_setup(args)
    if command == "doctor":
        return cmd_gh_doctor(args)
    if command == "status":
        return cmd_gh_status(args)
    if command == "branch":
        return cmd_branch_doctor(args)
    print(fail("Unknown GitHub command: ") + str(command))
    print("Usage: devsecops github [setup|doctor|status|branch]")
    return EXIT_VALIDATION_FAILED


def cmd_terraform(args: argparse.Namespace) -> int:
    command = getattr(args, "terraform_command", None)
    if command == "plan":
        return cmd_plan(args)
    if command == "bootstrap":
        return cmd_bootstrap(args)
    print(fail("Usage: devsecops terraform plan <env> | bootstrap [--apply]"))
    return EXIT_VALIDATION_FAILED


def cmd_snapshot(args: argparse.Namespace) -> int:
    root = repo_root()
    command = getattr(args, "snapshot_command", None) or "list"
    output_format = getattr(args, "format", "human")
    if command == "list":
        snapshots = list_snapshots(root)
        if output_format == "json":
            emit_json({"kind": "snapshots", "schema_version": CONTRACT_SCHEMA_VERSION, "snapshots": snapshots})
        elif snapshots:
            draw_table(["#", "Snapshot", "Created", "Operation"], snapshot_rows(snapshots), title="Snapshots")
        else:
            print(warn("No snapshots found."))
        return EXIT_OK
    if command == "show":
        selection = getattr(args, "selection", None)
        snapshot = resolve_snapshot_selection(root, selection) if selection else resolve_snapshot(root, last=True)
        if not snapshot:
            print(warn("Snapshot not found."))
            return EXIT_VALIDATION_FAILED
        if output_format == "json":
            payload = dict(snapshot)
            payload["changes"] = snapshot_changes(root, snapshot)
            emit_json({"kind": "snapshot", "schema_version": CONTRACT_SCHEMA_VERSION, "snapshot": payload})
        else:
            print_snapshot_detail(root, snapshot)
        return EXIT_OK
    if command == "restore":
        rollback_args = argparse.Namespace(
            to=getattr(args, "to", None),
            last=getattr(args, "last", False),
            dry_run=getattr(args, "dry_run", False),
            yes=getattr(args, "yes", False),
        )
        return cmd_rollback(rollback_args)
    print(fail("Unknown snapshot command: ") + str(command))
    print("Usage: devsecops snapshot [list|show|restore]")
    return EXIT_VALIDATION_FAILED


def run_plan(root: Path, env_name: str, no_init: bool = False, create_workspace: bool = False) -> int:
    cfg = load_config(root)
    if env_name not in cfg["environments"]:
        print(fail("Unknown environment: ") + env_name)
        return 1
    if not (root / GENERATED_TFVARS).exists():
        print(warn("Missing generated tfvars. Generating deployment files first."))
        run_render(root)

    if not no_init:
        init_command = ["terraform", "-chdir=terraform", "init", "-input=false", "-no-color"]
        print(info("$ " + " ".join(init_command)))
        init_result = subprocess.run(init_command, cwd=root, check=False)  # nosec B603
        if init_result.returncode != 0:
            return init_result.returncode

    select_command = ["terraform", "-chdir=terraform", "workspace", "select", env_name]
    print(info("$ " + " ".join(select_command)))
    select_result = subprocess.run(select_command, cwd=root, check=False)  # nosec B603
    if select_result.returncode != 0:
        if not create_workspace:
            print(warn(f"Workspace `{env_name}` does not exist. Re-run with --create-workspace if this is expected."))
            return select_result.returncode
        new_command = ["terraform", "-chdir=terraform", "workspace", "new", env_name]
        print(info("$ " + " ".join(new_command)))
        new_result = subprocess.run(new_command, cwd=root, check=False)  # nosec B603
        if new_result.returncode != 0:
            return new_result.returncode

    plan_command = ["terraform", "-chdir=terraform", "plan", "-input=false", "-no-color"]
    print(info("$ " + " ".join(plan_command)))
    plan_result = subprocess.run(plan_command, cwd=root, check=False)  # nosec B603
    if plan_result.returncode != 0:
        return plan_result.returncode
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    return run_plan(
        repo_root(),
        args.environment,
        no_init=args.no_init,
        create_workspace=args.create_workspace,
    )


def cmd_bootstrap(args: argparse.Namespace) -> int:
    root = repo_root()
    cfg = load_config(root)
    bucket = cfg["backend"]["bucket"]
    if not bucket or bucket.startswith("replace-with"):
        print(fail("Set backend.bucket in ") + CONFIG_FILE + " before bootstrap.")
        return 1
    command = [
        "terraform",
        "-chdir=terraform/bootstrap",
        "apply" if args.apply else "plan",
        "-input=false",
        "-no-color",
        f"-var=state_bucket_name={bucket}",
        f"-var=lock_table_name={cfg['backend']['lock_table']}",
        f"-var=aws_region={cfg['backend']['region']}",
    ]
    if args.apply:
        command.insert(4, "-auto-approve")
    print(info("$ terraform -chdir=terraform/bootstrap init -input=false -no-color"))
    init = subprocess.run(  # nosec B603, B607
        ["terraform", "-chdir=terraform/bootstrap", "init", "-input=false", "-no-color"],
        cwd=root,
        check=False,
    )
    if init.returncode != 0:
        return init.returncode
    print(info("$ " + " ".join(command)))
    return subprocess.run(command, cwd=root, check=False).returncode  # nosec B603


def explain_text(topic: str, cfg: dict[str, Any] | None = None) -> list[str]:
    cfg = cfg or default_config()
    normalized = normalize_control_topic(topic)
    if normalized == "all":
        return [
            "Available controls:",
            *[f"{control.id}: {control.title} ({control_state(cfg, control.id)})" for control in control_catalog()],
            "Use `devsecops explain <control>` for concrete CLI, Terraform, GitHub, AWS, scanner, and audit behavior.",
        ]
    control = control_by_id(topic)
    if not control:
        return [
            f"Unknown control: {topic}",
            "Available controls: " + ", ".join(control.id for control in control_catalog()),
        ]
    return [
        f"Control: {control.title}",
        f"State: {control_state(cfg, control.id)}",
        "CLI: " + "; ".join(control.cli_options),
        "Terraform: " + " ".join(control.terraform),
        "GitHub: " + " ".join(control.github),
        "AWS: " + " ".join(control.aws),
        "Scanners: " + " ".join(control.scanners),
        "Audit evidence: " + "; ".join(control.audit_evidence),
        "Guidance: " + control.guidance,
    ]


def cmd_explain(args: argparse.Namespace) -> int:
    draw_box(f"Explain: {args.topic}", explain_text(args.topic, load_config(repo_root())))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    root = repo_root()
    command = getattr(args, "config_command", None) or "show"

    if command in {"new", "create"}:
        preset_name = getattr(args, "preset", "balanced")
        path = config_path(root)
        if path.exists() and not getattr(args, "force", False):
            print(fail(f"{CONFIG_FILE} already exists. Use `devsecops config reset` or pass `--force`."))
            return 1
        if path.exists():
            snapshot_before_change(root, "config-new", "Before replacing local source config.")
        cfg = clean_config(preset_name)
        write_config(root, cfg)
        print(ok("Created clean config ") + str(path))
        if getattr(args, "render", False):
            return run_render(root, snapshot=False)
        return 0

    if command == "reset":
        preset_name = getattr(args, "preset", "balanced")
        snapshot_before_change(root, "config-reset", f"Before resetting local source config to `{preset_name}`.")
        cfg = clean_config(preset_name)
        write_config(root, cfg)
        print(ok("Reset config ") + f"{CONFIG_FILE} to `{preset_name}` preset.")
        if getattr(args, "render", False):
            return run_render(root, snapshot=False)
        return 0

    if command == "validate":
        return cmd_validate_config(args)

    if command == "set":
        return cmd_set(args)

    if command == "schema":
        output_format = getattr(args, "format", "json")
        if output_format == "markdown":
            print(config_schema_markdown())
        else:
            print(json.dumps(config_schema(), indent=2, sort_keys=True))
        return 0

    if command == "diff":
        path = config_path(root)
        if not path.exists():
            print(warn(f"{CONFIG_FILE} does not exist. Run `devsecops config new --preset balanced`."))
            return 1
        preset_name = getattr(args, "preset", None)
        diff = config_preset_diff(root, preset_name) if preset_name else config_file_diff(root)
        if diff:
            print(diff, end="")
            return 1 if getattr(args, "exit_code", False) else 0
        print(ok("No config diff detected."))
        return 0

    if command != "show":
        print(fail("Unknown config command: ") + str(command))
        print("Usage: devsecops config [show|new|validate|diff|reset|schema]")
        return 1

    path = config_path(root)
    if not path.exists():
        print(warn(f"{CONFIG_FILE} does not exist. Run `devsecops config new --preset balanced`."))
        return 1
    output_format = getattr(args, "format", "toml")
    if output_format == "json":
        print(json.dumps(load_config(root), indent=2, sort_keys=True))
    else:
        print(path.read_text(encoding="utf-8"))
    return 0


def menu_status(root: Path, cfg: dict[str, Any], checks: list[Check] | None = None) -> list[str]:
    checks = checks or collect_checks(root, cfg, deep=False)
    breakdown_score = overall_breakdown_score(checks)
    image_state = "configured" if cfg["lambda_image_uri"] else "missing"
    backend_state = "configured" if not cfg["backend"]["bucket"].startswith("replace-with") else "missing"
    return [
        f"Project: {cfg['project_name']}",
        f"Region: {cfg['aws_region']}",
        f"Lambda image: {image_state}",
        f"Backend: {backend_state}",
        f"Health check: {'enabled' if cfg['enable_http_validation'] else 'disabled'}",
        f"DAST: {'enabled' if cfg['enable_dast'] else 'disabled'}",
        "Readiness: " + progress_bar(breakdown_score) + "  [i] details",
    ]


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    else:
        print("\n" * 3)


def pause_for_menu() -> None:
    input("\n[Enter] Back to main menu")
    clear_screen()


MAIN_MENU_ITEMS = [
    ("1", "Continue setup"),
    ("2", "Status"),
    ("3", "Deploy"),
    ("4", "Diagnose problems"),
    ("5", "Configuration"),
    ("6", "Advanced"),
    ("0", "Exit"),
]


def print_main_menu(root: Path) -> None:
    cfg = load_config(root)
    checks = collect_checks(root, cfg, deep=False)
    breakdown_score = overall_breakdown_score(checks)
    action = next_action(root, cfg)
    image_state = "set" if cfg["lambda_image_uri"] else "missing"
    backend_state = "set" if not cfg["backend"]["bucket"].startswith("replace-with") else "missing"
    health_state = "on" if cfg["enable_http_validation"] else "off"
    dast_state = "on" if cfg["enable_dast"] else "off"

    print(color("DevSecOps Pipeline Kit", Style.BOLD))
    print(f"{cfg['project_name']} | {cfg['aws_region']} | status {breakdown_score}%")
    print(f"image: {image_state} | backend: {backend_state} | health: {health_state} | DAST: {dast_state}")
    print()
    print_next_action(action)
    print()
    for key, label in MAIN_MENU_ITEMS:
        print(f"[{key}] {label}")


def open_menu_section(title: str, handler: Any, *args: Any) -> None:
    clear_screen()
    draw_box(title, ["[Enter] returns to the main menu after this section."])
    print()
    handler(*args)
    pause_for_menu()


def continue_setup_destination(action: dict[str, Any]) -> str:
    action_id = str(action["id"])
    command = str(action["command"])
    if action_id == "missing_project_files":
        return "blocked"
    if action_id == "missing_config" and command.startswith(("devsecops setup", "devsecops config new")):
        return "setup"
    if action_id in {"missing_config", "missing_image", "missing_backend"}:
        return "configuration"
    if action_id == "missing_github_setup" and command in {"devsecops generate", "devsecops render"}:
        return "deployment_files"
    if action_id == "missing_github_setup":
        return "github"
    if action_id == "missing_aws_evidence":
        return "diagnostics"
    if action_id == "ready_for_deploy":
        return "deploy"
    if action_id == "ready_for_release_evidence":
        return "reports"
    return "blocked"


def menu_continue_setup(root: Path) -> None:
    action = next_action(root, load_config(root))
    destination = continue_setup_destination(action)
    if destination == "setup":
        clear_screen()
        cmd_setup(argparse.Namespace(preset="balanced", render=False, yes=False))
        pause_for_menu()
    elif destination == "configuration":
        menu_config_hub(root)
    elif destination == "deployment_files":
        menu_generated_files_hub(root)
    elif destination == "github":
        menu_github_hub()
    elif destination == "diagnostics":
        menu_doctor_hub(root)
    elif destination == "deploy":
        menu_deploy_hub()
    elif destination == "reports":
        menu_reports_hub()
    else:
        clear_screen()
        print_next_action(action)
        pause_for_menu()


def show_production_deploy_command() -> None:
    draw_box(
        "Start Production Deployment",
        [
            "Production deployment is delegated to the protected GitHub Actions workflow.",
            "Running the command below may apply Terraform changes to the prod AWS environment.",
            "This menu displays the command but does not execute it automatically.",
        ],
    )
    print("Deploy command:")
    print(f"  {PRODUCTION_DEPLOY_COMMAND}")
    print("Docs: docs/first-successful-pipeline.md#7-run-the-production-workflow-dispatch")


def menu_deploy_hub() -> None:
    clear_screen()
    draw_box(
        "Deploy",
        [
            "Check deployment status, start the protected workflow, or inspect the deployed service.",
            "Opening this section does not change GitHub or AWS.",
        ],
    )
    print()
    print("[1] Check deployment status")
    print("[2] Show production deploy command")
    print("[3] Recent deployment runs")
    print("[4] Deployed AWS resources")
    print("[5] Validate production health endpoint")
    print("[6] Deployment rollback guidance")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    print()
    if choice == "1":
        cmd_status(argparse.Namespace(deep=True, strict=False, format="human", watch=False, interval=5))
    elif choice == "2":
        show_production_deploy_command()
    elif choice == "3":
        cmd_gh_status(argparse.Namespace(strict=False, limit=8, format="human"))
    elif choice == "4":
        cmd_aws_outputs(argparse.Namespace(environment="prod", strict=False, format="human"))
    elif choice == "5":
        cmd_health(
            argparse.Namespace(
                url=None,
                timeout=20,
                aws_sigv4=True,
                aws_region=None,
                format="human",
            )
        )
    elif choice == "6":
        cmd_explain(argparse.Namespace(topic="rollback"))
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_config_hub(root: Path) -> None:
    clear_screen()
    draw_box("Configuration", ["Inspect, validate, and edit local source configuration."])
    print()
    print("[1] Project setup")
    print("[2] Show config")
    print("[3] Validate config")
    print("[4] Edit one setting")
    print("[5] Apply policy preset")
    print("[6] Compare config with canonical form")
    print("[7] Advanced control setup")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        cmd_setup(argparse.Namespace(preset="balanced", render=False, yes=False))
    elif choice == "2":
        cmd_config(argparse.Namespace(config_command="show", format="toml"))
    elif choice == "3":
        cmd_config(argparse.Namespace(config_command="validate", format="human"))
    elif choice == "4":
        key = prompt_text("Config key", "backend.bucket")
        if is_cancel_input(key):
            clear_screen()
            return
        value = prompt_text("Value", "")
        if is_cancel_input(value):
            clear_screen()
            return
        render_after = prompt_bool("Generate deployment files after update", False)
        cmd_config(argparse.Namespace(config_command="set", key=key, value=value, render=render_after))
    elif choice == "5":
        preset_name = prompt_text("Preset", "balanced")
        if is_cancel_input(preset_name):
            clear_screen()
            return
        cmd_preset(argparse.Namespace(command="apply", name=preset_name, render=False))
    elif choice == "6":
        cmd_config(argparse.Namespace(config_command="diff", preset=None, exit_code=False))
    elif choice == "7":
        cmd_compose(argparse.Namespace())
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_readiness_section(root: Path) -> None:
    clear_screen()
    print_readiness_details(root)
    pause_for_menu()


def menu_doctor_hub(root: Path) -> None:
    clear_screen()
    draw_box("Diagnose Problems", ["Check local setup, integrations, deployments, or all areas together."])
    print()
    print("[1] Local setup")
    print("[2] Local setup with Terraform/AWS checks")
    print("[3] GitHub connection")
    print("[4] AWS connection and prod resources")
    print("[5] Recent deployment runs")
    print("[6] Main branch protection")
    print("[7] All checks (compact)")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        cmd_doctor(argparse.Namespace(doctor_command="local", deep=False, strict=False, format="human"))
    elif choice == "2":
        cmd_doctor(argparse.Namespace(doctor_command="local", deep=True, strict=False, format="human"))
    elif choice == "3":
        cmd_doctor(argparse.Namespace(doctor_command="github", strict=False, format="human"))
    elif choice == "4":
        cmd_doctor(argparse.Namespace(doctor_command="aws", environment="prod", strict=False, format="human"))
    elif choice == "5":
        cmd_doctor(argparse.Namespace(doctor_command="actions", strict=False, limit=8, format="human"))
    elif choice == "6":
        cmd_doctor(argparse.Namespace(doctor_command="branch", branch=DEFAULT_BRANCH, strict=False, format="human"))
    elif choice == "7":
        cmd_doctor(
            argparse.Namespace(
                doctor_command="all",
                deep=False,
                branch=DEFAULT_BRANCH,
                environment="prod",
                strict=False,
                format="compact",
            )
        )
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_terraform_hub(root: Path) -> None:
    clear_screen()
    draw_box("Terraform", ["Plan environments or inspect backend bootstrap changes."])
    print()
    print("[1] Bootstrap backend plan")
    print("[2] Plan dev")
    print("[3] Plan staging")
    print("[4] Plan prod")
    print("[5] Custom plan")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        cmd_bootstrap(argparse.Namespace(apply=False))
    elif choice in {"2", "3", "4"}:
        env_name = {"2": "dev", "3": "staging", "4": "prod"}[choice]
        run_plan(root, env_name)
    elif choice == "5":
        env_name = prompt_text("Environment", "dev")
        if is_cancel_input(env_name):
            clear_screen()
            return
        run_plan(root, env_name)
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_github_hub() -> None:
    clear_screen()
    draw_box("GitHub Connection", ["Prepare repository settings and inspect GitHub readiness."])
    print()
    print("[1] Repository setup commands")
    print("[2] Diagnose GitHub connection")
    print("[3] Recent workflow runs")
    print("[4] Main branch protection")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        cmd_github_setup(
            argparse.Namespace(
                write=False,
                apply=False,
                deploy_role_arn=None,
                plan_role_arn=None,
                snyk_token=None,
            )
        )
    elif choice == "2":
        cmd_gh_doctor(argparse.Namespace(strict=False, format="human"))
    elif choice == "3":
        cmd_gh_status(argparse.Namespace(strict=False, limit=8, format="human"))
    elif choice == "4":
        cmd_branch_doctor(argparse.Namespace(branch=DEFAULT_BRANCH, strict=False, format="human"))
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_reference_hub() -> None:
    clear_screen()
    draw_box("Reference", ["Inspect controls, environments, architecture, or a focused control explanation."])
    print()
    print("[1] Security controls")
    print("[2] Environment table")
    print("[3] Architecture")
    print("[4] Explain control")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        cmd_controls(argparse.Namespace())
    elif choice == "2":
        cmd_envs(argparse.Namespace())
    elif choice == "3":
        cmd_architecture(argparse.Namespace())
    elif choice == "4":
        topic = prompt_text("Topic", "oidc")
        if is_cancel_input(topic):
            clear_screen()
            return
        cmd_explain(argparse.Namespace(topic=topic))
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_generated_files_hub(root: Path) -> None:
    clear_screen()
    draw_box(
        "Deployment Files",
        [
            "Generate CLI-owned Terraform inputs and GitHub setup helpers from local config.",
            "Preview is read-only; generate creates a local snapshot before replacing managed files.",
        ],
    )
    print()
    print("[1] Preview generated file changes")
    print("[2] Generate deployment files")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        run_render(root, dry_run=True)
    elif choice == "2":
        run_render(root)
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_reports_hub() -> None:
    clear_screen()
    draw_box(
        "Reports and Release Evidence",
        ["Export readiness evidence or collect maintainer-focused release artifacts."],
    )
    print()
    print("[1] Export readiness report (Markdown)")
    print("[2] Export audit report (JSON)")
    print("[3] Collect release-candidate evidence")
    print("[4] Check stable-release criteria")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        cmd_report(argparse.Namespace(deep=False, format="markdown", output=None, print=False))
    elif choice == "2":
        cmd_report(argparse.Namespace(deep=False, format="json", output=None, print=False))
    elif choice == "3":
        cmd_evidence(argparse.Namespace(evidence_command="collect", rc=True, output=None))
    elif choice == "4":
        cmd_criteria(argparse.Namespace(evidence_dir=None, format="human", strict=False))
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_advanced_hub(root: Path) -> None:
    clear_screen()
    draw_box(
        "Advanced",
        ["Direct access to generated files, providers, evidence, controls, and recovery."],
    )
    print()
    print("[1] Deployment files")
    print("[2] Terraform")
    print("[3] GitHub connection")
    print("[4] Reports and release evidence")
    print("[5] Security and reference")
    print("[6] Snapshots / local rollback")
    print("[0] Back")
    choice = input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        menu_generated_files_hub(root)
    elif choice == "2":
        menu_terraform_hub(root)
    elif choice == "3":
        menu_github_hub()
    elif choice == "4":
        menu_reports_hub()
    elif choice == "5":
        menu_reference_hub()
    elif choice == "6":
        menu_rollback_section(root)
    else:
        print(warn("Unknown option."))


def menu_rollback_section(root: Path) -> None:
    clear_screen()
    draw_box(
        "Snapshots / Rollback",
        rollback_boundary_lines() + ["Choose a number to inspect changes, or type `b`, `back`, `0`, or `cancel` to return."],
    )
    snapshots = print_snapshot_list(root)
    if not snapshots:
        pause_for_menu()
        return

    selection = prompt_text("Snapshot number or id", "1")
    if is_cancel_input(selection):
        return
    snapshot = resolve_snapshot_selection(root, selection)
    if not snapshot:
        print(fail("Snapshot not found."))
        pause_for_menu()
        return

    clear_screen()
    draw_box("Local Snapshot Restore", rollback_boundary_lines())
    print()
    print_snapshot_detail(root, snapshot)
    print()
    print("[1] Preview rollback")
    print("[2] Roll back to this snapshot")
    print("[0] Back to main menu")
    action = input("\nChoose: ").strip()

    if action == "1":
        print()
        print(info("Preview only. No files changed."))
        pause_for_menu()
        return
    if action == "2":
        changes = snapshot_changes(root, snapshot)
        if not changes:
            print(info("Snapshot matches current files. Nothing to roll back."))
            pause_for_menu()
            return
        confirmation = input(f"\nRollback to {snapshot.get('id')}? Type yes to continue: ").strip().lower()
        if confirmation != "yes":
            print(info("Rollback cancelled."))
            pause_for_menu()
            return
        snapshot_before_change(root, "rollback", f"Before rolling back to {snapshot.get('id')}.")
        restore_snapshot(root, snapshot)
        print(ok("Rolled back to snapshot ") + str(snapshot.get("id")))
        pause_for_menu()


def cmd_menu(args: argparse.Namespace) -> int:
    root = repo_root()
    while True:
        clear_screen()
        print_main_menu(root)
        choice = input("\nChoose: ").strip().lower()
        if choice in {"1", "continue", "setup", "next"}:
            menu_continue_setup(root)
        elif choice in {"2", "status", "dashboard", "d"}:
            open_menu_section(
                "Status",
                cmd_status,
                argparse.Namespace(deep=False, strict=False, format="human", watch=False, interval=5),
            )
        elif choice in {"i", "info", "readiness", "?"}:
            menu_readiness_section(root)
        elif choice in {"3", "deploy"}:
            menu_deploy_hub()
        elif choice in {"4", "diagnose", "doctor", "o"}:
            menu_doctor_hub(root)
        elif choice in {"5", "config", "configuration", "c"}:
            menu_config_hub(root)
        elif choice in {"6", "advanced", "a"}:
            menu_advanced_hub(root)
        elif choice in {"t", "terraform"}:
            menu_terraform_hub(root)
        elif choice in {"g", "github"}:
            menu_github_hub()
        elif choice in {"r", "render", "files"}:
            menu_generated_files_hub(root)
        elif choice in {"p", "report", "reports"}:
            menu_reports_hub()
        elif choice in {"s", "snapshot", "snapshots"}:
            menu_rollback_section(root)
        elif choice in {"h", "help", "reference"}:
            menu_reference_hub()
        elif choice in {"0", "q", "quit", "exit"}:
            clear_screen()
            return 0
        else:
            clear_screen()
            print(warn("Unknown option."))
            pause_for_menu()


def build_parser() -> argparse.ArgumentParser:
    """Build the parser with this module as the command-handler registry."""

    return _parser_builder.build_parser(sys.modules[__name__])


def should_print_next_postlude(args: argparse.Namespace) -> bool:
    """Keep machine-readable output clean while guiding every human flow."""

    command = getattr(args, "command", None)
    if command is None or command in {"menu", "setup", "status", "next", "start", "dashboard", "tui", "completion"}:
        return False
    if getattr(args, "format", None) in {"json", "markdown", "toml"}:
        return False
    if command == "config" and getattr(args, "config_command", "show") in {"show", "schema"}:
        return False
    github_setup_output = command in {"github-setup", "gh-setup"} or (
        command == "github" and getattr(args, "github_command", None) == "setup"
    )
    if github_setup_output and not getattr(args, "write", False) and not getattr(args, "apply", False):
        return False
    return True


def print_next_postlude() -> None:
    root = repo_root()
    print()
    print_next_action(next_action(root, load_config(root)), title="Recommended Next Step")



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = int(args.func(args))
        if should_print_next_postlude(args):
            print_next_postlude()
        return result
    except KeyboardInterrupt:
        print()
        print(warn("Interrupted."))
        return EXIT_INTERRUPTED
    except SetupStateError as exc:
        print(fail("Setup state error: ") + str(exc))
        return EXIT_VALIDATION_FAILED
    except ConfigMigrationError as exc:
        print(fail("Config migration error: ") + str(exc))
        return EXIT_VALIDATION_FAILED
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(fail("Unexpected error: ") + str(exc))
        return EXIT_UNEXPECTED_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
