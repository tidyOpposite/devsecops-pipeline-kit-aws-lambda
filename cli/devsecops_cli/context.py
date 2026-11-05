"""Project-context detection and prioritized next-action workflow.

This module converts filesystem, configuration, GitHub, and AWS observations
into one shared action contract.  It does not perform the suggested mutation;
CLI surfaces decide how and when to present or execute the returned command.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from .aws import LAMBDA_NOT_DEPLOYED, collect_aws_checks
from .config import config_path, load_config, validate_config
from .github import collect_github_checks
from .images import is_immutable_image
from .models import Check
from .paths import CONFIG_FILE, DIST_DIR, GENERATED_TFVARS, REQUIRED_PROJECT_FILES
from .readiness import WORKLOAD_CHECKS, deployment_gate
from .render import generated_artifact_gaps

PRODUCTION_DEPLOY_COMMAND = "devsecops deploy prod"


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def missing_project_files(root: Path) -> list[str]:
    """Return required repository paths that are absent below ``root``."""

    return [path for path in REQUIRED_PROJECT_FILES if not (root / path).exists()]


def project_context(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify local project maturity from source and generated-file signals.

    Stages are descriptive rather than readiness decisions.  External GitHub
    and AWS evidence is intentionally deferred to :func:`next_action`.
    """

    cfg = cfg or load_config(root)
    config_exists = config_path(root).exists()
    missing_files = missing_project_files(root)
    generated_tfvars = (root / GENERATED_TFVARS).exists()
    generated_setup = (root / DIST_DIR / "github-setup.sh").exists()
    # A partial repository must not be mistaken for a fresh empty directory;
    # any owned source or generated artifact counts as a project signal.
    has_any_project_signal = config_exists or any((root / path).exists() for path in REQUIRED_PROJECT_FILES) or generated_tfvars or generated_setup

    if not has_any_project_signal and not any(root.iterdir()):
        stage = "empty_directory"
    elif missing_files:
        stage = "installed_cli_not_project_repo" if not has_any_project_signal else "incomplete_project_repo"
    elif not config_exists:
        stage = "project_repo_without_config"
    elif generated_tfvars and generated_setup:
        # Generated files alone do not make a production candidate: warning
        # policies and placeholder backend values still require remediation.
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
    observations: list[Check] | None = None,
    local_only: bool = False,
    pre_deploy: bool = False,
) -> dict[str, Any]:
    """Return the highest-priority action that advances project readiness.

    Local prerequisites and security policy are evaluated before external
    tools.  This ordering prevents noisy provider checks from obscuring an
    earlier condition that the user can resolve locally.
    """

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

    # The order below is part of the user journey: each returned action should
    # unlock the checks that follow it, so only one recommendation is needed.
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
            why=f"{CONFIG_FILE} is the source of truth for generated deployment files and status checks.",
            changes=f"Creates {CONFIG_FILE} from the balanced preset; GitHub and AWS are not changed.",
            command="devsecops setup --preset balanced --yes",
            docs="docs/first-successful-pipeline.md",
            context=context,
        )
    if validation_failures:
        return _next_action(
            action_id="missing_config",
            title="Local source configuration is invalid",
            why=f"{len(validation_failures)} invalid config setting(s) block deployment-file generation and deployment.",
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
            changes="Stores the image URI in local config; GitHub and AWS are not changed.",
            command="devsecops config set lambda_image_uri <immutable-ecr-image-uri>",
            docs="docs/bring-your-own-image.md",
            context=context,
        )
    backend_bucket = str(cfg["backend"]["bucket"])
    if not backend_bucket or backend_bucket.startswith("replace-with"):
        return _next_action(
            action_id="missing_backend",
            title="The Terraform backend bucket is not configured",
            why="A real S3 bucket is required for shared, locked Terraform state before production setup.",
            changes="Updates the local backend bucket setting; GitHub and AWS are not changed.",
            command="devsecops config set backend.bucket <state-bucket>",
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
    if generated_artifact_gaps(root, cfg):
        return _next_action(
            action_id="missing_github_setup",
            title="Generated deployment helpers are missing or outdated",
            why="Deployment files must match the current local configuration.",
            changes="Creates or updates only CLI-owned files under terraform/ and dist/devsecops/.",
            command="devsecops generate",
            docs="docs/first-successful-pipeline.md#5-configure-github-repository-settings",
            context=context,
        )
    if observations is not None:
        local_gaps = [check for check in observations if check.scored and check.status != "OK" and check.name in {
            "Terraform validate", "Bootstrap validate", "Git branch", "`terraform` CLI", "`git` CLI", "Config schema",
        }]
        if local_gaps:
            return _next_action(
                action_id="local_checks_failed", title="Local deployment checks need attention",
                why="; ".join(f"{check.name}: {check.detail}" for check in local_gaps),
                changes="Read-only diagnostics for the failed local prerequisites.",
                command="devsecops doctor local --deep --strict", docs="docs/troubleshooting.md", context=context,
            )
    if not command_exists_fn("gh"):
        return _next_action(
            action_id="missing_github_cli",
            title="GitHub CLI is not available",
            why="The protected setup and deployment commands require GitHub CLI before repository state can be inspected or changed.",
            changes="Install GitHub CLI locally, then authenticate it; no repository or AWS resources are changed by this check.",
            command="gh auth login  # after installing https://cli.github.com/",
            docs="docs/troubleshooting.md#github-doctor-cannot-inspect-the-repository",
            context=context,
        )
    if local_only:
        return _next_action(
            action_id="verify_cloud", title="Deployment prerequisites need verification",
            why="GitHub approvals, Terraform validation, and AWS resources need a fresh inspection.",
            changes="Read-only checks of the deployment repository and AWS account.",
            command="devsecops status --pre-deploy --strict", docs="docs/first-successful-pipeline.md", context=context,
        )
    github_checks = ([check for check in observations if check.name.startswith(("GitHub", "Branch `", "Required check"))]
                     if observations is not None else github_checks_fn(root, cfg))
    github_by_name = {check.name: check for check in github_checks}
    github_auth = github_by_name.get("GitHub auth")
    if github_auth is not None and github_auth.status != "OK":
        return _next_action(
            action_id="missing_github_auth",
            title="GitHub CLI is not authenticated",
            why="The CLI must authenticate before it can inspect or apply repository variables, secrets, and workflow runs.",
            changes="Authenticates GitHub CLI on this machine; the DevSecOps CLI does not write repository or AWS settings in this step.",
            command="gh auth login",
            docs="docs/troubleshooting.md#github-doctor-cannot-inspect-the-repository",
            context=context,
        )
    # Informational provider observations must not block progress; only checks
    # explicitly included in readiness scoring become actionable gaps.
    github_gaps = [check for check in github_checks if check.scored and check.status != "OK"]
    if github_gaps:
        if all(check.name == "GitHub OIDC roles" for check in github_gaps):
            repository = github_by_name.get("GitHub repository")
            target = repository.detail if repository is not None and repository.status == "OK" else "<owner/repo>"
            return _next_action(
                action_id="missing_oidc_verification", title="OIDC roles need verification",
                why=github_gaps[0].detail, changes="Runs separate plan and prod identity checks with environment approval.",
                command=f"gh workflow run verify-oidc.yml --ref main --repo {target}",
                docs="AWS_policy.md#verify-role-setup", context=context,
            )
        approval_gap = next((check for check in github_gaps if check.name == "GitHub environment approvals"), None)
        if approval_gap:
            return _next_action(
                action_id="missing_github_approvals", title="Production environment protection is not verified",
                why=approval_gap.detail, changes="Read-only inspection of GitHub Environment prod protection rules.",
                command="devsecops doctor github --strict", docs="docs/first-successful-pipeline.md#5-configure-github-repository-settings", context=context,
            )
        branch_gaps = [check for check in github_gaps if check.name.startswith(("Branch `", "Required check"))]
        if branch_gaps:
            return _next_action(
                action_id="missing_branch_protection", title="Production branch protection is incomplete",
                why="; ".join(check.detail for check in branch_gaps),
                changes="Read-only inspection of branch rules; configure the reported requirements in GitHub.",
                command="devsecops doctor branch --strict", docs="docs/troubleshooting.md#branch-protection-doctor-reports-missing-checks", context=context,
            )
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
    aws_names = {"AWS CLI", "AWS identity", "State bucket", "Lock table", "ECR repository", "Lambda execution role",
                 "Lambda function", "API Gateway", "CloudWatch log group", "Configured ECR image"}
    aws_checks = ([check for check in observations if check.name in aws_names]
                  if observations is not None else aws_checks_fn(root, cfg, env_name="prod"))
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
    backend_gaps = [check for check in aws_checks if check.name in {"State bucket", "Lock table"} and check.status != "OK"]
    if backend_gaps:
        return _next_action(
            action_id="missing_backend_resources", title="Terraform backend is not ready",
            why="; ".join(check.detail for check in backend_gaps),
            changes="Previews the backend infrastructure plan; no resources are applied.",
            command="devsecops terraform bootstrap", docs="docs/first-successful-pipeline.md#4-configure-terraform-backend", context=context,
        )
    if observations is None:
        return _next_action(
            action_id="verify_cloud", title="Complete deployment readiness verification",
            why="Terraform, GitHub and AWS prerequisites need to be checked together.",
            changes="Read-only checks of the deployment prerequisites.",
            command="devsecops status --pre-deploy --strict", docs="docs/first-successful-pipeline.md", context=context,
        )
    prerequisites, detail = deployment_gate(observations, pre_deploy=True)
    if prerequisites != "OK":
        return _next_action(
            action_id="readiness_gaps", title="Deployment prerequisites need attention",
            why=detail, changes="Read-only diagnosis of the deployment prerequisites.",
            command="devsecops status --pre-deploy --strict", docs="docs/troubleshooting.md", context=context,
        )
    lambda_absent = any(
        check.name == "Lambda function" and check.status == "WARN" and check.detail == LAMBDA_NOT_DEPLOYED
        for check in observations
    )
    if pre_deploy or lambda_absent:
        return _next_action(
            action_id="ready_for_deploy",
            title="Ready to deploy",
            why="Local, GitHub and AWS prerequisites are verified. Review the exact inputs and workflow before dispatch.",
            changes="Read-only preview of the pinned production deployment.",
            command=PRODUCTION_DEPLOY_COMMAND + " --dry-run",
            docs="docs/first-successful-pipeline.md#7-run-the-production-workflow-dispatch",
            context=context,
            blocked=False,
        )
    deployed, detail = deployment_gate(observations, pre_deploy=False)
    if deployed != "OK":
        workload_gaps = [
            f"{check.name}: {check.detail}"
            for check in observations if check.name in WORKLOAD_CHECKS and check.status != "OK"
        ]
        return _next_action(
            action_id="readiness_gaps", title="Production workload verification is incomplete",
            why="; ".join(workload_gaps) or detail,
            changes="Read-only workload inspection and health probe.",
            command="devsecops status --deep --strict", docs="docs/troubleshooting.md", context=context,
        )
    return _next_action(
        action_id="ready_for_release_evidence",
        title="Deployed and healthy",
        why="AWS workload resources were verified and /health returned HTTP 2xx.",
        changes="Writes a local release-candidate evidence bundle under dist/devsecops/; GitHub and AWS are not changed.",
        command="devsecops evidence collect --rc",
        docs="docs/v1.0.0-release-candidate-checklist.md",
        context=context,
        blocked=False,
    )


__all__ = ["PRODUCTION_DEPLOY_COMMAND", "missing_project_files", "next_action", "project_context"]
