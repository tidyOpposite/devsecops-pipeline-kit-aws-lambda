"""Exercise the core command boundary, migration and deployment-scoped cleanup."""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import deployment, main, migration, teardown
from devsecops_cli.paths import find_project_root
from test_deployment import ACCOUNT, PROJECT, REGION, FakeDeployment
from test_teardown import BUCKET, FakeS3


class CoreCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for file in main.REQUIRED_PROJECT_FILES:
            path = self.root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n")

    def run_cli(self, args):
        with (
            patch.object(main, "find_project_root", return_value=self.root),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            code = main.main(args)
        return code, json.loads(out.getvalue())

    def legacy(self):
        directory = self.root / ".devsecops/labs/service"
        directory.mkdir(parents=True)
        project = "kit-lab-service-abcdef"
        settings = {
            "schema_version": 1,
            "name": "service",
            "account_id": ACCOUNT,
            "region": REGION,
            "project_name": project,
            "profile": "named-source",
            "aws_binary": "/usr/bin/aws",
            "reserved_concurrency": 10,
        }
        state = {
            "resources": [],
            "outputs": {
                "lab_context": {
                    "value": {
                        "project_name": project,
                        "account_id": ACCOUNT,
                        "region": REGION,
                        "environment": "dev",
                        "purpose": "SingleOperatorLab",
                    }
                }
            },
        }
        deployment.write_json(directory / "settings.json", settings)
        deployment.write_json(directory / "state.tfstate", state)
        return directory, settings

    def test_help_and_parser_expose_only_core_commands(self):
        parser = main.build_parser()
        help_text = parser.format_help()
        for command in ("init", "plan", "apply", "status", "request", "logs", "cleanup", "migrate"):
            self.assertIn(command, help_text)
        for command in (
            "lab",
            "demo",
            "dry-run",
            "deploy",
            "github",
            "setup",
            "menu",
            "tui",
            "generate",
        ):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                parser.parse_args([command])
            self.assertEqual(error.exception.code, 2)

    def test_missing_checkout_fails_before_runtime_or_filesystem_writes(self):
        (self.root / "terraform/main.tf").unlink()
        with patch.object(deployment, "execute") as execute:
            code, result = self.run_cli(
                [
                    "init",
                    "service",
                    "--expected-account-id",
                    ACCOUNT,
                    "--region",
                    REGION,
                    "--profile",
                    "named",
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(code, 1)
        self.assertEqual(result["kind"], "command-error")
        execute.assert_not_called()
        self.assertFalse((self.root / ".devsecops").exists())

    def test_root_discovery_works_from_subdirectories_and_stops_at_nested_git(self):
        child = self.root / "docs/nested"
        child.mkdir(parents=True)
        self.assertEqual(find_project_root(child), self.root)
        (child / ".git").write_text("gitdir: fixture")
        self.assertEqual(find_project_root(child), child)

    def test_migration_preview_and_apply_preserve_scope_state_and_original_settings(self):
        source, settings = self.legacy()
        state_bytes = (source / "state.tfstate").read_bytes()
        with patch.object(
            deployment.Deployment, "aws", side_effect=AssertionError("Migration must stay offline")
        ):
            code, result = self.run_cli(["migrate", "service", "--format", "json"])
            self.assertEqual((code, result["status"]), (0, "review-required"))
            self.assertEqual(deployment.read_json(source / "settings.json"), settings)
            self.assertFalse((self.root / ".devsecops/deployments/service").exists())
            code, result = self.run_cli(["migrate", "service", "--yes", "--format", "json"])
        self.assertEqual((code, result["status"]), (0, "migrated"))
        target = deployment.Deployment(self.root, "service")
        target.load()
        self.assertEqual(target.settings["purpose"], "SingleOperatorLab")
        self.assertEqual(target.settings["project_name"], settings["project_name"])
        self.assertEqual(target.state.read_bytes(), state_bytes)
        self.assertEqual(deployment.read_json(target.home / "settings.v1.json"), settings)
        self.assertFalse(source.exists())
        target.outputs()

    def test_migration_rejects_existing_destination_foreign_state_and_symlinks(self):
        source, settings = self.legacy()
        destination = self.root / ".devsecops/deployments/service"
        destination.mkdir(parents=True)
        with self.assertRaisesRegex(deployment.DeploymentError, "already exists"):
            migration.migrate(self.root, "service", True)
        destination.rmdir()
        state = deployment.read_json(source / "state.tfstate")
        state["outputs"]["lab_context"]["value"]["account_id"] = "999999999999"
        deployment.write_json(source / "state.tfstate", state)
        with self.assertRaisesRegex(deployment.DeploymentError, "context"):
            migration.migrate(self.root, "service", True)
        self.assertEqual(deployment.read_json(source / "settings.json"), settings)
        (source / "link").symlink_to(source / "state.tfstate")
        with self.assertRaisesRegex(deployment.DeploymentError, "symlinks"):
            migration.migrate(self.root, "service", True)

    def test_failed_migration_restores_settings_and_keeps_state(self):
        source, settings = self.legacy()
        with patch.object(migration.os, "rename", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                migration.migrate(self.root, "service", True)
        self.assertEqual(deployment.read_json(source / "settings.json"), settings)
        self.assertTrue((source / "state.tfstate").is_file())

    def test_migration_rejects_noninteger_schema_before_rewriting_settings(self):
        source, settings = self.legacy()
        for value in (True, 1.0, "1", None):
            with self.subTest(schema=value):
                invalid = {**settings, "schema_version": value}
                deployment.write_json(source / "settings.json", invalid)
                with self.assertRaisesRegex(deployment.DeploymentError, "Unsupported legacy"):
                    migration.migrate(self.root, "service", True)
                self.assertEqual(deployment.read_json(source / "settings.json"), invalid)
                self.assertFalse((source / "settings.v1.json").exists())
                self.assertFalse((self.root / ".devsecops/deployments/service").exists())

    def test_config_rejects_noninteger_schema(self):
        source, legacy = self.legacy()
        settings = {**legacy, "schema_version": 2, "purpose": "SingleOperatorLab"}
        instance = deployment.Deployment(self.root, "service")
        deployment.write_json(instance.settings_path, settings)
        code, result = self.run_cli(["config", "service", "--format", "json"])
        self.assertEqual((code, result["status"]), (0, "configured"))
        for value in (2.0, True, "2", None):
            with self.subTest(schema=value):
                deployment.write_json(instance.settings_path, {**settings, "schema_version": value})
                code, result = self.run_cli(["config", "service", "--format", "json"])
                self.assertEqual(code, 1)
                self.assertEqual(result["kind"], "command-error")

    def test_migrated_old_plan_is_rejected_without_terraform(self):
        source, _ = self.legacy()
        plan_id = "a" * 32
        review = source / "plans" / plan_id / "review.json"
        deployment.write_json(review, {"kind": "single-operator-lab-plan", "schema_version": 1})
        migration.migrate(self.root, "service", True)
        target = deployment.Deployment(self.root, "service")
        target.load()
        review = target.home / "plans" / plan_id / "review.json"
        with patch.object(target, "tf", side_effect=AssertionError("old plan must not execute")):
            with self.assertRaisesRegex(deployment.DeploymentError, "stale"):
                target.apply(plan_id, deployment.digest(review), True)

    def test_init_does_not_silently_recreate_an_existing_legacy_deployment(self):
        self.legacy()
        with patch.object(
            deployment.Deployment, "aws", side_effect=AssertionError("No provider call")
        ):
            code, result = self.run_cli(
                [
                    "init",
                    "service",
                    "--expected-account-id",
                    ACCOUNT,
                    "--region",
                    REGION,
                    "--profile",
                    "named",
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("migrate", result["error"])
        self.assertFalse((self.root / ".devsecops/deployments/service").exists())

    def test_config_is_offline_and_json_never_contains_provider_progress(self):
        instance = FakeDeployment(self.root)
        instance.settings = {
            "schema_version": 2,
            "name": "diploma",
            "account_id": ACCOUNT,
            "region": REGION,
            "project_name": PROJECT,
            "profile": "named-source",
            "aws_binary": "/usr/bin/aws",
            "purpose": "Deployment",
            "reserved_concurrency": 10,
        }
        deployment.write_json(instance.settings_path, instance.settings)
        with patch.object(
            deployment.Deployment, "aws", side_effect=AssertionError("Config stays offline")
        ):
            code, result = self.run_cli(["config", "diploma", "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(result["settings"]["profile"], "named-source")

    def test_cleanup_requires_owned_state_bucket_and_uses_named_deployment_client(self):
        instance = deployment.Deployment(self.root, "service")
        settings = {
            "schema_version": 2,
            "name": "service",
            "account_id": ACCOUNT,
            "region": "us-east-1",
            "project_name": "kit-service-abcdef",
            "profile": "named-source",
            "aws_binary": "/usr/bin/aws",
            "purpose": "Deployment",
            "reserved_concurrency": 10,
        }
        deployment.write_json(instance.settings_path, settings)
        deployment.write_json(
            instance.state,
            {
                "resources": [
                    {
                        "module": "module.storage",
                        "type": "aws_s3_bucket",
                        "name": "output_bucket",
                        "instances": [
                            {
                                "attributes": {
                                    "bucket": BUCKET,
                                    "tags": {
                                        "Project": settings["project_name"],
                                        "Environment": "dev",
                                        "Purpose": "Deployment",
                                    },
                                }
                            }
                        ],
                    }
                ]
            },
        )
        s3 = FakeS3()
        s3.region = "us-east-1"

        def adapter(self, args, *, payload=None, secret=False):
            return s3(args, "us-east-1", payload)

        args = [
            "cleanup",
            "service",
            "bucket-plan",
            "--bucket",
            BUCKET,
            "--purpose",
            "workload-data",
            "--output",
            "inventory.json",
            "--format",
            "json",
        ]
        with patch.object(deployment.Deployment, "aws", new=adapter):
            code, result = self.run_cli(args)
            self.assertEqual(code, 0)
            self.assertTrue((self.root / "inventory.json").is_file())
            self.assertFalse(s3.mutations())
            digest = result["cleanup"]["sha256"]
            code, result = self.run_cli(
                [
                    "cleanup",
                    "service",
                    "bucket-purge",
                    "--bucket",
                    BUCKET,
                    "--purpose",
                    "workload-data",
                    "--manifest",
                    "inventory.json",
                    "--sha256",
                    digest,
                    "--acknowledge-backup",
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(result["cleanup"]["status"], "empty")
        args[args.index(BUCKET)] = "foreign-bucket"
        with patch.object(deployment.Deployment, "aws") as aws:
            code, result = self.run_cli(args)
        self.assertEqual(code, 1)
        aws.assert_not_called()

    def test_cleanup_manifest_purpose_mismatch_is_rejected_before_deletion(self):
        s3 = FakeS3()
        path = self.root / "inventory.json"
        with patch.object(teardown, "aws_json", side_effect=s3):
            result = teardown.bucket_plan(BUCKET, ACCOUNT, "us-east-1", "workload-data", path)
            with self.assertRaisesRegex(teardown.TeardownError, "purpose"):
                teardown.bucket_purge(
                    path,
                    result["sha256"],
                    BUCKET,
                    ACCOUNT,
                    "us-east-1",
                    True,
                    expected_purpose="workload-logs",
                )
        self.assertFalse(s3.mutations())

    def test_runtime_aws_boundary_uses_profile_and_stdin_without_ambient_credentials(self):
        instance = deployment.Deployment(self.root, "service")
        instance.settings = {
            "profile": "named-source",
            "region": REGION,
            "aws_binary": "/usr/bin/aws",
        }
        payload = {"Objects": [{"Key": "private key", "VersionId": "explicit"}]}
        with (
            patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "ambient-secret"}),
            patch.object(
                deployment.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, "{}", ""),
            ) as run,
        ):
            instance.aws(
                ["s3api", "delete-objects", "--delete", "file:///dev/stdin"], payload=payload
            )
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
        self.assertNotIn("AWS_ACCESS_KEY_ID", run.call_args.kwargs["env"])
        self.assertEqual(
            run.call_args.args[0][run.call_args.args[0].index("--profile") + 1], "named-source"
        )

    def test_corrupt_settings_and_aws_json_shapes_fail_as_domain_errors(self):
        instance = deployment.Deployment(self.root, "service")
        deployment.write_json(instance.settings_path, [])
        with self.assertRaises(deployment.DeploymentError):
            instance.load()
        with patch.object(
            instance, "run", return_value=subprocess.CompletedProcess([], 0, "[]", "")
        ):
            instance.settings = {"aws_binary": "/usr/bin/aws", "profile": "named", "region": REGION}
            with self.assertRaisesRegex(deployment.DeploymentError, "invalid JSON"):
                instance.aws(["sts", "get-caller-identity"])

    def test_unexpected_boundary_error_is_json_without_exception_values(self):
        with patch.object(deployment, "execute", side_effect=RuntimeError("private-sentinel")):
            code, result = self.run_cli(["status", "service", "--format", "json"])
        self.assertEqual(code, 70)
        self.assertEqual(result["kind"], "command-error")
        self.assertNotIn("private-sentinel", json.dumps(result))
