"""Shared deployment types and image policies."""

from __future__ import annotations

import re

from .models import EcrImageRef

ECR_IMAGE_RE = re.compile(
    r"(?P<registry>\d{12}\.dkr\.ecr\.(?P<region>[a-z0-9-]+)\.amazonaws\.com)/"
    r"(?P<repository>[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?)"
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})|@(?P<digest>sha256:[A-Fa-f0-9]{64}))"
)


def is_immutable_image(image_uri: str) -> bool:
    """Return whether an image uses a digest or a permitted release tag.

    The kit reserves ``latest`` and ``bootstrap`` as moving tags.  Other tags
    are treated as operator-managed immutable release identifiers.
    """

    if not isinstance(image_uri, str):
        return False
    if re.fullmatch(r"[^\s@]+@sha256:[A-Fa-f0-9]{64}", image_uri):
        return True
    match = re.fullmatch(r"[^\s@]+:(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})", image_uri)
    return match is not None and match.group("tag").lower() not in {"latest", "bootstrap"}


def parse_ecr_image_uri(image_uri: str) -> EcrImageRef | None:
    """Parse a complete private ECR image URI into its typed components."""

    match = ECR_IMAGE_RE.fullmatch(image_uri) if isinstance(image_uri, str) else None
    if not match:
        return None
    return EcrImageRef(
        registry=match.group("registry"),
        region=match.group("region"),
        repository=match.group("repository"),
        tag=match.group("tag"),
        digest=match.group("digest"),
    )
