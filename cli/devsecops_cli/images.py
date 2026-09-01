"""Container-image reference parsing and deployment validation policies.

The module separates general immutability checks from AWS ECR-specific parsing.
This lets the CLI recognize immutable bring-your-own images while applying
region and repository checks only when an ECR reference can be decomposed.
"""

from __future__ import annotations

import re
from typing import Any

from .models import Check, EcrImageRef


# ECR references must identify exactly one tag or digest; accepting both would
# make downstream ``describe-images`` lookup semantics ambiguous.
ECR_IMAGE_RE = re.compile(
    r"^(?P<registry>\d{12}\.dkr\.ecr\.(?P<region>[^.]+)\.amazonaws\.com)/"
    r"(?P<repository>[^:@]+)(?::(?P<tag>[^@]+)|@(?P<digest>sha256:[A-Fa-f0-9]{64}))$"
)


def is_immutable_image(image_uri: str) -> bool:
    """Return whether an image uses a digest or a permitted release tag.

    The kit reserves ``latest`` and ``bootstrap`` as moving tags.  Other tags
    are treated as operator-managed immutable release identifiers.
    """

    if not image_uri:
        return False
    if "@sha256:" in image_uri:
        return True
    if ":" not in image_uri:
        return False
    tag = image_uri.rsplit(":", 1)[1]
    return tag not in {"latest", "bootstrap"}


def parse_ecr_image_uri(image_uri: str) -> EcrImageRef | None:
    """Parse a complete private ECR image URI into its typed components."""

    match = ECR_IMAGE_RE.match(image_uri)
    if not match:
        return None
    return EcrImageRef(
        registry=match.group("registry"),
        region=match.group("region"),
        repository=match.group("repository"),
        tag=match.group("tag"),
        digest=match.group("digest"),
    )


def expected_ecr_repository_name(cfg: dict[str, Any], env_name: str) -> str:
    """Return the repository name created by the reference Terraform stack."""

    return f"{cfg['project_name']}-{env_name}-lambda-repo"


def image_uri_from_config_or_override(cfg: dict[str, Any], image_uri: str | None = None) -> str:
    """Resolve an explicit image override or fall back to local configuration.

    An explicitly supplied empty string remains an empty override; only
    ``None`` means that the caller did not provide a value.
    """

    return str(image_uri if image_uri is not None else cfg["lambda_image_uri"]).strip()


def collect_image_preflight_checks(
    cfg: dict[str, Any],
    image_uri: str | None = None,
    env_name: str = "prod",
) -> list[Check]:
    """Validate image presence, ECR shape, immutability, region, and repository.

    Repository mismatch is informational for readiness scoring because
    bring-your-own ECR repositories are supported when IAM permits access.
    Region mismatch remains a failure because Lambda cannot pull a function
    image from an ECR repository in another region.
    """

    checks: list[Check] = []
    resolved_uri = image_uri_from_config_or_override(cfg, image_uri)
    image_ref = parse_ecr_image_uri(resolved_uri) if resolved_uri else None
    expected_shape = "123456789012.dkr.ecr.<region>.amazonaws.com/<repository>:<immutable-tag> or @sha256:<digest>"

    checks.append(
        Check(
            "Lambda image URI",
            "OK" if resolved_uri else "FAIL",
            resolved_uri if resolved_uri else "Set lambda_image_uri or pass --image-uri.",
        )
    )
    checks.append(
        Check(
            "Lambda image shape",
            "OK" if image_ref else ("FAIL" if resolved_uri else "WARN"),
            f"ECR image URI for repository `{image_ref.repository}`."
            if image_ref
            else f"Expected {expected_shape}."
            if resolved_uri
            else "Cannot inspect shape until an image URI is set.",
        )
    )
    checks.append(
        Check(
            "Lambda image immutability",
            "OK" if is_immutable_image(resolved_uri) else ("FAIL" if resolved_uri else "WARN"),
            "Uses an immutable tag or digest."
            if is_immutable_image(resolved_uri)
            else "Use an immutable tag or digest; do not use latest or bootstrap."
            if resolved_uri
            else "Cannot inspect immutability until an image URI is set.",
        )
    )

    if image_ref:
        expected_region = str(cfg["aws_region"])
        checks.append(
            Check(
                "Lambda image region",
                "OK" if image_ref.region == expected_region else "FAIL",
                image_ref.region
                if image_ref.region == expected_region
                else f"Image region `{image_ref.region}` does not match aws_region `{expected_region}`.",
            )
        )
        # The reference repository is a convention rather than an ownership
        # requirement, so a different valid ECR repository does not block.
        expected_repository = expected_ecr_repository_name(cfg, env_name)
        checks.append(
            Check(
                "Lambda image repository",
                "OK" if image_ref.repository == expected_repository else "WARN",
                image_ref.repository
                if image_ref.repository == expected_repository
                else (
                    f"Configured image uses `{image_ref.repository}`; Terraform also creates `{expected_repository}`. "
                    "This is allowed for bring-your-own images if the deploy role can pull it."
                ),
                scored=False,
            )
        )
    else:
        checks.append(Check("Lambda image region", "WARN", "Cannot compare image region until the URI matches ECR shape."))
        checks.append(Check("Lambda image repository", "WARN", "Cannot compare repository until the URI matches ECR shape.", scored=False))

    return checks




__all__ = [
    "collect_image_preflight_checks",
    "expected_ecr_repository_name",
    "image_uri_from_config_or_override",
    "is_immutable_image",
    "parse_ecr_image_uri",
]
