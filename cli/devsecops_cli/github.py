"""GitHub CLI adapter, repository diagnostics, and Actions parsers.

The adapter shells out to ``gh`` to preserve the user's existing authentication
and repository context.  It converts provider output into stable domain models
and never requests secret values: secret diagnostics inspect names only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .config import PIPELINE_CONFIG_VARIABLE, PROD_APPROVAL_ENVIRONMENT, pipeline_config_json, prod_approval_environment
from .deploy import DEPLOYMENT_WORKFLOW_NAME
from .images import is_immutable_image
from .models import ActionsStatus, Check
from .setup import iam_role_identity, is_iam_role_arn


# Repository variables are non-secret deployment inputs whose values can be
# compared with local configuration.  Secret contracts are name-only.
REQUIRED_GH_VARIABLES = [
    PIPELINE_CONFIG_VARIABLE,
    "PROJECT_NAME",
    "LAMBDA_IMAGE_URI",
    "API_AUTHORIZATION_TYPE",
    "ENABLE_SNYK_SCAN",
    "ENABLE_HTTP_VALIDATION",
    "ENABLE_DAST",
    "PROD_APPROVAL_ENVIRONMENT",
]
BASE_REQUIRED_GH_SECRETS = ["AWS_ROLE_TO_ASSUME_ARN"]
PLAN_ROLE_ENV_NAME = "AWS_PLAN_ROLE_TO_ASSUME_ARN"
DEPLOY_ROLE_ENV_NAME = "AWS_ROLE_TO_ASSUME_ARN"
SNYK_ENV_NAME = "SNYK_TOKEN"
DEFAULT_BRANCH = "main"
OIDC_WORKFLOW = "verify-oidc.yml"
SETUP_IN_PROGRESS_CONFIG = '{"setup_in_progress":true}'
REQUIRED_BRANCH_CHECKS = ["Security and Terraform Validate", "Terraform Format and Validate"]

RUNBOOKS_DIR = "docs/runbooks"
RUNBOOK_FAILED_PLAN = f"{RUNBOOKS_DIR}/failed-terraform-plan.md"
RUNBOOK_FAILED_APPLY = f"{RUNBOOKS_DIR}/failed-terraform-apply.md"
RUNBOOK_FAILED_VALIDATION = f"{RUNBOOKS_DIR}/failed-validation.md"
RUNBOOK_MISSING_IMAGE = f"{RUNBOOKS_DIR}/missing-image.md"
RUNBOOK_FAILED_ROLLBACK = f"{RUNBOOKS_DIR}/failed-rollback.md"


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run_command(command: list[str], root: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _gh_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return _run_command(["gh", *args], root, timeout=timeout)


def _gh_stream_command(root: Path, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Run an interactive-style ``gh`` command with inherited output streams."""

    return subprocess.run(  # nosec B603
        ["gh", *args],
        cwd=root,
        text=True,
        timeout=timeout,
        check=False,
    )


def compact_error(result: subprocess.CompletedProcess[str]) -> str:
    """Return the final provider-output line for a compact diagnostic."""

    output = (result.stderr or result.stdout or "").strip().splitlines()
    return output[-1] if output else f"Command exited with {result.returncode}."


def github_expected_variables(cfg: dict[str, Any]) -> dict[str, str]:
    """Map normalized local settings to their GitHub variable representation."""

    return {
        PIPELINE_CONFIG_VARIABLE: pipeline_config_json(cfg),
        "PROJECT_NAME": str(cfg["project_name"]),
        "LAMBDA_IMAGE_URI": str(cfg["lambda_image_uri"]),
        "API_AUTHORIZATION_TYPE": str(cfg["api_authorization_type"]),
        "ENABLE_SNYK_SCAN": str(cfg["enable_snyk_scan"]).lower(),
        "ENABLE_HTTP_VALIDATION": str(cfg["enable_http_validation"]).lower(),
        "ENABLE_DAST": str(cfg["enable_dast"]).lower(),
        "PROD_APPROVAL_ENVIRONMENT": prod_approval_environment(cfg),
    }


def required_github_secrets(cfg: dict[str, Any]) -> list[str]:
    """Return secret names required by the configured workflow features."""

    required = [*BASE_REQUIRED_GH_SECRETS, PLAN_ROLE_ENV_NAME]
    if cfg["enable_snyk_scan"]:
        required.append(SNYK_ENV_NAME)
    return required


def optional_github_secrets(cfg: dict[str, Any]) -> list[str]:
    """Return recognized secret names that are optional for this posture."""

    optional = ["AWS_REGION"]
    if not cfg["enable_snyk_scan"]:
        optional.append(SNYK_ENV_NAME)
    return optional


def parse_gh_items(stdout: str, value_key: str | None = None) -> dict[str, str]:
    """Parse ``gh`` list output into a name-to-value mapping.

    JSON is preferred, but the plain-table fallback supports older GitHub CLI
    output and test fixtures.  When ``value_key`` is absent, only item presence
    is retained—this is the path used for repository secrets.
    """

    if not stdout.strip():
        return {}
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError:
        return parse_gh_plain_table(stdout, value_key=value_key)
    items: dict[str, str] = {}
    if not isinstance(decoded, list):
        return items
    for entry in decoded:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        name = str(entry["name"])
        if value_key is None:
            items[name] = ""
        else:
            items[name] = str(entry.get(value_key, ""))
    return items


def parse_gh_plain_table(stdout: str, value_key: str | None = None) -> dict[str, str]:
    """Parse the stable first column of legacy ``gh`` table output."""

    items: dict[str, str] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or line.upper().startswith("NAME"):
            continue
        parts = line.split()
        name = parts[0]
        items[name] = " ".join(parts[1:]) if value_key is not None and len(parts) > 1 else ""
    return items


def github_variable_checks(cfg: dict[str, Any], variables: dict[str, str]) -> list[Check]:
    """Compare required repository variables with normalized local values."""

    checks: list[Check] = []
    expected = github_expected_variables(cfg)
    for name in REQUIRED_GH_VARIABLES:
        actual = variables.get(name)
        wanted = expected[name]
        if actual is None:
            checks.append(Check(f"GitHub variable {name}", "WARN", "Missing."))
        elif name == "LAMBDA_IMAGE_URI" and not wanted:
            checks.append(Check(f"GitHub variable {name}", "WARN", "Local config has no expected image URI."))
        elif name == PIPELINE_CONFIG_VARIABLE:
            try:
                remote_config = json.loads(actual)
                wanted_config = json.loads(wanted)
                matches = remote_config == wanted_config
                only_image_differs = isinstance(remote_config, dict) and (
                    {key: value for key, value in remote_config.items() if key != "lambda_image_uri"}
                    == {key: value for key, value in wanted_config.items() if key != "lambda_image_uri"}
                )
            except (json.JSONDecodeError, TypeError):
                matches = False
                only_image_differs = False
            checks.append(Check(
                f"GitHub variable {name}", "OK" if matches else "WARN",
                "Matches local Terraform settings." if matches else
                "Only lambda_image_uri differs from local settings; an exact-image dispatch can override it." if only_image_differs else
                "Expected current local settings. Run `devsecops github setup --apply` to synchronize configuration.",
            ))
        elif actual != wanted:
            checks.append(Check(f"GitHub variable {name}", "WARN", f"Expected `{wanted}`, found `{actual}`."))
        elif name == "LAMBDA_IMAGE_URI" and not is_immutable_image(actual):
            checks.append(Check(f"GitHub variable {name}", "FAIL", "Value is not immutable."))
        else:
            checks.append(Check(f"GitHub variable {name}", "OK", actual or "Configured."))
    return checks


def github_secret_checks(
    cfg: dict[str, Any], secrets: dict[str, str], production_secrets: dict[str, str] | None = None,
) -> list[Check]:
    """Report required and optional secrets by name without exposing values."""

    checks: list[Check] = []
    production_secrets = production_secrets or {}
    for name in required_github_secrets(cfg):
        scope = "prod environment" if name != PLAN_ROLE_ENV_NAME and name in production_secrets else "repository"
        present = name in (production_secrets if scope == "prod environment" else secrets)
        checks.append(
            Check(
                f"GitHub secret {name}",
                "OK" if present else "WARN",
                f"Present in {scope}; value and runtime access require verification." if present else f"Missing from {scope}.",
            )
        )
    for name in optional_github_secrets(cfg):
        present = name in secrets or (name == SNYK_ENV_NAME and name in production_secrets)
        checks.append(
            Check(
                f"GitHub secret {name}",
                "OK" if present else "INFO",
                "Present; optional for this configuration." if present else "Optional.",
                scored=False,
            )
        )
    return checks


def role_argument_checks(args: Any) -> list[Check]:
    values = [getattr(args, "deploy_role_arn", None), getattr(args, "plan_role_arn", None)]
    checks = []
    for label, value in zip(("Deploy", "Plan"), values):
        status = "FAIL" if value and not is_iam_role_arn(value) else "OK" if value else "INFO"
        checks.append(Check(f"{label} role ARN argument", status,
                            "Valid IAM role ARN." if status == "OK" else "Pass a valid IAM role ARN." if value
                            else "Retain the existing secret if present.", scored=bool(value)))
    if any(values):
        distinct = all(value and is_iam_role_arn(value) for value in values) and iam_role_identity(values[0]) != iam_role_identity(values[1])
        checks.append(Check("Separate IAM roles", "OK" if distinct else "FAIL",
                            "Two different role ARNs supplied." if distinct else "Supply both role ARNs and use different plan and deploy roles."))
    return checks


def github_secret_inventory(
    root: Path, repository: str, *, gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> tuple[dict[str, str], dict[str, str]]:
    """Read version metadata for the two secret scopes used by the workflow."""

    inventories = []
    for scope in ([], ["--env", PROD_APPROVAL_ENVIRONMENT]):
        try:
            result = gh_command_fn(root, ["secret", "list", "--repo", repository, *scope, "--json", "name,updatedAt"])
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("Cannot inspect GitHub secret metadata. Retry after restoring GitHub access.") from None
        if result.returncode != 0:
            where = "prod environment" if scope else "repository"
            raise ValueError(f"Cannot inspect {where} secrets. Verify access and create the prod environment before setup.")
        try:
            entries = json.loads(result.stdout)
        except ValueError:
            entries = None
        if not isinstance(entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("name"), str) for entry in entries):
            raise ValueError("GitHub returned invalid secret metadata.")
        inventories.append({entry["name"]: str(entry.get("updatedAt") or "") for entry in entries})
    return inventories[0], inventories[1]


def oidc_verification_check(
    root: Path, repository: str, secrets: dict[str, str], production_secrets: dict[str, str], *,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> Check:
    name = "GitHub OIDC roles"
    guidance = f"Run {OIDC_WORKFLOW} from main to verify plan and prod roles separately."
    result = gh_command_fn(root, [
        "run", "list", "--repo", repository, "--workflow", OIDC_WORKFLOW, "--branch", DEFAULT_BRANCH,
        "--event", "workflow_dispatch", "--limit", "1", "--json", "databaseId,headSha,status,conclusion,createdAt",
    ])
    runs = parse_gh_runs(result.stdout) if result.returncode == 0 else []
    if not runs:
        return Check(name, "WARN", guidance)
    run = runs[0]
    ref = gh_command_fn(root, ["api", f"repos/{repository}/git/ref/heads/{DEFAULT_BRANCH}", "--jq", ".object.sha"])
    if ref.returncode != 0 or not re.fullmatch(r"[a-f0-9]{40}", ref.stdout.strip()) or run.get("headSha") != ref.stdout.strip():
        return Check(name, "WARN", "OIDC verification does not match current main. " + guidance)
    try:
        created = dt.datetime.fromisoformat(str(run["createdAt"]).replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("Missing verification timestamp timezone")
        for value in (
            secrets.get(PLAN_ROLE_ENV_NAME, ""),
            production_secrets.get(DEPLOY_ROLE_ENV_NAME, secrets.get(DEPLOY_ROLE_ENV_NAME, "")),
        ):
            if dt.datetime.fromisoformat(value.replace("Z", "+00:00")) > created:
                return Check(name, "WARN", "Role secrets changed after OIDC verification. " + guidance)
    except (ValueError, KeyError, TypeError):
        return Check(name, "WARN", "Cannot verify the role secret revision. " + guidance)
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return Check(name, "WARN", "The latest OIDC verification is incomplete or failed. " + guidance)
    identifier = str(run.get("databaseId") or "")
    if not identifier.isdecimal():
        return Check(name, "WARN", guidance)
    result = gh_command_fn(root, ["run", "view", identifier, "--repo", repository, "--json", "jobs"])
    jobs = parse_json_object(result.stdout).get("jobs") if result.returncode == 0 else None
    if not isinstance(jobs, list):
        return Check(name, "WARN", guidance)
    for role in ("plan", "deploy"):
        matches = [job for job in jobs if isinstance(job, dict) and job.get("name") == f"Verify {role} OIDC role"]
        if len(matches) != 1 or matches[0].get("status") != "completed" or matches[0].get("conclusion") != "success":
            return Check(name, "WARN", guidance)
        observations = matches[0].get("steps")
        if not isinstance(observations, list):
            return Check(name, "WARN", guidance)
        steps = {step.get("name"): step.get("conclusion") for step in observations if isinstance(step, dict)}
        if steps.get(f"Validate {role} role settings") != "success" or steps.get(f"Verify assumed {role} identity") != "success":
            return Check(name, "WARN", guidance)
    return Check(name, "OK", f"Run {identifier} verified separate plan and prod roles on current main with current role secrets.")


def parse_json_object(stdout: str) -> dict[str, Any]:
    """Return a decoded JSON object, or an empty mapping for invalid shapes."""

    if not stdout.strip():
        return {}
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def required_status_check_names(protection: dict[str, Any]) -> set[str]:
    """Normalize both GitHub branch-protection status-check response shapes.

    GitHub may expose legacy string ``contexts`` and newer app-aware ``checks``;
    combining them keeps diagnostics compatible across repository settings.
    """

    status_checks = protection.get("required_status_checks")
    if not isinstance(status_checks, dict):
        return set()
    names = set()
    contexts = status_checks.get("contexts", [])
    if isinstance(contexts, list):
        names.update(str(context) for context in contexts)
    checks = status_checks.get("checks", [])
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and check.get("context"):
                names.add(str(check["context"]))
    return names


def branch_protection_checks(
    branch: str,
    protected: bool | None,
    protection: dict[str, Any] | None,
    required_checks: list[str] | None = None,
) -> list[Check]:
    """Evaluate branch protection, pull-request review, and CI check policy."""

    required_checks = required_checks or REQUIRED_BRANCH_CHECKS
    checks: list[Check] = []
    if protected is True:
        checks.append(Check(f"Branch `{branch}` protection", "OK", "Enabled."))
    elif protected is False:
        checks.append(Check(f"Branch `{branch}` protection", "WARN", "Branch is not protected."))
    else:
        checks.append(Check(f"Branch `{branch}` protection", "WARN", "Could not inspect branch protection."))

    if not protection:
        checks.append(Check("Pull request requirement", "WARN", "Could not inspect protection rules."))
        for required in required_checks:
            checks.append(Check(f"Required check `{required}`", "WARN", "Could not inspect status checks."))
        return checks

    pr_reviews = protection.get("required_pull_request_reviews")
    checks.append(
        Check(
            "Pull request requirement",
            "OK" if isinstance(pr_reviews, dict) else "WARN",
            "Pull request reviews are required." if isinstance(pr_reviews, dict) else "Pull request reviews are not required.",
        )
    )

    status_names = required_status_check_names(protection)
    checks.append(
        Check(
            "Required status checks",
            "OK" if status_names else "WARN",
            ", ".join(sorted(status_names)) if status_names else "No required status checks configured.",
        )
    )
    for required in required_checks:
        checks.append(
            Check(
                f"Required check `{required}`",
                "OK" if required in status_names else "WARN",
                "Configured." if required in status_names else "Missing from branch protection.",
            )
        )
    return checks


def parse_gh_runs(stdout: str) -> list[dict[str, Any]]:
    """Parse a JSON run list while discarding malformed entries."""

    if not stdout.strip():
        return []
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [entry for entry in decoded if isinstance(entry, dict)]


def list_workflow_runs(
    root: Path,
    args: list[str],
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> tuple[list[dict[str, Any]], str | None]:
    """Run a pre-built ``gh run list`` query and normalize its JSON output."""

    if not command_exists_fn("gh"):
        return [], "`gh` not found on PATH."
    result = gh_command_fn(root, args)
    if result.returncode != 0:
        return [], compact_error(result)
    try:
        runs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        runs = None
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        return [], "Could not parse `gh run list` output."
    return runs, None


def view_workflow_run(
    root: Path,
    args: list[str],
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> tuple[dict[str, Any], str | None]:
    """Read one Actions run without allowing an interactive ``gh`` prompt."""

    if not command_exists_fn("gh"):
        return {}, "`gh` not found on PATH."
    result = gh_command_fn(root, args)
    if result.returncode != 0:
        return {}, compact_error(result)
    payload = parse_json_object(result.stdout)
    if not payload:
        return {}, "Could not parse `gh run view` output."
    return payload, None


def dispatch_workflow(
    root: Path,
    args: list[str],
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> subprocess.CompletedProcess[str]:
    """Dispatch a pre-built workflow command with a conventional missing-tool result."""

    if not command_exists_fn("gh"):
        return subprocess.CompletedProcess(["gh", *args], 127, "", "`gh` not found on PATH.")
    return gh_command_fn(root, args)


def read_workflow_logs(
    root: Path,
    args: list[str],
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_stream_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_stream_command,
) -> subprocess.CompletedProcess[str]:
    """Stream workflow logs without buffering potentially large output."""

    if not command_exists_fn("gh"):
        return subprocess.CompletedProcess(["gh", *args], 127, "", "`gh` not found on PATH.")
    return gh_stream_command_fn(root, args, timeout=300)


def watch_workflow_run(
    root: Path,
    args: list[str],
    *,
    stream: bool = True,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
    gh_stream_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_stream_command,
) -> subprocess.CompletedProcess[str]:
    """Watch a workflow run, optionally streaming progress directly to the user."""

    if not command_exists_fn("gh"):
        return subprocess.CompletedProcess(["gh", *args], 127, "", "`gh` not found on PATH.")
    if stream:
        return gh_stream_command_fn(root, args, timeout=3600)
    return gh_command_fn(root, args, timeout=3600)


def actions_run_rows(runs: list[dict[str, Any]]) -> list[list[str]]:
    """Project workflow-run dictionaries into presentation rows."""

    rows: list[list[str]] = []
    for run in runs:
        rows.append(
            [
                str(run.get("workflowName", "")),
                str(run.get("headBranch", "")),
                str(run.get("status", "")),
                str(run.get("conclusion") or ""),
                str(run.get("createdAt", "")),
            ]
        )
    return rows


def failed_job_rows(workflow_name: str, stdout: str) -> list[list[str]]:
    """Extract unsuccessful jobs from a ``gh run view --json jobs`` payload."""

    payload = parse_json_object(stdout)
    jobs = payload.get("jobs", [])
    rows: list[list[str]] = []
    if not isinstance(jobs, list):
        return rows
    for job in jobs:
        if not isinstance(job, dict):
            continue
        conclusion = str(job.get("conclusion") or "")
        if conclusion and conclusion not in {"success", "skipped"}:
            rows.append(
                [
                    workflow_name,
                    str(job.get("name", "")),
                    str(job.get("status", "")),
                    conclusion,
                ]
            )
    return rows


def runbook_for_failure(workflow_name: str, job_name: str, step_name: str, conclusion: str = "") -> str:
    """Select the most specific troubleshooting runbook for a failed location.

    The failed step takes precedence over broad job and workflow titles.
    Rollback steps can mention failed validation and must still select rollback.
    """

    # Prefer the failed step; broad job names contain both deploy and rollback.
    text = (step_name or job_name or workflow_name).lower()
    if "rollback" in text or "roll back" in text:
        return RUNBOOK_FAILED_ROLLBACK
    if any(marker in text for marker in ["health", "smoke", "dast", "zap", "validate", "fmt", "trivy"]):
        return RUNBOOK_FAILED_VALIDATION
    if "require lambda image" in text or "lambda_image_uri" in text or "image uri" in text or "snyk" in text:
        return RUNBOOK_MISSING_IMAGE
    if "apply" in text or "deploy" in text:
        return RUNBOOK_FAILED_APPLY
    if "ecr image" in text or "image" in text:
        return RUNBOOK_MISSING_IMAGE
    if "plan" in text:
        return RUNBOOK_FAILED_PLAN
    return "docs/troubleshooting.md#actions-status-cannot-show-workflow-runs"


def failed_step_rows(workflow_name: str, stdout: str) -> list[list[str]]:
    """Extract failed steps and attach a runbook to each actionable row."""

    payload = parse_json_object(stdout)
    jobs = payload.get("jobs", [])
    rows: list[list[str]] = []
    if not isinstance(jobs, list):
        return rows
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_name = str(job.get("name", ""))
        job_conclusion = str(job.get("conclusion") or "")
        if not job_conclusion or job_conclusion in {"success", "skipped"}:
            continue
        steps = job.get("steps", [])
        added_step = False
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_conclusion = str(step.get("conclusion") or "")
                if step_conclusion and step_conclusion not in {"success", "skipped"}:
                    step_name = str(step.get("name", ""))
                    runbook = runbook_for_failure(workflow_name, job_name, step_name, step_conclusion)
                    rows.append([workflow_name, job_name, step_name, step_conclusion, runbook])
                    added_step = True
        if not added_step:
            # Jobs can fail before GitHub reports step details (for example,
            # environment approval or runner startup failures).
            runbook = runbook_for_failure(workflow_name, job_name, "", job_conclusion)
            rows.append([workflow_name, job_name, "(job failed before step details)", job_conclusion, runbook])
    return rows


def actions_next_actions(run: dict[str, Any], failed_steps: list[list[str]]) -> list[str]:
    """Turn failed-step rows into copyable commands and runbook guidance."""

    run_id = str(run.get("databaseId") or "")
    run_url = str(run.get("url") or "")
    workflow_name = str(run.get("workflowName") or "")
    if workflow_name == DEPLOYMENT_WORKFLOW_NAME:
        log_command = (
            f"devsecops deploy logs --run-id {run_id} --failed"
            if run_id
            else "devsecops deploy logs --run-id <run-id> --failed"
        )
    else:
        log_command = f"gh run view {run_id} --log-failed" if run_id else "gh run view <run-id> --log-failed"
    actions = []
    for workflow, job, step, conclusion, runbook in failed_steps:
        location = f"{workflow} / {job}"
        if step and not step.startswith("("):
            location += f" / {step}"
        suffix = f" Open {run_url}" if run_url else ""
        actions.append(f"{location} ended with {conclusion}. Run `{log_command}` and follow `{runbook}`.{suffix}")
    return actions



def collect_github_checks(
    root: Path,
    cfg: dict[str, Any],
    *,
    repository: str = "",
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> list[Check]:
    """Inspect CLI availability, authentication, repository, variables, and secrets.

    Authentication failure short-circuits repository API calls to avoid
    repeating the same credential error for every downstream check.
    """

    checks: list[Check] = []
    if not command_exists_fn("gh"):
        return [
            Check("GitHub CLI", "WARN", "`gh` not found on PATH."),
            Check("GitHub auth", "WARN", "Install `gh` and run `gh auth login`."),
            Check("GitHub repository", "WARN", "Cannot inspect repository without `gh`."),
        ]

    checks.append(Check("GitHub CLI", "OK", "Installed."))

    auth = gh_command_fn(root, ["auth", "status"])
    if auth.returncode != 0:
        checks.append(Check("GitHub auth", "WARN", compact_error(auth)))
        return checks
    checks.append(Check("GitHub auth", "OK", "Authenticated."))

    repo = gh_command_fn(root, ["repo", "view", *([repository] if repository else []), "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if repo.returncode != 0 or not repo.stdout.strip():
        checks.append(Check("GitHub repository", "WARN", compact_error(repo)))
        return checks
    else:
        repository = repo.stdout.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            return [*checks, Check("GitHub repository", "FAIL", "GitHub did not identify an owner/repository.")]
        checks.append(Check("GitHub repository", "OK", repository))

    variables_result = gh_command_fn(root, ["variable", "list", "--repo", repository, "--json", "name,value"])
    if variables_result.returncode != 0:
        checks.append(Check("GitHub variables", "WARN", compact_error(variables_result)))
    else:
        checks.extend(github_variable_checks(cfg, parse_gh_items(variables_result.stdout, value_key="value")))

    try:
        secrets, production_secrets = github_secret_inventory(root, repository, gh_command_fn=gh_command_fn)
    except ValueError as exc:
        checks.append(Check("GitHub secrets", "WARN", str(exc)))
    else:
        checks.extend(github_secret_checks(cfg, secrets, production_secrets))
        try:
            verification = oidc_verification_check(root, repository, secrets, production_secrets, gh_command_fn=gh_command_fn)
        except (OSError, subprocess.TimeoutExpired):
            verification = Check("GitHub OIDC roles", "WARN", "Cannot inspect OIDC verification. Retry after restoring GitHub access.")
        checks.append(verification)

    if cfg["use_prod_approval_environment"]:
        checks.append(production_environment_check(root, repository, gh_command_fn=gh_command_fn))

    return checks


def production_environment_check(
    root: Path,
    repository: str,
    *,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> Check:
    """Verify the GitHub protections that back the production OIDC trust."""

    name = "GitHub environment approvals"
    settings = f"Settings > Environments > {PROD_APPROVAL_ENVIRONMENT}"
    if not repository:
        return Check(name, "FAIL", "Cannot verify production environment protection without repository access.")

    endpoint = f"repos/{repository}/environments/{PROD_APPROVAL_ENVIRONMENT}"
    result = gh_command_fn(root, ["api", endpoint])
    if result.returncode != 0:
        return Check(name, "FAIL", f"Cannot read {settings}: {compact_error(result)}")

    environment = parse_json_object(result.stdout)
    rules = environment.get("protection_rules")
    reviewer_rule = {}
    if isinstance(rules, list):
        reviewer_rule = next(
            (rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers"), {}
        )
    reviewers = reviewer_rule.get("reviewers")
    if not isinstance(reviewers, list) or not any(isinstance(entry, dict) and entry.get("reviewer") for entry in reviewers):
        return Check(name, "FAIL", f"Add a required reviewer in {settings}.")
    if reviewer_rule.get("prevent_self_review") is not True:
        return Check(name, "FAIL", f"Enable Prevent self-review in {settings}.")
    if environment.get("can_admins_bypass") is not False:
        return Check(name, "FAIL", f"Verify that Allow administrators to bypass configured protection rules is disabled in {settings}.")

    branch_detail = f"Allow only the exact {DEFAULT_BRANCH} branch and no tags in {settings}."
    branch_policy = environment.get("deployment_branch_policy")
    if not isinstance(branch_policy, dict) or branch_policy.get("custom_branch_policies") is not True:
        return Check(name, "FAIL", branch_detail)

    result = gh_command_fn(root, ["api", f"{endpoint}/deployment-branch-policies"])
    if result.returncode != 0:
        return Check(name, "FAIL", f"Cannot verify production deployment branches: {compact_error(result)}")
    payload = parse_json_object(result.stdout)
    policies = payload.get("branch_policies")
    if payload.get("total_count") != 1 or not isinstance(policies, list) or len(policies) != 1:
        return Check(name, "FAIL", branch_detail)
    rule = policies[0]
    if not isinstance(rule, dict) or rule.get("name") != DEFAULT_BRANCH or rule.get("type") != "branch":
        return Check(name, "FAIL", branch_detail)
    return Check(name, "OK", f"Production requires an independent reviewer, disables admin bypass, and allows only the {DEFAULT_BRANCH} branch.")


def collect_branch_checks(
    root: Path,
    branch: str = DEFAULT_BRANCH,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> list[Check]:
    """Inspect required protection settings for the deployment branch."""

    if not command_exists_fn("gh"):
        return [
            Check("GitHub CLI", "WARN", "`gh` not found on PATH."),
            Check(f"Branch `{branch}` protection", "WARN", "Cannot inspect branch protection without `gh`."),
        ]

    auth = gh_command_fn(root, ["auth", "status"])
    if auth.returncode != 0:
        return [
            Check("GitHub auth", "WARN", compact_error(auth)),
            Check(f"Branch `{branch}` protection", "WARN", "Cannot inspect branch protection without GitHub auth."),
        ]

    repo = gh_command_fn(root, ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if repo.returncode != 0 or not repo.stdout.strip():
        return [
            Check("GitHub repository", "WARN", compact_error(repo)),
            Check(f"Branch `{branch}` protection", "WARN", "Cannot inspect branch protection without repo context."),
        ]

    repo_name = repo.stdout.strip()
    checks = [
        Check("GitHub CLI", "OK", "Installed."),
        Check("GitHub auth", "OK", "Authenticated."),
        Check("GitHub repository", "OK", repo_name),
    ]

    branch_result = gh_command_fn(root, ["api", f"repos/{repo_name}/branches/{branch}"])
    if branch_result.returncode != 0:
        checks.append(Check(f"Branch `{branch}`", "WARN", compact_error(branch_result)))
        checks.extend(branch_protection_checks(branch, None, None))
        return checks

    branch_payload = parse_json_object(branch_result.stdout)
    protected_value = branch_payload.get("protected")
    protected = protected_value if isinstance(protected_value, bool) else None

    protection_result = gh_command_fn(root, ["api", f"repos/{repo_name}/branches/{branch}/protection"])
    protection_payload: dict[str, Any] | None
    if protection_result.returncode == 0:
        protection_payload = parse_json_object(protection_result.stdout)
    else:
        protection_payload = None
        checks.append(Check("Protection details", "WARN", compact_error(protection_result)))

    checks.extend(branch_protection_checks(branch, protected, protection_payload))
    return checks


def github_status_rows(
    root: Path,
    limit: int = 5,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> tuple[list[list[str]], str | None]:
    """Return recent Actions runs as rows plus a non-throwing provider error."""

    if not command_exists_fn("gh"):
        return [], "`gh` not found on PATH."
    result = gh_command_fn(
        root,
        [
            "run",
            "list",
            "--limit",
            str(limit),
            "--json",
            "databaseId,workflowName,headBranch,status,conclusion,createdAt,url",
        ],
    )
    if result.returncode != 0:
        return [], compact_error(result)
    runs = parse_gh_runs(result.stdout)
    if not runs and result.stdout.strip():
        return [], "Could not parse `gh run list` output."
    return actions_run_rows(runs), None


def collect_github_actions_status(
    root: Path,
    limit: int = 8,
    failed_jobs_limit: int = 3,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> ActionsStatus:
    """Collect recent runs and bounded failure details with remediation steps.

    Only the first ``failed_jobs_limit`` failed runs receive additional API
    calls, keeping dashboard refreshes responsive on repositories with a long
    failure history.
    """

    if not command_exists_fn("gh"):
        return ActionsStatus([], [], [], [], "`gh` not found on PATH.")
    result = gh_command_fn(
        root,
        [
            "run",
            "list",
            "--limit",
            str(limit),
            "--json",
            "databaseId,workflowName,headBranch,status,conclusion,createdAt,url",
        ],
    )
    if result.returncode != 0:
        return ActionsStatus([], [], [], [], compact_error(result))
    runs = parse_gh_runs(result.stdout)
    if not runs and result.stdout.strip():
        return ActionsStatus([], [], [], [], "Could not parse `gh run list` output.")

    failed_rows: list[list[str]] = []
    failed_step_rows_result: list[list[str]] = []
    next_actions_result: list[str] = []
    failed_runs = [run for run in runs if str(run.get("conclusion") or "") == "failure"]
    for run in failed_runs[:failed_jobs_limit]:
        run_id = run.get("databaseId")
        if not run_id:
            continue
        job_result = gh_command_fn(root, ["run", "view", str(run_id), "--json", "jobs"])
        if job_result.returncode != 0:
            workflow_name = str(run.get("workflowName", ""))
            failed_rows.append([workflow_name, "(jobs)", "unknown", compact_error(job_result)])
            run_id_text = str(run_id)
            run_url = str(run.get("url") or "")
            log_command = (
                f"devsecops deploy logs --run-id {run_id_text} --failed"
                if workflow_name == DEPLOYMENT_WORKFLOW_NAME
                else f"gh run view {run_id_text} --log-failed"
            )
            next_actions_result.append(
                f"Could not inspect failed jobs for run {run_id_text}. Run `{log_command}` "
                f"and see `docs/troubleshooting.md#actions-status-cannot-show-workflow-runs`."
                + (f" Open {run_url}" if run_url else "")
            )
            failed_step_rows_result.append(
                [
                    workflow_name,
                    "(jobs)",
                    "(could not inspect failed steps)",
                    "unknown",
                    "docs/troubleshooting.md#actions-status-cannot-show-workflow-runs",
                ]
            )
            continue
        workflow_name = str(run.get("workflowName", ""))
        failed_rows.extend(failed_job_rows(workflow_name, job_result.stdout))
        run_failed_steps = failed_step_rows(workflow_name, job_result.stdout)
        failed_step_rows_result.extend(run_failed_steps)
        next_actions_result.extend(actions_next_actions(run, run_failed_steps))
    return ActionsStatus(actions_run_rows(runs), failed_rows, failed_step_rows_result, next_actions_result)


def github_actions_status(
    root: Path,
    limit: int = 8,
    failed_jobs_limit: int = 3,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> tuple[list[list[str]], list[list[str]], str | None]:
    """Return the legacy tuple view of the richer Actions status model."""

    status = collect_github_actions_status(
        root,
        limit=limit,
        failed_jobs_limit=failed_jobs_limit,
        command_exists_fn=command_exists_fn,
        gh_command_fn=gh_command_fn,
    )
    return status.runs, status.failed_jobs, status.error



def github_setup_precheck(
    root: Path,
    cfg: dict[str, Any],
    args: Any,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    gh_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _gh_command,
) -> list[Check]:
    """Validate local prerequisites and arguments before repository mutation.

    This function performs read-only GitHub inspection.  Applying variables or
    secrets remains the responsibility of the explicitly authorized command.
    """

    checks = role_argument_checks(args)
    if any(check.status == "FAIL" for check in checks):
        return checks
    repository = str(getattr(args, "repo", None) or "")
    if repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return [*checks, Check("GitHub repository", "FAIL", "Use --repo OWNER/REPO.")]
    gh_available = command_exists_fn("gh")
    checks.append(Check("GitHub CLI", "OK" if gh_available else "WARN", "Installed." if gh_available else "`gh` not found on PATH."))
    if gh_available:
        auth = gh_command_fn(root, ["auth", "status"])
        checks.append(Check("GitHub auth", "OK" if auth.returncode == 0 else "WARN", "Authenticated." if auth.returncode == 0 else compact_error(auth)))
        if auth.returncode == 0:
            repo = gh_command_fn(root, ["repo", "view", *([repository] if repository else []), "--json", "nameWithOwner", "-q", ".nameWithOwner"])
            checks.append(
                Check(
                    "GitHub repository",
                    "OK" if repo.returncode == 0 and repo.stdout.strip() else "WARN",
                    repo.stdout.strip() if repo.returncode == 0 and repo.stdout.strip() else compact_error(repo),
                )
            )
    if cfg["enable_snyk_scan"]:
        checks.append(
            Check(
                "Snyk token argument",
                "OK" if bool(getattr(args, "snyk_token", None)) else "INFO",
                "Provided." if getattr(args, "snyk_token", None) else "Retain the existing SNYK_TOKEN if present.",
                scored=bool(getattr(args, "snyk_token", None)),
            )
        )
    else:
        checks.append(Check("Snyk token argument", "INFO", "Optional because enable_snyk_scan is false.", scored=False))
    return checks



__all__ = [
    "DEFAULT_BRANCH",
    "DEPLOY_ROLE_ENV_NAME",
    "PLAN_ROLE_ENV_NAME",
    "REQUIRED_BRANCH_CHECKS",
    "RUNBOOK_FAILED_APPLY",
    "RUNBOOK_FAILED_PLAN",
    "RUNBOOK_FAILED_ROLLBACK",
    "RUNBOOK_FAILED_VALIDATION",
    "RUNBOOK_MISSING_IMAGE",
    "SNYK_ENV_NAME",
    "actions_next_actions",
    "actions_run_rows",
    "branch_protection_checks",
    "collect_branch_checks",
    "collect_github_actions_status",
    "collect_github_checks",
    "failed_job_rows",
    "failed_step_rows",
    "dispatch_workflow",
    "github_actions_status",
    "github_expected_variables",
    "github_secret_checks",
    "github_setup_precheck",
    "github_status_rows",
    "github_variable_checks",
    "list_workflow_runs",
    "optional_github_secrets",
    "parse_gh_items",
    "parse_gh_plain_table",
    "parse_gh_runs",
    "parse_json_object",
    "read_workflow_logs",
    "required_github_secrets",
    "required_status_check_names",
    "runbook_for_failure",
    "view_workflow_run",
    "watch_workflow_run",
]
