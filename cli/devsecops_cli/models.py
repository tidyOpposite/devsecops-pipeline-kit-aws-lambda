"""Shared deployment types and image policies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EcrImageRef:
    """Parsed reference to an Amazon ECR container image.

    Valid parser output identifies the image with either ``tag`` or ``digest``;
    downstream AWS lookup code relies on that exclusivity.
    """

    registry: str
    region: str
    repository: str
    tag: str | None = None
    digest: str | None = None

    @property
    def registry_id(self) -> str:
        return self.registry.split(".", 1)[0]


class ConfigValidationError(ValueError):
    """An expected config syntax, shape, or value error with repair guidance."""
