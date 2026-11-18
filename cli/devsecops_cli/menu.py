"""Interactive navigation for the core deployment commands."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from . import deployment
from .paths import REQUIRED_PROJECT_FILES

RunCommand = Callable[[list[str]], int]
MENU_SHORTCUTS = {
    "continue": "1",
    "setup": "1",
    "status": "2",
    "dashboard": "2",
    "deploy": "3",
    "diagnose": "4",
    "doctor": "4",
    "config": "5",
    "configuration": "5",
    "advanced": "6",
}


def deployment_names(root: Path, directory: str) -> list[str]:
    base = root / ".devsecops" / directory
    if not base.is_dir():
        return []
    return sorted(
        item.name
        for item in base.iterdir()
        if deployment.NAME.fullmatch(item.name) and (item / "settings.json").is_file()
    )


def readiness(root: Path, name: str | None) -> tuple[str, list[tuple[str, bool, str]], str]:
    checkout = all((root / path).is_file() for path in REQUIRED_PROJECT_FILES)
    terraform = shutil.which("terraform")
    instance = deployment.Deployment(root, name) if name else None
    aws = shutil.which("aws") or shutil.which(str(Path.home() / ".local/bin/aws"))
    summary = name or "Select a deployment"
    scope = False
    scope_detail = "Choose a deployment in Advanced or start with Continue setup."
    registry = False
    image = False
    if instance and instance.settings_path.is_file():
        try:
            instance.load()
            settings = instance.settings
            aws = shutil.which(settings["aws_binary"])
            summary = f"{settings['project_name']} | {settings['region']}"
            state = instance.outputs()
            registry = state.get("repository_url") == instance.repository
            recorded = state.get("image_uri")
            image = (
                registry
                and isinstance(recorded, str)
                and bool(
                    re.fullmatch(re.escape(instance.repository) + r"@sha256:[a-f0-9]{64}", recorded)
                )
            )
            scope = True
            scope_detail = f"Account {settings['account_id']} | profile {settings['profile']}"
        except (OSError, ValueError, TypeError, AttributeError) as error:
            scope_detail = f"Cannot verify local settings or state: {error}"
    elif name and (root / ".devsecops" / "labs" / name / "settings.json").is_file():
        scope_detail = f"Legacy lab {name} found. Review migration in Advanced."

    checks = [
        ("Source checkout", checkout, str(root) if checkout else "Open the project checkout."),
        (
            "AWS CLI executable",
            bool(aws),
            aws or "Install AWS CLI v2 or check the saved executable.",
        ),
        (
            "Terraform executable",
            bool(terraform),
            terraform or "Install Terraform and add it to PATH.",
        ),
        ("Deployment scope and state", scope, scope_detail),
        (
            "Registry recorded",
            registry,
            "Present in local state." if registry else "Plan and apply the registry stage.",
        ),
        (
            "Lambda image recorded",
            image,
            "Own ECR digest in local state."
            if image
            else "Publish an image and apply a workload plan.",
        ),
    ]
    next_action = next(
        (detail for _, ready, detail in checks if not ready),
        "Run Status to verify the live Lambda, image and signed health.",
    )
    return summary, checks, next_action


def choose_name(root: Path) -> str | None:
    current = deployment_names(root, "deployments")
    legacy = deployment_names(root, "labs")
    if current:
        print("Deployments: " + ", ".join(current))
    if legacy:
        print("Legacy labs: " + ", ".join(legacy))
    name = input("Deployment name (Enter to go back): ").strip()
    if name and not deployment.NAME.fullmatch(name):
        raise deployment.DeploymentError(
            "Use 3–16 lowercase letters, digits or hyphens, starting with a letter."
        )
    return name or None


def run(root: Path, name: str | None, command: RunCommand) -> int:
    if name is not None and not deployment.NAME.fullmatch(name):
        print(
            "Use a deployment name of 3–16 lowercase letters, digits or hyphens, starting with a letter."
        )
        return 2
    try:
        return run_loop(root, name, command)
    except EOFError:
        print("\nInput closed. Exiting menu.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting menu.")
        return 130


def run_loop(root: Path, name: str | None, command: RunCommand) -> int:
    current = deployment_names(root, "deployments")
    if name is None and len(current) == 1:
        name = current[0]
    while True:
        summary, checks, action = readiness(root, name)
        score = 100 * sum(ready for _, ready, _ in checks) // len(checks)
        if sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb":
            print("\033[2J\033[H", end="")
        print("\nDevSecOps Pipeline Kit")
        print(f"{summary} | readiness {score}% (local)")
        print(
            f"image: {'recorded' if checks[-1][1] else 'missing'} | backend: local | live health: use Status"
        )
        print(f"\nNext Action\n{action}\n")
        print("[1] Continue setup\n[2] Status\n[3] Deploy\n[4] Diagnose problems")
        print("[5] Configuration\n[6] Advanced\n[i] Readiness details\n[0] Exit")
        choice = input("\nChoose: ").strip().lower()
        choice = MENU_SHORTCUTS.get(choice, choice)
        if choice in {"0", "q", "quit", "exit"}:
            return 0
        try:
            if choice in {"i", "info", "readiness", "?", "4"}:
                print("\nReadiness details")
                for label, ready, detail in checks:
                    print(f"[{'OK' if ready else 'PENDING'}] {label}: {detail}")
                print("Status verifies AWS identity, the live image, signed health and capacity.")
            elif choice == "6":
                name = advanced(root, name, command)
            elif choice in {"1", "2", "3", "5"}:
                name = name or choose_name(root)
                if name:
                    run_action(root, name, choice, command)
            else:
                print("Unknown option. Choose one of the entries shown above.")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            print(f"Error: {error}")
        input("\n[Enter] Back to main menu ")


def run_action(root: Path, name: str, choice: str, command: RunCommand) -> None:
    instance = deployment.Deployment(root, name)
    if not instance.settings_path.is_file():
        if (root / ".devsecops" / "labs" / name / "settings.json").is_file():
            print(f"Legacy lab {name} found. Review migration in Advanced before continuing.")
        elif choice == "1":
            account = input("Expected AWS account ID: ").strip()
            region = input("AWS region: ").strip()
            profile = input("AWS CLI profile: ").strip()
            command(
                [
                    "init",
                    name,
                    f"--expected-account-id={account}",
                    f"--region={region}",
                    f"--profile={profile}",
                ]
            )
        else:
            print("Set up this deployment with Continue setup.")
    elif choice == "1":
        print("Deployment scope saved. Open Deploy to prepare a registry or workload plan.")
    elif choice == "2":
        command(["status", name])
    elif choice == "3":
        deploy(instance, command)
    else:
        command(["config", name])


def deploy(instance: deployment.Deployment, command: RunCommand) -> None:
    print("\nDeploy\n[1] Plan registry\n[2] Plan workload or update\n[3] Plan rollback")
    print("[4] Plan destroy\n[5] Review/apply a saved plan\n[0] Back")
    choice = input("Choose: ").strip()
    stages = {"1": "registry", "2": "workload", "3": "rollback", "4": "destroy"}
    if choice in stages:
        stage = stages[choice]
        flags = [f"--stage={stage}"]
        if stage in {"workload", "rollback"}:
            flags.append("--image-uri=" + input("Immutable ECR image URI: ").strip())
        command(["plan", instance.name, *flags])
    elif choice == "5":
        review_and_apply(instance, command)
    elif choice != "0":
        print("Unknown deploy option.")


def review_and_apply(instance: deployment.Deployment, command: RunCommand) -> None:
    plan_id = input("Saved plan ID: ").strip()
    checksum = input("Review SHA-256: ").strip()
    with instance.locked():
        instance.load()
        directory, review = instance.reviewed(plan_id, checksum)
        content = (directory / "plan.txt").read_bytes()
        if hashlib.sha256(content).hexdigest() != review["files"]["plan.txt"]:
            raise deployment.DeploymentError("Plan text changed during review. Create a new plan.")
    print(f"\nSaved {review['stage']} plan for {instance.name}")
    print(f"AWS account {review['account_id']} | region {review['region']}")
    print(f"Plan ID: {plan_id}\nReview SHA-256: {checksum}\n")
    print(re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", content.decode("utf-8", errors="replace")))
    if input("Apply this exact saved plan? [y/N]: ").strip().lower() not in {"y", "yes"}:
        print("Apply cancelled.")
        return
    command(["apply", instance.name, f"--plan-id={plan_id}", f"--sha256={checksum}", "--yes"])


def advanced(root: Path, name: str | None, command: RunCommand) -> str | None:
    print("\nAdvanced\n[1] Select deployment\n[2] Read Lambda logs\n[3] Send a signed API request")
    print("[4] Show concurrency policy\n[5] Review legacy migration\n[0] Back")
    choice = input("Choose: ").strip()
    if choice == "1":
        return choose_name(root) or name
    if choice == "0":
        return name
    if choice not in {"2", "3", "4", "5"}:
        print("Unknown advanced option.")
        return name
    name = name or choose_name(root)
    if name is None:
        return None
    if choice == "5":
        if command(["migrate", name]) == 0:
            print(f"After reviewing the migration, run: devsecops migrate {name} --yes")
    elif not deployment.Deployment(root, name).settings_path.is_file():
        print("Set up this deployment with Continue setup, or review legacy migration above.")
    elif choice == "3":
        method = input("HTTP method [GET]: ").strip().upper() or "GET"
        path = input("API path [/health]: ").strip() or "/health"
        flags = [f"--method={method}", f"--path={path}"]
        if method == "POST":
            flags.append("--body=" + input("JSON body: "))
        command(["request", name, *flags])
    else:
        command(["logs" if choice == "2" else "concurrency", name])
    return name
