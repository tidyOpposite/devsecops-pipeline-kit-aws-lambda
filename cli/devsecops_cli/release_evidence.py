"""Verify the evidence used to accept and publish a stable release."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from . import VERSION
from .config import config_shape_errors, validate_config
from .deploy import is_commit_sha
from .images import parse_ecr_image_uri
from .render import checklist, github_setup_script, github_variables, terraform_tfvars

PRODUCTION_EVIDENCE_REQUIRED_FILES = [
    "release-proof.json", "release-install.txt", "release-checksums.txt",
    "config.json", "config-validate.json", "readiness.json", "readiness-report.md",
    "audit-report.json", "terraform-generated.auto.tfvars", "github-setup.sh",
    "github-variables.env", "setup-checklist.md", "github-doctor.json", "branch-doctor.json",
    "github-status.json", "workflow-run.json", "automatic-rollback-run.json", "manual-rollback-run.json",
    "terraform-output.json", "aws-outputs.json", "aws-doctor.json", "health.json", "health-response.txt",
    "cloudwatch-log-groups.json", "cloudwatch-tail.txt", "active-lambda-image.txt", "notes.md",
]
WSL2_EVIDENCE_REQUIRED_FILES = ["wsl2-transcript.txt"]
MAX_EVIDENCE_FILE_BYTES = 8 * 1024 * 1024
PRODUCTION_JOB = "Manual Apply, Deploy, or Roll Back Production"
RECOVERY_STEP = "Roll back Lambda image on failed deployment validation"
HEALTH_STEP = "Smoke test Lambda health endpoint"
MANUAL_RECOVERY_STEP = "Restore requested Lambda image"
VERIFY_INTENT_STEP = "Verify reviewed production intent before approval"
DEPLOY_STEPS = {"Terraform apply workload with configured Lambda image": "success", HEALTH_STEP: "success"}
RUN_REQUIREMENTS = {
    "workflow-run.json": ("DevSecOps deploy prod", "success", DEPLOY_STEPS),
    "automatic-rollback-run.json": ("DevSecOps deploy prod", "failure", DEPLOY_STEPS | {HEALTH_STEP: "failure", RECOVERY_STEP: "success"}),
    "manual-rollback-run.json": ("DevSecOps rollback prod", "success", {MANUAL_RECOVERY_STEP: "success"}),
}


def evidence_check(name: str, valid: bool, detail: str) -> dict[str, str]:
    return {"name": name, "status": "OK" if valid else "BLOCKED", "detail": detail}


def read_evidence(directory: Path, names: list[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    documents, checks = {}, []
    for name in names:
        path = directory / name
        try:
            if not path.is_file() or path.is_symlink():
                raise ValueError("Expected a regular evidence file")
            if path.stat().st_size > MAX_EVIDENCE_FILE_BYTES:
                raise ValueError("Evidence file exceeds the size limit")
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                raise ValueError("Evidence file is empty")
            if path.suffix == ".json":
                content = json.loads(content)
                if not isinstance(content, dict) or not content:
                    raise ValueError("Expected a non-empty JSON object")
            documents[name] = content
            checks.append(evidence_check(name, True, str(path)))
        except (OSError, ValueError) as exc:
            checks.append(evidence_check(name, False, f"{path}: {exc}"))
    return documents, checks


def valid_digest_uri(value: Any) -> bool:
    ref = parse_ecr_image_uri(value)
    return bool(ref and ref.digest and ref.digest == ref.digest.lower())


def run_id(value: Any) -> bool:
    return type(value) is int and value > 0


def passing_checks(payload: dict, kind: str, required: set[str] | None = None) -> bool:
    checks = payload.get("checks")
    if payload.get("kind") != kind or not isinstance(checks, list) or not checks:
        return False
    return all(isinstance(check, dict) and (check.get("scored") is False or check.get("status") == "OK")
               for check in checks) and (required or set()) <= {check.get("name") for check in checks if check.get("status") == "OK"}


def job_steps(job: dict) -> dict[str, str]:
    return {step["name"]: step["conclusion"] for step in job["steps"] if step["status"] == "completed"}


def workflow_run_checks(document: dict, proof: dict, requirement: tuple, expected_id: int) -> tuple[dict, dict]:
    title, conclusion, required_steps = requirement
    run = document["run"]
    if (run.get("id") != expected_id or run.get("head_branch") != "main" or run.get("head_sha") != proof["commit_sha"]
            or run.get("path", "").split("@", 1)[0] != ".github/workflows/deploy.yml"
            or run.get("event") != "workflow_dispatch" or run.get("display_title") != title
            or run.get("status") != "completed" or run.get("conclusion") != conclusion
            or run.get("repository", {}).get("full_name", "").lower() != proof["repository"].lower()):
        raise ValueError("Run identity, source commit, event, or conclusion does not match the release proof")
    jobs = document["jobs"]
    production = next(job for job in jobs if job.get("name") == PRODUCTION_JOB)
    gate = next(job for job in jobs if job.get("name") == "Security and Terraform Validate")
    if (production.get("status") != "completed" or production.get("conclusion") != conclusion
            or gate.get("status") != "completed" or gate.get("conclusion") != "success"
            or job_steps(gate).get(VERIFY_INTENT_STEP) != "success"
            or not required_steps.items() <= job_steps(production).items()):
        raise ValueError("Production job, intent gate, or required deployment and recovery steps did not produce the expected outcomes")
    return gate, production


def cloud_checks(documents: dict[str, Any], image: str, cfg: dict) -> bool:
    terraform = {key: value["value"] for key, value in documents["terraform-output.json"].items()}
    aws = documents["aws-outputs.json"]
    outputs = aws["outputs"]
    health = documents["health.json"]
    health_response = next(check for check in health["checks"] if check["name"] == "Health response")
    health_url = terraform["api_gateway_health_url"]
    log_group = f"/aws/lambda/{terraform['lambda_function_name']}"
    return (
        aws.get("kind") == "aws-outputs" and aws.get("environment") == "prod"
        and terraform.get("environment") == terraform.get("terraform_workspace") == "prod"
        and image == terraform.get("lambda_current_image_uri") == outputs.get("lambda_image_uri") == documents["active-lambda-image.txt"]
        and outputs.get("aws_region") == cfg["aws_region"]
        and outputs.get("lambda_state") == "Active" and outputs.get("lambda_last_update_status") == "Successful"
        and outputs.get("lambda_function_name") == terraform["lambda_function_name"]
        and outputs.get("cloudwatch_log_group") == log_group
        and any(group.get("logGroupName") == log_group for group in documents["cloudwatch-log-groups.json"]["logGroups"])
        and isinstance(health_url, str) and health_url.startswith("https://") and outputs.get("api_gateway_health_url") == health_url
        and passing_checks(health, "health", {"Health endpoint URL", "Health response"})
        and any(check["name"] == "Health endpoint URL" and check["detail"].startswith(health_url + " (") for check in health["checks"])
        and re.match(r"HTTP 2\d\d:", health_response["detail"]) is not None
    )


def github_evidence(root: Path, repository: str, proof: dict, runs: dict[str, int]) -> None:
    if repository.lower() != proof["repository"].lower():
        raise ValueError("Evidence must come from the release repository")

    def api(path: str) -> str:
        command = ["gh", "api", f"repos/{repository}/{path}"]
        options = {"cwd": root, "capture_output": True, "text": True, "timeout": 45, "check": False}
        result = subprocess.run(command, **options)
        if result.returncode and path.endswith("/logs") and "--allow-escape-sequences" in result.stderr:
            # Logs are inspected in memory and never passed to the terminal.
            result = subprocess.run([*command, "--allow-escape-sequences"], **options)
        if result.returncode:
            raise ValueError(f"Cannot verify GitHub endpoint {path}")
        return result.stdout

    ci = json.loads(api(f"actions/runs/{proof['ci_run_id']}"))
    if (ci.get("head_sha") != proof["commit_sha"] or ci.get("head_branch") != "main"
            or ci.get("path", "").split("@", 1)[0] != ".github/workflows/ci.yml"
            or ci.get("event") not in {"push", "workflow_dispatch"}
            or ci.get("status") != "completed" or ci.get("conclusion") != "success"):
        raise ValueError("Candidate CI run is not successful on the release commit")

    for name, identifier in runs.items():
        run = json.loads(api(f"actions/runs/{identifier}"))
        jobs = json.loads(api(f"actions/runs/{identifier}/jobs?per_page=100"))["jobs"]
        gate, production = workflow_run_checks({"run": run, "jobs": jobs}, proof, RUN_REQUIREMENTS[name], identifier)
        intent_key = {
            "workflow-run.json": "image_uri", "automatic-rollback-run.json": "failed_image_uri",
            "manual-rollback-run.json": "manual_rollback_image_uri",
        }[name]
        if not run_id(gate.get("id")) or f"- Image: `{proof[intent_key]}`" not in api(f"actions/jobs/{gate['id']}/logs"):
            raise ValueError(f"GitHub job log does not verify the dispatched image digest for {name}")
        if name != "workflow-run.json":
            restored = proof["manual_rollback_image_uri"] if name == "manual-rollback-run.json" else proof["image_uri"]
            pattern = rf"Verified Lambda recovery: {re.escape(restored)}, Terraform state matches, /health returned HTTP 2\d\d\."
            if not run_id(production.get("id")) or re.search(pattern, api(f"actions/jobs/{production['id']}/logs")) is None:
                raise ValueError(f"GitHub job log does not verify the restored digest and HTTP 2xx for {name}")


def production_evidence_checks(root: Path, directory: Path, *, repository: str | None = None,
                               artifacts_dir: Path | None = None) -> list[dict[str, str]]:
    documents, checks = read_evidence(directory, PRODUCTION_EVIDENCE_REQUIRED_FILES)
    if len(documents) != len(PRODUCTION_EVIDENCE_REQUIRED_FILES):
        return checks

    def require(valid: bool, detail: str) -> None:
        if not valid:
            raise ValueError(detail)

    try:
        proof = documents["release-proof.json"]
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10, check=False)
        require(proof.get("schema_version") == 1 and proof.get("tag") == f"v{VERSION}"
                and commit.returncode == 0 and is_commit_sha(commit.stdout.strip()) and proof.get("commit_sha") == commit.stdout.strip(),
                "Release proof must match the CLI version and checked-out commit")
        images = [proof["image_uri"], proof["failed_image_uri"], proof["manual_rollback_image_uri"]]
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", proof["repository"]) is not None and run_id(proof["ci_run_id"])
                and all(valid_digest_uri(image) for image in images) and len(set(images)) == len(images)
                and re.fullmatch(r"[a-f0-9]{64}", proof["wheel_sha256"]) is not None,
                "Release proof needs repository, CI run ID, wheel checksum, and deployment and rollback digests")

        wheel = f"devsecops_pipeline_cli-{VERSION}-py3-none-any.whl"
        checksums = documents["release-checksums.txt"].splitlines()
        require(documents["release-install.txt"] == f"devsecops {VERSION}"
                and f"{wheel}: OK" in checksums and f"{proof['wheel_sha256']}  {wheel}" in checksums,
                "Install version or candidate wheel checksum evidence is missing or mismatched")
        if artifacts_dir is not None:
            with (artifacts_dir / wheel).open("rb") as handle:
                require(hashlib.file_digest(handle, "sha256").hexdigest() == proof["wheel_sha256"],
                        "The publication wheel differs from the wheel verified in the evidence")

        cfg = documents["config.json"]
        require(not config_shape_errors(cfg) and all(check.status == "OK" for check in validate_config(cfg)),
                "Configuration must pass strict validation")
        for name, render in [("terraform-generated.auto.tfvars", terraform_tfvars), ("github-setup.sh", github_setup_script),
                             ("github-variables.env", github_variables), ("setup-checklist.md", checklist)]:
            require(documents[name] == render(cfg).strip(), f"{name} does not match the reviewed configuration")
        require(documents["readiness-report.md"].startswith("# DevSecOps Pipeline Readiness Report")
                and f"Project: `{cfg['project_name']}`" in documents["readiness-report.md"],
                "The readiness report does not describe the reviewed project")
        for name, kind, required in [
            ("config-validate.json", "config", {"Config schema version"}),
            ("readiness.json", "status", {"Lambda function", "GitHub environment approvals"}),
            ("github-doctor.json", "github", {"GitHub repository", "GitHub environment approvals"}),
            ("branch-doctor.json", "branch-protection", {"Branch `main` protection"}),
            ("aws-doctor.json", "aws", {"AWS identity", "Lambda function"}),
        ]:
            require(passing_checks(documents[name], kind, required), f"{name} does not show successful required checks")
        require(any(check["name"] == "GitHub repository" and check["detail"].lower() == proof["repository"].lower()
                    for check in documents["github-doctor.json"]["checks"]), "GitHub doctor evidence is for a different repository")
        require(documents["audit-report.json"].get("kind") == "audit-evidence"
                and documents["audit-report.json"].get("cli_version") == VERSION
                and documents["audit-report.json"].get("config_validation", {}).get("strict_pass") is True,
                "Audit report must use the release CLI version and show strict configuration success")
        require(documents["github-status.json"].get("kind") == "github-actions-status"
                and documents["github-status.json"].get("error") is None and bool(documents["github-status.json"].get("runs")),
                "GitHub status must contain observed workflow runs")
        require(cloud_checks(documents, proof["image_uri"], cfg), "Terraform, AWS, CloudWatch or HTTP 2xx evidence does not match the deployed digest and environment")

        runs = {name: documents[name]["run"]["id"] for name in RUN_REQUIREMENTS}
        require(all(run_id(identifier) for identifier in runs.values()) and len(set(runs.values())) == len(runs),
                "Deploy, automatic rollback and manual rollback need distinct GitHub run IDs")
        for name, identifier in runs.items():
            workflow_run_checks(documents[name], proof, RUN_REQUIREMENTS[name], identifier)
        if repository is not None:
            github_evidence(root, repository, proof, runs)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, StopIteration, subprocess.TimeoutExpired) as exc:
        return [*checks, evidence_check("Release evidence contents", False, str(exc))]
    return [*checks, evidence_check("Release evidence contents", True, "Release identity, deployment, recovery and package evidence match.")]


def wsl_evidence_checks(directory: Path, root: Path) -> list[dict[str, str]]:
    documents, checks = read_evidence(directory, WSL2_EVIDENCE_REQUIRED_FILES)
    if not documents:
        return checks
    text = documents["wsl2-transcript.txt"]
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10, check=False)
        commit = head.stdout.strip()
        valid = (head.returncode == 0 and is_commit_sha(commit)
                 and f"Release commit: {commit}" in text.splitlines() and f"devsecops {VERSION}" in text.splitlines()
                 and re.search(r"^Linux .*microsoft.*WSL2", text, flags=re.MULTILINE | re.IGNORECASE) is not None
                 and f"Successfully installed devsecops-pipeline-cli-{VERSION}" in text
                 and "Guided setup complete" in text and "# bash completion for devsecops" in text
                 and re.search(r"^Ran [1-9]\d* tests? in .*\n(?:\s*\n)?OK(?:\s|$)", text, flags=re.MULTILINE) is not None)
    except (OSError, subprocess.TimeoutExpired):
        valid = False
    return [*checks, evidence_check("WSL2 transcript contents", valid, "Transcript must show the release commit, WSL2 kernel, installed version, demo, completion and passing tests.")]


def unpack_evidence(archive: Path, directory: Path) -> None:
    """Copy only known evidence files, without extracting arbitrary paths."""

    directory.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        for name in [*PRODUCTION_EVIDENCE_REQUIRED_FILES, *WSL2_EVIDENCE_REQUIRED_FILES]:
            matches = [entry for entry in bundle.infolist() if entry.filename == name]
            if not matches:
                continue
            if len(matches) != 1 or matches[0].file_size > MAX_EVIDENCE_FILE_BYTES:
                raise ValueError(f"Invalid archive entry: {name}")
            (directory / name).write_bytes(bundle.read(matches[0]))


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "unpack":
        raise SystemExit("Usage: python -m devsecops_cli.release_evidence unpack ARCHIVE DIRECTORY")
    try:
        unpack_evidence(Path(sys.argv[2]), Path(sys.argv[3]))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(f"Cannot unpack release evidence: {error}") from None
