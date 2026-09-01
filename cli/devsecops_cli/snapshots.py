"""Filesystem snapshot and local rollback services.

This module enforces the CLI-owned path allowlist.  It intentionally has no
terminal output so commands can present the same operations as text, JSON, or
an interactive menu without coupling storage logic to the UI.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from .paths import SNAPSHOT_DIR, SNAPSHOT_FILES, SNAPSHOT_FILE_PATHS


def snapshot_id(operation: str, now: dt.datetime | None = None) -> str:
    """Build a sortable UTC identifier with a filesystem-safe operation suffix."""

    current = now or dt.datetime.now(dt.UTC)
    safe_operation = re.sub(r"[^a-z0-9-]+", "-", operation.lower()).strip("-") or "change"
    return f"{current.strftime('%Y%m%dT%H%M%SZ')}-{safe_operation}"


def snapshot_base(root: Path) -> Path:
    """Return the snapshot store below the explicit project root."""

    return root / SNAPSHOT_DIR


def create_snapshot(
    root: Path,
    operation: str,
    description: str,
    *,
    id_factory: Callable[[str], str] = snapshot_id,
) -> Path:
    """Copy allowlisted files and their prior-presence state into a snapshot.

    Recording absent files is essential: restoring the snapshot must remove an
    owned artifact that was created only after the snapshot.  Identifier
    collisions receive numeric suffixes instead of overwriting history.
    """

    base = snapshot_base(root)
    base.mkdir(parents=True, exist_ok=True)
    base_id = id_factory(operation)
    snapshot_path = base / base_id
    counter = 2
    while snapshot_path.exists():
        snapshot_path = base / f"{base_id}-{counter}"
        counter += 1
    snapshot_path.mkdir(parents=True)

    files = []
    for relative_path in SNAPSHOT_FILES:
        source = root / relative_path
        target = snapshot_path / "files" / relative_path
        entry = {"path": str(relative_path), "present": source.exists()}
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        files.append(entry)

    manifest = {
        "id": snapshot_path.name,
        "created_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "operation": operation,
        "description": description,
        "files": files,
    }
    (snapshot_path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return snapshot_path


def read_snapshot_manifest(snapshot_path: Path) -> dict[str, Any]:
    """Read a manifest best-effort, returning empty data for malformed entries."""

    manifest_path = snapshot_path / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def snapshot_entry_relative_path(file_entry: dict[str, Any]) -> Path | None:
    """Resolve an entry only when its exact path is in the restore allowlist.

    This is the traversal and scope boundary for manifests, including manifests
    copied from elsewhere or edited after creation.
    """

    raw_path = str(file_entry.get("path", ""))
    if raw_path not in SNAPSHOT_FILE_PATHS:
        return None
    return Path(raw_path)


def list_snapshots(root: Path) -> list[dict[str, Any]]:
    """Return valid snapshot manifests in newest-first identifier order."""

    base = snapshot_base(root)
    if not base.exists():
        return []
    snapshots = []
    for snapshot_path in base.iterdir():
        if not snapshot_path.is_dir():
            continue
        manifest = read_snapshot_manifest(snapshot_path)
        if not manifest:
            continue
        manifest["_path"] = str(snapshot_path)
        snapshots.append(manifest)
    return sorted(snapshots, key=lambda item: str(item.get("id", "")), reverse=True)


def resolve_snapshot(
    root: Path,
    snapshot_id_value: str | None = None,
    last: bool = False,
) -> dict[str, Any] | None:
    """Resolve the newest snapshot or an exact snapshot identifier."""

    snapshots = list_snapshots(root)
    if not snapshots:
        return None
    if last or not snapshot_id_value:
        return snapshots[0]
    for snapshot in snapshots:
        if snapshot.get("id") == snapshot_id_value:
            return snapshot
    return None


def file_line_counts(before: str, after: str) -> tuple[int, int]:
    """Estimate changed line counts without constructing a full text diff.

    Equal-length edits count as one addition and removal so modified content is
    never displayed as an unchanged zero-line delta.
    """

    before_lines = before.splitlines()
    after_lines = after.splitlines()
    added = max(0, len(after_lines) - len(before_lines))
    removed = max(0, len(before_lines) - len(after_lines))
    if added == 0 and removed == 0 and before != after:
        added = 1
        removed = 1
    return added, removed


def snapshot_changes(root: Path, snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Describe modifications, additions, and deletions since a snapshot."""

    snapshot_path = Path(str(snapshot["_path"]))
    changes: list[dict[str, str]] = []
    for file_entry in snapshot.get("files", []):
        if not isinstance(file_entry, dict):
            continue
        relative = snapshot_entry_relative_path(file_entry)
        if relative is None:
            continue
        before_present = bool(file_entry.get("present"))
        before_path = snapshot_path / "files" / relative
        current_path = root / relative
        current_present = current_path.exists()

        if before_present and current_present:
            before_text = before_path.read_text(encoding="utf-8", errors="replace")
            current_text = current_path.read_text(encoding="utf-8", errors="replace")
            if before_text == current_text:
                continue
            added, removed = file_line_counts(before_text, current_text)
            detail = f"modified since snapshot (+{added}/-{removed} line estimate)"
        elif before_present and not current_present:
            detail = "deleted since snapshot; rollback will restore it"
        elif not before_present and current_present:
            detail = "created since snapshot; rollback will remove it"
        else:
            continue
        changes.append({"path": str(relative), "detail": detail})
    return changes


def snapshot_rows(snapshots: list[dict[str, Any]]) -> list[list[str]]:
    """Project manifests into numbered presentation rows."""

    return [
        [
            str(index + 1),
            str(snapshot.get("id", "")),
            str(snapshot.get("created_at", "")),
            str(snapshot.get("operation", "")),
        ]
        for index, snapshot in enumerate(snapshots)
    ]


def resolve_snapshot_selection(root: Path, selection: str) -> dict[str, Any] | None:
    """Resolve a one-based displayed number or an exact identifier."""

    snapshots = list_snapshots(root)
    if not snapshots:
        return None
    if selection.isdigit():
        index = int(selection) - 1
        if 0 <= index < len(snapshots):
            return snapshots[index]
    for snapshot in snapshots:
        if snapshot.get("id") == selection:
            return snapshot
    return None


def restore_snapshot(root: Path, snapshot: dict[str, Any], dry_run: bool = False) -> list[dict[str, str]]:
    """Restore only allowlisted files to their recorded presence and contents.

    A dry run returns the same change description without touching the
    filesystem.  Cloud resources, Terraform state, and unowned paths are never
    candidates for this operation.
    """

    changes = snapshot_changes(root, snapshot)
    if dry_run:
        return changes
    snapshot_path = Path(str(snapshot["_path"]))
    for file_entry in snapshot.get("files", []):
        if not isinstance(file_entry, dict):
            continue
        relative = snapshot_entry_relative_path(file_entry)
        if relative is None:
            continue
        destination = root / relative
        source = snapshot_path / "files" / relative
        if bool(file_entry.get("present")):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        elif destination.exists():
            destination.unlink()
    return changes


__all__ = [
    "create_snapshot",
    "file_line_counts",
    "list_snapshots",
    "read_snapshot_manifest",
    "resolve_snapshot",
    "resolve_snapshot_selection",
    "restore_snapshot",
    "snapshot_base",
    "snapshot_changes",
    "snapshot_entry_relative_path",
    "snapshot_id",
    "snapshot_rows",
]
