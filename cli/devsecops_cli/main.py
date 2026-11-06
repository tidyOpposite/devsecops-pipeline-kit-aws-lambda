#!/usr/bin/env python3
"""DevSecOps Pipeline Kit CLI.

This CLI is intentionally dependency-free so it can run before the project has
any Python environment configured. It uses a local TOML config and generates
ignored Terraform/GitHub helper artifacts.  Domain rules live in focused
modules; this file coordinates them into commands and human-facing workflows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import textwrap
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import VERSION
from . import aws as _aws_adapter
from . import doctor as _doctor_service
from . import github as _github_adapter
from . import parser as _parser_builder
from . import context as _project_context_service
from . import snapshots as _snapshot_store
from . import teardown as _teardown
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
    verify_ecr_lambda_image,
)
from .deploy import (
    DEPLOYMENT_ENVIRONMENT,
    DEPLOYMENT_REF,
    DEPLOYMENT_STATE_SCHEMA_VERSION,
    DEPLOYMENT_WORKFLOW,
    DEPLOYMENT_WORKFLOW_NAME,
    DEPLOYMENT_WORKFLOW_PATH,
    PRODUCTION_JOB,
    DeploymentIntent,
    DeploymentStateError,
    active_deployment_runs,
    deployment_exit_code,
    deployment_result,
    deployment_job_rows,
    deployment_state_path,
    deployment_status_payload,
    deployment_title,
    display_gh_command,
    empty_deployment_state,
    is_deployment_run,
    is_commit_sha,
    latest_deployment,
    load_deployment_state,
    newest_deployment_run,
    parse_run_url,
    record_deployment,
    matches_deployment_request,
    save_deployment_state,
    select_dispatched_run,
    utc_now,
    workflow_dispatch_args,
    workflow_run_list_args,
    workflow_run_log_args,
    workflow_run_view_args,
    workflow_run_watch_args,
)
from .config import (
    AWS_REGION_RE,
    CONFIG_MIGRATION_CONTRACT,
    CONFIG_SCHEMA_VERSION,
    CONFIG_SET_PATHS,
    ENVIRONMENTS,
    LOG_RETENTION_DAYS,
    NO_APPROVAL_ENVIRONMENT,
    PROD_APPROVAL_ENVIRONMENT,
    PIPELINE_CONFIG_VARIABLE,
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
    config_with_preset,
    control_by_id,
    control_catalog,
    control_state,
    control_to_dict,
    deep_merge,
    default_config,
    deployment_config_sha256,
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
    production_policy_blockers,
    uses_strict_cors,
    unified_text_diff,
    validate_config,
    toml_value,
    write_config,
)
from .workflow import decode_pipeline_config
from .release_evidence import (
    PLATFORM_EVIDENCE_REQUIRED_FILES,
    production_evidence_checks,
    platform_evidence_checks,
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
from .formatting import display_width, markdown_table, pad_text, terminal_width, wrap_text
from .github import (
    DEFAULT_BRANCH,
    DEPLOY_ROLE_ENV_NAME,
    PLAN_ROLE_ENV_NAME,
    OIDC_WORKFLOW,
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
from .models import ActionsStatus, Check, ConfigMigrationError, ConfigValidationError, Control, EcrImageRef, InputCancelled
from .paths import (
    AUDIT_REPORT,
    CONFIG_FILE,
    DEPLOYMENT_STATE_FILE,
    DIST_DIR,
    GENERATED_ARTIFACT_DOC,
    GENERATED_TFVARS,
    PRODUCTION_EVIDENCE_DIR,
    RC_EVIDENCE_DIR,
    REQUIRED_PROJECT_FILES,
    SNAPSHOT_DIR,
    SNAPSHOT_FILES,
    SNAPSHOT_FILE_PATHS,
    find_project_root,
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
    generated_artifact_gaps,
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
    deployment_gate,
    grouped_readiness_checks,
    overall_breakdown_score,
    readiness_action_detail_for_check,
    readiness_action_for_check,
    readiness_breakdown_dicts,
    readiness_breakdown_rows,
    readiness_category_for_check,
    readiness_gap_dicts,
    readiness_gap_rows,
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
    PRODUCTION_SETUP_COMMAND,
    collect_demo_checks,
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

# Stable process statuses are part of the public automation contract documented
# by ``devsecops inventory``.
EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_MISSING_EXTERNAL_TOOL = 2
EXIT_AUTH_FAILED = 3
EXIT_UNEXPECTED_ERROR = 70
EXIT_INTERRUPTED = 130
READINESS_CATEGORIES = ["Local", "Terraform", "GitHub", "AWS", "Security", "Deployment"]
CANCEL_INPUTS = {"b", "back", "cancel", "q", "quit"}
MENU_CANCEL_INPUTS = CANCEL_INPUTS | {"0"}


# Terminal presentation and interactive input helpers.
class Style:
    """ANSI style codes used only when the active output stream supports color."""

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
    """Resolve the caller's project, including commands run in subdirectories."""

    return find_project_root()


# Local snapshot presentation delegates storage and allowlist enforcement to
# ``snapshots.py``; command handlers here only explain and confirm operations.
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


def print_text(text: str, *, subsequent_indent: str = "") -> None:
    """Wrap human guidance; machine formats and shell commands stay literal."""

    print("\n".join(wrap_text(text, terminal_width(), subsequent_indent)))


def print_command(command: str, label: str = "Next command") -> None:
    text = f"{label}: {command}"
    if display_width(text) <= terminal_width():
        print(text)
    else:
        print_text(f"{label}:")
        # Keep a single copyable command; terminal soft wrapping must not
        # insert whitespace into quoted values, URLs, or immutable digests.
        print(command)


def read_input(prompt: str = "") -> str:
    lines = wrap_text(prompt, terminal_width())
    suffix = " " if display_width(lines[-1]) < terminal_width() else ""
    try:
        answer = input("\n".join(lines) + suffix)
    except EOFError:
        # input() leaves the cursor after its prompt when stdin closes.
        print()
        raise
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        # Piped input is not echoed with the newline an interactive TTY shows.
        print()
    return answer


def draw_box(title: str, lines: list[str], width: int = 74) -> None:
    width = max(1, min(width, terminal_width()))
    if width < 6:
        for line in [title, *lines]:
            print("\n".join(wrap_text(line, width)))
        return
    print("+" + "-" * (width - 2) + "+")
    for part in wrap_text(title, width - 4):
        print("| " + pad_text(part, width - 4) + " |")
    print("+" + "-" * (width - 2) + "+")
    for line in lines:
        for wrapped in wrap_text(line, width - 4):
            print("| " + pad_text(wrapped, width - 4) + " |")
    print("+" + "-" * (width - 2) + "+")


def draw_table(headers: list[str], rows: list[list[str]], title: str | None = None) -> None:
    widths = [display_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], display_width(cell))
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    available = terminal_width()
    if title:
        print_text(info(title))
    if len(border) > available or any("\n" in cell for row in [headers, *rows] for cell in row):
        # Keep long diagnostics readable without truncating commands or URLs.
        for row_index, row in enumerate(rows):
            if row_index:
                print("-" * available)
            for label, cell in zip(headers, row):
                print_text(f"{label}: {cell}", subsequent_indent="  ")
        return
    print(border)
    print("|" + "|".join(f" {pad_text(headers[index], widths[index])} " for index in range(len(headers))) + "|")
    print(border)
    for row in rows:
        print("|" + "|".join(f" {pad_text(row[index], widths[index])} " for index in range(len(headers))) + "|")
    print(border)


def progress_bar(score: int, width: int = 28) -> str:
    width = max(1, min(width, terminal_width() - 19))
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
    value = read_input(f"{label}{suffix}: ").strip()
    if allow_cancel and is_cancel_input(value):
        raise InputCancelled
    return value or default


def prompt_bool(label: str, default: bool = False, allow_cancel: bool = False) -> bool:
    default_text = "y" if default else "n"
    while True:
        value = read_input(f"{label} [y/n, default {default_text}{cancel_hint(allow_cancel)}]: ").strip().lower()
        if allow_cancel and is_cancel_input(value):
            raise InputCancelled
        if not value:
            return default
        if value in {"y", "yes", "true", "1"}:
            return True
        if value in {"n", "no", "false", "0"}:
            return False
        print(warn("Use y or n."))


def prompt_int(
    label: str, default: int, allow_cancel: bool = False, *, choices: tuple[int, ...] | None = None,
) -> int:
    while True:
        value = read_input(f"{label} [{default}{cancel_hint(allow_cancel)}]: ").strip()
        if allow_cancel and is_cancel_input(value):
            raise InputCancelled
        try:
            parsed = int(value) if value else default
        except ValueError:
            print(warn("Use a number."))
            continue
        if choices is None or parsed in choices:
            return parsed
        guidance = "Choose one of " + ", ".join(map(str, choices)) + "."
        print(warn(textwrap.fill(guidance, width=shutil.get_terminal_size((80, 24)).columns)))


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


# External-command wrappers preserve legacy patch points in tests and route
# provider-specific behavior to the focused AWS and GitHub adapters.
def run_command(command: list[str], root: Path, timeout: int = 30, *, input_data: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        input=input_data,
    )


def gh_command(root: Path, args: list[str], timeout: int = 30, *, input_data: str | None = None) -> subprocess.CompletedProcess[str]:
    if input_data is not None:
        return run_command(["gh", *args], root, timeout=timeout, input_data=input_data)
    return run_command(["gh", *args], root, timeout=timeout)


def gh_stream_command(root: Path, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["gh", *args],
        cwd=root,
        text=True,
        timeout=timeout,
        check=False,
    )


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


def collect_aws_checks(
    root: Path, cfg: dict[str, Any], env_name: str = "prod", *, include_workload: bool = True
) -> list[Check]:
    """Collect AWS checks through the provider adapter using current CLI dependencies."""

    return _aws_adapter.collect_aws_checks(
        root,
        cfg,
        env_name,
        include_workload=include_workload,
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
    *,
    trusted_host: str | None = None,
) -> list[Check]:
    return _aws_adapter.collect_health_checks(
        root,
        cfg,
        url=url,
        timeout=timeout,
        aws_sigv4=aws_sigv4,
        aws_region=aws_region,
        trusted_host=trusted_host,
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


def inspect_active_lambda_image(
    root: Path,
    cfg: dict[str, Any],
    env_name: str = DEPLOYMENT_ENVIRONMENT,
) -> tuple[str, str | None]:
    return _aws_adapter.inspect_active_lambda_image(
        root,
        cfg,
        env_name,
        command_exists_fn=command_exists,
        aws_json_fn=aws_json,
    )



def collect_github_checks(root: Path, cfg: dict[str, Any], *, repository: str = "") -> list[Check]:
    return _github_adapter.collect_github_checks(
        root,
        cfg,
        repository=repository,
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


def list_deployment_runs(root: Path, limit: int = 20, *, repository: str = "") -> tuple[list[dict[str, Any]], str | None]:
    return _github_adapter.list_workflow_runs(
        root,
        workflow_run_list_args(limit, repository),
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )


def view_deployment_run(root: Path, run_id: str, *, repository: str = "") -> tuple[dict[str, Any], str | None]:
    return _github_adapter.view_workflow_run(
        root,
        workflow_run_view_args(run_id, repository),
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )


def dispatch_deployment_workflow(
    root: Path,
    operation: str,
    intent: DeploymentIntent,
) -> subprocess.CompletedProcess[str]:
    return _github_adapter.dispatch_workflow(
        root,
        workflow_dispatch_args(operation, intent),
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
    )


def read_deployment_logs(
    root: Path,
    run_id: str,
    failed_only: bool = False,
    *, repository: str = "",
) -> subprocess.CompletedProcess[str]:
    return _github_adapter.read_workflow_logs(
        root,
        workflow_run_log_args(run_id, failed_only=failed_only, repository=repository),
        command_exists_fn=command_exists,
        gh_stream_command_fn=gh_stream_command,
    )


def watch_deployment_run(
    root: Path,
    run_id: str,
    interval: int = 5,
    stream: bool = True,
    *, repository: str = "",
) -> subprocess.CompletedProcess[str]:
    return _github_adapter.watch_workflow_run(
        root,
        workflow_run_watch_args(run_id, interval, repository),
        stream=stream,
        command_exists_fn=command_exists,
        gh_command_fn=gh_command,
        gh_stream_command_fn=gh_stream_command,
    )


def github_actions_status(
    root: Path,
    limit: int = 8,
    failed_jobs_limit: int = 3,
) -> tuple[list[list[str]], list[list[str]], str | None]:
    status = collect_github_actions_status(root, limit=limit, failed_jobs_limit=failed_jobs_limit)
    return status.runs, status.failed_jobs, status.error



def apply_github_setup(root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> int:
    failures = [check for check in validate_config(cfg) if check.status == "FAIL"]
    if failures:
        emit_check_output("GitHub settings were not changed", failures, output_format="compact")
        return EXIT_VALIDATION_FAILED
    precheck = github_setup_precheck(root, cfg, args)
    if any(check.scored and check.status != "OK" for check in precheck):
        emit_check_output("GitHub setup blocked", precheck, output_format="compact")
        return strict_exit_code(precheck, strict=True, fail_on_warn=True)
    repository = next(check.detail for check in precheck if check.name == "GitHub repository")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ConfigValidationError("GitHub did not identify an owner/repository.")
    print(f"GitHub destination: {repository}")
    print("Configuration stays blocked while synchronization is incomplete.")
    try:
        existing_secrets, production_secrets = _github_adapter.github_secret_inventory(root, repository, gh_command_fn=gh_command)
    except ValueError as exc:
        print(fail(str(exc)))
        return EXIT_VALIDATION_FAILED
    try:
        variables = gh_command(root, ["variable", "list", "--repo", repository, "--json", "name,value"])
    except (OSError, subprocess.TimeoutExpired):
        print(fail("Cannot inspect the destination repository variables. Retry after restoring GitHub access."))
        return EXIT_VALIDATION_FAILED
    if variables.returncode != 0:
        print(fail("Cannot inspect the destination repository variables."))
        return EXIT_VALIDATION_FAILED
    existing_variables = _github_adapter.parse_gh_items(variables.stdout, value_key="value")
    supplied = {
        DEPLOY_ROLE_ENV_NAME: getattr(args, "deploy_role_arn", None),
        PLAN_ROLE_ENV_NAME: getattr(args, "plan_role_arn", None),
        SNYK_ENV_NAME: getattr(args, "snyk_token", None),
    }
    scopes = {
        name: PROD_APPROVAL_ENVIRONMENT if name != PLAN_ROLE_ENV_NAME and name in production_secrets else "repository"
        for name in supplied
    }
    for name in required_github_secrets(cfg):
        current = production_secrets if scopes[name] == PROD_APPROVAL_ENVIRONMENT else existing_secrets
        if not supplied[name] and name not in current:
            print(fail(f"Missing {name} for {scopes[name]}. Supply its setup argument before writing settings."))
            return EXIT_VALIDATION_FAILED
    expected = github_expected_variables(cfg)
    if not expected["LAMBDA_IMAGE_URI"]:
        expected.pop("LAMBDA_IMAGE_URI")
    operations = [("variable", PIPELINE_CONFIG_VARIABLE, _github_adapter.SETUP_IN_PROGRESS_CONFIG, "repository")]
    operations.extend(("variable", name, value, "repository") for name, value in expected.items() if name != PIPELINE_CONFIG_VARIABLE)
    operations.extend(("secret", name, value.strip() if value else None, scopes[name]) for name, value in supplied.items())
    operations.append(("variable", PIPELINE_CONFIG_VARIABLE, expected[PIPELINE_CONFIG_VARIABLE], "repository"))
    rows = []
    failed = False
    for kind, name, value, scope in operations:
        if failed:
            rows.append([scope, kind, name, "Not attempted"])
            continue
        if value is None:
            rows.append([scope, kind, name, "Retained" if name in (production_secrets if scope == PROD_APPROVAL_ENVIRONMENT else existing_secrets) else "Optional"])
            continue
        if kind == "variable" and existing_variables.get(name) == value:
            rows.append([scope, kind, name, "Unchanged"])
            continue
        command = [kind, "set", name, "--repo", repository]
        if scope == PROD_APPROVAL_ENVIRONMENT:
            command.extend(["--env", scope])
        try:
            result = gh_command(root, command, input_data=value) if kind == "secret" else gh_command(root, [*command, "--body", value])
        except subprocess.TimeoutExpired:
            status = "Unconfirmed (timeout)"
            failed = True
        except OSError:
            status = "Failed (cannot execute gh)"
            failed = True
        else:
            failed = result.returncode != 0
            status = "Failed" if failed else "Applied"
        rows.append([scope, kind, name, status])
        if not failed and kind == "variable":
            existing_variables[name] = value
    draw_table(["Scope", "Kind", "Setting", "Result"], rows, title=f"GitHub setup result for {repository}")
    if failed:
        print(fail("GitHub setup is incomplete. Retry with the same arguments to finish synchronization."))
        print(f"Pinned destination for retry: --repo {repository}")
        return EXIT_VALIDATION_FAILED
    print(ok("Applied GitHub repository variables/secrets available from config and arguments."))
    print(f"Before production, verify OIDC roles with {OIDC_WORKFLOW} in {repository}.")
    return EXIT_OK



def github_setup_precheck(root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> list[Check]:
    try:
        return _github_adapter.github_setup_precheck(
            root, cfg, args, command_exists_fn=command_exists, gh_command_fn=gh_command,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [Check("GitHub setup inspection", "FAIL", "Cannot inspect GitHub. Restore access before retrying setup.")]



def collect_checks(
    root: Path, cfg: dict[str, Any], deep: bool = False, *, include_workload: bool = True
) -> list[Check]:
    return _doctor_service.collect_checks(
        root,
        cfg,
        deep,
        include_workload=include_workload,
        command_exists_fn=command_exists,
        run_command_fn=run_command,
        image_preflight_fn=collect_image_preflight_checks,
        aws_checks_fn=collect_aws_checks,
    )



def next_action(root: Path, cfg: dict[str, Any] | None = None, *,
                observations: list[Check] | None = None, local_only: bool = False,
                pre_deploy: bool = False) -> dict[str, Any]:
    return _project_context_service.next_action(
        root,
        cfg,
        command_exists_fn=command_exists,
        github_checks_fn=collect_github_checks,
        aws_checks_fn=collect_aws_checks,
        observations=observations,
        local_only=local_only,
        pre_deploy=pre_deploy,
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
    print_command(action["command"])
    print_text(lines[4])



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
    print(info("Readiness gaps:"))
    for check_name, status, detail, action in rows:
        label = fail(status) if status == "FAIL" else warn(status)
        print_text(f"  {label} {check_name}: {detail}", subsequent_indent="  ")
        print_text(f"    Fix: {action}", subsequent_indent="  ")


def collect_dashboard_checks(root: Path, cfg: dict[str, Any], mode: str = "full", *, include_demo: bool = True) -> list[Check]:
    if mode == "compact" and include_demo:
        demo = collect_demo_checks(root, cfg)
        if demo is not None:
            return demo
    checks = _doctor_service.collect_dashboard_checks(
        root,
        cfg,
        mode,
        collect_checks_fn=collect_checks,
        github_checks_fn=collect_github_checks,
        branch_checks_fn=collect_branch_checks,
    )
    if mode == "full":
        api = next((check for check in checks if check.name == "API Gateway" and check.status == "OK"), None)
        if api is not None:
            if api.detail.startswith("https://"):
                url = api.detail.rstrip("/") + "/health"
                status, detail = fetch_health_url(
                    url,
                    aws_sigv4=cfg["api_authorization_type"] == "AWS_IAM",
                    aws_region=cfg["aws_region"],
                    allow_redirects=False,
                )
                checks.append(Check(
                    "Health response", "OK" if status is not None and 200 <= status < 300 else "FAIL",
                    f"HTTP {status} from {url}." if status is not None else detail,
                ))
            else:
                checks.append(Check("Health response", "FAIL", "The production API has no HTTPS endpoint."))
    return checks



def print_readiness_details(root: Path, deep: bool = False, *, checks: list[Check] | None = None) -> None:
    cfg = load_config(root)
    checks = checks if checks is not None else collect_checks(root, cfg, deep=deep)
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
            print_text(f"{label} {check_name}")
            print_text(f"  Current: {detail}", subsequent_indent="  ")
            print_text(f"  Fix: {action}", subsequent_indent="  ")
            print()
    else:
        print(ok("All scored readiness checks are OK."))


def print_checks(checks: list[Check], title: str = "Readiness") -> None:
    print_text(info(f"{title}: ") + progress_bar(readiness_score(checks)))
    print()
    rows = []
    for check in checks:
        fix = readiness_action_for_check(check) if check.scored and check.status != "OK" else ""
        rows.append([check.name, check.status, check.detail, fix])
    draw_table(["Check", "Status", "Detail", "Fix"], rows)


def print_readiness_gates(checks: list[Check]) -> None:
    draw_table(["Gate", "Status", "Detail"], readiness_gate_rows(checks), title="Readiness Gates")


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_compact_checks(checks: list[Check], title: str | None = None) -> None:
    if title:
        print_text(info(title))
    print(f"Score: {readiness_score(checks)}%")
    gaps = [check for check in checks if check.scored and check.status in {"WARN", "FAIL"}]
    if not gaps:
        print(ok("No scored gaps."))
        return
    for check in gaps:
        label = fail(check.status) if check.status == "FAIL" else warn(check.status)
        print_text(f"{label} {check.name}: {check.detail}", subsequent_indent="  ")
        print_text(f"  Fix: {readiness_action_for_check(check)}", subsequent_indent="  ")


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
        print_text(f"{label} {check.name}: {check.detail}", subsequent_indent="  ")
        print_text(f"  Fix: {readiness_action_detail_for_check(check)}", subsequent_indent="  ")


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
    """Print deterministic completion code for the requested shell."""

    print(completion_script(args.shell, args.program), end="")
    return EXIT_OK


def cmd_envs(args: argparse.Namespace) -> int:
    """Show normalized per-environment runtime configuration."""

    cfg = load_config(repo_root())
    draw_table(
        ["Env", "Memory", "Timeout", "Logs", "Burst/Rate", "CORS"],
        env_rows(cfg),
        title="Environment Configuration",
    )
    return 0


def cmd_controls(args: argparse.Namespace) -> int:
    """Show the security-control catalog in human or JSON form."""

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
        "|-- PR validation without AWS credentials",
        "|-- Manual sandbox plan from main with isolated state",
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
    """Print the compact cross-provider architecture overview."""

    draw_box("Architecture", architecture_lines())
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    """Emit the public command and artifact compatibility inventory."""

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


def print_demo_status(cfg: dict[str, Any], checks: list[Check], action: dict[str, Any]) -> None:
    complete = all(check.status == "OK" for check in checks)
    draw_box("Demo complete" if complete else "Local demo", [
        f"Project: {cfg['project_name']} | Region: {cfg['aws_region']}",
        "Local configuration and preview verified." if complete else "Complete or refresh the local setup and preview.",
    ])
    draw_table(["Local check", "Status", "Detail"], [[check.name, check.status, check.detail] for check in checks], title="Demo Readiness")
    print(f"Overall: {score_status(readiness_score(checks))} (local demo)")
    print()
    print_next_action(action)
    print_command(PRODUCTION_SETUP_COMMAND, label="Configure production separately when ready")


def render_dashboard(root: Path, mode: str = "full", clear: bool = False, *,
                     cfg: dict[str, Any] | None = None, checks: list[Check] | None = None,
                     action: dict[str, Any] | None = None) -> None:
    """Render the unified status surface at compact or full detail."""

    if clear:
        clear_screen()
    mode = mode if mode in {"compact", "pre-deploy", "full"} else "full"
    cfg = cfg if cfg is not None else load_config(root)
    checks = checks if checks is not None else collect_dashboard_checks(root, cfg, mode=mode)
    action = action if action is not None else next_action(
        root, cfg, observations=checks, local_only=mode == "compact", pre_deploy=mode == "pre-deploy",
    )
    if any(check.name == "Demo dry-run" for check in checks):
        print_demo_status(cfg, checks, action)
        return
    header(cfg)
    print()
    for line in menu_status(root, cfg, checks=checks):
        print_text(line)
    print()
    print_readiness_breakdown(checks, compact=mode != "full")
    print()
    print_next_action(action)
    if mode != "full":
        if mode == "compact":
            print()
            print_text(info("Run `devsecops status --deep` for GitHub, AWS, and deep Terraform checks."))
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
    """Render the compatibility dashboard once or on a refresh loop."""

    root = repo_root()
    interval = max(1, int(args.interval))
    while True:
        cfg = load_config(root)
        demo = collect_demo_checks(root, cfg) if args.mode is None else None
        mode = args.mode or ("compact" if demo is not None else "full")
        render_dashboard(root, mode=mode, clear=bool(args.watch), cfg=cfg, checks=demo)
        if not args.watch:
            return 0
        print()
        print(info(f"Watching dashboard every {interval}s. Press Ctrl-C to stop."))
        time.sleep(interval)


def status_payload(checks: list[Check], action: dict[str, Any], deep: bool, *, pre_deploy: bool = False) -> dict[str, Any]:
    """Return the preferred status contract with one unambiguous score."""

    payload = checks_payload("status", checks, context={"deep": deep, "pre_deploy": pre_deploy})
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
    pre_deploy = bool(getattr(args, "pre_deploy", False))
    deep = bool(getattr(args, "deep", False)) or pre_deploy
    mode = "pre-deploy" if pre_deploy else "full" if deep else "compact"
    output_format = getattr(args, "format", "human")
    watch = bool(getattr(args, "watch", False))
    if watch and output_format != "human":
        return emit_command_error(args, "--watch is available only with human output.", EXIT_VALIDATION_FAILED)

    interval = max(1, int(getattr(args, "interval", 5)))
    while True:
        if deep and output_format == "human":
            scope = "deployment prerequisites" if pre_deploy else "deployment prerequisites and workload health"
            print(info(f"Checking {scope}..."), flush=True)
        cfg = load_config(root)
        strict = bool(getattr(args, "strict", False))
        checks = (collect_dashboard_checks(root, cfg, mode=mode, include_demo=False)
                  if strict and not deep else collect_dashboard_checks(root, cfg, mode=mode))
        action = next_action(root, cfg, observations=checks, local_only=not deep, pre_deploy=pre_deploy)
        if output_format == "json":
            payload = status_payload(checks, action, deep, pre_deploy=pre_deploy)
            if any(check.name == "Demo dry-run" for check in checks):
                payload["context"]["scope"] = "demo"
                payload["demo_complete"] = all(check.status == "OK" for check in checks)
            emit_json(payload)
        elif output_format == "compact":
            if any(check.name == "Demo dry-run" for check in checks):
                print_demo_status(cfg, checks, action)
            else:
                print_readiness_breakdown(checks, compact=True)
                print()
                print_next_action(action)
        else:
            render_dashboard(root, mode=mode, clear=watch, cfg=cfg, checks=checks, action=action)

        result = strict_exit_code(checks, strict=strict, fail_on_warn=True)
        if strict and result == EXIT_OK:
            prerequisites = deployment_gate(checks, pre_deploy=True)[0]
            workload = deployment_gate(checks, pre_deploy=False)[0]
            if prerequisites != "OK" or (not pre_deploy and workload != "OK"):
                result = EXIT_VALIDATION_FAILED
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
    """Render the optional Rich UI and report whether Rich was available."""

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        return False

    cfg = load_config(root)
    checks = collect_dashboard_checks(root, cfg, mode="compact")
    action = next_action(root, cfg, observations=checks, local_only=True)
    console = Console()
    if any(check.name == "Demo dry-run" for check in checks):
        complete = all(check.status == "OK" for check in checks)
        console.print(Panel(f"Project: {cfg['project_name']}\nLocal configuration and preview.\nOverall: {readiness_score(checks)}% (local demo)",
                            title="Demo complete" if complete else "Local demo"))
        table = Table(title="Demo Readiness")
        for name in ("Local check", "Status", "Detail"):
            table.add_column(name)
        for check in checks:
            table.add_row(check.name, check.status, check.detail)
        console.print(table)
        console.print(Panel("\n".join(next_action_lines(action)[:3]), title="Next Action"))
        print_command(action["command"])
        print_text(f"Docs: {action['docs']}")
        print_command(PRODUCTION_SETUP_COMMAND, label="Configure production separately when ready")
        return True
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

    gap_table = Table(title="Readiness Details")
    gap_table.add_column("Check")
    gap_table.add_column("Status")
    gap_table.add_column("Fix")
    for check_name, status, _detail, fix in readiness_gap_rows(checks)[:5]:
        gap_table.add_row(check_name, status, fix)
    if gap_table.row_count:
        console.print(gap_table)
    else:
        console.print(Panel("All scored readiness checks are OK.", title="Readiness Details"))
    console.print(Panel("\n".join(next_action_lines(action)[:3]), title="Next Action"))
    print_command(action["command"])
    print_text(f"Docs: {action['docs']}")
    console.print("[dim]Full Textual mode is intentionally deferred until doctor workflows stabilize.[/dim]")
    return True


def cmd_tui(args: argparse.Namespace) -> int:
    """Open the optional TUI or fall back to the compact text dashboard."""

    root = repo_root()
    if render_rich_tui(root):
        return 0
    print(warn("Rich/Textual UI is optional and not installed. Falling back to compact dashboard."))
    print(info('Install optional UI dependencies with `pipx install ".[tui]"` or `python3 -m pip install -e ".[tui]"`.'))
    print()
    render_dashboard(root, mode="compact", clear=False)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Print the single highest-priority next action for the project."""

    root = repo_root()
    cfg = load_config(root)
    action = next_action(root, cfg, local_only=True)
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


# Resumable guided-setup orchestration.  Each step persists progress before
# work begins so interruption never falsely records an action as complete.
def choose_setup_mode(args: argparse.Namespace, state: dict[str, Any] | None) -> tuple[str, str]:
    """Resolve setup mode and preset from arguments, saved state, or a prompt."""

    requested_mode = getattr(args, "mode", None)
    requested_preset = getattr(args, "preset", None)
    if requested_mode:
        return requested_mode, requested_preset or str(setup_profile(requested_mode)["preset"])
    if requested_preset:
        return mode_for_preset(requested_preset), requested_preset
    if state is not None:
        return str(state["mode"]), str(state.get("preset") or setup_profile(str(state["mode"]))["preset"])
    if bool(getattr(args, "yes", False)):
        return "demo", "student-demo"

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
        value = read_input("\nChoose mode [1, b/back/0 to pause]: ").strip().lower()
        if not value:
            value = "1"
        if is_cancel_input(value):
            raise InputCancelled
        if value in choices:
            mode = choices[value]
            return mode, str(setup_profile(mode)["preset"])
        print(warn("Choose 1, 2, or 3."))


def begin_setup_step(root: Path, state: dict[str, Any], step: str, detail: str = "") -> None:
    """Persist a setup stage as pending before attempting its work."""

    mark_setup_step(state, step, "pending", detail)
    save_setup_state(root, state)


def setup_argument_error(
    args: argparse.Namespace, mode: str, cfg: dict[str, Any], *, new_interactive_config: bool = False,
) -> str | None:
    """Validate supplied inputs before creating progress, snapshots or config."""

    github_values = [
        getattr(args, "deploy_role_arn", None),
        getattr(args, "plan_role_arn", None),
        getattr(args, "snyk_token", None),
    ]
    if any(value is not None for value in github_values) and not bool(getattr(args, "apply_github", False)):
        return "Role ARN and Snyk token options require --apply-github."
    cloud_options = [
        getattr(args, "backend_bucket", None),
        getattr(args, "backend_region", None),
        getattr(args, "backend_lock_table", None),
    ]
    if mode == "demo" and (any(value is not None for value in cloud_options) or bool(getattr(args, "apply_github", False))):
        return "Backend and GitHub apply options require --mode standard or --mode production."
    role_failures = [check for check in _github_adapter.role_argument_checks(args) if check.status == "FAIL"]
    if role_failures:
        return " ".join(check.detail for check in role_failures)
    for option in ("deploy_role_arn", "plan_role_arn", "snyk_token"):
        value = getattr(args, option, None)
        if value is not None and not value.strip():
            return f"--{option.replace('_', '-')} cannot be empty."
    image = getattr(args, "image_uri", None)
    image_ref = parse_ecr_image_uri(image.strip()) if image is not None else None
    # A new interactive config has no chosen region yet. Validate the supplied
    # image now, then offer its region when gathering the new config inputs.
    image_cfg = dict(cfg, aws_region=image_ref.region) if new_interactive_config and image_ref else cfg
    if image is not None and any(check.status == "FAIL" for check in validate_setup_image(image_cfg, image)):
        return "Invalid --image-uri. Use an immutable ECR image URI in the configured AWS region."
    bucket = getattr(args, "backend_bucket", None)
    if bucket is not None and not is_backend_bucket_configured(bucket):
        return "Invalid --backend-bucket. Supply a valid, non-placeholder S3 bucket name."
    region = getattr(args, "backend_region", None)
    if region is not None and not AWS_REGION_RE.fullmatch(region):
        return "Invalid --backend-region. Use an AWS region such as us-east-1."
    lock_table = getattr(args, "backend_lock_table", None)
    if lock_table is not None and not lock_table.strip():
        return "--backend-lock-table cannot be empty."
    return None


def review_setup_preset(
    root: Path, cfg: dict[str, Any], args: argparse.Namespace, mode: str, preset_name: str,
) -> tuple[dict[str, Any] | None, bool]:
    """Review the exact replacement before any setup writes or provider calls.

    Return an approved candidate and whether noninteractive setup must stop.
    Keeping the existing config is an explicit interactive choice; --yes alone
    cannot authorize replacing policy or per-environment settings.
    """

    if not config_path(root).exists():
        return None, False
    authorized = bool(getattr(args, "apply_mode_preset", False))
    blockers = setup_config_blockers(cfg, mode)
    needs_posture = bool(blockers) and not any(check.status == "FAIL" for check in blockers)
    if not authorized and not needs_posture:
        return None, False
    candidate = config_with_preset(cfg, preset_name)
    diff = unified_text_diff(canonical_config_text(cfg), canonical_config_text(candidate), CONFIG_FILE, f"setup preset:{preset_name}")
    if not diff:
        return None, False
    print()
    if blockers:
        emit_check_output("Mode configuration requirements", blockers, output_format="compact")
    print_text(f"Proposed `{preset_name}` preset changes (not saved):")
    print(diff, end="")
    print_text("Project, region, image, admin role, and backend values are preserved.")
    if not authorized:
        if bool(getattr(args, "yes", False)):
            print_text(fail("Existing settings were kept. --yes does not authorize a preset replacement."))
            print_text("Review the diff, then rerun with --apply-mode-preset and the same options to accept it, or run setup interactively to keep the current settings.")
            return None, True
        authorized = prompt_bool("Replace existing policy and environment settings with these changes", False, allow_cancel=True)
    if authorized:
        return candidate, False
    print_text(info("Keeping existing configuration; unmet mode requirements remain pending."))
    return None, False


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
    """Return local availability for tools used across setup modes."""

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
        print_text(
            warn("Setup can prepare local inputs, but these stages remain incomplete: ")
            + ", ".join(sorted(missing))
        )
        print_text("Install guidance: docs/distribution.md and docs/first-successful-pipeline.md")


def write_setup_config_change(root: Path, cfg: dict[str, Any], description: str) -> None:
    """Snapshot an existing config before persisting a guided-setup change."""

    if config_path(root).exists():
        snapshot_before_change(root, "setup", description)
    write_config(root, cfg)
    print_text(ok("Updated ") + str(config_path(root)))


def create_setup_config(
    root: Path, state: dict[str, Any], interactive: bool, image_uri: str | None = None,
) -> dict[str, Any] | None:
    """Create or reuse the local source configuration for guided setup."""

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
        image_ref = parse_ecr_image_uri(image_uri.strip()) if image_uri is not None else None
        if image_ref:
            cfg["aws_region"] = image_ref.region
        cfg["project_name"] = prompt_matching_text(
            "Project name",
            str(cfg["project_name"]),
            PROJECT_NAME_RE,
            "Use 3-32 lowercase letters, digits, or hyphens; start with a letter.",
        )
        while True:
            cfg["aws_region"] = prompt_matching_text(
                "AWS region",
                str(cfg["aws_region"]),
                AWS_REGION_RE,
                "Use an AWS region such as us-east-1 or eu-central-1.",
            )
            if image_ref is None or cfg["aws_region"] == image_ref.region:
                break
            print(warn(f"The supplied image requires AWS region {image_ref.region}. Choose that region or pause setup."))
        cfg["backend"]["region"] = cfg["aws_region"]
        cfg["backend"]["lock_table"] = f"{cfg['project_name']}-terraform-locks"
    write_config(root, cfg)
    print_text(ok("Created clean config ") + str(config_path(root)))
    return cfg


def validate_setup_image(cfg: dict[str, Any], image_uri: str) -> list[Check]:
    """Apply production image preflight rules during guided setup."""

    return collect_image_preflight_checks(cfg, image_uri=image_uri, env_name="prod")


def configure_setup_image(
    root: Path,
    cfg: dict[str, Any],
    image_uri: str | None,
    interactive: bool,
) -> tuple[dict[str, Any], bool]:
    """Resolve, validate, and optionally persist the setup image choice.

    The boolean result distinguishes invalid user input from a valid decision
    to defer image configuration until a later setup run.
    """

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
        print_text("[1] Enter an existing image URI")
        print_text("[2] Show the image guide and continue later")
        print_text("[0] Pause setup")
        choice = read_input("\nChoose: ").strip().lower()
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
    """Resolve backend names and persist them without creating AWS resources."""

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
    """Inspect AWS identity only for setup modes that need cloud context."""

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
    """Check configured backend resources without creating or changing them."""

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
        print_text(info("Step 6/9 - AWS identity: not required in demo mode."))
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
    """Inspect GitHub and optionally apply explicitly authorized setup.

    The boolean result signals an attempted mutation failure, distinct from
    ordinary readiness gaps that can safely be resumed later.
    """

    if not setup_profile(mode)["cloud_required"]:
        print_text(info("Step 7/9 - GitHub repository / OIDC: not required in demo mode."))
        return [], False

    checks = collect_github_checks(root, cfg)
    apply_requested = bool(getattr(args, "apply_github", False))
    if github_setup_ready(checks) and not apply_requested:
        print(ok("Step 7/9 - GitHub repository variables and OIDC role secrets are ready."))
        return checks, False
    if not apply_requested and all(check.status == "OK" for check in checks if check.scored and check.name != "GitHub OIDC roles"):
        print(info("GitHub settings are present. Separate OIDC role verification is still required."))
        return checks, False

    emit_check_output("Step 7/9 - GitHub Repository / OIDC", checks, output_format="compact")
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
    apply_args = argparse.Namespace(
        deploy_role_arn=deploy_role_arn,
        plan_role_arn=plan_role_arn,
        snyk_token=snyk_token,
    )
    precheck = github_setup_precheck(root, cfg, apply_args)
    apply_args.repo = next((check.detail for check in precheck if check.name == "GitHub repository" and check.status == "OK"), None)
    emit_check_output("GitHub Setup Precheck", precheck)
    print()
    result = apply_github_setup(root, cfg, apply_args)
    if result != EXIT_OK:
        return checks, True
    return collect_github_checks(root, cfg), False


def save_reconciled_setup(root: Path, state: dict[str, Any], stages: list[SetupStage]) -> None:
    """Persist observable stage results and the next resume point."""

    for stage in stages:
        mark_setup_step(state, stage.id, stage.status, stage.detail)
    pending = first_pending_stage(stages)
    state["last_step"] = pending.id if pending else "summary"
    save_setup_state(root, state)


def print_setup_summary(state: dict[str, Any], stages: list[SetupStage]) -> None:
    """Present required-stage progress and the exact resume command."""

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
    print_text(f"Saved progress: {SETUP_STATE_FILE}")
    next_command = setup_next_command(pending, str(state["mode"]))
    if pending:
        print_text(f"Resume point: {pending.title} - {pending.detail}")
    else:
        print_text(ok("Demo complete. Local config and preview are verified." if state["mode"] == "demo"
                 else "Guided setup complete. No deployment was started."))
    print()
    draw_box(
        "Next Action",
        [
            pending.title if pending else "Explore the local demo" if state["mode"] == "demo" else "Validate the resulting project status",
            pending.detail if pending else "Preview the saved config without cloud access." if state["mode"] == "demo" else "Guided setup is complete; review the unified status before deployment.",
            "Rerunning setup rechecks observable state and resumes without repeating completed work.",
        ],
    )
    print_command(next_command)
    if state["mode"] == "demo" and pending is None:
        print_command(PRODUCTION_SETUP_COMMAND, label="Configure production separately when ready")


def cmd_setup(args: argparse.Namespace) -> int:
    """Run or resume guided setup without starting a cloud deployment.

    GitHub mutation requires ``--apply-github`` or interactive confirmation,
    while AWS calls in this workflow remain read-only inspections.
    """

    root = repo_root()
    cfg = load_config(root)
    context = project_context(root, cfg)
    draw_box(
        "Guided Project Setup",
        [
            "Resumable onboarding for the first successful pipeline path.",
            f"Project context: {context['stage']}",
            "New setups start with a local demo. Saved modes resume unchanged.",
            f"Progress is stored locally in {SETUP_STATE_FILE}; secrets are never stored there.",
        ],
    )
    if context["missing_project_files"]:
        print()
        print_next = argparse.Namespace(format="human")
        cmd_next(print_next)
        return EXIT_VALIDATION_FAILED

    state = load_setup_state(root)
    setup_started = False
    try:
        mode, preset_name = choose_setup_mode(args, state)
        argument_error = setup_argument_error(
            args, mode, cfg,
            new_interactive_config=not config_path(root).exists() and not bool(getattr(args, "yes", False)),
        )
        if argument_error:
            print_text(fail(argument_error))
            return EXIT_VALIDATION_FAILED
        preset_candidate, review_required = review_setup_preset(root, cfg, args, mode, preset_name)
        if review_required:
            return EXIT_VALIDATION_FAILED
        if state is None:
            state = new_setup_state(mode, preset=preset_name)
            print_text(info(f"Starting {mode} setup with the `{preset_name}` preset."))
        else:
            previous_mode = str(state["mode"])
            previous_preset = str(state.get("preset", ""))
            if previous_mode != mode or previous_preset != preset_name:
                state = switch_setup_mode(state, mode, preset=preset_name)
                print_text(info(f"Switched saved setup from {previous_mode} to {mode} mode."))
            else:
                print_text(
                    info(
                        f"Resuming saved {mode} setup from step "
                        f"`{state.get('last_step', 'mode')}`."
                    )
                )
        mark_setup_step(state, "mode", "complete", f"Mode: {mode}; preset: {preset_name}")
        save_setup_state(root, state)
        setup_started = True

        interactive = not bool(getattr(args, "yes", False))
        input_error = False

        begin_setup_step(root, state, "dependencies")
        dependency_status = setup_dependency_status()
        print()
        print_setup_dependencies(mode, dependency_status)

        begin_setup_step(root, state, "config")
        cfg = create_setup_config(root, state, interactive, getattr(args, "image_uri", None)) or load_config(root)
        if preset_candidate is not None:
            write_setup_config_change(root, preset_candidate, f"Before applying `{preset_name}` preset in guided setup.")
            cfg = load_config(root)

        config_exists = config_path(root).exists()
        config_blockers = setup_config_blockers(cfg, mode) if config_exists else []
        config_valid = config_exists and not config_blockers
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
                print_text(info("Step 4/9 - Lambda image: demo mode will use a sample URI only for dry-run."))
                print_text("Bring-your-own-image guide: docs/bring-your-own-image.md")
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
                print_text(info("Step 5/9 - Terraform backend: not required in demo mode."))

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
        dry_run_can_run = config_valid and not input_error and bool(
            effective_image or is_immutable_image(str(cfg.get("lambda_image_uri", "")))
        )
        current_fingerprint = setup_config_fingerprint(cfg, image_override=effective_image)
        if dry_run_can_run and state.get("dry_run_fingerprint") != current_fingerprint:
            print()
            dry_run_result = cmd_dry_run(
                argparse.Namespace(
                    preset=preset_name,
                    image_uri=effective_image,
                    environment="dev" if mode == "demo" else "prod",
                    demo=mode == "demo",
                )
            )
            if dry_run_result == EXIT_OK:
                state["dry_run_fingerprint"] = current_fingerprint
                save_setup_state(root, state)
            else:
                input_error = True
        elif dry_run_can_run:
            print_text(ok("Step 8/9 - Dry-run is already current; no need to repeat it."))
        else:
            print_text(warn("Step 8/9 - Dry-run is waiting for a valid config and immutable image."))

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
        if input_error:
            print(fail("Setup inputs need attention. Correct the reported errors and rerun setup."))
            return EXIT_VALIDATION_FAILED
        print_setup_summary(state, stages)
        pending = first_pending_stage(stages)
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
    except (InputCancelled, EOFError):
        if setup_started and state is not None:
            save_setup_state(root, state)
            print_text(
                info(
                    f"Setup paused at step `{state.get('last_step', 'mode')}`. "
                    "Rerun `devsecops setup` to resume."
                )
            )
        else:
            print(info("Setup paused before any changes were saved."))
        return EXIT_OK


def cmd_start(args: argparse.Namespace) -> int:
    """Compatibility handler for the previous public command name."""

    return cmd_setup(args)


# Release-criteria and evidence helpers return serializable dictionaries rather
# than terminal-specific objects so the same facts can feed JSON and tables.
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


def v1_criteria_payload(root: Path, evidence_dir: Path | None = None, *, repository: str | None = None,
                        artifacts_dir: Path | None = None) -> dict[str, Any]:
    """Evaluate source, test, and evidence requirements for stable release."""

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
                f"docs/release-v{VERSION}.md",
            ],
            [
                file_exists_check(root, "Distribution guide", "docs/distribution.md"),
                file_exists_check(root, "Release checklist", "docs/release-checklist.md"),
                file_exists_check(root, "Upgrade guide", "docs/upgrade-guide.md"),
                file_exists_check(root, "Current version release notes", f"docs/release-v{VERSION}.md"),
            ],
            "Update distribution, release, upgrade, and current version release-note docs.",
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
            production_evidence_checks(root, evidence_dir, repository=repository, artifacts_dir=artifacts_dir),
            f"Run docs/production-deployment-evidence.md and store the required files under {evidence_dir_display}.",
        ),
        make_criterion(
            "supported-platform-transcript-attached",
            "Supported platform compatibility transcript is attached.",
            [str(evidence_dir / PLATFORM_EVIDENCE_REQUIRED_FILES[0]), "docs/distribution.md"],
            platform_evidence_checks(evidence_dir, root),
            f"Capture macOS or supported Ubuntu install, dry-run, completion, and test transcript in {evidence_dir_display}/{PLATFORM_EVIDENCE_REQUIRED_FILES[0]}. Windows/WSL2 are not release targets.",
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
    """Show stable-release criteria and optionally enforce them via exit code."""

    root = repo_root()
    evidence_arg = getattr(args, "evidence_dir", None)
    artifacts_arg = getattr(args, "artifacts_dir", None)
    payload = v1_criteria_payload(
        root, Path(evidence_arg) if evidence_arg else None,
        repository=getattr(args, "verify_github", None),
        artifacts_dir=root / artifacts_arg if artifacts_arg else None,
    )
    if getattr(args, "format", "human") == "json":
        emit_json(payload)
    else:
        print_v1_criteria(payload)
    if getattr(args, "strict", False) and not payload["stable_ready"]:
        return EXIT_VALIDATION_FAILED
    return EXIT_OK


def terraform_validate_evidence(root: Path) -> dict[str, Any]:
    """Capture Terraform validation as bounded release evidence."""

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
    """Write a deterministic local release-candidate evidence bundle."""

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
    """Validate evidence arguments and collect the requested local bundle."""

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


# Configuration, policy composition, reporting, and local snapshot commands.
def cmd_validate_config(args: argparse.Namespace) -> int:
    """Validate configuration and apply strict warning semantics when requested."""

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
    """Set one allowlisted configuration key after taking a snapshot."""

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
    failures = [check for check in validate_config(cfg) if check.status == "FAIL"]
    if failures:
        emit_check_output("Setting was not saved", failures, output_format="compact")
        return EXIT_VALIDATION_FAILED
    snapshot_before_change(root, "set", f"Before setting {args.key} to {args.value}.")
    write_config(root, cfg)
    print(ok("Updated ") + f"{CONFIG_FILE}: {args.key} = {toml_value(value)}")
    if args.render:
        return run_render(root, snapshot=False)
    return 0


def apply_preset(root: Path, name: str, render: bool = False) -> int:
    """Apply policy defaults while preserving project identity and backend."""

    if name not in PRESETS:
        print(fail("Unknown preset: ") + name)
        print("Available presets: " + ", ".join(PRESET_ORDER))
        return 1
    current = load_config(root)
    cfg = config_with_preset(current, name)
    snapshot_before_change(root, "preset", f"Before applying `{name}` preset.")
    write_config(root, cfg)
    print(ok("Applied preset ") + name)
    if render:
        return run_render(root, snapshot=False)
    return 0


def cmd_preset(args: argparse.Namespace) -> int:
    """Dispatch preset list, show, apply, and compatibility forms."""

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
    """Interactively compose controls, then regenerate owned local artifacts."""

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
    """Generate a readiness or audit report under snapshot protection."""

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
    """Print, write, or explicitly apply the GitHub repository setup helper."""

    root = repo_root()
    cfg = load_config(root)
    if args.apply:
        precheck = github_setup_precheck(root, cfg, args)
        args.repo = next((check.detail for check in precheck if check.name == "GitHub repository" and check.status == "OK"), getattr(args, "repo", None))
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
    """List local snapshots and optionally inspect one snapshot's drift."""

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
    """Restore only CLI-owned local files from a confirmed snapshot."""

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
        confirmation = read_input(f"\nRollback to {snapshot.get('id')}? Type yes to continue: ").strip().lower()
        if confirmation != "yes":
            print(info("Rollback cancelled."))
            return 0
    snapshot_before_change(root, "rollback", f"Before rolling back to {snapshot.get('id')}.")
    restore_snapshot(root, snapshot)
    print(ok("Rolled back to snapshot ") + str(snapshot.get("id")))
    return 0


def cmd_gh_doctor(args: argparse.Namespace) -> int:
    """Run repository-variable and secret-presence diagnostics through ``gh``."""

    root = repo_root()
    cfg = load_config(root)
    checks = collect_github_checks(root, cfg, **({"repository": args.repo} if getattr(args, "repo", None) else {}))
    emit_check_output(
        "GitHub",
        checks,
        output_format=getattr(args, "format", "human"),
        context={"scope": "repository, prod secret metadata, and OIDC verification through GitHub CLI"},
    )
    return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)


def cmd_gh_status(args: argparse.Namespace) -> int:
    """Show recent Actions runs with failed jobs, steps, and remediation."""

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


# Production deployment is intentionally centralized behind a protected GitHub
# workflow.  Local handlers validate intent, dispatch an exact image, and keep
# non-secret correlation metadata; they never run Terraform apply directly.
def deployment_error_exit_code(error: str) -> int:
    lowered = error.lower()
    if "not found on path" in lowered:
        return EXIT_MISSING_EXTERNAL_TOOL
    if any(marker in lowered for marker in ("auth", "login", "logged in", "credentials")):
        return EXIT_AUTH_FAILED
    return EXIT_VALIDATION_FAILED


def deployment_preflight_exit_code(checks: list[Check]) -> int:
    github_cli = next((check for check in checks if check.name == "GitHub CLI"), None)
    if github_cli is not None and github_cli.status != "OK" and "not found" in github_cli.detail.lower():
        return EXIT_MISSING_EXTERNAL_TOOL
    github_auth = next((check for check in checks if check.name == "GitHub auth"), None)
    if github_auth is not None and github_auth.status != "OK":
        return EXIT_AUTH_FAILED
    return EXIT_VALIDATION_FAILED


def production_deployment_preflight_checks(
    root: Path,
    cfg: dict[str, Any],
    runs: list[dict[str, Any]],
    runs_error: str | None,
    active_image_uri: str,
    active_image_error: str | None,
) -> list[Check]:
    """Assemble every local and provider gate required before production deploy."""

    checks: list[Check] = []
    config_exists = config_path(root).exists()
    checks.append(
        Check(
            "Local config",
            "OK" if config_exists else "FAIL",
            str(config_path(root)) if config_exists else f"Create {CONFIG_FILE} with `devsecops setup`.",
        )
    )
    missing_files = missing_project_files(root)
    checks.append(
        Check(
            "Project deployment files",
            "OK" if not missing_files else "FAIL",
            "Terraform modules and protected workflow are present."
            if not missing_files
            else "Missing: " + ", ".join(missing_files),
        )
    )

    policy_blockers = production_policy_blockers(validate_config(cfg))
    checks.append(
        Check(
            "Production config policy",
            "OK" if config_exists and not policy_blockers else "FAIL",
            "Strict production controls are ready."
            if config_exists and not policy_blockers
            else "; ".join(f"{check.name}: {check.detail}" for check in policy_blockers)
            or "Local config is missing.",
        )
    )
    checks.extend(collect_image_preflight_checks(cfg, env_name=DEPLOYMENT_ENVIRONMENT))

    missing_generated = generated_artifact_gaps(root, cfg)
    checks.append(
        Check(
            "Generated deployment helpers",
            "OK" if not missing_generated else "FAIL",
            "Generated inputs match current local configuration."
            if not missing_generated
            else "Run `devsecops generate`: " + ", ".join(missing_generated),
        )
    )
    github_checks = exact_image_dispatch_github_checks(collect_github_checks(root, cfg))
    checks.extend(github_checks)
    github_check_names = {check.name for check in github_checks}
    checks.extend(
        check
        for check in collect_branch_checks(root, DEPLOYMENT_REF)
        if check.name not in github_check_names
    )

    if runs_error:
        checks.append(Check("Concurrent production run", "FAIL", runs_error))
    else:
        active = active_deployment_runs(runs)
        checks.append(
            Check(
                "Concurrent production run",
                "FAIL" if active else "OK",
                f"Run {active[0].get('databaseId')} is already {active[0].get('status')}."
                if active
                else "No queued or running manual workflow uses the production deployment lane.",
            )
        )
    checks.append(
        Check(
            "Current Lambda image",
            "INFO",
            active_image_uri
            or active_image_error
            or "No deployed Lambda image found; this appears to be the first deployment.",
            scored=False,
        )
    )
    return checks


def exact_image_dispatch_github_checks(checks: list[Check]) -> list[Check]:
    """Ignore only the repository image fallback when dispatch binds an exact target."""

    adjusted: list[Check] = []
    for check in checks:
        if check.name == "GitHub variable LAMBDA_IMAGE_URI" or (
            check.name == "GitHub variable PIPELINE_CONFIG_JSON"
            and check.detail.startswith("Only lambda_image_uri differs")
        ):
            adjusted.append(
                Check(
                    check.name,
                    "INFO",
                    check.detail + " The CLI supplies the reviewed image directly for this workflow run.",
                    scored=False,
                )
            )
        else:
            adjusted.append(check)
    return adjusted


def rollback_github_checks(checks: list[Check]) -> list[Check]:
    """Keep incident rollback available when only local desired-state values drift."""

    adjusted: list[Check] = []
    for check in exact_image_dispatch_github_checks(checks):
        local_mismatch = check.name.startswith("GitHub variable ") and (
            check.detail.startswith("Expected `") or "Local config has no expected" in check.detail
        )
        if local_mismatch:
            adjusted.append(
                Check(
                    check.name,
                    "INFO",
                    check.detail + " Local desired-state drift does not block an explicit rollback target.",
                    scored=False,
                )
            )
        else:
            adjusted.append(check)
    return adjusted


def rollback_deployment_preflight_checks(
    root: Path,
    cfg: dict[str, Any],
    target_image_uri: str,
    runs: list[dict[str, Any]],
    runs_error: str | None,
    active_image_uri: str,
    active_image_error: str | None,
) -> list[Check]:
    """Validate an explicit rollback target while tolerating desired-state drift."""

    workflow_exists = (root / DEPLOYMENT_WORKFLOW_PATH).exists()
    checks = [
        Check(
            "Protected deployment workflow",
            "OK" if workflow_exists else "FAIL",
            DEPLOYMENT_WORKFLOW_PATH if workflow_exists else f"Missing {DEPLOYMENT_WORKFLOW_PATH}.",
        )
    ]
    image_checks = collect_image_preflight_checks(cfg, image_uri=target_image_uri, env_name=DEPLOYMENT_ENVIRONMENT)
    if not config_path(root).exists():
        image_checks = [
            Check(check.name, "INFO", check.detail, scored=False)
            if check.name in {"Lambda image region", "Lambda image repository"}
            else check
            for check in image_checks
        ]
    checks.extend(image_checks)
    checks.extend(rollback_github_checks(collect_github_checks(root, cfg)))
    if runs_error:
        checks.append(Check("Concurrent production run", "FAIL", runs_error))
    else:
        active = active_deployment_runs(runs)
        checks.append(
            Check(
                "Concurrent production run",
                "FAIL" if active else "OK",
                f"Run {active[0].get('databaseId')} is already {active[0].get('status')}."
                if active
                else "No queued or running manual workflow uses the production deployment lane.",
            )
        )
    if active_image_uri and active_image_uri == target_image_uri:
        checks.append(Check("Rollback changes image", "INFO", "The requested digest is already active. The workflow will verify it and reconcile Terraform state.", scored=False))
    else:
        checks.append(
            Check(
                "Current Lambda image",
                "INFO",
                active_image_uri or active_image_error or "Could not observe the current image locally.",
                scored=False,
            )
        )
    return checks


def save_dispatched_run(root: Path, record: dict[str, str]) -> None:
    try:
        record_deployment(root, record)
    except (DeploymentStateError, OSError) as exc:
        print(warn(f"Could not save the deployment request locally: {exc}"), file=sys.stderr)


def find_deployment_request(root: Path, record: dict[str, str], attempts: int) -> dict[str, Any]:
    if not record["request_id"]:
        return {}
    for attempt in range(attempts):
        try:
            runs, error = list_deployment_runs(root, limit=100, repository=record["repository"])
        except subprocess.TimeoutExpired:
            return {}
        if error:
            return {}
        run = select_dispatched_run(runs, record)
        if run:
            record.update(run_id=str(run["databaseId"]), run_url=run["url"])
            save_dispatched_run(root, record)
            return run
        if attempt + 1 < attempts:
            time.sleep(1)
    return {}


def resolve_deployment_run(
    root: Path, run_id: str | None = None, *, attempts: int = 1,
) -> tuple[dict[str, Any], dict[str, str] | None, str | None]:
    """Resolve a journaled request without falling back to another run."""

    record = latest_deployment(root, run_id)
    selected_run_id = str(run_id or (record or {}).get("run_id") or "")
    if not selected_run_id:
        if record:
            candidate = find_deployment_request(root, record, attempts)
            if not candidate:
                return {}, record, None
        else:
            runs, error = list_deployment_runs(root)
            if error:
                return {}, None, error
            candidate = newest_deployment_run(runs)
            if candidate is None:
                return {}, None, "No production deployment run was found. Start one with `devsecops deploy prod`."
        selected_run_id = str(candidate.get("databaseId") or "")
    if selected_run_id:
        if not re.fullmatch(r"[1-9][0-9]*", selected_run_id):
            return {}, record, "A GitHub Actions run ID must be a positive integer."
        repo = (record or {}).get("repository", "")
        run, error = view_deployment_run(root, selected_run_id, **({"repository": repo} if repo else {}))
        if error:
            return {}, record, error
        if str(run.get("databaseId") or "") != selected_run_id or not is_deployment_run(run):
            return {}, record, f"Run {selected_run_id} does not belong to the protected deployment workflow."
        if record and record["request_id"]:
            if not matches_deployment_request(run, record):
                return {}, record, f"Run {selected_run_id} does not match the saved deployment request."
            return run, record, None
        # Old journals could correlate to a different run. The GitHub result
        # is still useful on its own, without the unverified journal fields.
        return run, None, None
    return {}, record, "The deployment run has no GitHub Actions run ID."


def confirm_cloud_deployment(operation: str) -> bool:
    """Require an operation-specific phrase before protected cloud mutation."""

    expected = DEPLOYMENT_ENVIRONMENT if operation == "deploy" else "rollback"
    try:
        answer = read_input(f"Type {expected} to dispatch this {operation} workflow: ").strip().lower()
    except EOFError:
        return False
    return answer == expected


def review_deployment_intent(
    root: Path, image_uri: str, cfg: dict[str, Any] | None = None,
) -> tuple[DeploymentIntent, dict[str, Any]]:
    """Pin the destination, remote commit, effective configuration, and image before confirmation."""

    repository = gh_command(root, ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    if repository.returncode != 0 or not repository.stdout.strip():
        raise ConfigValidationError(f"Cannot identify the deployment repository: {compact_error(repository)}")
    name = repository.stdout.strip()
    ref = gh_command(root, ["api", f"repos/{name}/git/ref/heads/{DEPLOYMENT_REF}", "--jq", ".object.sha"])
    commit_sha = ref.stdout.strip()
    if ref.returncode != 0 or not is_commit_sha(commit_sha):
        raise ConfigValidationError(f"Cannot verify the remote {DEPLOYMENT_REF} commit in {name}.")

    if cfg is None:
        remote = gh_command(root, ["api", f"repos/{name}/actions/variables/{PIPELINE_CONFIG_VARIABLE}", "--jq", ".value"])
        if remote.returncode != 0:
            raise ConfigValidationError(f"Cannot read the repository configuration for rollback: {compact_error(remote)}")
        cfg = decode_pipeline_config(remote.stdout, production=True, image_uri=image_uri)

    if not command_exists("aws"):
        raise ConfigValidationError("Install and authenticate AWS CLI to verify the selected ECR image.")
    digest_uri = verify_ecr_lambda_image(root, image_uri, cfg["aws_region"], aws_json_fn=aws_json)
    intent = DeploymentIntent(name, commit_sha, deployment_config_sha256(cfg, digest_uri), digest_uri, uuid.uuid4().hex)
    return intent, cfg


def print_deployment_intent(
    operation: str,
    intent: DeploymentIntent,
    cfg: dict[str, Any],
    previous_image_uri: str,
    source_run_id: str = "",
) -> None:
    """Show the pinned deployment inputs before the operator confirms them."""

    title = "Production Deployment" if operation == "deploy" else "Production Rollback"
    backend = cfg["backend"]
    lines = [
        f"Operation: {operation}",
        f"Repository: {intent.repository}",
        f"Environment: {DEPLOYMENT_ENVIRONMENT}",
        f"Protected ref: {DEPLOYMENT_REF}",
        f"Commit SHA: {intent.commit_sha}",
        f"Config SHA-256: {intent.config_sha256}",
        f"Project and region: {cfg['project_name']} ({cfg['aws_region']})",
        f"State: s3://{backend['bucket']}/{backend['workspace_key_prefix']}/{DEPLOYMENT_ENVIRONMENT}/{backend['key']} ({backend['region']})",
        f"Target image: {intent.image_uri}",
        f"Current image: {previous_image_uri or '(not observed locally)'}",
        "Execution: protected GitHub Actions environment with OIDC and Terraform state",
    ]
    if source_run_id:
        lines.insert(1, f"Deployment being reversed: run {source_run_id}")
    draw_box(title, lines)
    print("Underlying GitHub command:")
    print("  " + display_gh_command(workflow_dispatch_args(operation, intent)))


def dispatch_cloud_deployment(
    root: Path,
    operation: str,
    intent: DeploymentIntent,
    source_run_id: str,
    *,
    watch: bool,
    interval: int,
) -> int:
    """Recheck concurrency, dispatch the workflow, journal it, and optionally watch.

    The production lane is checked again after confirmation to close the race
    between initial preflight and workflow dispatch.
    """

    current_runs, current_runs_error = list_deployment_runs(root, repository=intent.repository)
    if current_runs_error:
        print(fail("Could not recheck the production deployment lane: ") + current_runs_error)
        return deployment_error_exit_code(current_runs_error)
    active = active_deployment_runs(current_runs)
    if active:
        print(
            fail("Deployment was not dispatched: ")
            + f"run {active[0].get('databaseId')} became {active[0].get('status')} during confirmation."
        )
        return EXIT_VALIDATION_FAILED
    print(f"Request: {intent.request_id}", flush=True)
    dispatch_timed_out = False
    try:
        result = dispatch_deployment_workflow(root, operation, intent)
    except subprocess.TimeoutExpired:
        dispatch_timed_out = True
        run_id, run_url = "", ""
    else:
        if result.returncode != 0:
            print(fail("GitHub workflow dispatch failed: ") + compact_error(result))
            return deployment_error_exit_code(compact_error(result))
        run_id, run_url = parse_run_url(result.stdout or "", intent.repository)

    record = {
        "operation": operation,
        "environment": DEPLOYMENT_ENVIRONMENT,
        "ref": DEPLOYMENT_REF,
        "repository": intent.repository,
        "commit_sha": intent.commit_sha,
        "config_sha256": intent.config_sha256,
        "request_id": intent.request_id,
        "dispatch_acknowledged": "false" if dispatch_timed_out else "true",
        "requested_image_uri": intent.image_uri,
        "source_run_id": source_run_id,
        "run_id": run_id,
        "run_url": run_url,
        "dispatched_at": utc_now(),
    }
    save_dispatched_run(root, record)
    if not run_id:
        find_deployment_request(root, record, attempts=8)
        run_id, run_url = record["run_id"], record["run_url"]

    if not run_id:
        message = "Dispatch response timed out; run unconfirmed." if dispatch_timed_out else "Dispatched, run unconfirmed."
        print(warn(message + " Check status before dispatching again."))
        print("Next command: devsecops deploy status --watch")
        return EXIT_VALIDATION_FAILED if watch or dispatch_timed_out else EXIT_OK
    print(ok("Protected production workflow dispatched."))
    print(f"Run: {run_id}")
    print(f"URL: {run_url}")
    print(f"Next command: devsecops deploy status --run-id {run_id} --watch")

    if not watch:
        return EXIT_OK
    print(info("Watching deployment run through GitHub CLI..."))
    try:
        watch_result = watch_deployment_run(root, run_id, interval, stream=True, repository=intent.repository)
    except subprocess.TimeoutExpired:
        print(warn("Watch timed out. Checking the exact run for a conclusion."))
    else:
        if (watch_result.stdout or "").strip():
            print((watch_result.stdout or "").rstrip())
        if watch_result.returncode != 0 and (watch_result.stderr or "").strip():
            print(warn(compact_error(watch_result)))
    refreshed, error = view_deployment_run(root, run_id, repository=intent.repository)
    if error:
        print(fail(error))
        return deployment_error_exit_code(error)
    if (str(refreshed.get("databaseId")) != run_id or not matches_deployment_request(refreshed, record)
            or refreshed.get("status") != "completed"):
        print(warn("The requested run has no verified conclusion."))
        return EXIT_VALIDATION_FAILED
    result, detail = deployment_result(refreshed)
    print(ok(detail) if result == "success" else fail(detail))
    return deployment_exit_code(refreshed)


def cmd_deploy_prod(args: argparse.Namespace) -> int:
    """Preflight and optionally dispatch an exact-image production deployment."""

    root = repo_root()
    cfg = load_config(root)
    if getattr(args, "interval", 5) < 3:
        print(fail("--interval must be at least 3 seconds."))
        return EXIT_VALIDATION_FAILED
    runs, runs_error = list_deployment_runs(root)
    active_image_uri, active_image_error = inspect_active_lambda_image(root, cfg)
    checks = production_deployment_preflight_checks(
        root,
        cfg,
        runs,
        runs_error,
        active_image_uri,
        active_image_error,
    )
    image_uri = str(cfg.get("lambda_image_uri") or "")
    emit_check_output("Production Deployment Preflight", checks)
    blockers = [check for check in checks if check.scored and check.status != "OK"]
    if blockers:
        print()
        print(fail(f"Deployment blocked by {len(blockers)} preflight check(s)."))
        return deployment_preflight_exit_code(checks)
    intent, cfg = review_deployment_intent(root, image_uri, cfg)
    print_deployment_intent("deploy", intent, cfg, active_image_uri)
    if getattr(args, "dry_run", False):
        print()
        print(info("Dry run only. No workflow was dispatched and AWS was not changed."))
        return EXIT_OK
    if not getattr(args, "yes", False) and not confirm_cloud_deployment("deploy"):
        print(info("Production deployment cancelled. No workflow was dispatched."))
        return EXIT_OK
    return dispatch_cloud_deployment(
        root,
        "deploy",
        intent,
        "",
        watch=getattr(args, "watch", False),
        interval=getattr(args, "interval", 5),
    )


def read_deployment_recovery_point(root: Path, run: dict[str, Any]) -> dict[str, str]:
    """Read the runner's recovery point for a completed production deployment."""

    run_id = str(run.get("databaseId") or "")
    attempt = str(run.get("attempt") or "")
    operation, _ = deployment_title(str(run.get("displayTitle") or ""))
    run_url = str(run.get("url") or "")
    identity = re.fullmatch(r"https://github\.com/([\w.-]+/[\w.-]+)/actions/runs/([1-9][0-9]*)", run_url)
    if (deployment_result(run)[0] != "success" or operation != "deploy"
            or not identity or identity[2] != run_id or not re.fullmatch(r"[1-9][0-9]*", attempt)
            or not is_commit_sha(str(run.get("headSha") or ""))):
        raise ConfigValidationError(
            "Rollback inference requires a completed, successful production deployment that applied and passed health validation. "
            "For incident recovery, pass a reviewed --image-uri."
        )
    repository = identity[1]
    metadata = gh_command(root, ["api", f"repos/{repository}/actions/runs/{run_id}"])
    source = _github_adapter.parse_json_object(metadata.stdout)
    if (metadata.returncode != 0 or str(source.get("path") or "").split("@", 1)[0] != DEPLOYMENT_WORKFLOW_PATH
            or str(source.get("id")) != run_id or str(source.get("run_attempt")) != attempt
            or source.get("head_sha") != run["headSha"] or source.get("head_branch") != DEPLOYMENT_REF
            or source.get("event") != "workflow_dispatch"
            or source.get("status") != "completed" or source.get("conclusion") != "success"):
        raise ConfigValidationError("Could not verify the successful source run and attempt.")
    with tempfile.TemporaryDirectory(prefix="devsecops-recovery-") as directory:
        result = gh_command(root, [
            "run", "download", run_id, "--repo", repository, "--name", f"deployment-recovery-{attempt}", "--dir", directory,
        ])
        if result.returncode != 0:
            raise ConfigValidationError("The source run has no downloadable recovery point. Pass a reviewed --image-uri.")
        path = Path(directory) / "deployment-recovery.json"
        try:
            if path.is_symlink() or path.stat().st_size > 8192:
                raise ValueError("Invalid recovery point file")
            point = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigValidationError("Could not read the source run's recovery point.") from exc
    expected = {"run_id": run_id, "attempt": attempt, "commit_sha": run["headSha"]}
    if (not isinstance(point, dict) or str(point.get("repository") or "").lower() != repository.lower()
            or any(point.get(key) != value for key, value in expected.items())):
        raise ConfigValidationError("The recovery point does not belong to the selected run and attempt.")
    previous = parse_ecr_image_uri(point.get("previous_image_uri"))
    deployed = parse_ecr_image_uri(point.get("deployed_image_uri"))
    if not deployed or not deployed.digest or (point.get("previous_image_uri") != "" and (not previous or not previous.digest)):
        raise ConfigValidationError("The source run's recovery point does not contain exact image digests.")
    return point


def cmd_deploy_rollback(args: argparse.Namespace) -> int:
    """Resolve, preflight, and optionally dispatch a production image rollback."""

    root = repo_root()
    if getattr(args, "interval", 5) < 3:
        print(fail("--interval must be at least 3 seconds."))
        return EXIT_VALIDATION_FAILED
    source_run_id = str(getattr(args, "run_id", None) or "")
    target_image_uri = str(getattr(args, "image_uri", None) or "").strip()
    point = None
    if not target_image_uri:
        if not source_run_id and not latest_deployment(root):
            print(fail("No rollback target is available."))
            print("Pass `--run-id` for a successful deployment or a reviewed `--image-uri`.")
            return EXIT_VALIDATION_FAILED
        run, record, error = resolve_deployment_run(root, source_run_id or None)
        if not run or error:
            print(fail(error or "The deployment request has no confirmed run."))
            print("Pass `--run-id` for a successful deployment or a reviewed `--image-uri`.")
            return deployment_error_exit_code(error or "")
        if "jobs" not in run:
            run, record, error = resolve_deployment_run(root, str(run["databaseId"]))
            if error:
                raise ConfigValidationError(error)
        point = read_deployment_recovery_point(root, run)
        if record and record["requested_image_uri"] != point["deployed_image_uri"]:
            raise ConfigValidationError("The recovery point's deployed image does not match the recorded request.")
        source_run_id = point["run_id"]
        target_image_uri = point["previous_image_uri"]
        if not target_image_uri:
            raise ConfigValidationError("The source run has no previous image. Pass a reviewed --image-uri.")

    intent, cfg = review_deployment_intent(root, target_image_uri)
    if point:
        expected_arn = rf"arn:aws:lambda:{re.escape(cfg['aws_region'])}:[0-9]{{12}}:function:{re.escape(expected_lambda_function_name(cfg, 'prod'))}"
        if (point["repository"].lower() != intent.repository.lower()
                or not re.fullmatch(expected_arn, str(point.get("function_arn") or ""))):
            raise ConfigValidationError("The recovery point is for a different repository or Lambda function.")
        intent = replace(intent, rollback_from_image_uri=point["deployed_image_uri"], rollback_function_arn=point["function_arn"])
    runs, runs_error = list_deployment_runs(root)
    active_image_uri, active_image_error = inspect_active_lambda_image(root, cfg)
    if point and active_image_uri != point["deployed_image_uri"]:
        raise ConfigValidationError("The active image could not be verified against the source deployment. Review an explicit --image-uri.")
    checks = rollback_deployment_preflight_checks(
        root,
        cfg,
        intent.image_uri,
        runs,
        runs_error,
        active_image_uri,
        active_image_error,
    )
    emit_check_output("Production Rollback Preflight", checks)
    blockers = [check for check in checks if check.scored and check.status != "OK"]
    if blockers:
        print()
        print(fail(f"Rollback blocked by {len(blockers)} preflight check(s)."))
        return deployment_preflight_exit_code(checks)
    print_deployment_intent("rollback", intent, cfg, active_image_uri, source_run_id)
    if getattr(args, "dry_run", False):
        print()
        print(info("Dry run only. No rollback workflow was dispatched and AWS was not changed."))
        return EXIT_OK
    if not getattr(args, "yes", False) and not confirm_cloud_deployment("rollback"):
        print(info("Production rollback cancelled. No workflow was dispatched."))
        return EXIT_OK
    return dispatch_cloud_deployment(
        root,
        "rollback",
        intent,
        source_run_id,
        watch=getattr(args, "watch", False),
        interval=getattr(args, "interval", 5),
    )


def emit_deployment_status(
    run: dict[str, Any],
    record: dict[str, str] | None,
    active_image_uri: str,
    active_image_error: str | None,
    output_format: str,
) -> None:
    """Render one stable deployment status in JSON, compact, or human form."""

    payload = deployment_status_payload(run, record, active_image_uri)
    if output_format == "json":
        if active_image_error:
            payload["active_image_warning"] = active_image_error
        emit_json(payload)
        return

    operation = payload["operation"] or "unknown"
    run_id = str(run.get("databaseId") or "")
    status = str(run.get("status") or "unknown")
    conclusion = str(run.get("conclusion") or "")
    if output_format == "compact":
        print(f"prod {operation} | run {run_id or '?'} | {status} | {payload['deployment_result']}")
        print(payload["deployment_detail"])
        if run.get("url"):
            print(str(run["url"]))
        return

    draw_box(
        "Production Deployment Status",
        [
            f"Run: {run_id or '(unknown)'}",
            f"Operation: {operation}",
            f"Status: {status}",
            f"Conclusion: {conclusion or '(pending)'}",
            f"Deployment result: {payload['deployment_result']}",
            payload["deployment_detail"],
            f"Ref: {run.get('headBranch') or DEPLOYMENT_REF} ({str(run.get('headSha') or '')[:12] or 'unknown SHA'})",
            f"Requested image: {(record or {}).get('requested_image_uri') or '(not recorded locally)'}",
            f"Previous image: {payload['previous_image_uri'] or '(no verified recovery digest)'}",
            f"Active AWS image: {active_image_uri or '(not observed locally)'}",
            f"URL: {run.get('url') or '(not available)'}",
        ],
    )
    print("Underlying GitHub command:")
    print("  " + display_gh_command(workflow_run_view_args(run_id, (record or {}).get("repository", ""))))
    rows = deployment_job_rows(run)
    if rows:
        print()
        draw_table(["Job", "Status", "Conclusion", "Started", "Completed"], rows, title="Deployment Jobs")
    if active_image_error:
        print()
        print(warn("AWS image inspection: ") + active_image_error)
    print()
    if status != "completed":
        print(f"Next command: devsecops deploy status --run-id {run_id} --watch")
    elif payload["deployment_result"] == "success":
        print("Next command: devsecops health --aws-sigv4")
    else:
        print(f"Next command: devsecops deploy logs --run-id {run_id} --failed")


def cmd_deploy_status(args: argparse.Namespace) -> int:
    """Resolve, optionally watch, and report a protected deployment run."""

    root = repo_root()
    interval = getattr(args, "interval", 5)
    output_format = getattr(args, "format", "human")
    if interval < 3:
        if output_format == "json":
            emit_json(
                {
                    "kind": "deployment-status",
                    "schema_version": CONTRACT_SCHEMA_VERSION,
                    "error": "--interval must be at least 3 seconds.",
                }
            )
        else:
            print(fail("--interval must be at least 3 seconds."))
        return EXIT_VALIDATION_FAILED
    watch_incomplete = False
    watch = bool(getattr(args, "watch", False))
    run, record, error = resolve_deployment_run(root, getattr(args, "run_id", None), **({"attempts": 8} if watch else {}))
    if error:
        if output_format == "json":
            emit_json(
                {
                    "kind": "deployment-status",
                    "schema_version": CONTRACT_SCHEMA_VERSION,
                    "error": error,
                    "run": None,
                    "jobs": [],
                }
            )
        else:
            print(fail(error))
        return deployment_error_exit_code(error)

    if not run:
        payload = deployment_status_payload(run, record)
        if output_format == "json":
            emit_json(payload)
        else:
            print(warn(f"{payload['run_confirmation'].capitalize()}. Request: {payload['request_id'] or '(legacy request)'}"))
            print("Next command: devsecops deploy status --watch")
        return EXIT_VALIDATION_FAILED if watch else EXIT_OK

    run_id = str(run.get("databaseId") or "")
    repository = (record or {}).get("repository", "")
    scope = {"repository": repository} if repository else {}
    if watch and run.get("status") != "completed":
        if output_format != "json":
            print(info("Underlying GitHub command: ") + display_gh_command(workflow_run_watch_args(run_id, interval, repository)))
        try:
            watched = watch_deployment_run(root, run_id, interval, stream=output_format != "json", **scope)
        except subprocess.TimeoutExpired:
            if output_format != "json":
                print(warn("Watch timed out. Checking the exact run for a conclusion."))
        else:
            if output_format != "json" and (watched.stdout or "").strip():
                print((watched.stdout or "").rstrip())
        refreshed, refresh_error = view_deployment_run(root, run_id, **scope)
        if not refresh_error and (str(refreshed.get("databaseId")) != run_id or not is_deployment_run(refreshed)
                                  or (record and not matches_deployment_request(refreshed, record))):
            refresh_error = "The refreshed run does not match the selected deployment."
        if refresh_error:
            if output_format == "json":
                emit_json(
                    {
                        "kind": "deployment-status",
                        "schema_version": CONTRACT_SCHEMA_VERSION,
                        "error": refresh_error,
                        "run": None,
                        "jobs": [],
                    }
                )
            else:
                print(fail(refresh_error))
            return deployment_error_exit_code(refresh_error)
        run = refreshed
        if run.get("status") != "completed":
            watch_incomplete = True
            if output_format != "json":
                print(warn("GitHub stopped watching before the deployment reached a conclusion."))

    cfg = load_config(root)
    active_image_uri, active_image_error = inspect_active_lambda_image(root, cfg)
    if deployment_result(run)[0] == "success" and any(
        step.get("name") == "Upload deployment recovery point" and step.get("conclusion") == "success"
        for job in run.get("jobs") or [] if job.get("name") == PRODUCTION_JOB
        for step in job.get("steps") or []
    ):
        try:
            point = read_deployment_recovery_point(root, run)
        except (ConfigValidationError, subprocess.TimeoutExpired):
            pass
        else:
            if record and record["requested_image_uri"] != point["deployed_image_uri"]:
                print(warn("The recovery point's deployed image does not match the recorded request."), file=sys.stderr)
            else:
                record = {**(record or {}), "requested_image_uri": point["deployed_image_uri"],
                          "previous_image_uri": point["previous_image_uri"]}
    emit_deployment_status(run, record, active_image_uri, active_image_error, output_format)
    return EXIT_VALIDATION_FAILED if watch_incomplete else deployment_exit_code(run)


def cmd_deploy_logs(args: argparse.Namespace) -> int:
    """Stream full or failed-only logs for a verified deployment run."""

    root = repo_root()
    run, record, error = resolve_deployment_run(root, getattr(args, "run_id", None))
    if error:
        print(fail(error))
        return deployment_error_exit_code(error)
    if not run:
        print(fail("Dispatched, run unconfirmed. Run `devsecops deploy status --watch` to locate this request."))
        return EXIT_VALIDATION_FAILED
    run_id = str(run.get("databaseId") or "")
    failed_only = bool(getattr(args, "failed", False))
    repository = (record or {}).get("repository", "")
    command = workflow_run_log_args(run_id, failed_only=failed_only, repository=repository)
    draw_box(
        "Production Deployment Logs",
        [
            f"Run: {run_id}",
            f"Scope: {'failed steps only' if failed_only else 'full workflow log'}",
            "Logs are streamed from GitHub Actions; no repository or cloud state is changed.",
        ],
    )
    print("Underlying GitHub command:")
    print("  " + display_gh_command(command))
    print()
    result = read_deployment_logs(root, run_id, failed_only=failed_only, **({"repository": repository} if repository else {}))
    if result.returncode != 0:
        print(fail(compact_error(result)))
        return deployment_error_exit_code(compact_error(result))
    if result.stdout is not None:
        if result.stdout:
            print(result.stdout.rstrip())
        else:
            print(warn("GitHub returned no log lines for this scope."))
    print()
    status = str(run.get("status") or "")
    if status != "completed":
        next_command = f"devsecops deploy status --run-id {run_id} --watch"
    elif deployment_result(run)[0] == "success":
        next_command = "devsecops health --aws-sigv4"
    else:
        next_command = "devsecops deploy rollback --image-uri <known-good-immutable-ecr-image-uri> --dry-run"
    print(f"Next command: {next_command}")
    return EXIT_OK


def cmd_deploy(args: argparse.Namespace) -> int:
    """Dispatch the grouped deployment command to its operation handler."""

    command = getattr(args, "deploy_command", None) or "status"
    if command == "prod":
        return cmd_deploy_prod(args)
    if command == "status":
        return cmd_deploy_status(args)
    if command == "logs":
        return cmd_deploy_logs(args)
    if command == "rollback":
        return cmd_deploy_rollback(args)
    print(fail("Unknown deploy command: ") + str(command))
    print("Usage: devsecops deploy [prod|status|logs|rollback]")
    return EXIT_VALIDATION_FAILED


def cmd_branch_doctor(args: argparse.Namespace) -> int:
    """Inspect deployment-branch protection and required checks."""

    checks = collect_branch_checks(repo_root(), branch=args.branch)
    emit_check_output(
        "Branch Protection",
        checks,
        output_format=getattr(args, "format", "human"),
        context={"branch": args.branch},
    )
    return strict_exit_code(checks, strict=getattr(args, "strict", False), fail_on_warn=True)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Dispatch scoped diagnostics or aggregate all provider check sets."""

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
    """Run the legacy interactive configuration initializer safely."""

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
                    choices=LOG_RETENTION_DAYS,
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
    """Adapt parsed legacy init arguments to the reusable initializer."""

    return run_init(repo_root(), force=args.force, defaults=args.defaults)


def cmd_preflight(args: argparse.Namespace) -> int:
    """Validate the selected image and emit the requested output contract."""

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
    """Resolve an in-memory config for a no-write first-success preview."""

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
    """Preview generated files and readiness without filesystem or cloud writes."""

    root = repo_root()
    state = load_setup_state(root)
    requested_environment = getattr(args, "environment", None)
    demo = (bool(getattr(args, "demo", False)) or getattr(args, "preset", None) == "student-demo"
            or bool(state and state["mode"] == "demo" and requested_environment is None))
    env_name = requested_environment or ("dev" if demo else "prod")
    cfg, source = dry_run_config(root, getattr(args, "preset", "balanced"), getattr(args, "image_uri", None))
    if demo and not getattr(args, "image_uri", None) and not is_immutable_image(str(cfg.get("lambda_image_uri", ""))):
        cfg["lambda_image_uri"] = demo_image_uri(cfg)
    outputs = render_outputs(root, cfg)
    image_checks = collect_image_preflight_checks(cfg, env_name=env_name)
    readiness_checks = [] if demo else collect_checks(root, cfg, deep=False)

    draw_box(
        "First Successful Pipeline Dry Run",
        [
            "No files changed.",
            "AWS credentials are not required for this dry run.",
            f"Config source: {source}",
            f"Demo preview environment: {env_name}" if demo else f"Environment target: {env_name}",
        ],
    )
    print_render_plan(root, outputs, title="Files that would be generated")
    print()
    print_checks(image_checks, title="Image validation")
    print()
    if demo:
        failures = [check for check in validate_config(cfg) if check.status == "FAIL"]
        if failures:
            print_checks(failures, title="Demo configuration")
        else:
            print_text(ok("Demo configuration is valid. Cloud connections are not required."))
    else:
        print_gap_summary(readiness_checks, limit=8)
    print()
    print_text(info("Next documented path: docs/first-successful-pipeline.md"))
    validation = validate_config(cfg)
    return EXIT_VALIDATION_FAILED if any(check.status == "FAIL" for check in [*image_checks, *validation]) else EXIT_OK


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
    """Generate all CLI-owned artifacts, optionally as a no-write plan."""

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
    """Adapt generate/render command arguments to the shared renderer."""

    return run_render(repo_root(), dry_run=getattr(args, "dry_run", False))


def cmd_readiness(args: argparse.Namespace) -> int:
    """Emit readiness details and enforce optional strict scoring."""

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
    """Resolve and probe the workload health endpoint, optionally with SigV4."""

    root = repo_root()
    cfg = load_config(root)
    checks = collect_health_checks(
        root,
        cfg,
        url=getattr(args, "url", None),
        timeout=getattr(args, "timeout", 20),
        aws_sigv4=getattr(args, "aws_sigv4", False),
        aws_region=getattr(args, "aws_region", None),
        trusted_host=getattr(args, "trusted_host", None),
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
    """Run read-only AWS identity, backend, and workload diagnostics."""

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
    """Inspect deployed AWS output values without changing resources."""

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
    """Dispatch the grouped AWS command."""

    command = getattr(args, "aws_command", None) or "outputs"
    if command == "doctor":
        return cmd_aws_doctor(args)
    if command == "outputs":
        return cmd_aws_outputs(args)
    print(fail("Unknown AWS command: ") + str(command))
    print("Usage: devsecops aws [doctor|outputs]")
    return EXIT_VALIDATION_FAILED


def cmd_github(args: argparse.Namespace) -> int:
    """Dispatch the grouped GitHub command."""

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
    """Dispatch Terraform planning or backend bootstrap operations."""

    command = getattr(args, "terraform_command", None)
    if command == "plan":
        return cmd_plan(args)
    if command == "bootstrap":
        return cmd_bootstrap(args)
    if command == "teardown":
        return cmd_teardown(args)
    print(fail("Usage: devsecops terraform plan <env> | bootstrap [--apply]"))
    return EXIT_VALIDATION_FAILED


def cmd_teardown(args: argparse.Namespace) -> int:
    """Guide decommissioning; S3 mutations require a separately reviewed plan."""

    action = getattr(args, "teardown_command", None)
    if action is None:
        payload = dict(kind="teardown-guide", schema_version=1, docs="docs/runbooks/finish-demo.md",
                       phases=["Freeze deployments and stop workload writers", "Review scope and export restorable backups",
                               "Review and empty workload S3/ECR data", "Apply a reviewed workload destroy plan per workspace",
                               "Keep shared state backend; retire it last only if exclusively unused", "Verify resources, KMS schedule and delayed billing"],
                       message="Local demo setup creates no AWS resources. For cloud resources follow the runbook; this guide changes nothing.")
    else:
        if not command_exists("aws"):
            return emit_command_error(args, "AWS CLI is required for a bucket inventory or approved cleanup.", EXIT_MISSING_EXTERNAL_TOOL)
        try:
            root = repo_root()
            if config_path(root).is_file():
                cfg = load_config(root)
                backend_bucket = str(cfg["backend"]["bucket"])
                protected = {backend_bucket: "backend-state", backend_bucket + "-logs": "backend-logs"}
                if args.bucket in protected:
                    if action == "bucket-plan" and args.purpose != protected[args.bucket]:
                        raise _teardown.TeardownError("Configured backend buckets must use their backend purpose; workload cleanup cannot select them.")
                    if action == "bucket-purge" and not args.allow_backend_cleanup:
                        raise _teardown.TeardownError("Configured backend cleanup additionally requires --allow-backend-cleanup.")
            if action == "bucket-plan":
                path = args.output if args.output.is_absolute() else root / args.output
                payload = _teardown.bucket_plan(args.bucket, args.expected_account_id, args.region, args.purpose, path)
            else:
                path = args.manifest if args.manifest.is_absolute() else root / args.manifest
                payload = _teardown.bucket_purge(path, args.sha256, args.bucket, args.expected_account_id, args.region,
                                                 args.acknowledge_backup, args.allow_backend_cleanup)
        except (OSError, _teardown.TeardownError) as error:
            return emit_command_error(args, str(error), EXIT_VALIDATION_FAILED)
    if getattr(args, "format", "human") == "json":
        emit_json(payload)
    else:
        draw_box("Finish Demo / Decommission", [payload["message"]])
        if action is None:
            for index, phase in enumerate(payload["phases"], 1):
                print_text(f"{index}. {phase}")
            print_text("Runbook: " + payload["docs"])
        else:
            draw_table(["Field", "Value"], [[key, str(value)] for key, value in payload.items() if key not in {"kind", "schema_version", "message"}])
    return EXIT_OK


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Dispatch snapshot list, show, or local restore operations."""

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
    """Initialize Terraform, select the environment workspace, and run plan."""

    cfg = load_config(root)
    if env_name not in cfg["environments"]:
        print(fail("Unknown environment: ") + env_name)
        return 1
    if generated_artifact_gaps(root, cfg):
        print(warn("Deployment files are missing or outdated. Generating them first."))
        rendered = run_render(root)
        if rendered != EXIT_OK:
            return rendered

    if not no_init:
        init_command = ["terraform", "-chdir=terraform", "init", "-input=false", "-no-color", "-backend-config=../dist/devsecops/backend.hcl"]
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
    """Adapt parsed plan arguments to the shared Terraform plan flow."""

    return run_plan(
        repo_root(),
        args.environment,
        no_init=args.no_init,
        create_workspace=args.create_workspace,
    )


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Plan or explicitly apply the separate remote-state bootstrap stack."""

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
    """Return human guidance for a control topic or the full catalog."""

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
    """Print security-control guidance for the requested topic."""

    draw_box(f"Explain: {args.topic}", explain_text(args.topic, load_config(repo_root())))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Dispatch grouped configuration read and write operations."""

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
        return emit_command_error(args, f"{CONFIG_FILE} does not exist. Run `devsecops setup`.", EXIT_VALIDATION_FAILED)
    output_format = getattr(args, "format", "toml")
    if output_format == "json":
        print(json.dumps(load_config(root), indent=2, sort_keys=True))
    else:
        print(path.read_text(encoding="utf-8"))
    return 0


# Interactive menu routing reuses command handlers rather than reimplementing
# operations, preserving the same validation and mutation boundaries as CLI use.
def menu_status(root: Path, cfg: dict[str, Any], checks: list[Check] | None = None) -> list[str]:
    """Build the compact project summary displayed by interactive menus."""

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
        "Readiness: " + progress_bar(breakdown_score),
    ]


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    else:
        print("\n" * 3)


def pause_for_menu() -> None:
    read_input("\n[Enter] Back to main menu")
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
    checks = collect_dashboard_checks(root, cfg, mode="compact")
    breakdown_score = overall_breakdown_score(checks)
    action = next_action(root, cfg, observations=checks, local_only=True)
    if any(check.name == "Demo dry-run" for check in checks):
        print_demo_status(cfg, checks, action)
        print()
        for key, label in MAIN_MENU_ITEMS:
            if key == "0" and all(check.status == "OK" for check in checks):
                print_text("[7] Configure production setup")
            if key == "0":
                print_text("[i] Readiness details")
            print_text(f"[{key}] {label}")
        return
    image_state = "set" if cfg["lambda_image_uri"] else "missing"
    backend_state = "set" if not cfg["backend"]["bucket"].startswith("replace-with") else "missing"
    health_state = "on" if cfg["enable_http_validation"] else "off"
    dast_state = "on" if cfg["enable_dast"] else "off"

    print(color("DevSecOps Pipeline Kit", Style.BOLD))
    print_text(f"{cfg['project_name']} | {cfg['aws_region']} | status {breakdown_score}%")
    print_text(f"image: {image_state} | backend: {backend_state} | health: {health_state} | DAST: {dast_state}")
    print()
    print_next_action(action)
    print()
    for key, label in MAIN_MENU_ITEMS:
        if key == "0":
            print_text("[i] Readiness details")
        print_text(f"[{key}] {label}")


def open_menu_section(title: str, handler: Any, *args: Any) -> None:
    clear_screen()
    draw_box(title, ["[Enter] returns to the main menu after this section."])
    print()
    handler(*args)
    pause_for_menu()


def menu_continue_setup(root: Path) -> None:
    """Resume the saved setup mode and stage directly from the main menu."""

    clear_screen()
    cmd_setup(argparse.Namespace(render=False, yes=False))
    pause_for_menu()


def show_production_deploy_command() -> None:
    draw_box(
        "Start Production Deployment",
        [
            "The CLI runs readiness checks, prevents overlapping production runs, and asks for confirmation.",
            "It then delegates deployment to the protected GitHub Actions environment.",
            "This menu does not execute it automatically.",
        ],
    )
    print("Preview first:")
    print(f"  {PRODUCTION_DEPLOY_COMMAND} --dry-run")
    print("Deploy command:")
    print(f"  {PRODUCTION_DEPLOY_COMMAND}")
    print("Docs: docs/first-successful-pipeline.md#7-run-the-production-workflow-dispatch")


def show_production_rollback_command() -> None:
    draw_box(
        "Roll Back Production Deployment",
        [
            "Cloud rollback can use the previous digest captured by a successful deployment.",
            "It uses the same protected GitHub environment, OIDC role, Terraform state, and validation steps.",
            "This is separate from `devsecops snapshot restore`, which changes local CLI-owned files only.",
        ],
    )
    print("Preview first:")
    print("  devsecops deploy rollback --dry-run")
    print("Rollback command:")
    print("  devsecops deploy rollback")


def menu_deploy_hub() -> None:
    """Present read-only deployment operations and copyable mutation commands."""

    clear_screen()
    draw_box(
        "Deploy",
        [
            "Check deployment status, start the protected workflow, or inspect the deployed service.",
            "Opening this section does not change GitHub or AWS.",
        ],
    )
    print()
    print_text("[1] Current deployment status")
    print_text("[2] Deploy production (review and confirmation required)")
    print_text("[3] Deployment logs")
    print_text("[4] Deployed AWS resources")
    print_text("[5] Validate production health endpoint")
    print_text("[6] Roll back production (review and confirmation required)")
    print_text("[7] Preview production deployment")
    print_text("[8] Preview production rollback")
    print_text("[9] Check production prerequisites")
    print_text("[10] Finish demo / cleanup guide")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    print()
    if choice == "1":
        cmd_deploy_status(argparse.Namespace(run_id=None, format="human", watch=False, interval=5))
    elif choice == "2":
        cmd_deploy_prod(argparse.Namespace(dry_run=False, yes=False, watch=False, interval=5))
    elif choice == "3":
        cmd_deploy_logs(argparse.Namespace(run_id=None, failed=False))
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
        cmd_deploy_rollback(argparse.Namespace(dry_run=False, yes=False, watch=False, interval=5, run_id=None, image_uri=None))
    elif choice == "7":
        cmd_deploy_prod(argparse.Namespace(dry_run=True, yes=False, watch=False, interval=5))
    elif choice == "8":
        cmd_deploy_rollback(argparse.Namespace(dry_run=True, yes=False, watch=False, interval=5, run_id=None, image_uri=None))
    elif choice == "9":
        cmd_status(argparse.Namespace(pre_deploy=True, strict=True, format="human"))
    elif choice == "10":
        cmd_teardown(argparse.Namespace(teardown_command=None, format="human"))
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_config_hub(root: Path) -> None:
    """Present local configuration and policy-composition operations."""

    clear_screen()
    draw_box("Configuration", ["Inspect, validate, and edit local source configuration."])
    print()
    print_text("[1] Project setup")
    print_text("[2] Show config")
    print_text("[3] Validate config")
    print_text("[4] Edit one setting")
    print_text("[5] Apply policy preset")
    print_text("[6] Compare config with canonical form")
    print_text("[7] Advanced control setup")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
    if choice in MENU_CANCEL_INPUTS:
        clear_screen()
        return
    if choice == "1":
        cmd_setup(argparse.Namespace(render=False, yes=False))
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
    cfg = load_config(root)
    checks = collect_dashboard_checks(root, cfg, mode="compact")
    if any(check.name == "Demo dry-run" for check in checks):
        print_demo_status(cfg, checks, next_action(root, cfg, observations=checks, local_only=True))
    else:
        print_readiness_details(root, checks=checks)
    pause_for_menu()


def menu_doctor_hub(root: Path) -> None:
    """Present scoped diagnostic commands without changing provider state."""

    clear_screen()
    draw_box("Diagnose Problems", ["Check local setup, integrations, deployments, or all areas together."])
    print()
    print_text("[1] Local setup")
    print_text("[2] Local setup with Terraform/AWS checks")
    print_text("[3] GitHub connection")
    print_text("[4] AWS connection and prod resources")
    print_text("[5] Recent deployment runs")
    print_text("[6] Main branch protection")
    print_text("[7] All checks (compact)")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
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
    """Present Terraform plan and backend-bootstrap entry points."""

    clear_screen()
    draw_box("Terraform", ["Plan environments or inspect backend bootstrap changes."])
    print()
    print_text("[1] Bootstrap backend plan")
    print_text("[2] Plan dev")
    print_text("[3] Plan staging")
    print_text("[4] Plan prod")
    print_text("[5] Custom plan")
    print_text("[6] Finish demo / cleanup guide")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
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
    elif choice == "6":
        cmd_teardown(argparse.Namespace(teardown_command=None, format="human"))
    else:
        print(warn("Unknown option."))
    pause_for_menu()


def menu_github_hub() -> None:
    """Present GitHub setup and read-only repository diagnostics."""

    clear_screen()
    draw_box("GitHub Connection", ["Prepare repository settings and inspect GitHub readiness."])
    print()
    print_text("[1] Repository setup commands")
    print_text("[2] Diagnose GitHub connection")
    print_text("[3] Recent workflow runs")
    print_text("[4] Main branch protection")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
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
    print_text("[1] Security controls")
    print_text("[2] Environment table")
    print_text("[3] Architecture")
    print_text("[4] Explain control")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
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
    """Present preview and generation paths for CLI-owned artifacts."""

    clear_screen()
    draw_box(
        "Deployment Files",
        [
            "Generate CLI-owned Terraform inputs and GitHub setup helpers from local config.",
            "Preview is read-only; generate creates a local snapshot before replacing managed files.",
        ],
    )
    print()
    print_text("[1] Preview generated file changes")
    print_text("[2] Generate deployment files")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
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
    """Present readiness, audit, and release-evidence report operations."""

    clear_screen()
    draw_box(
        "Reports and Release Evidence",
        ["Export readiness evidence or collect maintainer-focused release artifacts."],
    )
    print()
    print_text("[1] Export readiness report (Markdown)")
    print_text("[2] Export audit report (JSON)")
    print_text("[3] Collect release-candidate evidence")
    print_text("[4] Check stable-release criteria")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
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
    """Group lower-frequency provider, evidence, and recovery tools."""

    clear_screen()
    draw_box(
        "Advanced",
        ["Direct access to generated files, providers, evidence, controls, and recovery."],
    )
    print()
    print_text("[1] Deployment files")
    print_text("[2] Terraform")
    print_text("[3] GitHub connection")
    print_text("[4] Reports and release evidence")
    print_text("[5] Security and reference")
    print_text("[6] Snapshots / local rollback")
    print_text("[0] Back")
    choice = read_input("\nChoose: ").strip().lower()
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
    """Inspect and optionally restore local snapshots with confirmation."""

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
    print_text("[1] Preview rollback")
    print_text("[2] Roll back to this snapshot")
    print_text("[0] Back to main menu")
    action = read_input("\nChoose: ").strip()

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
        confirmation = read_input(f"\nRollback to {snapshot.get('id')}? Type yes to continue: ").strip().lower()
        if confirmation != "yes":
            print(info("Rollback cancelled."))
            pause_for_menu()
            return
        snapshot_before_change(root, "rollback", f"Before rolling back to {snapshot.get('id')}.")
        restore_snapshot(root, snapshot)
        print(ok("Rolled back to snapshot ") + str(snapshot.get("id")))
        pause_for_menu()


def cmd_menu(args: argparse.Namespace) -> int:
    """Run the interactive menu loop until the operator exits."""

    try:
        return run_menu_loop(repo_root())
    except EOFError:
        print_text(info("\nInput closed. Exiting menu."))
        return EXIT_OK


def run_menu_loop(root: Path) -> int:
    while True:
        clear_screen()
        print_main_menu(root)
        choice = read_input("\nChoose: ").strip().lower()
        if choice in {"1", "continue", "setup", "next"}:
            menu_continue_setup(root)
        elif choice in {"2", "status", "dashboard", "d"}:
            open_menu_section(
                "Status",
                cmd_status,
                argparse.Namespace(deep=False, strict=False, format="human", watch=False, interval=5),
            )
        elif choice in {"7", "production"}:
            open_menu_section("Configure Production Setup", cmd_setup,
                              argparse.Namespace(mode="production", render=False, yes=False))
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
    if command is None or command in {"menu", "setup", "status", "deploy", "next", "start", "dashboard", "tui", "completion"}:
        return False
    if command == "terraform" and getattr(args, "terraform_command", None) == "teardown":
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
    """Append the shared next action after eligible human-readable commands."""

    root = repo_root()
    print()
    print_next_action(next_action(root, load_config(root), local_only=True), title="Recommended Next Step")


def emit_command_error(args: argparse.Namespace, message: str, code: int) -> int:
    """Keep expected and boundary errors machine-readable when JSON is requested."""

    if getattr(args, "format", None) == "json":
        emit_json({"kind": "command-error", "schema_version": CONTRACT_SCHEMA_VERSION,
                   "command": getattr(args, "command", None), "error": message, "exit_code": code})
    else:
        print_text(fail(message))
    return code



def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run one handler, and translate boundary errors to exits.

    Expected domain failures are handled by command functions.  This final
    boundary keeps interrupts, corrupt local state, migration failures, and
    truly unexpected exceptions from leaking tracebacks in normal CLI use.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = int(args.func(args))
        if should_print_next_postlude(args):
            try:
                print_next_postlude()
            except (ConfigValidationError, ConfigMigrationError, SetupStateError, OSError, subprocess.SubprocessError):
                # Guidance must not undo a completed command or contact providers.
                print_text(warn("Next step unavailable. Run `devsecops setup` or `devsecops config validate` for details."))
        return result
    except KeyboardInterrupt:
        return emit_command_error(args, "Interrupted.", EXIT_INTERRUPTED)
    except EOFError:
        return emit_command_error(args, "Input closed. Command cancelled before completing interactive input.", EXIT_INTERRUPTED)
    except SetupStateError as exc:
        return emit_command_error(args, "Setup state error: " + str(exc), EXIT_VALIDATION_FAILED)
    except DeploymentStateError as exc:
        return emit_command_error(args, "Deployment state error: " + str(exc), EXIT_VALIDATION_FAILED)
    except ConfigMigrationError as exc:
        return emit_command_error(args, "Config migration error: " + str(exc), EXIT_VALIDATION_FAILED)
    except ConfigValidationError as exc:
        return emit_command_error(args, str(exc), EXIT_VALIDATION_FAILED)
    except subprocess.TimeoutExpired:
        return emit_command_error(args, "External check timed out. Check connectivity and retry the command.", EXIT_VALIDATION_FAILED)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        return emit_command_error(args, "Unexpected error: " + str(exc), EXIT_UNEXPECTED_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
