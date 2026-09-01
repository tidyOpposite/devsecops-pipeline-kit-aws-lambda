"""Deployment journey contracts and local, non-secret run metadata.

Provider calls remain in the GitHub and AWS adapters.  This module owns the
stable command vocabulary, workflow arguments, run selection, and the small
local journal that lets ``deploy status``, ``deploy logs``, and
``deploy rollback`` refer to the same workflow run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from .paths import DEPLOYMENT_STATE_FILE


DEPLOYMENT_STATE_SCHEMA_VERSION = 1
DEPLOYMENT_STATE_HISTORY_LIMIT = 50
DEPLOYMENT_WORKFLOW = "deploy.yml"
DEPLOYMENT_WORKFLOW_PATH = ".github/workflows/deploy.yml"
DEPLOYMENT_WORKFLOW_NAME = "Secure Serverless DevSecOps Pipeline"
DEPLOYMENT_REF = "main"
DEPLOYMENT_ENVIRONMENT = "prod"
DEPLOYMENT_RUN_JSON_FIELDS = (
    "databaseId,workflowName,displayTitle,event,headBranch,headSha,status,"
    "conclusion,createdAt,updatedAt,url,jobs"
)
DEPLOYMENT_LIST_JSON_FIELDS = (
    "databaseId,workflowName,displayTitle,event,headBranch,headSha,status,"
    "conclusion,createdAt,updatedAt,url"
)
ACTIVE_RUN_STATUSES = frozenset({"queued", "in_progress", "requested", "waiting", "pending"})
DEPLOYMENT_OPERATIONS = frozenset({"deploy", "rollback"})
_RUN_URL_RE = re.compile(r"https://github\.com/[^\s/]+/[^\s/]+/actions/runs/(?P<run_id>\d+)")


class DeploymentStateError(ValueError):
    """Raised when the local deployment journal cannot be trusted."""


def utc_now() -> str:
    """Return a stable, second-precision UTC timestamp for journal records."""

    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_deployment_state() -> dict[str, Any]:
    """Build a fresh deployment-journal envelope for the current schema."""

    return {"schema_version": DEPLOYMENT_STATE_SCHEMA_VERSION, "deployments": []}


def deployment_state_path(root: Path) -> Path:
    """Return the project-local path of the non-secret deployment journal."""

    return root / DEPLOYMENT_STATE_FILE


def _clean_record(record: dict[str, Any]) -> dict[str, str]:
    """Keep only the documented, non-secret deployment metadata fields."""

    operation = str(record.get("operation") or "")
    if operation not in DEPLOYMENT_OPERATIONS:
        raise DeploymentStateError(f"Unknown deployment operation `{operation or '(missing)'}`.")
    cleaned = {
        "operation": operation,
        "environment": str(record.get("environment") or DEPLOYMENT_ENVIRONMENT),
        "ref": str(record.get("ref") or DEPLOYMENT_REF),
        "requested_image_uri": str(record.get("requested_image_uri") or ""),
        "previous_image_uri": str(record.get("previous_image_uri") or ""),
        "source_run_id": str(record.get("source_run_id") or ""),
        "run_id": str(record.get("run_id") or ""),
        "run_url": str(record.get("run_url") or ""),
        "dispatched_at": str(record.get("dispatched_at") or utc_now()),
    }
    return cleaned


def load_deployment_state(root: Path) -> dict[str, Any]:
    """Load, validate, and sanitize the deployment journal.

    Corrupt or unsupported state is rejected instead of guessed because an
    incorrect previous image could lead an operator to the wrong rollback.
    """

    path = deployment_state_path(root)
    if not path.exists():
        return empty_deployment_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentStateError(f"Could not read {DEPLOYMENT_STATE_FILE}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DeploymentStateError(f"{DEPLOYMENT_STATE_FILE} must contain a JSON object.")
    schema_version = payload.get("schema_version")
    if schema_version != DEPLOYMENT_STATE_SCHEMA_VERSION:
        raise DeploymentStateError(
            f"Unsupported deployment state schema `{schema_version}`; expected {DEPLOYMENT_STATE_SCHEMA_VERSION}."
        )
    records = payload.get("deployments")
    if not isinstance(records, list):
        raise DeploymentStateError(f"{DEPLOYMENT_STATE_FILE} field `deployments` must be a list.")
    cleaned: list[dict[str, str]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DeploymentStateError(f"Deployment record {index + 1} must be an object.")
        cleaned.append(_clean_record(record))
    return {"schema_version": DEPLOYMENT_STATE_SCHEMA_VERSION, "deployments": cleaned}


def save_deployment_state(root: Path, state: dict[str, Any]) -> Path:
    """Atomically persist a bounded, owner-readable deployment history."""

    records = state.get("deployments")
    if not isinstance(records, list):
        raise DeploymentStateError("Deployment state field `deployments` must be a list.")
    payload = {
        "schema_version": DEPLOYMENT_STATE_SCHEMA_VERSION,
        "deployments": [_clean_record(record) for record in records[:DEPLOYMENT_STATE_HISTORY_LIMIT]],
    }
    path = deployment_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        # Write beside the destination so os.replace remains atomic on the same
        # filesystem; restrictive permissions protect operational metadata.
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def record_deployment(root: Path, record: dict[str, Any]) -> dict[str, str]:
    """Prepend one sanitized deployment record and persist the journal."""

    state = load_deployment_state(root)
    cleaned = _clean_record(record)
    records = [cleaned, *state["deployments"]]
    save_deployment_state(root, {"deployments": records})
    return cleaned


def latest_deployment(root: Path, run_id: str | None = None) -> dict[str, str] | None:
    """Return the newest record, or the record for a specific workflow run."""

    records = load_deployment_state(root)["deployments"]
    if run_id is None:
        return records[0] if records else None
    wanted = str(run_id)
    return next((record for record in records if record["run_id"] == wanted), None)


def rollback_target(root: Path, source_run_id: str | None = None) -> tuple[str, dict[str, str] | None]:
    """Resolve the previous image recorded for a deployment workflow run."""

    record = latest_deployment(root, source_run_id)
    if record is None:
        return "", None
    return record["previous_image_uri"], record


def workflow_dispatch_args(operation: str, image_uri: str) -> list[str]:
    """Build ``gh`` arguments for the protected production workflow dispatch."""

    if operation not in DEPLOYMENT_OPERATIONS:
        raise ValueError(f"Unsupported deployment operation: {operation}")
    return [
        "workflow",
        "run",
        DEPLOYMENT_WORKFLOW,
        "--ref",
        DEPLOYMENT_REF,
        "--raw-field",
        f"mode={operation}",
        "--raw-field",
        f"environment={DEPLOYMENT_ENVIRONMENT}",
        "--raw-field",
        f"image_uri={image_uri}",
    ]


def workflow_run_list_args(limit: int = 20) -> list[str]:
    """Build ``gh`` arguments for candidate deployment-run discovery."""

    return [
        "run",
        "list",
        "--workflow",
        DEPLOYMENT_WORKFLOW,
        "--event",
        "workflow_dispatch",
        "--branch",
        DEPLOYMENT_REF,
        "--limit",
        str(limit),
        "--json",
        DEPLOYMENT_LIST_JSON_FIELDS,
    ]


def workflow_run_view_args(run_id: str) -> list[str]:
    """Build ``gh`` arguments for structured details of one run."""

    return ["run", "view", str(run_id), "--json", DEPLOYMENT_RUN_JSON_FIELDS]


def workflow_run_log_args(run_id: str, failed_only: bool = False) -> list[str]:
    """Build ``gh`` arguments for all logs or only failed-step logs."""

    return ["run", "view", str(run_id), "--log-failed" if failed_only else "--log"]


def workflow_run_watch_args(run_id: str, interval: int = 5) -> list[str]:
    """Build ``gh`` arguments that propagate the watched run's exit status."""

    return ["run", "watch", str(run_id), "--exit-status", "--interval", str(interval)]


def display_gh_command(args: list[str]) -> str:
    """Render a copyable shell-safe representation of a GitHub CLI command."""

    return shlex.join(["gh", *args])


def parse_run_url(output: str) -> tuple[str, str]:
    """Extract a GitHub Actions run identifier and URL from dispatch output."""

    match = _RUN_URL_RE.search(output or "")
    if not match:
        return "", ""
    return match.group("run_id"), match.group(0)


def is_deployment_run(run: dict[str, Any]) -> bool:
    """Return whether a GitHub run matches this CLI's deployment contract.

    Event, protected branch, workflow identity, and display title are all
    checked to avoid selecting an unrelated manual workflow run.
    """

    if str(run.get("event") or "") != "workflow_dispatch":
        return False
    if str(run.get("headBranch") or "") != DEPLOYMENT_REF:
        return False
    workflow_name = str(run.get("workflowName") or "")
    if workflow_name and workflow_name != DEPLOYMENT_WORKFLOW_NAME:
        return False
    title = str(run.get("displayTitle") or "").lower()
    return title in {"devsecops deploy prod", "devsecops rollback prod"}


def active_deployment_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter candidate runs to deployment-related work still in progress."""

    return [
        run
        for run in runs
        if str(run.get("status") or "") in ACTIVE_RUN_STATUSES
        and (
            is_deployment_run(run)
            # Older workflow revisions did not set a deployment-specific title.
            or (
                str(run.get("event") or "") == "workflow_dispatch"
                and str(run.get("headBranch") or "") == DEPLOYMENT_REF
            )
        )
    ]


def newest_deployment_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the first valid deployment run from newest-first API results."""

    return next((run for run in runs if is_deployment_run(run)), None)


def select_dispatched_run(
    before_run_ids: set[str],
    runs: list[dict[str, Any]],
    operation: str | None = None,
) -> dict[str, Any] | None:
    """Find the newly created run by excluding the pre-dispatch snapshot.

    Comparing identifiers is more reliable than timestamps when GitHub API
    results arrive with coarse or delayed time metadata.
    """

    expected_title = f"devsecops {operation} {DEPLOYMENT_ENVIRONMENT}" if operation else ""
    for run in runs:
        run_id = str(run.get("databaseId") or "")
        title = str(run.get("displayTitle") or "").lower()
        if (
            run_id
            and run_id not in before_run_ids
            and is_deployment_run(run)
            and (not expected_title or title == expected_title)
        ):
            return run
    return None


def deployment_job_rows(run: dict[str, Any]) -> list[list[str]]:
    """Normalize optional GitHub job objects into presentation rows."""

    jobs = run.get("jobs")
    if not isinstance(jobs, list):
        return []
    rows: list[list[str]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        rows.append(
            [
                str(job.get("name") or ""),
                str(job.get("status") or ""),
                str(job.get("conclusion") or ""),
                str(job.get("startedAt") or ""),
                str(job.get("completedAt") or ""),
            ]
        )
    return rows


def deployment_status_payload(
    run: dict[str, Any],
    record: dict[str, str] | None = None,
    active_image_uri: str = "",
) -> dict[str, Any]:
    """Combine provider run data and local journal context into stable JSON.

    Journal metadata takes precedence because it records the exact image intent
    supplied by the CLI.  The workflow title is only a compatibility fallback.
    """

    record = record or {}
    operation = record.get("operation") or ""
    if not operation:
        title = str(run.get("displayTitle") or "").lower()
        if title == f"devsecops rollback {DEPLOYMENT_ENVIRONMENT}":
            operation = "rollback"
        elif title == f"devsecops deploy {DEPLOYMENT_ENVIRONMENT}":
            operation = "deploy"
    return {
        "kind": "deployment-status",
        "schema_version": 1,
        "environment": record.get("environment") or DEPLOYMENT_ENVIRONMENT,
        "operation": operation,
        "requested_image_uri": record.get("requested_image_uri") or "",
        "previous_image_uri": record.get("previous_image_uri") or "",
        "active_image_uri": active_image_uri,
        "run": {
            key: run.get(key)
            for key in (
                "databaseId",
                "workflowName",
                "displayTitle",
                "event",
                "headBranch",
                "headSha",
                "status",
                "conclusion",
                "createdAt",
                "updatedAt",
                "url",
            )
        },
        "jobs": [
            {
                "name": row[0],
                "status": row[1],
                "conclusion": row[2],
                "started_at": row[3],
                "completed_at": row[4],
            }
            for row in deployment_job_rows(run)
        ],
    }


def deployment_exit_code(run: dict[str, Any]) -> int:
    """Map a completed unsuccessful workflow to a failing CLI exit status.

    Queued and in-progress runs remain successful observations; their eventual
    outcome is handled by the watch command rather than status inspection.
    """

    status = str(run.get("status") or "")
    conclusion = str(run.get("conclusion") or "")
    if status == "completed" and conclusion not in {"success", "neutral", "skipped"}:
        return 1
    return 0


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "DEPLOYMENT_ENVIRONMENT",
    "DEPLOYMENT_LIST_JSON_FIELDS",
    "DEPLOYMENT_OPERATIONS",
    "DEPLOYMENT_REF",
    "DEPLOYMENT_RUN_JSON_FIELDS",
    "DEPLOYMENT_STATE_HISTORY_LIMIT",
    "DEPLOYMENT_STATE_SCHEMA_VERSION",
    "DEPLOYMENT_WORKFLOW",
    "DEPLOYMENT_WORKFLOW_PATH",
    "DEPLOYMENT_WORKFLOW_NAME",
    "DeploymentStateError",
    "active_deployment_runs",
    "deployment_exit_code",
    "deployment_job_rows",
    "deployment_state_path",
    "deployment_status_payload",
    "display_gh_command",
    "empty_deployment_state",
    "is_deployment_run",
    "latest_deployment",
    "load_deployment_state",
    "newest_deployment_run",
    "parse_run_url",
    "record_deployment",
    "rollback_target",
    "save_deployment_state",
    "select_dispatched_run",
    "utc_now",
    "workflow_dispatch_args",
    "workflow_run_list_args",
    "workflow_run_log_args",
    "workflow_run_view_args",
    "workflow_run_watch_args",
]
