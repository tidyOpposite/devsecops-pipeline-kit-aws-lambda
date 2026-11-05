"""Validate a publication identity before building or changing a release."""

import argparse
import re
import tomllib
from pathlib import Path

from . import VERSION

_BASE = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"


def version_from_tag(tag: str) -> str:
    """Map supported semantic release tags to canonical Python versions."""

    match = re.fullmatch(r"v" + _BASE + r"(?:-(a|alpha|b|beta|rc)\.(0|[1-9]\d*))?", tag)
    if match is None:
        raise ValueError("Use vX.Y.Z or vX.Y.Z-rc.N (also a.N/b.N); development versions cannot be published.")
    major, minor, patch, label, number = match.groups()
    suffix = {"alpha": "a", "beta": "b"}.get(label, label) if label else ""
    return f"{major}.{minor}.{patch}{suffix}{number if label else ''}"


def validate_release_version(root: Path, tag: str) -> Path:
    """Require the tag, CLI, both packages and versioned notes to agree."""

    expected = version_from_tag(tag)
    if expected != VERSION:
        raise ValueError(f"Tag {tag} requires CLI version {expected}; current source is {VERSION}.")
    for name in ("pyproject.toml", "cli/pyproject.toml"):
        metadata = tomllib.loads((root / name).read_text(encoding="utf-8"))
        if metadata.get("project", {}).get("version") != expected:
            raise ValueError(f"{name} must declare version {expected}.")
    notes = root / f"docs/release-v{expected}.md"
    if not notes.is_file():
        raise ValueError(f"Missing current version release notes: {notes.name}.")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        notes = validate_release_version(args.root, args.tag)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Release version error: {error}\n")
    print(f"Release identity verified: {args.tag}; notes: {notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
