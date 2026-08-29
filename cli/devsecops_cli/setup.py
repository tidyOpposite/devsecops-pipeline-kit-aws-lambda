"""Resumable guided-setup state and progress evaluation.

The state file records only workflow progress.  It never stores credentials or
secret values, and observable stages are re-evaluated from the current project,
tooling, AWS identity, and GitHub repository on every run.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import PRESETS, config_path, validate_config
from .images import is_immutable_image
from .models import Check
from .paths import SETUP_STATE_FILE


SETUP_STATE_SCHEMA_VERSION = 1
SETUP_MODES = ("demo", "standard", "production")
SETUP_STEP_ORDER = (
    "mode",
    "dependencies",
    "config",
    "image",
    "backend",
    "aws",
    "github",
    "dry_run",
    "summary",
)
SETUP_PROFILES: dict[str, dict[str, Any]] = {
    "demo": {
        "preset": "student-demo",
        "title": "Demo",
        "description": "Local learning path with a safe dry-run and no AWS or GitHub changes.",
        "required_tools": (),
        "recommended_tools": ("git",),
        "cloud_required": False,
    },
    "standard": {
        "preset": "balanced",
        "title": "Standard",
        "description": "Practical baseline for connecting one AWS account and GitHub repository.",
        "required_tools": ("git", "terraform", "aws", "gh"),
        "recommended_tools": (),
        "cloud_required": True,
    },
    "production": {
        "preset": "enterprise",
        "title": "Production",
        "description": "Strict production posture with every cloud connection verified.",
        "required_tools": ("git", "terraform", "aws", "gh"),
        "recommended_tools": (),
        "cloud_required": True,
    },
}

_S3_BUCKET_RE = re.compile(
    r"^(?!\d+\.\d+\.\d+\.\d+$)(?!.*\.\.)(?!.*\.-|.*-\.)"
    r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"
)
_IAM_ROLE_ARN_RE = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):iam::\d{12}:role\/[A-Za-z0-9+=,.@_\/-]{1,512}$"
)


class SetupStateError(Exception):
    """Raised when persisted setup progress cannot be loaded safely."""


@dataclass(frozen=True)
class SetupStage:
    """One reconciled guided-setup stage."""

    id: str
    title: str
    status: str
    detail: str


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def setup_state_path(root: Path) -> Path:
    return root / SETUP_STATE_FILE


def setup_profile(mode: str) -> dict[str, Any]:
    if mode not in SETUP_PROFILES:
        raise ValueError(f"Unknown setup mode: {mode}")
    return dict(SETUP_PROFILES[mode])


def mode_for_preset(preset: str) -> str:
    if preset == "student-demo":
        return "demo"
    if preset in {"strict", "enterprise"}:
        return "production"
    return "standard"


def new_setup_state(mode: str, preset: str | None = None) -> dict[str, Any]:
    profile = setup_profile(mode)
    timestamp = _now()
    return {
        "schema_version": SETUP_STATE_SCHEMA_VERSION,
        "mode": mode,
        "preset": preset or profile["preset"],
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_step": "mode",
        "steps": {},
        "dry_run_fingerprint": "",
    }


def load_setup_state(root: Path) -> dict[str, Any] | None:
    path = setup_state_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupStateError(
            f"Cannot read {SETUP_STATE_FILE}. Move the invalid file aside and rerun setup."
        ) from exc
    if not isinstance(payload, dict):
        raise SetupStateError(f"{SETUP_STATE_FILE} must contain a JSON object.")
    version = payload.get("schema_version")
    if version != SETUP_STATE_SCHEMA_VERSION:
        raise SetupStateError(
            f"{SETUP_STATE_FILE} uses schema_version {version!r}; "
            f"this CLI supports {SETUP_STATE_SCHEMA_VERSION}."
        )
    mode = payload.get("mode")
    if mode not in SETUP_MODES:
        raise SetupStateError(f"{SETUP_STATE_FILE} contains an unknown setup mode: {mode!r}.")
    if not isinstance(payload.get("steps", {}), dict):
        raise SetupStateError(f"{SETUP_STATE_FILE} field `steps` must be an object.")
    preset = payload.get("preset")
    if preset not in PRESETS:
        raise SetupStateError(f"{SETUP_STATE_FILE} contains an unknown config preset: {preset!r}.")
    return payload


def save_setup_state(root: Path, state: dict[str, Any]) -> Path:
    """Atomically persist non-secret setup progress."""

    path = setup_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["schema_version"] = SETUP_STATE_SCHEMA_VERSION
    state["updated_at"] = _now()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def switch_setup_mode(state: dict[str, Any], mode: str, preset: str | None = None) -> dict[str, Any]:
    """Change mode explicitly and invalidate event-derived progress."""

    setup_profile(mode)
    if state.get("mode") == mode and (preset is None or state.get("preset") == preset):
        return state
    state["mode"] = mode
    state["preset"] = preset or setup_profile(mode)["preset"]
    state["last_step"] = "mode"
    state["steps"] = {}
    state["dry_run_fingerprint"] = ""
    return state


def mark_setup_step(state: dict[str, Any], step: str, status: str, detail: str = "") -> None:
    if step not in SETUP_STEP_ORDER:
        raise ValueError(f"Unknown setup step: {step}")
    if status not in {"complete", "pending", "not-required"}:
        raise ValueError(f"Unknown setup status: {status}")
    state["last_step"] = step
    state.setdefault("steps", {})[step] = {
        "status": status,
        "detail": detail,
        "updated_at": _now(),
    }


def setup_config_fingerprint(cfg: dict[str, Any], image_override: str | None = None) -> str:
    payload = dict(cfg)
    if image_override:
        payload["lambda_image_uri"] = image_override
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def demo_image_uri(cfg: dict[str, Any]) -> str:
    """Return a non-contacted sample URI aligned with the configured region."""

    region = str(cfg.get("aws_region") or "us-east-1")
    project = str(cfg.get("project_name") or "devsecops-pipeline")
    return f"123456789012.dkr.ecr.{region}.amazonaws.com/{project}-prod-lambda-repo:sha-demo123"


def is_backend_bucket_configured(value: str) -> bool:
    normalized = value.strip()
    return bool(_S3_BUCKET_RE.fullmatch(normalized)) and not normalized.startswith("replace-with")


def is_iam_role_arn(value: str) -> bool:
    return bool(_IAM_ROLE_ARN_RE.fullmatch(value.strip()))


def github_setup_ready(checks: list[Check]) -> bool:
    required_names = {"GitHub CLI", "GitHub auth", "GitHub repository"}
    observed_names = {check.name for check in checks}
    return required_names <= observed_names and all(
        check.status == "OK" for check in checks if check.scored
    )


def setup_config_blockers(cfg: dict[str, Any], mode: str) -> list[Check]:
    """Return schema or mode-posture checks that block the config stage."""

    checks = validate_config(cfg)
    failures = [check for check in checks if check.status == "FAIL"]
    if mode == "demo":
        return failures
    standard_policy_checks = {
        "Production CORS policy",
        "API authorization policy",
        "Production approval gate policy",
        "Separate plan role policy",
    }
    if mode == "standard":
        policy_gaps = [
            check
            for check in checks
            if check.name in standard_policy_checks and check.status != "OK"
        ]
    else:
        policy_gaps = [
            check
            for check in checks
            if check.scored
            and check.name != "Lambda image immutability policy"
            and check.status != "OK"
        ]
    return [*failures, *[check for check in policy_gaps if check not in failures]]


def setup_stages(
    root: Path,
    cfg: dict[str, Any],
    state: dict[str, Any],
    *,
    dependency_status: dict[str, bool],
    backend_checks: list[Check],
    aws_identity: Check | None,
    github_checks: list[Check],
) -> list[SetupStage]:
    """Reconcile persisted progress with the current observable project state."""

    mode = str(state["mode"])
    profile = setup_profile(mode)
    required_tools = tuple(profile["required_tools"])
    missing_tools = [tool for tool in required_tools if not dependency_status.get(tool, False)]
    recommended_missing = [
        tool for tool in profile["recommended_tools"] if not dependency_status.get(tool, False)
    ]
    if missing_tools:
        dependency_stage = SetupStage(
            "dependencies",
            "Check dependencies",
            "pending",
            "Missing required tools: " + ", ".join(missing_tools),
        )
    else:
        detail = "Required tools are available."
        if recommended_missing:
            detail += " Optional for this mode: " + ", ".join(recommended_missing) + "."
        dependency_stage = SetupStage("dependencies", "Check dependencies", "complete", detail)

    config_exists = config_path(root).exists()
    config_failures = setup_config_blockers(cfg, mode) if config_exists else []
    config_stage = SetupStage(
        "config",
        "Create config",
        "complete" if config_exists and not config_failures else "pending",
        str(config_path(root))
        if config_exists and not config_failures
        else f"{len(config_failures)} invalid setting(s)."
        if config_exists
        else "Local source config has not been created.",
    )

    image_uri = str(cfg.get("lambda_image_uri", ""))
    image_ready = bool(image_uri and is_immutable_image(image_uri))
    if not profile["cloud_required"] and not image_ready:
        image_stage = SetupStage(
            "image",
            "Choose Lambda image",
            "not-required",
            "Demo dry-run uses a clearly marked sample URI without saving it to config.",
        )
    else:
        image_stage = SetupStage(
            "image",
            "Choose Lambda image",
            "complete" if image_ready else "pending",
            image_uri if image_ready else "An immutable ECR image URI is still required.",
        )

    backend_bucket = str(cfg.get("backend", {}).get("bucket", ""))
    backend_configured = is_backend_bucket_configured(backend_bucket)
    backend_check_names = {"State bucket", "Lock table"}
    backend_ready = (
        backend_configured
        and backend_check_names <= {check.name for check in backend_checks}
        and all(
            check.status == "OK"
            for check in backend_checks
            if check.name in backend_check_names
        )
    )
    if not profile["cloud_required"]:
        backend_stage = SetupStage(
            "backend",
            "Configure Terraform backend",
            "not-required",
            "Remote state is not required for demo dry-run.",
        )
    else:
        backend_stage = SetupStage(
            "backend",
            "Configure Terraform backend",
            "complete" if backend_ready else "pending",
            backend_bucket
            if backend_ready
            else "A real S3 state bucket name is still required."
            if not backend_configured
            else "; ".join(check.detail for check in backend_checks if check.status != "OK")
            or "Backend names are configured but the bucket and lock table are not verified.",
        )

    if not profile["cloud_required"]:
        aws_stage = SetupStage(
            "aws",
            "Verify AWS identity",
            "not-required",
            "AWS credentials are not used in demo mode.",
        )
        github_stage = SetupStage(
            "github",
            "Connect GitHub repository / OIDC",
            "not-required",
            "GitHub is not changed or queried in demo mode.",
        )
    else:
        aws_ready = aws_identity is not None and aws_identity.status == "OK"
        aws_stage = SetupStage(
            "aws",
            "Verify AWS identity",
            "complete" if aws_ready else "pending",
            aws_identity.detail if aws_identity is not None else "AWS identity could not be verified.",
        )
        github_ready = github_setup_ready(github_checks)
        github_stage = SetupStage(
            "github",
            "Connect GitHub repository / OIDC",
            "complete" if github_ready else "pending",
            "Repository variables and required OIDC role secrets are present."
            if github_ready
            else "GitHub authentication, repository variables, or OIDC role secrets are incomplete.",
        )

    effective_image = demo_image_uri(cfg) if mode == "demo" and not image_ready else None
    fingerprint = setup_config_fingerprint(cfg, image_override=effective_image)
    dry_run_ready = state.get("dry_run_fingerprint") == fingerprint
    dry_run_stage = SetupStage(
        "dry_run",
        "Run safe dry-run",
        "complete" if dry_run_ready else "pending",
        "Dry-run matches the current setup inputs."
        if dry_run_ready
        else "Dry-run has not succeeded for the current setup inputs.",
    )

    stages = [
        SetupStage(
            "mode",
            "Choose mode",
            "complete",
            f"{profile['title']}: {profile['description']}",
        ),
        dependency_stage,
        config_stage,
        image_stage,
        backend_stage,
        aws_stage,
        github_stage,
        dry_run_stage,
    ]
    summary_ready = all(stage.status in {"complete", "not-required"} for stage in stages)
    stages.append(
        SetupStage(
            "summary",
            "Review summary and next command",
            "complete" if summary_ready else "pending",
            "Guided setup is complete."
            if summary_ready
            else "One or more required stages still need attention.",
        )
    )
    return stages


def first_pending_stage(stages: list[SetupStage]) -> SetupStage | None:
    return next((stage for stage in stages if stage.status == "pending"), None)


def completed_stage_count(stages: list[SetupStage]) -> tuple[int, int]:
    required = [stage for stage in stages if stage.status != "not-required"]
    return sum(stage.status == "complete" for stage in required), len(required)


def setup_next_command(stage: SetupStage | None, mode: str) -> str:
    if stage is None:
        return "devsecops status --deep" if mode != "demo" else "devsecops status"
    if stage.id == "backend" and "bucket name is still required" not in stage.detail:
        return "devsecops terraform bootstrap"
    return {
        "dependencies": "devsecops setup",
        "config": "devsecops setup",
        "image": "devsecops setup",
        "backend": "devsecops setup",
        "aws": "aws sts get-caller-identity",
        "github": "devsecops setup",
        "dry_run": "devsecops setup",
        "summary": "devsecops setup",
    }.get(stage.id, "devsecops setup")


__all__ = [
    "SETUP_MODES",
    "SETUP_PROFILES",
    "SETUP_STATE_FILE",
    "SETUP_STATE_SCHEMA_VERSION",
    "SETUP_STEP_ORDER",
    "SetupStage",
    "SetupStateError",
    "completed_stage_count",
    "demo_image_uri",
    "first_pending_stage",
    "github_setup_ready",
    "is_backend_bucket_configured",
    "is_iam_role_arn",
    "load_setup_state",
    "mark_setup_step",
    "mode_for_preset",
    "new_setup_state",
    "save_setup_state",
    "setup_config_blockers",
    "setup_config_fingerprint",
    "setup_next_command",
    "setup_profile",
    "setup_stages",
    "setup_state_path",
    "switch_setup_mode",
]
