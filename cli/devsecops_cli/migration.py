"""Explicit local-only migration of the previous saved-plan state layout."""

from __future__ import annotations

import fcntl
import os
import re
from pathlib import Path

from .deployment import SCHEMA, Deployment, DeploymentError, read_json, write_json


def migrate(root: Path, name: str, yes: bool = False) -> dict:
    target = Deployment(root, name)
    source = root / ".devsecops" / "labs" / name
    if source.is_symlink() or not source.is_dir():
        raise DeploymentError("No regular legacy state directory for this name.")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise DeploymentError(
            "Legacy directory contains symlinks; regular local files are required."
        )
    with (source / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DeploymentError(
                "A legacy operation is running; finish it before migration."
            ) from error
        if target.home.exists():
            raise DeploymentError(
                "Destination already exists; migration never merges or overwrites state."
            )
        original = read_json(source / "settings.json")
        if (
            not isinstance(original, dict)
            or type(original.get("schema_version")) is not int
            or original.get("schema_version") != 1
            or original.get("name") != name
            or not isinstance(original.get("project_name"), str)
            or not re.fullmatch(
                r"kit-lab-" + re.escape(name) + r"-[a-f0-9]{6}", original["project_name"]
            )
        ):
            raise DeploymentError(
                "Unsupported legacy settings; preserve the originals and inspect manually."
            )
        settings = {**original, "schema_version": SCHEMA, "purpose": "SingleOperatorLab"}
        probe = Deployment(root, name)
        probe.settings = settings
        probe.state = source / "state.tfstate"
        probe.validate_settings()
        probe.outputs()
        result = {
            "kind": "deployment-migration",
            "schema_version": SCHEMA,
            "status": "review-required",
            "source": str(source),
            "destination": str(target.home),
            "name": name,
            "project_name": settings["project_name"],
            "message": "AWS is unchanged. Old plans are invalid; create and review a new plan after migration.",
        }
        if not yes:
            return result
        backup = source / "settings.v1.json"
        if backup.exists():
            raise DeploymentError(
                "Legacy backup already exists; inspect the previous migration attempt."
            )
        write_json(backup, original)
        try:
            write_json(source / "settings.json", settings)
            target.home.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.rename(source, target.home)
        except OSError:
            if source.exists():
                write_json(source / "settings.json", original)
            raise
        result["status"] = "migrated"
        return result
