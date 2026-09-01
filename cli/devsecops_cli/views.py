"""Pure row builders shared by text, rich, and Markdown presentations.

These helpers translate domain configuration into strings without printing or
performing I/O, keeping column semantics consistent across CLI surfaces.
"""

from __future__ import annotations

from typing import Any

from .config import (
    PRESET_ORDER,
    PRESET_POSTURE_LABELS,
    control_catalog,
    control_state,
    has_wildcard_cors,
    preset_config,
    prod_approval_environment,
)
from .models import Control


def env_rows(cfg: dict[str, Any]) -> list[list[str]]:
    """Build environment rows in the configuration's stable insertion order."""

    rows: list[list[str]] = []
    for env_name, env_cfg in cfg["environments"].items():
        rows.append(
            [
                env_name,
                str(env_cfg["lambda_memory_size"]),
                str(env_cfg["lambda_timeout"]),
                str(env_cfg["log_retention_days"]),
                f"{env_cfg['api_throttling_burst_limit']}/{env_cfg['api_throttling_rate_limit']}",
                ",".join(env_cfg["cors_allowed_origins"]),
            ]
        )
    return rows


def preset_rows() -> list[list[str]]:
    """Summarize every preset's scanners, validation, CORS, and release gates."""

    rows: list[list[str]] = []
    for name in PRESET_ORDER:
        cfg = preset_config(name)
        scanners = "Snyk" if cfg["enable_snyk_scan"] else "none"
        validation = "/health"
        if cfg["enable_dast"]:
            validation += " + DAST"
        if not cfg["enable_http_validation"] and not cfg["enable_dast"]:
            validation = "none"
        prod_cors = "wildcard" if has_wildcard_cors(cfg["environments"]["prod"]["cors_allowed_origins"]) else "explicit"
        rows.append(
            [
                name,
                PRESET_POSTURE_LABELS[name],
                scanners,
                validation,
                prod_cors,
                "on" if cfg["use_prod_approval_environment"] else "off",
                "on" if cfg["use_separate_aws_plan_role"] else "off",
            ]
        )
    return rows


def preset_detail_rows(cfg: dict[str, Any]) -> list[list[str]]:
    """Flatten policy controls and environment settings for detail tables."""

    rows: list[list[str]] = [
        ["Snyk container scan", "on" if cfg["enable_snyk_scan"] else "off"],
        ["HTTP validation", "on" if cfg["enable_http_validation"] else "off"],
        ["DAST", "on" if cfg["enable_dast"] else "off"],
        ["Prod approval environment", prod_approval_environment(cfg)],
        ["Separate AWS plan role", "on" if cfg["use_separate_aws_plan_role"] else "off"],
    ]
    for env_name, env_cfg in cfg["environments"].items():
        rows.extend(
            [
                [f"{env_name}.lambda_memory_size", str(env_cfg["lambda_memory_size"])],
                [f"{env_name}.lambda_timeout", str(env_cfg["lambda_timeout"])],
                [f"{env_name}.log_retention_days", str(env_cfg["log_retention_days"])],
                [f"{env_name}.api_throttling_burst_limit", str(env_cfg["api_throttling_burst_limit"])],
                [f"{env_name}.api_throttling_rate_limit", str(env_cfg["api_throttling_rate_limit"])],
                [f"{env_name}.cors_allowed_origins", ",".join(env_cfg["cors_allowed_origins"])],
            ]
        )
    return rows



def compact_join(items: tuple[str, ...], limit: int = 2) -> str:
    """Join the first values and summarize any hidden remainder."""

    selected = list(items[:limit])
    if len(items) > limit:
        selected.append(f"+{len(items) - limit} more")
    return "; ".join(selected)


def generated_behavior_summary(control: Control) -> str:
    """Build a one-line cross-layer summary from a control definition."""

    parts = [
        f"Terraform: {control.terraform[0]}",
        f"GitHub: {control.github[0]}",
        f"AWS: {control.aws[0]}",
        f"Scanner: {control.scanners[0]}",
    ]
    return " | ".join(parts)


def control_rows(cfg: dict[str, Any]) -> list[list[str]]:
    """Build control rows with configuration-derived state and behavior."""

    return [
        [
            control.title,
            control_state(cfg, control.id),
            compact_join(control.cli_options),
            generated_behavior_summary(control),
        ]
        for control in control_catalog()
    ]


__all__ = [
    "compact_join",
    "control_rows",
    "env_rows",
    "generated_behavior_summary",
    "preset_detail_rows",
    "preset_rows",
]
