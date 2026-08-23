"""Local, Terraform, AWS, and GitHub diagnostic orchestration."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .aws import collect_aws_checks
from .config import PROJECT_NAME_RE, config_path, prod_approval_environment, validate_config
from .github import collect_branch_checks, collect_github_checks
from .images import collect_image_preflight_checks, is_immutable_image
from .models import Check
from .paths import CONFIG_FILE, GENERATED_TFVARS, REQUIRED_PROJECT_FILES


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run_command(command: list[str], root: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def compact_error(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").strip().splitlines()
    return output[-1] if output else f"Command exited with {result.returncode}."


def collect_checks(
    root: Path,
    cfg: dict[str, Any],
    deep: bool = False,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    run_command_fn: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
    image_preflight_fn: Callable[..., list[Check]] = collect_image_preflight_checks,
    aws_checks_fn: Callable[..., list[Check]] = collect_aws_checks,
) -> list[Check]:
    checks: list[Check] = []
    config_exists = config_path(root).exists()
    checks.append(
        Check(
            "Local config",
            "OK" if config_exists else "WARN",
            str(config_path(root)) if config_exists else f"Run `devsecops init` to create {CONFIG_FILE}.",
        )
    )

    valid_project = bool(PROJECT_NAME_RE.match(cfg["project_name"]))
    checks.append(
        Check(
            "Project name",
            "OK" if valid_project else "FAIL",
            cfg["project_name"] if valid_project else "Must be 3-32 chars: lowercase, digits, hyphens.",
        )
    )

    missing = [path for path in REQUIRED_PROJECT_FILES if not (root / path).exists()]
    checks.append(
        Check(
            "Project files",
            "OK" if not missing else "FAIL",
            "Required files present." if not missing else "Missing: " + ", ".join(missing),
        )
    )

    tool_checks = [("git", False), ("terraform", True)]
    if not deep:
        tool_checks.append(("aws", False))
    for command, required in tool_checks:
        exists = command_exists_fn(command)
        checks.append(
            Check(
                f"`{command}` CLI",
                "OK" if exists else ("FAIL" if required else "WARN"),
                "Installed." if exists else "Not found on PATH.",
            )
        )

    image_uri = cfg["lambda_image_uri"]
    if image_uri and is_immutable_image(image_uri):
        image_status = "OK"
        image_detail = image_uri
    elif image_uri:
        image_status = "FAIL"
        image_detail = "Use an immutable tag or digest, not latest/bootstrap."
    else:
        image_status = "WARN"
        image_detail = "Required before production deploy."
    checks.append(Check("Lambda image URI", image_status, image_detail))
    if image_uri:
        for preflight_check in image_preflight_fn(cfg):
            if preflight_check.name in {"Lambda image shape", "Lambda image region"}:
                checks.append(preflight_check)

    backend_bucket = cfg["backend"]["bucket"]
    backend_ready = backend_bucket and not backend_bucket.startswith("replace-with")
    checks.append(
        Check(
            "Backend bucket",
            "OK" if backend_ready else "WARN",
            backend_bucket if backend_ready else "Set a real S3 state bucket name.",
        )
    )
    checks.append(Check("Backend lock table", "OK", cfg["backend"]["lock_table"]))

    config_failures = [check for check in validate_config(cfg) if check.status == "FAIL"]
    config_policy_gaps = [
        check
        for check in validate_config(cfg)
        if check.name
        in {
            "Lambda image immutability policy",
            "Production CORS policy",
            "Production approval gate policy",
            "Separate plan role policy",
            "Deployment validation policy",
        }
        and check.status in {"WARN", "FAIL"}
    ]
    checks.append(
        Check(
            "Config schema",
            "OK" if not config_failures else "FAIL",
            "Environment settings valid."
            if not config_failures
            else f"{len(config_failures)} invalid setting(s). Run `devsecops validate-config`.",
        )
    )
    checks.append(
        Check(
            "Security policy posture",
            "OK" if not config_policy_gaps else "WARN",
            "No production-risky config values detected."
            if not config_policy_gaps
            else f"{len(config_policy_gaps)} policy gap(s). Run `devsecops config validate --strict`.",
        )
    )

    generated_tfvars = root / GENERATED_TFVARS
    checks.append(
        Check(
            "Rendered tfvars",
            "OK" if generated_tfvars.exists() else "WARN",
            str(generated_tfvars) if generated_tfvars.exists() else "Run `devsecops render`.",
        )
    )

    checks.append(
        Check(
            "Snyk container scan",
            "OK" if cfg["enable_snyk_scan"] else "INFO",
            "Enabled; requires SNYK_TOKEN." if cfg["enable_snyk_scan"] else "Disabled by config.",
            scored=False,
        )
    )
    checks.append(
        Check(
            "HTTP validation",
            "OK" if cfg["enable_http_validation"] else "INFO",
            "Enabled." if cfg["enable_http_validation"] else "Disabled by config.",
            scored=False,
        )
    )
    checks.append(
        Check(
            "Prod approval environment",
            "OK" if cfg["use_prod_approval_environment"] else "INFO",
            f"GitHub environment: {prod_approval_environment(cfg)}",
            scored=False,
        )
    )
    checks.append(
        Check(
            "Separate AWS plan role",
            "OK" if cfg["use_separate_aws_plan_role"] else "WARN",
            "AWS_PLAN_ROLE_TO_ASSUME_ARN is required; deploy role fallback is disabled."
            if cfg["use_separate_aws_plan_role"]
            else "Enable this control; workflows still require AWS_PLAN_ROLE_TO_ASSUME_ARN and do not fall back to the deploy role.",
            scored=False,
        )
    )
    checks.append(
        Check(
            "DAST",
            "OK" if cfg["enable_dast"] else "INFO",
            "Enabled." if cfg["enable_dast"] else "Disabled by config.",
            scored=False,
        )
    )

    if command_exists_fn("git"):
        branch = run_command_fn(["git", "branch", "--show-current"], root).stdout.strip()
        checks.append(
            Check(
                "Git branch",
                "OK" if branch == "main" else "WARN",
                branch or "Not inside a git branch.",
            )
        )

    if deep and command_exists_fn("terraform") and not missing:
        root_validate = run_command_fn(["terraform", "-chdir=terraform", "validate", "-no-color"], root)
        checks.append(
            Check(
                "Terraform validate",
                "OK" if root_validate.returncode == 0 else "FAIL",
                "Root module valid." if root_validate.returncode == 0 else compact_error(root_validate),
            )
        )
        bootstrap_validate = run_command_fn(
            ["terraform", "-chdir=terraform/bootstrap", "validate", "-no-color"],
            root,
        )
        checks.append(
            Check(
                "Bootstrap validate",
                "OK" if bootstrap_validate.returncode == 0 else "FAIL",
                "Bootstrap module valid."
                if bootstrap_validate.returncode == 0
                else compact_error(bootstrap_validate),
            )
        )
    elif deep and missing:
        checks.append(
            Check(
                "Terraform deep checks",
                "INFO",
                "Skipped because required project files are missing.",
                scored=False,
            )
        )

    if deep:
        checks.extend(aws_checks_fn(root, cfg, env_name="prod"))

    return checks



def collect_dashboard_checks(
    root: Path,
    cfg: dict[str, Any],
    mode: str = "full",
    *,
    collect_checks_fn: Callable[..., list[Check]] = collect_checks,
    github_checks_fn: Callable[..., list[Check]] = collect_github_checks,
    branch_checks_fn: Callable[..., list[Check]] = collect_branch_checks,
) -> list[Check]:
    checks = collect_checks_fn(root, cfg, deep=mode == "full")
    if mode == "full":
        checks.extend(github_checks_fn(root, cfg))
        checks.extend(branch_checks_fn(root))
    return checks



__all__ = ["collect_checks", "collect_dashboard_checks", "compact_error"]
