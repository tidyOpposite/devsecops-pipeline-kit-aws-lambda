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

PRODUCTION_DEPLOY_COMMAND = (
    'gh workflow run "Secure Serverless DevSecOps Pipeline" '
    "--ref main -f mode=deploy -f environment=prod"
)


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


def _next_action(
    *,
    action_id: str,
    title: str,
    why: str,
    changes: str,
    command: str,
    docs: str,
    context: dict[str, Any],
    blocked: bool = True,
) -> dict[str, Any]:
    """Build the shared next-action contract used by every CLI surface."""

    return {
        "id": action_id,
        "title": title,
        "detail": why,
        "why": why,
        "changes": changes,
        "command": command,
        "docs": docs,
        "blocked": blocked,
        "context": context,
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
        return _next_action(
            action_id="missing_project_files",
            title="Required project files are missing",
            why="The CLI needs the Terraform modules and GitHub workflows from the DevSecOps pipeline repository.",
            changes="No files will be changed; switch to a complete project checkout before continuing.",
            command="cd <devsecops-pipeline-repository>",
            docs="docs/troubleshooting.md#project-files-are-missing",
            context=context,
        )
    if not context["config_exists"]:
        return _next_action(
            action_id="missing_config",
            title="Local source configuration is missing",
            why=f"{CONFIG_FILE} is the source of truth for rendering and readiness checks.",
            changes=f"Creates {CONFIG_FILE} from the balanced preset; GitHub and AWS are not changed.",
            command="devsecops config new --preset balanced",
            docs="docs/first-successful-pipeline.md",
            context=context,
        )
    if validation_failures:
        return _next_action(
            action_id="missing_config",
            title="Local source configuration is invalid",
            why=f"{len(validation_failures)} invalid config setting(s) block rendering and deployment.",
            changes="Nothing is changed automatically; validation identifies the settings that must be corrected.",
            command="devsecops config validate",
            docs="docs/troubleshooting.md#config-validation-fails",
            context=context,
        )
    image_uri = str(cfg.get("lambda_image_uri", ""))
    if not image_uri or not is_immutable_image(image_uri):
        return _next_action(
            action_id="missing_image",
            title="An immutable Lambda image is not configured",
            why="Production deployment requires a prebuilt Lambda container image identified by an immutable tag or digest.",
            changes="Stores the image URI in local config and regenerates CLI-owned Terraform and GitHub helper artifacts.",
            command="devsecops config set lambda_image_uri <immutable-ecr-image-uri> --render",
            docs="docs/bring-your-own-image.md",
            context=context,
        )
    backend_bucket = str(cfg["backend"]["bucket"])
    if not backend_bucket or backend_bucket.startswith("replace-with"):
        return _next_action(
            action_id="missing_backend",
            title="The Terraform backend bucket is not configured",
            why="A real S3 bucket is required for shared, locked Terraform state before production setup.",
            changes="Updates the local backend bucket setting and regenerates CLI-owned helper artifacts.",
            command="devsecops config set backend.bucket <state-bucket> --render",
            docs="docs/first-successful-pipeline.md#4-configure-terraform-backend",
            context=context,
        )
    if validation_policy_gaps:
        return _next_action(
            action_id="missing_config",
            title="Production security policy gaps remain",
            why=f"{len(validation_policy_gaps)} policy gap(s) prevent the configuration from meeting the production posture.",
            changes="Nothing is changed automatically; strict validation lists every policy setting that needs attention.",
            command="devsecops config validate --strict",
            docs="docs/troubleshooting.md#config-validation-fails",
            context=context,
        )
    if not context["generated_tfvars"] or not context["generated_github_setup"]:
        return _next_action(
            action_id="missing_github_setup",
            title="Generated deployment helpers are missing",
            why="Terraform inputs and the GitHub setup script must be rendered from the validated local configuration.",
            changes="Creates or updates only CLI-owned files under terraform/ and dist/devsecops/.",
            command="devsecops render",
            docs="docs/first-successful-pipeline.md#5-configure-github-repository-settings",
            context=context,
        )
    github_checks = github_checks_fn(root, cfg)
    github_gaps = [check for check in github_checks if check.scored and check.status != "OK"]
    if github_gaps:
        return _next_action(
            action_id="missing_github_setup",
            title="GitHub repository setup is incomplete",
            why=f"{len(github_gaps)} required GitHub authentication, variable, secret, or repository check(s) are not ready.",
            changes="Applies the safe repository variables and role secrets supplied on the command line.",
            command="devsecops github setup --apply --deploy-role-arn <arn> --plan-role-arn <arn>",
            docs="docs/first-successful-pipeline.md#5-configure-github-repository-settings",
            context=context,
        )
    if not command_exists_fn("aws"):
        return _next_action(
            action_id="missing_aws_evidence",
            title="AWS CLI is not available",
            why="The CLI cannot verify AWS identity or deployed resources without the AWS CLI.",
            changes="No project or cloud resources are changed; the command only verifies the active AWS identity after installation.",
            command="aws sts get-caller-identity",
            docs="docs/troubleshooting.md#aws-doctor-cannot-inspect-resources",
            context=context,
        )
    aws_checks = aws_checks_fn(root, cfg, env_name="prod")
    aws_identity = next((check for check in aws_checks if check.name == "AWS identity"), None)
    if aws_identity is not None and aws_identity.status != "OK":
        return _next_action(
            action_id="missing_aws_evidence",
            title="AWS identity is not available",
            why="The active account and role must be verified before inspecting or changing production resources.",
            changes="No resources are changed; the command prints the identity associated with the current AWS credentials.",
            command="aws sts get-caller-identity",
            docs="docs/troubleshooting.md#aws-doctor-cannot-inspect-resources",
            context=context,
        )
    deployed_gaps = [check for check in aws_checks if check.scored and check.status != "OK"]
    if deployed_gaps:
        return _next_action(
            action_id="ready_for_deploy",
            title="Production deployment evidence is missing",
            why="Local and GitHub setup is ready, but deployed AWS resources still need to be created or verified.",
            changes="Triggers the protected production GitHub Actions workflow, which may apply Terraform changes in AWS.",
            command=PRODUCTION_DEPLOY_COMMAND,
            docs="docs/first-successful-pipeline.md#7-run-the-production-workflow-dispatch",
            context=context,
        )
    return _next_action(
        action_id="ready_for_release_evidence",
        title="Production readiness is complete",
        why="Local config, generated artifacts, GitHub setup, and deployed AWS evidence are ready for release-candidate collection.",
        changes="Writes a local release-candidate evidence bundle under dist/devsecops/; GitHub and AWS are not changed.",
        command="devsecops evidence collect --rc",
        docs="docs/v1.0.0-release-candidate-checklist.md",
        context=context,
        blocked=False,
    )


__all__ = ["PRODUCTION_DEPLOY_COMMAND", "missing_project_files", "next_action", "project_context"]
