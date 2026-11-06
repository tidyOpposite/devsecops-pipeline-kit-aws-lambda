"""Stable publication rejects evidence that cannot prove the release outcomes."""

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import VERSION, cloud_evidence, config, release_evidence as evidence, render
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
            "terraform-context.json": {
                "schema_version": 1, "captured_at": "2026-11-05T10:00:00Z", "expected_account_id": "123456789012",
                "aws_identity": {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/deploy/session", "UserId": "fixture"},
                "aws_region": cfg["aws_region"], "workspace": "prod", "backend": cloud_evidence.expected_backend(cfg),
                "lambda_function_arn": f"arn:aws:lambda:{cfg['aws_region']}:123456789012:function:{FUNCTION}", "lambda_image_uri": IMAGE,
            },
            "aws-outputs.json": {"kind": "aws-outputs", "environment": "prod", "outputs": {
                "aws_region": cfg["aws_region"], "lambda_state": "Active", "lambda_last_update_status": "Successful",
                "lambda_image_uri": IMAGE, "api_gateway_health_url": HEALTH, "cloudwatch_log_group": LOG_GROUP,
                "lambda_function_name": FUNCTION}},
            "health.json": checks("health", **{"Health endpoint URL": f"{HEALTH} (argument)", "Health response": "HTTP 200: ok"}),
            "health-response.txt": "ok", "health-status.txt": "200", "cloudwatch-log-groups.json": {"logGroups": [{"logGroupName": LOG_GROUP}]},
            "cloudwatch-tail.txt": "request completed", "active-lambda-image.txt": IMAGE, "notes.md": "Protected prod walkthrough",
            "platform-transcript.txt": f"Release commit: {self.commit}\nLinux host 6.8.0-generic x86_64 GNU/Linux\nID=ubuntu\nVERSION_ID=24.04\n"
                f"Successfully installed devsecops-pipeline-cli-{VERSION}\ndevsecops {VERSION}\n"
                "Demo complete\n# bash completion for devsecops\nRan 200 tests in 2s\n\nOK\n",
        }
        documents.update({name: workflow_run(identifier, self.commit, requirement)
                          for identifier, (name, requirement) in enumerate(evidence.RUN_REQUIREMENTS.items(), 11)})
        self.documents = documents
        for name, content in documents.items():
            self.write(name, content)

    def write(self, name, content):
        (self.directory / name).write_text(json.dumps(content) if isinstance(content, dict) else content, encoding="utf-8")

    def test_validated_evidence_and_reviewed_wheel_pass(self):
        document = self.documents["workflow-run.json"]
        document["run"]["display_title"] += " [" + "a" * 32 + "]"
        self.write("workflow-run.json", document)
        payload = v1_criteria_payload(ROOT, self.directory, artifacts_dir=self.directory)
        self.assertTrue(payload["stable_ready"], payload["stable_release_gates"])

    def test_http_204_evidence_allows_an_empty_response_body(self):
        self.write("health-response.txt", "")
        self.write("health-status.txt", "204")
        self.write("health.json", checks("health", **{"Health endpoint URL": f"{HEALTH} (argument)", "Health response": "HTTP 204: HTTP 204"}))
        payload = v1_criteria_payload(ROOT, self.directory)
        self.assertTrue(payload["stable_ready"], payload["stable_release_gates"])

    def test_platform_gate_accepts_macos_and_refuses_wsl_or_missing_identity(self):
        original = self.documents["platform-transcript.txt"]
        ubuntu = 'Linux host 6.8.0-generic x86_64 GNU/Linux\nID=ubuntu\nVERSION_ID=24.04\n'
        for platform, accepted in (
            ("Darwin host 25.5.0 arm64\nProductName:\tmacOS\nProductVersion:\t26.5.1\n", True),
            ("Darwin host 21.5.0 arm64\nProductName:\tmacOS\nProductVersion:\t12.5.1\n", False),
            ("Linux host 6.6-microsoft-standard-WSL2 x86_64\nID=ubuntu\nVERSION_ID=24.04\n", False),
            ("Linux host 6.8.0-generic x86_64 GNU/Linux\nID=debian\nVERSION_ID=12\n", False),
            ("Linux host 6.8.0-generic x86_64 GNU/Linux\n", False),
        ):
            with self.subTest(platform=platform):
                self.write("platform-transcript.txt", original.replace(ubuntu, platform))
                self.assertEqual(v1_criteria_payload(ROOT, self.directory)["stable_ready"], accepted)
        self.write("platform-transcript.txt", original)

    def test_archive_includes_required_supported_platform_transcript(self):
        archive = self.directory / "platform-bundle.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("platform-transcript.txt", self.documents["platform-transcript.txt"])
            bundle.writestr("wsl2-transcript.txt", "Historical unsupported platform")
        output = self.directory / "platform-unpacked"
        evidence.unpack_evidence(archive, output)
        self.assertEqual([path.name for path in output.iterdir()], ["platform-transcript.txt"])

    def test_blocks_wrong_commit_skipped_apply_digest_mismatch_and_unproven_platform(self):
        proof = self.documents["release-proof.json"]
        for name, content in [
            ("release-proof.json", proof | {"commit_sha": "f" * 40}),
            ("workflow-run.json", workflow_run(11, self.commit, ("DevSecOps deploy prod", "success", {}))),
            ("automatic-rollback-run.json", workflow_run(12, self.commit, ("DevSecOps deploy prod", "failure", evidence.DEPLOY_STEPS))),
            ("active-lambda-image.txt", ROLLBACK),
            ("health.json", checks("health", **{"Health endpoint URL": f"{HEALTH} (argument)", "Health response": "HTTP 302: moved"})),
            ("health-status.txt", "302"),
            ("terraform-context.json", self.documents["terraform-context.json"] | {"workspace": "staging"}),
            ("terraform-context.json", self.documents["terraform-context.json"] | {"expected_account_id": "999999999999"}),
            ("terraform-context.json", self.documents["terraform-context.json"] | {"backend": {"type": "local"}}),
            ("platform-transcript.txt", f"devsecops {VERSION}"),
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

    def test_production_capture_checks_context_before_writing_evidence(self):
        for mismatch in (None, "backend", "workspace", "account", "digest", "lambda_arn"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cfg = copy.deepcopy(self.documents["config.json"])
                config.write_config(root, cfg)
                backend = cloud_evidence.expected_backend(cfg)
                backend_type = backend.pop("type")
                backend["secret_key"] = "never-copy-backend-credentials"
                if mismatch == "backend":
                    backend["bucket"] = "another-project-state"
                metadata = root / "terraform/.terraform/terraform.tfstate"
                metadata.parent.mkdir(parents=True)
                metadata.write_text(json.dumps({"backend": {"type": backend_type, "config": backend}}))
                identity = self.documents["terraform-context.json"]["aws_identity"] | {}
                live = {"Code": {"ResolvedImageUri": IMAGE}, "Configuration": {
                    "FunctionArn": self.documents["terraform-context.json"]["lambda_function_arn"]}}
                if mismatch == "account":
                    identity["Account"] = "999999999999"
                if mismatch == "digest":
                    live["Code"]["ResolvedImageUri"] = ROLLBACK
                if mismatch == "lambda_arn":
                    live["Configuration"]["FunctionArn"] = live["Configuration"]["FunctionArn"].replace("123456789012", "999999999999")
                commands = []

                def provider(command, **kwargs):
                    commands.append(command)
                    self.assertEqual(kwargs["timeout"], 60)
                    if command[0] == "terraform":
                        payload = ("staging" if mismatch == "workspace" else "prod") if command[2] == "workspace" else json.dumps(self.documents["terraform-output.json"])
                    else:
                        self.assertEqual(command[2], "get-caller-identity" if command[1] == "sts" else "get-function")
                        payload = json.dumps(identity if command[1] == "sts" else live)
                    return subprocess.CompletedProcess(command, 0, payload, "")

                directory = root / "evidence"
                with patch.dict(os.environ, {}, clear=True), patch.object(cloud_evidence.subprocess, "run", side_effect=provider):
                    if mismatch:
                        with self.assertRaises(ValueError):
                            cloud_evidence.capture_cloud_evidence(root, directory, "123456789012")
                        self.assertFalse(directory.exists())
                    else:
                        cloud_evidence.capture_cloud_evidence(root, directory, "123456789012")
                        context = json.loads((directory / "terraform-context.json").read_text())
                        self.assertEqual(context["workspace"], "prod")
                        self.assertEqual((directory / "active-lambda-image.txt").read_text().strip(), IMAGE)
                        self.assertNotIn("never-copy", "".join(path.read_text() for path in directory.iterdir()))
                if mismatch == "backend":
                    self.assertFalse(commands)
                if mismatch == "workspace":
                    self.assertFalse([command for command in commands if command[0] == "aws"])
                self.assertFalse([command for command in commands if "apply" in command or "init" in command or "update-function-code" in command])

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
