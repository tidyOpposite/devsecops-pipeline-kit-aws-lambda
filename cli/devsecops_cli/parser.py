"""Argument parser construction for the public CLI contract."""

from __future__ import annotations

import argparse
import textwrap
from typing import Any

from . import VERSION
from .config import ENVIRONMENTS, PRESET_ORDER
from .github import DEFAULT_BRANCH
from .paths import PRODUCTION_EVIDENCE_DIR, RC_EVIDENCE_DIR
from .setup import SETUP_MODES

COMPLETION_SHELLS = ("bash", "zsh", "fish")


def _help_epilog(examples: tuple[str, ...], side_effects: tuple[str, ...]) -> str:
    example_lines = "\n".join(f"  {line}" for line in examples)
    effect_lines = "\n".join(
        textwrap.fill(line, width=78, initial_indent="  ", subsequent_indent="  ")
        for line in side_effects
    )
    return f"Examples:\n{example_lines}\n\nSide effects:\n{effect_lines}"


def build_parser(handlers: Any) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devsecops",
        description="CLI product for setting up, validating, deploying, and operating a secure AWS Lambda delivery pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Product boundary:
              The CLI owns local config and generated helper artifacts.
              Terraform, GitHub Actions, AWS, and scanners are transparent execution layers.

            Recommended three-command first run:
              devsecops setup --preset balanced --yes
              devsecops status
              devsecops dry-run --image-uri <immutable-ecr-image-uri>

            `devsecops` without arguments shows compact status and one next action.
            Human-readable commands finish with the same recommended next step.

            Docs:
              README.md
              docs/command-inventory.md
              docs/generated-artifacts.md

            Advanced maintainer commands:
              devsecops inventory --format json
              devsecops criteria --strict
              devsecops evidence collect --rc

            Legacy aliases still work:
              start, next, readiness, dashboard, preflight, render,
              init, set, validate-config, snapshots, rollback,
              github-setup, gh-doctor, aws-doctor, actions-status, branch-doctor,
              plan, bootstrap

            Additional documented hidden commands:
              preset, envs, controls, architecture, compose (experimental),
              tui (experimental)

            Additional stable operations remain callable and documented in the command inventory.

            Stability contract:
              Stable command flags and JSON kinds are listed by `devsecops inventory`.
              Experimental commands are excluded from the first-success workflow.

            Stable exit codes:
              0 ok, 1 validation failed, 2 missing external tool,
              3 authentication failed, 70 unexpected runtime error, 130 interrupted
            """
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{menu,setup,status,deploy,dry-run,generate,doctor,config}",
    )
    parser.set_defaults(func=handlers.cmd_overview)

    menu_parser = subparsers.add_parser(
        "menu",
        help="Open the simplified interactive product menu.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops menu",),
            (
                "Opening the menu changes nothing.",
                "Any selected write or provider action shows its own boundary before execution.",
            ),
        ),
    )
    menu_parser.set_defaults(func=handlers.cmd_menu)

    status_parser = subparsers.add_parser(
        "status",
        help="Show project status and the single recommended next action.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops status", "devsecops status --deep --strict"),
            ("Read-only; deep mode may query Terraform, GitHub, and AWS but never changes them.",),
        ),
    )
    status_parser.add_argument("--deep", action="store_true", help="Include GitHub, AWS, and deep Terraform checks.")
    status_parser.add_argument("--strict", action="store_true", help="Exit non-zero when a scored status gap remains.")
    status_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    status_parser.add_argument("--watch", action="store_true", help="Auto-refresh human status until interrupted.")
    status_parser.add_argument("--interval", type=int, default=5, help="Seconds between status refreshes in watch mode.")
    status_parser.set_defaults(func=handlers.cmd_status)

    dashboard_parser = subparsers.add_parser("dashboard", help=argparse.SUPPRESS)
    dashboard_parser.add_argument("--watch", action="store_true", help="Auto-refresh the dashboard until interrupted.")
    dashboard_parser.add_argument("--interval", type=int, default=5, help="Seconds between dashboard refreshes in watch mode.")
    dashboard_parser.add_argument("--mode", choices=["compact", "full"], default="full", help="Dashboard detail level.")
    dashboard_parser.set_defaults(func=handlers.cmd_dashboard)

    completion_parser = subparsers.add_parser("completion", help=argparse.SUPPRESS)
    completion_parser.add_argument("shell", choices=COMPLETION_SHELLS, help="Shell completion format to print.")
    completion_parser.add_argument("--program", default="devsecops", help="Program name to complete.")
    completion_parser.set_defaults(func=handlers.cmd_completion)

    inventory_parser = subparsers.add_parser("inventory", help=argparse.SUPPRESS)
    inventory_parser.add_argument("--format", choices=["human", "markdown", "json"], default="human", help="Output mode.")
    inventory_parser.add_argument("--status", choices=["all", "stable", "alias", "experimental", "support"], default="all", help="Command status filter.")
    inventory_parser.set_defaults(func=handlers.cmd_inventory)

    next_parser = subparsers.add_parser("next", help=argparse.SUPPRESS)
    next_parser.add_argument("--format", choices=["human", "json"], default="human", help="Output mode.")
    next_parser.set_defaults(func=handlers.cmd_next)

    setup_parser = subparsers.add_parser(
        "setup",
        help="Start or resume the guided project setup state machine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            (
                "devsecops setup --mode demo --yes",
                "devsecops setup --mode standard --image-uri <immutable-ecr-image-uri>",
            ),
            (
                "May write local config and .devsecops/setup-state.json.",
                "Only --apply-github changes repository variables or encrypted secrets.",
                "Never starts a workflow or deploys AWS resources.",
            ),
        ),
    )
    setup_parser.add_argument("--mode", choices=SETUP_MODES, help="Setup depth: local demo, standard cloud connection, or production.")
    setup_parser.add_argument("--preset", choices=PRESET_ORDER, help="Advanced preset override used only when creating config.")
    setup_parser.add_argument("--image-uri", help="Existing immutable ECR Lambda image URI to save in local config.")
    setup_parser.add_argument("--backend-bucket", help="Existing or planned S3 Terraform state bucket name.")
    setup_parser.add_argument("--backend-region", help="AWS region for the Terraform state backend.")
    setup_parser.add_argument("--backend-lock-table", help="DynamoDB table used for Terraform state locking.")
    setup_parser.add_argument("--apply-github", action="store_true", help="Apply GitHub variables and encrypted secrets; changes the current repository.")
    setup_parser.add_argument("--deploy-role-arn", help="AWS deploy role ARN used only with --apply-github.")
    setup_parser.add_argument("--plan-role-arn", help="Separate AWS plan role ARN used only with --apply-github.")
    setup_parser.add_argument("--snyk-token", help="Snyk token used only with --apply-github; never stored in setup progress.")
    setup_parser.add_argument("--generate", dest="render", action="store_true", help="Generate local deployment files from the resulting config.")
    setup_parser.add_argument("--yes", action="store_true", help="Use safe local defaults without prompts; does not imply --apply-github.")
    setup_parser.add_argument("--strict", action="store_true", help="Exit non-zero while a required setup stage remains incomplete.")
    setup_parser.set_defaults(func=handlers.cmd_setup)

    start_parser = subparsers.add_parser("start", help=argparse.SUPPRESS)
    start_parser.add_argument("--preset", choices=PRESET_ORDER, help="Preset to use when creating config.")
    start_parser.add_argument("--render", action="store_true", help="Render artifacts after config exists.")
    start_parser.add_argument("--yes", action="store_true", help="Create missing config without prompting.")
    start_parser.set_defaults(func=handlers.cmd_start)

    criteria_parser = subparsers.add_parser("criteria", help=argparse.SUPPRESS)
    criteria_parser.add_argument("--format", choices=["human", "json"], default="human", help="Output mode.")
    criteria_parser.add_argument(
        "--evidence-dir",
        help=f"Production evidence directory. Defaults to {PRODUCTION_EVIDENCE_DIR}/v{VERSION}.",
    )
    criteria_parser.add_argument("--strict", action="store_true", help="Exit non-zero until all criteria and stable-release gates are OK.")
    criteria_parser.set_defaults(func=handlers.cmd_criteria)

    evidence_parser = subparsers.add_parser("evidence", help=argparse.SUPPRESS)
    evidence_parser.set_defaults(func=handlers.cmd_evidence)
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_command", metavar="{collect}")
    evidence_collect_parser = evidence_subparsers.add_parser("collect", help="Collect local release-candidate evidence artifacts.")
    evidence_collect_parser.add_argument("--rc", action="store_true", help="Collect v1.0 release-candidate evidence.")
    evidence_collect_parser.add_argument("--output", help=f"Output directory. Defaults to {RC_EVIDENCE_DIR}.")
    evidence_collect_parser.set_defaults(func=handlers.cmd_evidence)

    tui_parser = subparsers.add_parser("tui", help=argparse.SUPPRESS)
    tui_parser.set_defaults(func=handlers.cmd_tui)

    envs_parser = subparsers.add_parser("envs", help=argparse.SUPPRESS)
    envs_parser.set_defaults(func=handlers.cmd_envs)

    controls_parser = subparsers.add_parser("controls", help=argparse.SUPPRESS)
    controls_parser.add_argument("--format", choices=["human", "json"], default="human", help="Output mode.")
    controls_parser.set_defaults(func=handlers.cmd_controls)

    architecture_parser = subparsers.add_parser("architecture", help=argparse.SUPPRESS)
    architecture_parser.set_defaults(func=handlers.cmd_architecture)

    init_parser = subparsers.add_parser("init", help=argparse.SUPPRESS)
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config without asking.")
    init_parser.add_argument("--defaults", action="store_true", help="Write default config without prompts.")
    init_parser.set_defaults(func=handlers.cmd_init)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run local, GitHub, AWS, branch, or Actions diagnostics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops doctor", "devsecops doctor all --deep --strict"),
            ("Read-only; provider diagnostics inspect observable state without changing it.",),
        ),
    )
    doctor_parser.add_argument("--deep", action="store_true", help="Run Terraform validate and AWS resource checks.")
    doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    doctor_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    doctor_parser.set_defaults(func=handlers.cmd_doctor, doctor_command="local")
    doctor_subparsers = doctor_parser.add_subparsers(dest="doctor_command", metavar="{local,github,aws,branch,actions,all}")

    doctor_local_parser = doctor_subparsers.add_parser("local", help="Check local config, files, tools, and deployment-file state.")
    doctor_local_parser.add_argument("--deep", action="store_true", help="Run Terraform validate and AWS resource checks.")
    doctor_local_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    doctor_local_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    doctor_local_parser.set_defaults(func=handlers.cmd_doctor)

    doctor_github_parser = doctor_subparsers.add_parser("github", help="Check GitHub CLI, repository variables, and secrets.")
    doctor_github_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    doctor_github_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    doctor_github_parser.set_defaults(func=handlers.cmd_doctor)

    doctor_aws_parser = doctor_subparsers.add_parser("aws", help="Check AWS identity, backend, and deployed resources.")
    doctor_aws_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="Environment resources to inspect.")
    doctor_aws_parser.add_argument("--strict", action="store_true", help="Exit non-zero on WARN or FAIL scored checks.")
    doctor_aws_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    doctor_aws_parser.set_defaults(func=handlers.cmd_doctor)

    doctor_branch_parser = doctor_subparsers.add_parser("branch", help="Check branch protection and required checks.")
    doctor_branch_parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch to inspect.")
    doctor_branch_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    doctor_branch_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    doctor_branch_parser.set_defaults(func=handlers.cmd_doctor)

    doctor_actions_parser = doctor_subparsers.add_parser("actions", help="Show recent GitHub Actions runs and failed jobs.")
    doctor_actions_parser.add_argument("--strict", action="store_true", help="Exit non-zero when status cannot be read.")
    doctor_actions_parser.add_argument("--limit", type=int, default=8, help="Number of workflow runs to inspect.")
    doctor_actions_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    doctor_actions_parser.set_defaults(func=handlers.cmd_doctor)

    doctor_all_parser = doctor_subparsers.add_parser("all", help="Run local, GitHub, branch, and AWS checks together.")
    doctor_all_parser.add_argument("--deep", action="store_true", help="Run Terraform validate in local checks.")
    doctor_all_parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch to inspect.")
    doctor_all_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="AWS environment resources to inspect.")
    doctor_all_parser.add_argument("--strict", action="store_true", help="Exit non-zero on WARN or FAIL scored checks.")
    doctor_all_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    doctor_all_parser.set_defaults(func=handlers.cmd_doctor)

    readiness_parser = subparsers.add_parser("readiness", help=argparse.SUPPRESS)
    readiness_parser.add_argument("--deep", action="store_true", help="Include Terraform/AWS deep checks.")
    readiness_parser.add_argument("--strict", action="store_true", help="Exit non-zero on any scored readiness gap.")
    readiness_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    readiness_parser.set_defaults(func=handlers.cmd_readiness)

    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Preview the first-success path without writing files or requiring AWS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops dry-run --image-uri <immutable-ecr-image-uri>",),
            ("No files, repository settings, Terraform state, or AWS resources are changed.",),
        ),
    )
    dry_run_parser.add_argument("--preset", choices=PRESET_ORDER, default="balanced", help="Preset to preview when no local config exists.")
    dry_run_parser.add_argument("--image-uri", help="Immutable ECR image URI to preview without writing it to config.")
    dry_run_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="Environment target for image naming checks.")
    dry_run_parser.set_defaults(func=handlers.cmd_dry_run)

    image_parser = subparsers.add_parser("image", help=argparse.SUPPRESS)
    image_parser.set_defaults(func=handlers.cmd_preflight, image_command="validate", image_uri=None, environment="prod", format="human")
    image_subparsers = image_parser.add_subparsers(dest="image_command", metavar="{validate}")
    image_validate_parser = image_subparsers.add_parser("validate", help="Validate image URI, immutability, region, and repository naming.")
    image_validate_parser.add_argument("--image-uri", help="Image URI to validate. Defaults to lambda_image_uri from local config.")
    image_validate_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="Environment target for image naming checks.")
    image_validate_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    image_validate_parser.set_defaults(func=handlers.cmd_preflight)

    preflight_parser = subparsers.add_parser("preflight", help=argparse.SUPPRESS)
    preflight_parser.add_argument("--image-uri", help="Image URI to check. Defaults to lambda_image_uri from local config.")
    preflight_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="Environment target for image naming checks.")
    preflight_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    preflight_parser.set_defaults(func=handlers.cmd_preflight)

    health_parser = subparsers.add_parser("health", help=argparse.SUPPRESS)
    health_parser.add_argument("--url", help="Health URL to check. Defaults to Terraform output api_gateway_health_url.")
    health_parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    health_parser.add_argument("--aws-sigv4", action="store_true", help="Sign the health request with AWS SigV4 for IAM-protected API Gateway routes.")
    health_parser.add_argument("--aws-region", help="AWS region to use for SigV4 signing. Defaults to AWS_REGION or AWS_DEFAULT_REGION.")
    health_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    health_parser.set_defaults(func=handlers.cmd_health)

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Start, inspect, troubleshoot, or roll back the protected production deployment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            (
                "devsecops deploy prod --dry-run",
                "devsecops deploy status --watch",
                "devsecops deploy logs --failed",
                "devsecops deploy rollback --dry-run",
            ),
            (
                "status and logs are read-only.",
                "prod and rollback dispatch the protected GitHub Actions workflow only after preflight and confirmation.",
            ),
        ),
    )
    deploy_parser.set_defaults(
        func=handlers.cmd_deploy,
        deploy_command="status",
        run_id=None,
        watch=False,
        interval=5,
        format="human",
    )
    deploy_subparsers = deploy_parser.add_subparsers(
        dest="deploy_command",
        metavar="{prod,status,logs,rollback}",
    )

    deploy_prod_parser = deploy_subparsers.add_parser(
        "prod",
        help="Dispatch the protected production workflow after readiness checks and confirmation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops deploy prod --dry-run", "devsecops deploy prod --watch"),
            (
                "Preflight and --dry-run are read-only.",
                "A confirmed run dispatches the protected workflow with the exact immutable image; the local CLI never writes AWS directly.",
            ),
        ),
    )
    deploy_prod_parser.add_argument("--dry-run", action="store_true", help="Run preflight and show the underlying command without dispatching it.")
    deploy_prod_parser.add_argument("--yes", action="store_true", help="Skip the explicit production confirmation prompt.")
    deploy_prod_parser.add_argument("--watch", action="store_true", help="Wait for the dispatched workflow and return its conclusion.")
    deploy_prod_parser.add_argument("--interval", type=int, default=5, help="Status refresh interval in seconds; minimum 3.")
    deploy_prod_parser.set_defaults(func=handlers.cmd_deploy)

    deploy_status_parser = deploy_subparsers.add_parser(
        "status",
        help="Show the matching deployment run, jobs, images, and next recovery action.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops deploy status", "devsecops deploy status --watch --format json"),
            ("Read-only; may wait for and inspect GitHub Actions and the active Lambda image.",),
        ),
    )
    deploy_status_parser.add_argument("--run-id", help="Inspect a specific deployment workflow run ID.")
    deploy_status_parser.add_argument("--watch", action="store_true", help="Wait for an active run and return its conclusion.")
    deploy_status_parser.add_argument("--interval", type=int, default=5, help="Status refresh interval in seconds; minimum 3.")
    deploy_status_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    deploy_status_parser.set_defaults(func=handlers.cmd_deploy)

    deploy_logs_parser = deploy_subparsers.add_parser(
        "logs",
        help="Show full or failed-step logs for the matching deployment run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops deploy logs", "devsecops deploy logs --failed"),
            ("Read-only; streams GitHub Actions logs without changing repository or cloud state.",),
        ),
    )
    deploy_logs_parser.add_argument("--run-id", help="Read logs for a specific deployment workflow run ID.")
    deploy_logs_parser.add_argument("--failed", action="store_true", help="Show failed-step logs instead of the full workflow log.")
    deploy_logs_parser.set_defaults(func=handlers.cmd_deploy)

    deploy_rollback_parser = deploy_subparsers.add_parser(
        "rollback",
        help="Dispatch a protected rollback to the previous recorded or explicitly supplied image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            (
                "devsecops deploy rollback --dry-run",
                "devsecops deploy rollback --image-uri <known-good-immutable-ecr-image-uri>",
            ),
            (
                "Preflight and --dry-run are read-only.",
                "A confirmed rollback dispatches the protected workflow; it never performs a direct local Lambda update.",
            ),
        ),
    )
    deploy_rollback_parser.add_argument("--run-id", help="Roll back the deployment recorded for this workflow run ID.")
    deploy_rollback_parser.add_argument("--image-uri", help="Explicit immutable ECR image URI to restore.")
    deploy_rollback_parser.add_argument("--dry-run", action="store_true", help="Run rollback preflight without dispatching a workflow.")
    deploy_rollback_parser.add_argument("--yes", action="store_true", help="Skip the explicit rollback confirmation prompt.")
    deploy_rollback_parser.add_argument("--watch", action="store_true", help="Wait for the rollback workflow and return its conclusion.")
    deploy_rollback_parser.add_argument("--interval", type=int, default=5, help="Status refresh interval in seconds; minimum 3.")
    deploy_rollback_parser.set_defaults(func=handlers.cmd_deploy)

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate CLI-owned Terraform and GitHub deployment files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            ("devsecops generate --dry-run", "devsecops generate"),
            (
                "Writes only documented CLI-owned files under terraform/ and dist/devsecops/.",
                "Does not apply Terraform or change GitHub/AWS.",
            ),
        ),
    )
    generate_parser.add_argument("--dry-run", action="store_true", help="Preview generated files without writing them.")
    generate_parser.set_defaults(func=handlers.cmd_render)

    render_parser = subparsers.add_parser("render", help=argparse.SUPPRESS)
    render_parser.add_argument("--dry-run", action="store_true", help="Preview generated files without writing them.")
    render_parser.set_defaults(func=handlers.cmd_render)

    report_parser = subparsers.add_parser("report", help=argparse.SUPPRESS)
    report_parser.add_argument("--deep", action="store_true", help="Include Terraform/AWS deep checks.")
    report_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Report output format.")
    report_parser.add_argument("--output", help="Report output path. Defaults to dist/devsecops/readiness-report.md or audit-report.json.")
    report_parser.add_argument("--print", action="store_true", help="Print report after writing it.")
    report_parser.set_defaults(func=handlers.cmd_report)

    snapshots_parser = subparsers.add_parser("snapshots", help=argparse.SUPPRESS)
    snapshots_parser.add_argument("--show", help="Show snapshot details by number or id.")
    snapshots_parser.set_defaults(func=handlers.cmd_snapshots)

    rollback_parser = subparsers.add_parser("rollback", help=argparse.SUPPRESS)
    rollback_parser.add_argument("--to", help="Snapshot number or id to restore.")
    rollback_parser.add_argument("--last", action="store_true", help="Restore the newest snapshot.")
    rollback_parser.add_argument("--dry-run", action="store_true", help="Preview rollback without changing files.")
    rollback_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    rollback_parser.set_defaults(func=handlers.cmd_rollback)

    github_parser = subparsers.add_parser("github", help=argparse.SUPPRESS)
    github_parser.set_defaults(func=handlers.cmd_github, github_command="status", strict=False, limit=8, format="human")
    github_subparsers = github_parser.add_subparsers(dest="github_command", metavar="{setup,doctor,status,branch}")

    github_group_setup_parser = github_subparsers.add_parser("setup", help="Print, write, or apply GitHub setup commands.")
    github_group_setup_parser.add_argument("--write", action="store_true", help="Write dist/devsecops/github-setup.sh.")
    github_group_setup_parser.add_argument("--apply", action="store_true", help="Apply safe GitHub variables/secrets with gh.")
    github_group_setup_parser.add_argument("--deploy-role-arn", help="Value for AWS_ROLE_TO_ASSUME_ARN when using --apply.")
    github_group_setup_parser.add_argument("--plan-role-arn", help="Value for AWS_PLAN_ROLE_TO_ASSUME_ARN when using --apply.")
    github_group_setup_parser.add_argument("--snyk-token", help="Optional SNYK_TOKEN value when using --apply.")
    github_group_setup_parser.set_defaults(func=handlers.cmd_github)

    github_group_doctor_parser = github_subparsers.add_parser("doctor", help="Check GitHub CLI, variables, and secrets.")
    github_group_doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    github_group_doctor_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    github_group_doctor_parser.set_defaults(func=handlers.cmd_github)

    github_group_status_parser = github_subparsers.add_parser("status", help="Show recent GitHub Actions runs and failed jobs.")
    github_group_status_parser.add_argument("--strict", action="store_true", help="Exit non-zero when status cannot be read.")
    github_group_status_parser.add_argument("--limit", type=int, default=8, help="Number of workflow runs to inspect.")
    github_group_status_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    github_group_status_parser.set_defaults(func=handlers.cmd_github)

    github_group_branch_parser = github_subparsers.add_parser("branch", help="Check branch protection and required checks.")
    github_group_branch_parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch to inspect.")
    github_group_branch_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    github_group_branch_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    github_group_branch_parser.set_defaults(func=handlers.cmd_github)

    aws_parser = subparsers.add_parser("aws", help=argparse.SUPPRESS)
    aws_parser.set_defaults(func=handlers.cmd_aws, aws_command="outputs", environment="prod", strict=False, format="human")
    aws_subparsers = aws_parser.add_subparsers(dest="aws_command", metavar="{outputs,doctor}")

    aws_outputs_parser = aws_subparsers.add_parser("outputs", help="Inspect deployed Lambda/API Gateway outputs from AWS.")
    aws_outputs_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="Environment resources to inspect.")
    aws_outputs_parser.add_argument("--strict", action="store_true", help="Exit non-zero on WARN or FAIL checks.")
    aws_outputs_parser.add_argument("--format", choices=["human", "json"], default="human", help="Output mode.")
    aws_outputs_parser.set_defaults(func=handlers.cmd_aws)

    aws_group_doctor_parser = aws_subparsers.add_parser("doctor", help="Check AWS identity, backend, and deployed resources.")
    aws_group_doctor_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="Environment resources to inspect.")
    aws_group_doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero on WARN or FAIL scored checks.")
    aws_group_doctor_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    aws_group_doctor_parser.set_defaults(func=handlers.cmd_aws)

    github_setup_parser = subparsers.add_parser("github-setup", help=argparse.SUPPRESS)
    github_setup_parser.add_argument("--write", action="store_true", help="Write dist/devsecops/github-setup.sh.")
    github_setup_parser.add_argument("--apply", action="store_true", help="Apply safe GitHub variables/secrets with gh.")
    github_setup_parser.add_argument("--deploy-role-arn", help="Value for AWS_ROLE_TO_ASSUME_ARN when using --apply.")
    github_setup_parser.add_argument("--plan-role-arn", help="Value for AWS_PLAN_ROLE_TO_ASSUME_ARN when using --apply.")
    github_setup_parser.add_argument("--snyk-token", help="Optional SNYK_TOKEN value when using --apply.")
    github_setup_parser.set_defaults(func=handlers.cmd_github_setup)

    gh_setup_parser = subparsers.add_parser("gh-setup", help=argparse.SUPPRESS)
    gh_setup_parser.add_argument("--write", action="store_true", help="Write dist/devsecops/github-setup.sh.")
    gh_setup_parser.add_argument("--apply", action="store_true", help="Apply safe GitHub variables/secrets with gh.")
    gh_setup_parser.add_argument("--deploy-role-arn", help="Value for AWS_ROLE_TO_ASSUME_ARN when using --apply.")
    gh_setup_parser.add_argument("--plan-role-arn", help="Value for AWS_PLAN_ROLE_TO_ASSUME_ARN when using --apply.")
    gh_setup_parser.add_argument("--snyk-token", help="Optional SNYK_TOKEN value when using --apply.")
    gh_setup_parser.set_defaults(func=handlers.cmd_github_setup)

    gh_doctor_parser = subparsers.add_parser("gh-doctor", help=argparse.SUPPRESS)
    gh_doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    gh_doctor_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    gh_doctor_parser.set_defaults(func=handlers.cmd_gh_doctor)

    aws_doctor_parser = subparsers.add_parser("aws-doctor", help=argparse.SUPPRESS)
    aws_doctor_parser.add_argument("--environment", choices=ENVIRONMENTS, default="prod", help="Environment resources to inspect.")
    aws_doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero on WARN or FAIL scored checks.")
    aws_doctor_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    aws_doctor_parser.set_defaults(func=handlers.cmd_aws_doctor)

    gh_status_parser = subparsers.add_parser("gh-status", help=argparse.SUPPRESS)
    gh_status_parser.add_argument("--strict", action="store_true", help="Exit non-zero when status cannot be read.")
    gh_status_parser.add_argument("--limit", type=int, default=8, help="Number of workflow runs to inspect.")
    gh_status_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    gh_status_parser.set_defaults(func=handlers.cmd_gh_status)

    actions_status_parser = subparsers.add_parser("actions-status", help=argparse.SUPPRESS)
    actions_status_parser.add_argument("--strict", action="store_true", help="Exit non-zero when status cannot be read.")
    actions_status_parser.add_argument("--limit", type=int, default=8, help="Number of workflow runs to inspect.")
    actions_status_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    actions_status_parser.set_defaults(func=handlers.cmd_gh_status)

    branch_doctor_parser = subparsers.add_parser("branch-doctor", help=argparse.SUPPRESS)
    branch_doctor_parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch to inspect.")
    branch_doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero on failed scored checks.")
    branch_doctor_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    branch_doctor_parser.set_defaults(func=handlers.cmd_branch_doctor)

    set_parser = subparsers.add_parser("set", help=argparse.SUPPRESS)
    set_parser.add_argument("key", help="Config key, for example backend.bucket.")
    set_parser.add_argument("value", help="New value. Lists use comma-separated values.")
    set_parser.add_argument("--render", action="store_true", help="Render artifacts after updating config.")
    set_parser.set_defaults(func=handlers.cmd_set)

    validate_config_parser = subparsers.add_parser("validate-config", help=argparse.SUPPRESS)
    validate_config_parser.add_argument("--strict", action="store_true", help="Exit non-zero on production-risk warnings.")
    validate_config_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    validate_config_parser.set_defaults(func=handlers.cmd_validate_config)

    preset_parser = subparsers.add_parser("preset", help=argparse.SUPPRESS)
    preset_parser.add_argument(
        "command",
        nargs="?",
        help="Use `list`, `show`, `apply`, or a preset name for backward-compatible apply.",
    )
    preset_parser.add_argument("name", nargs="?", help="Preset name for `show` or `apply`.")
    preset_parser.add_argument("--generate", dest="render", action="store_true", help="Generate deployment files after applying preset.")
    preset_parser.add_argument("--render", dest="render", action="store_true", help=argparse.SUPPRESS)
    preset_parser.set_defaults(func=handlers.cmd_preset)

    compose_parser = subparsers.add_parser("compose", help=argparse.SUPPRESS)
    compose_parser.set_defaults(func=handlers.cmd_compose)

    terraform_parser = subparsers.add_parser("terraform", help=argparse.SUPPRESS)
    terraform_parser.set_defaults(func=handlers.cmd_terraform)
    terraform_subparsers = terraform_parser.add_subparsers(dest="terraform_command", metavar="{plan,bootstrap}")

    terraform_plan_parser = terraform_subparsers.add_parser("plan", help="Run Terraform plan for an environment.")
    terraform_plan_parser.add_argument("environment", choices=ENVIRONMENTS)
    terraform_plan_parser.add_argument("--no-init", action="store_true", help="Skip Terraform init.")
    terraform_plan_parser.add_argument("--create-workspace", action="store_true", help="Create the workspace if it is missing.")
    terraform_plan_parser.set_defaults(func=handlers.cmd_terraform)

    terraform_bootstrap_parser = terraform_subparsers.add_parser("bootstrap", help="Plan or apply backend bootstrap.")
    terraform_bootstrap_parser.add_argument("--apply", action="store_true", help="Apply backend bootstrap with auto-approve.")
    terraform_bootstrap_parser.set_defaults(func=handlers.cmd_terraform)

    snapshot_parser = subparsers.add_parser("snapshot", help=argparse.SUPPRESS)
    snapshot_parser.add_argument("--format", choices=["human", "json"], default="human", help="Output mode for default list.")
    snapshot_parser.set_defaults(func=handlers.cmd_snapshot, snapshot_command="list")
    snapshot_subparsers = snapshot_parser.add_subparsers(dest="snapshot_command", metavar="{list,show,restore}")

    snapshot_list_parser = snapshot_subparsers.add_parser("list", help="List local CLI snapshots.")
    snapshot_list_parser.add_argument("--format", choices=["human", "json"], default="human", help="Output mode.")
    snapshot_list_parser.set_defaults(func=handlers.cmd_snapshot)

    snapshot_show_parser = snapshot_subparsers.add_parser("show", help="Show snapshot details by number or id.")
    snapshot_show_parser.add_argument("selection", nargs="?", help="Snapshot number or id. Defaults to newest snapshot.")
    snapshot_show_parser.add_argument("--format", choices=["human", "json"], default="human", help="Output mode.")
    snapshot_show_parser.set_defaults(func=handlers.cmd_snapshot)

    snapshot_restore_parser = snapshot_subparsers.add_parser("restore", help="Restore CLI-owned files from a snapshot.")
    snapshot_restore_parser.add_argument("--to", help="Snapshot number or id to restore.")
    snapshot_restore_parser.add_argument("--last", action="store_true", help="Restore the newest snapshot.")
    snapshot_restore_parser.add_argument("--dry-run", action="store_true", help="Preview rollback without changing files.")
    snapshot_restore_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    snapshot_restore_parser.set_defaults(func=handlers.cmd_snapshot)

    plan_parser = subparsers.add_parser("plan", help=argparse.SUPPRESS)
    plan_parser.add_argument("environment", choices=ENVIRONMENTS)
    plan_parser.add_argument("--no-init", action="store_true", help="Skip Terraform init.")
    plan_parser.add_argument("--create-workspace", action="store_true", help="Create the workspace if it is missing.")
    plan_parser.set_defaults(func=handlers.cmd_plan)

    bootstrap_parser = subparsers.add_parser("bootstrap", help=argparse.SUPPRESS)
    bootstrap_parser.add_argument("--apply", action="store_true", help="Apply backend bootstrap with auto-approve.")
    bootstrap_parser.set_defaults(func=handlers.cmd_bootstrap)

    explain_parser = subparsers.add_parser("explain", help=argparse.SUPPRESS)
    explain_parser.add_argument("topic", nargs="?", default="all")
    explain_parser.set_defaults(func=handlers.cmd_explain)

    config_parser = subparsers.add_parser(
        "config",
        help="Manage local source config.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(
            (
                "devsecops config show",
                "devsecops config set lambda_image_uri <immutable-ecr-image-uri>",
                "devsecops config validate --strict",
            ),
            (
                "show, validate, diff, and schema are read-only.",
                "set and reset write only local config after taking a recoverable CLI snapshot.",
            ),
        ),
    )
    config_parser.add_argument(
        "--format",
        choices=["toml", "json"],
        default="toml",
        help="Output format for `devsecops config` compatibility show mode.",
    )
    config_parser.set_defaults(func=handlers.cmd_config, config_command="show")
    config_subparsers = config_parser.add_subparsers(
        dest="config_command",
        metavar="{show,validate,diff,reset,set,schema}",
    )

    config_show_parser = config_subparsers.add_parser("show", help="Print local source config.")
    config_show_parser.add_argument("--format", choices=["toml", "json"], default="toml", help="Output format.")
    config_show_parser.set_defaults(func=handlers.cmd_config)

    config_new_parser = config_subparsers.add_parser("new", help=argparse.SUPPRESS)
    config_new_parser.add_argument("--preset", choices=PRESET_ORDER, default="balanced", help="Preset to use for the clean config.")
    config_new_parser.add_argument("--force", action="store_true", help="Replace an existing config after taking a snapshot.")
    config_new_parser.add_argument("--generate", dest="render", action="store_true", help="Generate deployment files after writing config.")
    config_new_parser.add_argument("--render", dest="render", action="store_true", help=argparse.SUPPRESS)
    config_new_parser.set_defaults(func=handlers.cmd_config)

    config_validate_parser = config_subparsers.add_parser("validate", help="Validate local source config values.")
    config_validate_parser.add_argument("--strict", action="store_true", help="Exit non-zero on production-risk warnings.")
    config_validate_parser.add_argument("--format", choices=["human", "compact", "json"], default="human", help="Output mode.")
    config_validate_parser.set_defaults(func=handlers.cmd_config)

    config_diff_parser = config_subparsers.add_parser("diff", help="Show canonical config diff or compare against a preset.")
    config_diff_parser.add_argument("--preset", choices=PRESET_ORDER, help="Compare current config against a clean preset.")
    config_diff_parser.add_argument("--exit-code", action="store_true", help="Exit 1 when a diff is present.")
    config_diff_parser.set_defaults(func=handlers.cmd_config)

    config_reset_parser = config_subparsers.add_parser("reset", help="Reset local source config to a clean preset.")
    config_reset_parser.add_argument("--preset", choices=PRESET_ORDER, default="balanced", help="Preset to reset to.")
    config_reset_parser.add_argument("--generate", dest="render", action="store_true", help="Generate deployment files after resetting config.")
    config_reset_parser.add_argument("--render", dest="render", action="store_true", help=argparse.SUPPRESS)
    config_reset_parser.set_defaults(func=handlers.cmd_config)

    config_set_parser = config_subparsers.add_parser("set", help="Set a local source config value.")
    config_set_parser.add_argument("key", help="Config key, for example backend.bucket.")
    config_set_parser.add_argument("value", help="New value. Lists use comma-separated values.")
    config_set_parser.add_argument("--generate", dest="render", action="store_true", help="Generate deployment files after updating config.")
    config_set_parser.add_argument("--render", dest="render", action="store_true", help=argparse.SUPPRESS)
    config_set_parser.set_defaults(func=handlers.cmd_config)

    config_create_parser = config_subparsers.add_parser("create", help=argparse.SUPPRESS)
    config_create_parser.add_argument("--preset", choices=PRESET_ORDER, default="balanced", help="Preset to use for the clean config.")
    config_create_parser.add_argument("--force", action="store_true", help="Replace an existing config after taking a snapshot.")
    config_create_parser.add_argument("--generate", dest="render", action="store_true", help="Generate deployment files after writing config.")
    config_create_parser.add_argument("--render", dest="render", action="store_true", help=argparse.SUPPRESS)
    config_create_parser.set_defaults(func=handlers.cmd_config)

    config_schema_parser = config_subparsers.add_parser("schema", help="Print the local config schema contract.")
    config_schema_parser.add_argument("--format", choices=["json", "markdown"], default="json", help="Schema output format.")
    config_schema_parser.set_defaults(func=handlers.cmd_config)
    for parser_choices in (subparsers, config_subparsers):
        if hasattr(parser_choices, "_choices_actions"):
            parser_choices._choices_actions = [  # type: ignore[attr-defined]
                choice for choice in parser_choices._choices_actions if getattr(choice, "help", None) != argparse.SUPPRESS
            ]
    primary_order = [
        "menu",
        "setup",
        "status",
        "deploy",
        "dry-run",
        "generate",
        "doctor",
        "config",
    ]
    order_index = {name: index for index, name in enumerate(primary_order)}
    subparsers._choices_actions.sort(  # type: ignore[attr-defined]
        key=lambda choice: order_index.get(getattr(choice, "dest", ""), len(primary_order))
    )
    return parser



__all__ = ["build_parser"]
