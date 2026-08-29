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
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_deployment_state() -> dict[str, Any]:
    return {"schema_version": DEPLOYMENT_STATE_SCHEMA_VERSION, "deployments": []}


def deployment_state_path(root: Path) -> Path:
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
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def record_deployment(root: Path, record: dict[str, Any]) -> dict[str, str]:
    state = load_deployment_state(root)
    cleaned = _clean_record(record)
    records = [cleaned, *state["deployments"]]
    save_deployment_state(root, {"deployments": records})
    return cleaned


def latest_deployment(root: Path, run_id: str | None = None) -> dict[str, str] | None:
    records = load_deployment_state(root)["deployments"]
    if run_id is None:
        return records[0] if records else None
    wanted = str(run_id)
    return next((record for record in records if record["run_id"] == wanted), None)


def rollback_target(root: Path, source_run_id: str | None = None) -> tuple[str, dict[str, str] | None]:
    record = latest_deployment(root, source_run_id)
    if record is None:
        return "", None
    return record["previous_image_uri"], record


def workflow_dispatch_args(operation: str, image_uri: str) -> list[str]:
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
    return ["run", "view", str(run_id), "--json", DEPLOYMENT_RUN_JSON_FIELDS]


def workflow_run_log_args(run_id: str, failed_only: bool = False) -> list[str]:
    return ["run", "view", str(run_id), "--log-failed" if failed_only else "--log"]


def workflow_run_watch_args(run_id: str, interval: int = 5) -> list[str]:
    return ["run", "watch", str(run_id), "--exit-status", "--interval", str(interval)]


def display_gh_command(args: list[str]) -> str:
    return shlex.join(["gh", *args])


def parse_run_url(output: str) -> tuple[str, str]:
    match = _RUN_URL_RE.search(output or "")
    if not match:
        return "", ""
    return match.group("run_id"), match.group(0)


def is_deployment_run(run: dict[str, Any]) -> bool:
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
    return next((run for run in runs if is_deployment_run(run)), None)


def select_dispatched_run(
    before_run_ids: set[str],
    runs: list[dict[str, Any]],
    operation: str | None = None,
) -> dict[str, Any] | None:
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
