"""Security gate failure propagation and credential boundaries, without AWS."""

import io
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import acceptance, scanner
from devsecops_cli.models import Check

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/workload@sha256:" + "a" * 64


def target():
    return {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main", "ENABLE_CLOUD_ACCEPTANCE": "true",
            "ACCEPTANCE_AWS_ACCOUNT_ID": "123456789012", "PRODUCTION_AWS_ACCOUNT_ID": "999999999999",
            "AWS_ACCEPTANCE_ROLE_ARN": "arn:aws:iam::123456789012:role/acceptance", "ACCEPTANCE_AWS_REGION": "us-east-1",
            "ACCEPTANCE_IMAGE_URI": IMAGE, "GITHUB_REPOSITORY": "owner/repository", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}


class SecurityGateTests(unittest.TestCase):
    def test_scanner_receives_only_token_and_readonly_archive_and_failures_block(self):
        for outcome in (0, 1, 2, 3, "timeout"):
            with self.subTest(outcome=outcome):
                calls = []

                def provider(command, **kwargs):
                    calls.append((command, kwargs))
                    if command[:3] == ["docker", "image", "save"]:
                        Path(command[command.index("--output") + 1]).write_bytes(b"archive fixture")
                    if command[:2] == ["docker", "run"]:
                        if outcome == "timeout":
                            raise subprocess.TimeoutExpired(command, 900)
                        if outcome:
                            raise subprocess.CalledProcessError(outcome, command)
                    return subprocess.CompletedProcess(command, 0, "never-log-registry-token\n", "")

                environment = {"LAMBDA_IMAGE_URI": IMAGE, "AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "fixture-key",
                               "AWS_SECRET_ACCESS_KEY": "fixture-secret", "SNYK_TOKEN": "never-log-snyk-token", "GH_TOKEN": "fixture-gh"}
                output = io.StringIO()
                with patch.dict(os.environ, environment, clear=True), patch.object(scanner.subprocess, "run", side_effect=provider), \
                     patch.object(scanner.sys, "argv", ["scanner", "scan"]), redirect_stderr(output), redirect_stdout(output):
                    self.assertEqual(scanner.main(), 0 if outcome == 0 else 1)
                container, _ = next(item for item in calls if item[0][:2] == ["docker", "run"])
                forwarded = [container[index + 1] for index, value in enumerate(container[:-1]) if value == "--env"]
                self.assertEqual(forwarded, ["HOME=/tmp", "SNYK_TOKEN"])
                mounts = [container[index + 1] for index, value in enumerate(container[:-1]) if value == "--mount"]
                self.assertEqual(len(mounts), 1)
                self.assertTrue(mounts[0].endswith(",dst=/scan/image.tar,readonly"))
                self.assertIn("--cap-drop=ALL", container)
                self.assertIn("--security-opt=no-new-privileges", container)
                self.assertIn("--read-only", container)
                self.assertIn("--user=65534:65534", container)
                self.assertFalse(any("docker.sock" in argument for argument in container))
                self.assertIn("docker-archive:/scan/image.tar", container)
                self.assertEqual(calls[-1][0][:3], ["docker", "image", "rm"])
                pull = next(command for command, _ in calls if command[:2] == ["docker", "pull"])
                self.assertEqual(pull[-1], IMAGE)
                login, login_options = next(item for item in calls if item[0][:2] == ["docker", "login"])
                self.assertEqual(login[-1], "123456789012.dkr.ecr.us-east-1.amazonaws.com")
                self.assertEqual(login_options["input"], "never-log-registry-token")
                self.assertNotIn("never-log", " ".join(argument for command, _ in calls for argument in command))
                self.assertNotIn("never-log", output.getvalue())
                config = Path(login_options["env"]["DOCKER_CONFIG"])
                self.assertFalse(config.parent.exists())

    def test_scanner_rejects_wrong_binary_version_and_mutable_image(self):
        with patch.object(scanner, "run", return_value=subprocess.CompletedProcess([], 0, "0.0.0\n", "")), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "reviewed CLI version"):
                scanner.prepare(ROOT)
        with patch.object(scanner, "run") as provider, patch.dict(os.environ, {"SNYK_TOKEN": "fixture"}, clear=True):
            for image in (IMAGE.split("@")[0] + ":latest", IMAGE.replace("us-east-1", "eu-west-1")):
                with self.assertRaises(ValueError):
                    scanner.scan(image, "us-east-1")
            provider.assert_not_called()

    def test_cloud_acceptance_guards_reject_wrong_accounts_refs_and_images_before_calls(self):
        for overrides in (
            {"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_REF": "refs/heads/feature"}, {"ENABLE_CLOUD_ACCEPTANCE": "false"},
            {"ACCEPTANCE_AWS_ACCOUNT_ID": "999999999999"}, {"PRODUCTION_AWS_ACCOUNT_ID": ""},
            {"AWS_ACCEPTANCE_ROLE_ARN": "arn:aws:iam::999999999999:role/production"},
            {"ACCEPTANCE_IMAGE_URI": IMAGE.split("@")[0] + ":latest"}, {"ACCEPTANCE_AWS_REGION": "eu-west-1"},
            {"ACCEPTANCE_IMAGE_URI": IMAGE.replace("123456789012", "999999999999")}, {"GITHUB_RUN_ID": ""},
        ):
            with self.subTest(overrides=overrides), patch.object(acceptance, "_aws_json") as aws, \
                 patch.object(acceptance, "protected_environment_check") as github:
                with self.assertRaises(ValueError):
                    acceptance.prepare(ROOT, target() | overrides, verify_identity=False)
                aws.assert_not_called()
                github.assert_not_called()
        values = acceptance.settings(target())
        self.assertEqual(len(values["project_name"]), 32)
        self.assertNotEqual(values["project_name"], acceptance.settings(target() | {"GITHUB_RUN_ATTEMPT": "2"})["project_name"])

    def test_cloud_acceptance_verifies_actual_identity_and_protection(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            (root / "terraform/acceptance").mkdir(parents=True)
            destination = root / "terraform/acceptance/acceptance.auto.tfvars.json"
            with patch.object(acceptance, "protected_environment_check", return_value=Check("Acceptance", "FAIL", "No reviewers")):
                with self.assertRaisesRegex(ValueError, "No reviewers"):
                    acceptance.prepare(root, target(), verify_identity=False)
            with patch.object(acceptance, "_aws_json", return_value=({"Account": "999999999999"}, subprocess.CompletedProcess([], 0, "", ""))), \
                 patch.object(acceptance, "verify_ecr_lambda_image") as image:
                with self.assertRaisesRegex(ValueError, "active AWS session"):
                    acceptance.prepare(root, target(), verify_identity=True)
                image.assert_not_called()
                self.assertFalse(destination.exists())
            with patch.object(acceptance, "_aws_json", return_value=({"Account": "123456789012"}, subprocess.CompletedProcess([], 0, "", ""))), \
                 patch.object(acceptance, "verify_ecr_lambda_image", return_value=IMAGE) as image:
                acceptance.prepare(root, target(), verify_identity=True)
                image.assert_called_once_with(root, IMAGE, "us-east-1")
                self.assertTrue(destination.exists())

    def test_dependabot_targets_have_real_manifests(self):
        source = (ROOT / ".github/dependabot.yml").read_text()
        for block in source.split('- package-ecosystem: "')[1:]:
            ecosystem = block.split('"', 1)[0]
            relative = re.search(r'directory: "([^"]+)"', block)[1]
            directory = ROOT / relative.lstrip("/")
            if ecosystem == "pip":
                self.assertTrue((directory / "pyproject.toml").is_file())
            elif ecosystem == "docker":
                self.assertTrue((directory / "Dockerfile").is_file())
            elif ecosystem == "terraform":
                self.assertTrue(list(directory.glob("*.tf")))
            elif ecosystem == "github-actions":
                self.assertTrue((directory / ".github/workflows").is_dir())

    def test_aws_acceptance_is_manual_and_separate_from_default_mock_tests(self):
        workflow = (ROOT / ".github/workflows/cloud-acceptance.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("environment: acceptance", workflow)
        self.assertIn("unset-current-credentials: true", workflow)
        self.assertIn("allowed_account_ids = [var.expected_account_id]", (ROOT / "terraform/acceptance/main.tf").read_text())
        self.assertLess(workflow.index("acceptance preflight"), workflow.index("role-to-assume:"))
        self.assertLess(workflow.index("acceptance prepare"), workflow.index("test -test-directory=cloud-tests"))
        self.assertIn('mock_provider "aws"', (ROOT / "terraform/acceptance/tests/mocked.tftest.hcl").read_text())
        self.assertNotIn('mock_provider "aws"', (ROOT / "terraform/acceptance/cloud-tests/runtime.tftest.hcl").read_text())
        source = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("test -test-directory=tests", source)
        self.assertNotIn("test -test-directory=cloud-tests", source)
        deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
        self.assertIn("TRIVY_SKIP_CHECK_UPDATE: 'true'", deploy)
        self.assertIn("cache: 'false'", deploy)
