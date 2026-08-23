"""Project-context detection and next-action workflow."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from .aws import collect_aws_checks
from .config import config_path, load_config, validate_config
from .github import collect_github_checks
from .images import is_immutable_image
from .models import Check
from .paths import CONFIG_FILE, DIST_DIR, GENERATED_TFVARS, REQUIRED_PROJECT_FILES


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def missing_project_files(root: Path) -> list[str]:
    return [path for path in REQUIRED_PROJECT_FILES if not (root / path).exists()]


def project_context(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config(root)
    config_exists = config_path(root).exists()
    missing_files = missing_project_files(root)
    generated_tfvars = (root / GENERATED_TFVARS).exists()
    generated_setup = (root / DIST_DIR / "github-setup.sh").exists()
    has_any_project_signal = config_exists or any((root / path).exists() for path in REQUIRED_PROJECT_FILES) or generated_tfvars or generated_setup

    if not has_any_project_signal and not any(root.iterdir()):
        stage = "empty_directory"
    elif missing_files:
        stage = "installed_cli_not_project_repo" if not has_any_project_signal else "incomplete_project_repo"
    elif not config_exists:
        stage = "project_repo_without_config"
    elif generated_tfvars and generated_setup:
        validation_gaps = [check for check in validate_config(cfg) if check.status in {"WARN", "FAIL"}]
        stage = "production_candidate" if not validation_gaps and not cfg["backend"]["bucket"].startswith("replace-with") else "rendered_project"
    else:
        stage = "configured_project"

    return {
        "stage": stage,
        "config_exists": config_exists,
        "missing_project_files": missing_files,
        "generated_tfvars": generated_tfvars,
        "generated_github_setup": generated_setup,
    }


def next_action(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    command_exists_fn: Callable[[str], bool] = _command_exists,
    github_checks_fn: Callable[..., list[Check]] = collect_github_checks,
    aws_checks_fn: Callable[..., list[Check]] = collect_aws_checks,
) -> dict[str, Any]:
    cfg = cfg or load_config(root)
    context = project_context(root, cfg)
    validation_checks = validate_config(cfg)
    validation_failures = [check for check in validation_checks if check.status == "FAIL"]
    validation_policy_gaps = [
        check
        for check in validation_checks
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

    if context["missing_project_files"]:
        return {
            "id": "missing_project_files",
            "title": "Missing project files",
            "detail": "Run this command inside the DevSecOps pipeline repo/template or copy the required Terraform and GitHub workflow files.",
            "command": "Use the DevSecOps pipeline repository/template, then rerun `devsecops next`.",
            "docs": "docs/troubleshooting.md#project-files-are-missing",
            "context": context,
        }
    if not context["config_exists"]:
        return {
            "id": "missing_config",
            "title": "Create local source config",
            "detail": f"{CONFIG_FILE} is missing.",
            "command": "devsecops config new --preset balanced",
            "docs": "docs/first-successful-pipeline.md",
            "context": context,
        }
    if validation_failures:
        return {
            "id": "missing_config",
            "title": "Fix invalid config",
            "detail": f"{len(validation_failures)} invalid config setting(s) block the pipeline.",
            "command": "devsecops config validate",
            "docs": "docs/troubleshooting.md#config-validation-fails",
            "context": context,
        }
    image_uri = str(cfg.get("lambda_image_uri", ""))
    if not image_uri or not is_immutable_image(image_uri):
        return {
            "id": "missing_image",
            "title": "Set immutable Lambda image",
            "detail": "Production deploy requires an immutable Lambda container image URI.",
            "command": "devsecops preflight --image-uri <immutable-ecr-image-uri> && devsecops config set lambda_image_uri <immutable-ecr-image-uri> --render",
            "docs": "docs/bring-your-own-image.md",
            "context": context,
        }
    backend_bucket = str(cfg["backend"]["bucket"])
    if not backend_bucket or backend_bucket.startswith("replace-with"):
        return {
            "id": "missing_backend",
            "title": "Configure Terraform backend",
            "detail": "Set a real S3 backend bucket before GitHub/AWS production setup.",
            "command": "devsecops config set backend.bucket <state-bucket> --render",
            "docs": "docs/first-successful-pipeline.md#4-configure-terraform-backend",
            "context": context,
        }
    if validation_policy_gaps:
        return {
            "id": "missing_config",
            "title": "Close production policy gaps",
            "detail": f"{len(validation_policy_gaps)} production policy gap(s) remain.",
            "command": "devsecops config validate --strict",
            "docs": "docs/troubleshooting.md#config-validation-fails",
            "context": context,
        }
    if not context["generated_tfvars"] or not context["generated_github_setup"]:
        return {
            "id": "missing_github_setup",
            "title": "Prepare GitHub setup",
            "detail": "Render helper artifacts before configuring repository variables/secrets with GitHub CLI.",
            "command": "devsecops render && devsecops github setup --write",
            "docs": "docs/first-successful-pipeline.md#5-configure-github-repository-settings",
            "context": context,
        }
    github_checks = github_checks_fn(root, cfg)
    github_gaps = [check for check in github_checks if check.scored and check.status != "OK"]
    if github_gaps:
        return {
            "id": "missing_github_setup",
            "title": "Complete GitHub setup",
            "detail": f"{len(github_gaps)} GitHub setup check(s) still need attention.",
            "command": "devsecops doctor github --strict && devsecops github setup --apply --deploy-role-arn <arn> --plan-role-arn <arn>",
            "docs": "docs/first-successful-pipeline.md#5-configure-github-repository-settings",
            "context": context,
        }
    if not command_exists_fn("aws"):
        return {
            "id": "missing_aws_evidence",
            "title": "Install or configure AWS CLI",
            "detail": "AWS evidence cannot be collected until AWS CLI is installed and authenticated.",
            "command": "aws sts get-caller-identity && devsecops doctor aws --environment prod --strict",
            "docs": "docs/troubleshooting.md#aws-doctor-cannot-inspect-resources",
            "context": context,
        }
    aws_checks = aws_checks_fn(root, cfg, env_name="prod")
    aws_identity = next((check for check in aws_checks if check.name == "AWS identity"), None)
    if aws_identity is not None and aws_identity.status != "OK":
        return {
            "id": "missing_aws_evidence",
            "title": "Collect AWS identity evidence",
            "detail": "AWS CLI is installed, but account evidence is not available yet.",
            "command": "aws sts get-caller-identity && devsecops doctor aws --environment prod --strict",
            "docs": "docs/troubleshooting.md#aws-doctor-cannot-inspect-resources",
            "context": context,
        }
    deployed_gaps = [check for check in aws_checks if check.scored and check.status != "OK"]
    if deployed_gaps:
        return {
            "id": "ready_for_deploy",
            "title": "Ready for deploy dispatch",
            "detail": "Local setup is ready enough to start or inspect the production workflow; deployed AWS evidence is not complete yet.",
            "command": "gh workflow run \"Secure Serverless DevSecOps Pipeline\" --ref main -f mode=deploy -f environment=prod",
            "docs": "docs/first-successful-pipeline.md#7-run-the-production-workflow-dispatch",
            "context": context,
        }
    return {
        "id": "ready_for_release_evidence",
        "title": "Ready for release evidence",
        "detail": "Local config, project files, generated artifacts, GitHub tooling, and AWS deployed evidence are ready for RC collection.",
        "command": "devsecops evidence collect --rc",
        "docs": "docs/v1.0.0-release-candidate-checklist.md",
        "context": context,
    }


__all__ = ["missing_project_files", "next_action", "project_context"]
