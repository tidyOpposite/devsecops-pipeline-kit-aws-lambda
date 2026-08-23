"""Shared domain models for the DevSecOps CLI.

The models in this module deliberately contain no command, filesystem, or
provider logic.  Keeping them dependency-free prevents the circular imports
that previously forced every helper module to import ``main``.
"""

from __future__ import annotations

from dataclasses import dataclass


class InputCancelled(Exception):
    """Raised when an interactive menu prompt is cancelled by the user."""


class ConfigMigrationError(Exception):
    """Raised when a local config cannot be migrated safely."""


@dataclass
class EcrImageRef:
    """Parsed reference to an Amazon ECR container image."""

    registry: str
    region: str
    repository: str
    tag: str | None = None
    digest: str | None = None


@dataclass(frozen=True)
class Control:
    """Security control exposed by the CLI inventory and explain commands."""

    id: str
    title: str
    cli_options: tuple[str, ...]
    terraform: tuple[str, ...]
    github: tuple[str, ...]
    aws: tuple[str, ...]
    scanners: tuple[str, ...]
    audit_evidence: tuple[str, ...]
    guidance: str


@dataclass
class ActionsStatus:
    """Normalized GitHub Actions status used by human and JSON renderers."""

    runs: list[list[str]]
    failed_jobs: list[list[str]]
    failed_steps: list[list[str]]
    next_actions: list[str]
    error: str | None = None


@dataclass
class Check:
    """A single readiness, validation, or integration check."""

    name: str
    status: str
    detail: str
    scored: bool = True


__all__ = [
    "ActionsStatus",
    "Check",
    "ConfigMigrationError",
    "Control",
    "EcrImageRef",
    "InputCancelled",
]
