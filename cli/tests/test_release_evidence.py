"""Stable publication rejects evidence that cannot prove the release outcomes."""

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import VERSION, config, release_evidence as evidence, render
from devsecops_cli.main import v1_criteria_payload


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "acme/pipeline"
REGISTRY = "123456789012.dkr.ecr.us-east-1.amazonaws.com/workload@sha256:"
IMAGE, BROKEN, ROLLBACK = (REGISTRY + char * 64 for char in "abc")
HEALTH = "https://abc123.execute-api.us-east-1.amazonaws.com/health"
FUNCTION = "devsecops-pipeline-prod-lambda"
LOG_GROUP = f"/aws/lambda/{FUNCTION}"
WHEEL = f"devsecops_pipeline_cli-{VERSION}-py3-none-any.whl"


def checks(kind, **items):
    return {"kind": kind, "checks": [{"name": name, "status": "OK", "scored": True, "detail": detail}
                                    for name, detail in items.items()]}


def workflow_run(identifier, commit, requirement):
    title, conclusion, steps = requirement

    def job(job_id, name, result, outcomes):
        return {"id": job_id, "name": name, "status": "completed", "conclusion": result,
                "steps": [{"name": step, "status": "completed", "conclusion": status} for step, status in outcomes.items()]}

    return {
        "run": {"id": identifier, "path": ".github/workflows/deploy.yml@main", "head_branch": "main", "head_sha": commit,
                "display_title": title, "event": "workflow_dispatch", "status": "completed", "conclusion": conclusion,
                "repository": {"full_name": REPOSITORY}},
        "jobs": [job(identifier * 10, "Security and Terraform Validate", "success", {evidence.VERIFY_INTENT_STEP: "success"}),
                 job(identifier * 10 + 1, evidence.PRODUCTION_JOB, conclusion, steps)],
    }


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)
        self.commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        self.wheel = self.directory / WHEEL
        self.wheel.write_bytes(b"reviewed wheel bytes")
        checksum = hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        cfg = config.preset_config("enterprise")
        cfg["lambda_image_uri"] = IMAGE
        cfg["backend"]["bucket"] = "devsecops-prod-tfstate"
        documents = {
            "release-proof.json": {"schema_version": 1, "tag": f"v{VERSION}", "commit_sha": self.commit,
                "repository": REPOSITORY, "ci_run_id": 10, "image_uri": IMAGE, "failed_image_uri": BROKEN,
                "manual_rollback_image_uri": ROLLBACK, "wheel_sha256": checksum},
            "release-install.txt": f"devsecops {VERSION}",
            "release-checksums.txt": f"{checksum}  {WHEEL}\n{WHEEL}: OK",
            "config.json": cfg,
            "config-validate.json": checks("config", **{"Config schema version": "1"}),
            "readiness.json": checks("status", **{"Lambda function": "Active", "GitHub environment approvals": "Verified"}),
            "readiness-report.md": "# DevSecOps Pipeline Readiness Report\nProject: `devsecops-pipeline`",
            "audit-report.json": {"kind": "audit-evidence", "cli_version": VERSION, "config_validation": {"strict_pass": True}},
            "terraform-generated.auto.tfvars": render.terraform_tfvars(cfg),
            "github-setup.sh": render.github_setup_script(cfg),
            "github-variables.env": render.github_variables(cfg),
            "setup-checklist.md": render.checklist(cfg),
            "github-doctor.json": checks("github", **{"GitHub repository": REPOSITORY, "GitHub environment approvals": "Verified"}),
            "branch-doctor.json": checks("branch-protection", **{"Branch `main` protection": "Enabled"}),
            "aws-doctor.json": checks("aws", **{"AWS identity": "Verified", "Lambda function": "Active"}),
            "github-status.json": {"kind": "github-actions-status", "error": None, "runs": [["11", "success"]]},
            "terraform-output.json": {name: {"value": value} for name, value in {
                "environment": "prod", "terraform_workspace": "prod", "lambda_current_image_uri": IMAGE,
                "api_gateway_health_url": HEALTH, "lambda_function_name": FUNCTION}.items()},
            "aws-outputs.json": {"kind": "aws-outputs", "environment": "prod", "outputs": {
                "aws_region": cfg["aws_region"], "lambda_state": "Active", "lambda_last_update_status": "Successful",
                "lambda_image_uri": IMAGE, "api_gateway_health_url": HEALTH, "cloudwatch_log_group": LOG_GROUP,
                "lambda_function_name": FUNCTION}},
            "health.json": checks("health", **{"Health endpoint URL": f"{HEALTH} (argument)", "Health response": "HTTP 200: ok"}),
            "health-response.txt": "ok", "cloudwatch-log-groups.json": {"logGroups": [{"logGroupName": LOG_GROUP}]},
            "cloudwatch-tail.txt": "request completed", "active-lambda-image.txt": IMAGE, "notes.md": "Protected prod walkthrough",
            "wsl2-transcript.txt": f"Release commit: {self.commit}\nLinux host 6.6-microsoft-standard-WSL2 x86_64\n"
                f"Successfully installed devsecops-pipeline-cli-{VERSION}\ndevsecops {VERSION}\n"
                "Guided setup complete\n# bash completion for devsecops\nRan 200 tests in 2s\n\nOK\n",
        }
        documents.update({name: workflow_run(identifier, self.commit, requirement)
                          for identifier, (name, requirement) in enumerate(evidence.RUN_REQUIREMENTS.items(), 11)})
        self.documents = documents
        for name, content in documents.items():
            self.write(name, content)

    def write(self, name, content):
        (self.directory / name).write_text(json.dumps(content) if isinstance(content, dict) else content, encoding="utf-8")

    def test_validated_evidence_and_reviewed_wheel_pass(self):
        payload = v1_criteria_payload(ROOT, self.directory, artifacts_dir=self.directory)
        self.assertTrue(payload["stable_ready"], payload["stable_release_gates"])

    def test_blocks_wrong_commit_skipped_apply_digest_mismatch_and_unproven_wsl(self):
        proof = self.documents["release-proof.json"]
        for name, content in [
            ("release-proof.json", proof | {"commit_sha": "f" * 40}),
            ("workflow-run.json", workflow_run(11, self.commit, ("DevSecOps deploy prod", "success", {}))),
            ("automatic-rollback-run.json", workflow_run(12, self.commit, ("DevSecOps deploy prod", "failure", evidence.DEPLOY_STEPS))),
            ("active-lambda-image.txt", ROLLBACK),
            ("health.json", checks("health", **{"Health endpoint URL": f"{HEALTH} (argument)", "Health response": "HTTP 302: moved"})),
            ("wsl2-transcript.txt", f"devsecops {VERSION}"),
        ]:
            with self.subTest(name=name):
                self.write(name, content)
                self.assertFalse(v1_criteria_payload(ROOT, self.directory)["stable_ready"])
                self.write(name, self.documents[name])
        self.wheel.write_bytes(b"different wheel")
        self.assertFalse(v1_criteria_payload(ROOT, self.directory, artifacts_dir=self.directory)["stable_ready"])

    def test_authenticated_github_crosscheck_rejects_a_different_restored_digest(self):
        response = {
            "actions/runs/10": {"head_sha": self.commit, "head_branch": "main", "path": ".github/workflows/ci.yml",
                                "event": "push", "status": "completed", "conclusion": "success"},
        }
        for identifier, (name, image) in enumerate(zip(evidence.RUN_REQUIREMENTS, [IMAGE, BROKEN, ROLLBACK]), 11):
            document = self.documents[name]
            response[f"actions/runs/{identifier}"] = document["run"]
            response[f"actions/runs/{identifier}/jobs?per_page=100"] = {"jobs": document["jobs"]}
            response[f"actions/jobs/{identifier * 10}/logs"] = f"- Image: `{image}`"
        response["actions/jobs/121/logs"] = f"Verified Lambda recovery: {IMAGE}, Terraform state matches, /health returned HTTP 200."
        response["actions/jobs/131/logs"] = f"Verified Lambda recovery: {ROLLBACK}, Terraform state matches, /health returned HTTP 200."
        run = subprocess.run

        def fake(command, **kwargs):
            if command[0] == "git":
                return run(command, **kwargs)
            endpoint = command[2].removeprefix(f"repos/{REPOSITORY}/")
            if endpoint.endswith("/logs") and "--allow-escape-sequences" not in command:
                return subprocess.CompletedProcess(command, 1, "", "pass --allow-escape-sequences")
            value = response[endpoint]
            return subprocess.CompletedProcess(command, 0, json.dumps(value) if isinstance(value, dict) else value, "")

        with patch.object(evidence.subprocess, "run", side_effect=fake):
            self.assertTrue(v1_criteria_payload(ROOT, self.directory, repository=REPOSITORY)["stable_ready"])
            response["actions/jobs/121/logs"] = response["actions/jobs/131/logs"]
            self.assertFalse(v1_criteria_payload(ROOT, self.directory, repository=REPOSITORY)["stable_ready"])

    def test_archive_copies_only_known_root_files(self):
        archive = self.directory / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../unexpected", "not evidence")
            bundle.writestr("release-proof.json", json.dumps(self.documents["release-proof.json"]))
        output = self.directory / "unpacked"
        evidence.unpack_evidence(archive, output)
        self.assertEqual([path.name for path in output.iterdir()], ["release-proof.json"])
        self.assertFalse((self.directory / "unexpected").exists())

    def test_stable_publisher_requires_verified_evidence_before_release_creation(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        stable = workflow.split("- name: Verify stable release evidence and retrieve reviewed assets", 1)[1]
        self.assertIn("if: steps.tag.outputs.stable == 'true'", stable)
        self.assertLess(stable.index("--verify-github"), stable.index("gh run download"))
        self.assertLess(stable.index("--artifacts-dir dist"), stable.index("- name: Create GitHub release"))
