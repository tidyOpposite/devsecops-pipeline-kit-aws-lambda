"""Setup must review replacements and reject bad input before any writes."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import main as cli
from devsecops_cli.paths import REQUIRED_PROJECT_FILES

ROOT = Path(__file__).resolve().parents[2]


class SetupTransitionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name in REQUIRED_PROJECT_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# setup fixture\n")
        binaries = self.root / "provider-stubs"
        binaries.mkdir()
        self.trace = self.root / "provider-calls"
        for name in ("aws", "gh", "terraform"):
            path = binaries / name
            path.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$SETUP_PROVIDER_TRACE"\nexit 99\n')
            path.chmod(0o755)
        self.environment = dict(os.environ, PYTHONPATH=str(ROOT / "cli"), NO_COLOR="1",
                                PATH=str(binaries) + os.pathsep + os.environ["PATH"], SETUP_PROVIDER_TRACE=str(self.trace))

    def invoke(self, *options, input=None):
        return subprocess.run([sys.executable, "-m", "devsecops_cli", "setup", *options], cwd=self.root,
                              env=self.environment, input=input, text=True, capture_output=True, timeout=20, check=False)

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def existing_demo(self, mode="demo"):
        cfg = cli.clean_config("student-demo")
        cfg["project_name"] = "custom-project"
        cfg["aws_region"] = "eu-central-1"
        cfg["lambda_image_uri"] = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/custom-image:release-1"
        cfg["terraform_admin_role_name"] = "custom-admin"
        cfg["backend"].update(bucket="custom-state-bucket", region="eu-central-1", lock_table="custom-locks")
        cfg["environments"]["prod"]["lambda_memory_size"] = 1536
        cli.write_config(self.root, cfg)
        state = cli.new_setup_state(mode)
        state["dry_run_fingerprint"] = cli.setup_config_fingerprint(cfg)
        cli.save_setup_state(self.root, state)
        generated = self.root / cli.DIST_DIR / "existing-file"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("previous generated data\n")
        return cfg

    def run_isolated(self, options, answers):
        output = io.StringIO()
        with patch.object(cli, "repo_root", return_value=self.root), \
             patch.object(cli, "command_exists", return_value=False), \
             patch.object(cli, "setup_aws_identity", return_value=None), \
             patch.object(cli, "setup_backend_resource_checks", return_value=[]), \
             patch.object(cli, "setup_github_connection", return_value=([], False)), \
             patch.object(cli, "cmd_dry_run", return_value=0), \
             patch("builtins.input", side_effect=answers), redirect_stdout(output):
            result = cli.main(["setup", *options])
        return result, output.getvalue()

    def test_yes_alone_shows_the_exact_preserving_diff_without_any_writes_or_providers(self):
        cfg = self.existing_demo()
        before = self.files()
        result = self.invoke("--mode", "production", "--yes")
        self.assertEqual(result.returncode, cli.EXIT_VALIDATION_FAILED, result.stdout + result.stderr)
        expected = cli.unified_text_diff(cli.canonical_config_text(cfg),
                                        cli.canonical_config_text(cli.config_with_preset(cfg, "enterprise")),
                                        cli.CONFIG_FILE, "setup preset:enterprise")
        self.assertIn(expected, result.stdout)
        self.assertIn("--apply-mode-preset", result.stdout)
        self.assertNotIn('-project_name = "custom-project"', result.stdout)
        self.assertEqual(self.files(), before)
        self.assertFalse(self.trace.exists())

    def test_bad_supplied_inputs_preserve_existing_config_progress_and_artifacts(self):
        self.existing_demo()
        cases = [
            ["--image-uri", "not-an-image"],
            ["--image-uri", ""],
            ["--image-uri", "123456789012.dkr.ecr.us-east-1.amazonaws.com/image:release-1"],
            ["--backend-bucket", "INVALID bucket"],
            ["--backend-bucket", ""],
            ["--backend-region", "invalid-region"],
            ["--backend-lock-table", " "],
            ["--deploy-role-arn", "arn:aws:iam::123456789012:role/deploy"],
            ["--apply-github", "--deploy-role-arn", "invalid-arn"],
            ["--apply-github", "--deploy-role-arn", "arn:aws:iam::123456789012:role/deploy"],
            ["--apply-github", "--deploy-role-arn", "arn:aws:iam::123456789012:role/Same",
             "--plan-role-arn", "arn:aws:iam::123456789012:role/same"],
            ["--apply-github", "--snyk-token", " "],
        ]
        before = self.files()
        for options in cases:
            with self.subTest(options=options):
                result = self.invoke("--mode", "production", "--yes", "--apply-mode-preset", *options)
                self.assertEqual(result.returncode, cli.EXIT_VALIDATION_FAILED, result.stdout + result.stderr)
                self.assertNotIn("Proposed `enterprise`", result.stdout)
                self.assertEqual(self.files(), before)
        result = self.invoke("--mode", "demo", "--yes", "--backend-region", "us-east-1")
        self.assertEqual(result.returncode, cli.EXIT_VALIDATION_FAILED)
        self.assertEqual(self.files(), before)

    def test_bad_initial_input_does_not_create_config_state_or_snapshots(self):
        before = self.files()
        for options in (["--mode", "demo", "--backend-bucket", "demo-state"],
                        ["--mode", "standard", "--backend-region", "bad"],
                        ["--mode", "production", "--image-uri", "invalid-image"]):
            with self.subTest(options=options):
                result = self.invoke("--yes", *options)
                self.assertEqual(result.returncode, cli.EXIT_VALIDATION_FAILED, result.stdout + result.stderr)
                self.assertEqual(self.files(), before)

    def test_new_interactive_config_can_select_the_supplied_images_region(self):
        image = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/new-image:release-1"
        code, output = self.run_isolated(["--mode", "standard", "--image-uri", image], ["y", "", "", "n"])
        self.assertEqual(code, cli.EXIT_OK, output)
        cfg = cli.load_config(self.root)
        self.assertEqual(cfg["aws_region"], "eu-central-1")
        self.assertEqual(cfg["lambda_image_uri"], image)

    def test_cancel_at_review_leaves_even_the_saved_mode_and_timestamp_unchanged(self):
        self.existing_demo()
        before = self.files()
        result = self.invoke("--mode", "production", input="0\n")
        self.assertEqual(result.returncode, cli.EXIT_OK, result.stdout + result.stderr)
        self.assertIn("before any changes were saved", result.stdout)
        self.assertEqual(self.files(), before)

    def test_enter_explicitly_keeps_config_and_records_unmet_production_requirements(self):
        self.existing_demo()
        original = cli.config_path(self.root).read_bytes()
        code, output = self.run_isolated(["--mode", "production", "--strict"], [""])
        self.assertNotEqual(code, cli.EXIT_OK)
        self.assertIn("Keeping existing configuration", output)
        self.assertEqual(cli.config_path(self.root).read_bytes(), original)
        state = cli.load_setup_state(self.root)
        self.assertEqual(state["mode"], "production")
        self.assertEqual(state["steps"]["config"]["status"], "pending")
        self.assertFalse(cli.list_snapshots(self.root))

    def test_interactive_acceptance_applies_only_the_reviewed_changes_with_recovery_snapshot(self):
        cfg = self.existing_demo()
        original = cli.config_path(self.root).read_bytes()
        code, output = self.run_isolated(["--mode", "production"], ["y"])
        self.assertEqual(code, cli.EXIT_OK, output)
        self.assertIn("Proposed `enterprise`", output)
        self.assertLess(output.index("setup preset:enterprise"), output.index("Updated"))
        self.assertEqual(cli.load_config(self.root), cli.config_with_preset(cfg, "enterprise"))
        self.assertEqual(cli.load_setup_state(self.root)["mode"], "production")
        snapshots = cli.list_snapshots(self.root)
        self.assertEqual(len(snapshots), 1)
        snapshot_files = [path for path in (self.root / ".devsecops").rglob(cli.CONFIG_FILE)]
        self.assertTrue(any(path.read_bytes() == original for path in snapshot_files))

    def test_explicit_flag_authorizes_noninteractive_replacement_without_prompting(self):
        cfg = self.existing_demo()
        code, output = self.run_isolated(["--mode", "production", "--yes", "--apply-mode-preset"], [])
        self.assertEqual(code, cli.EXIT_OK, output)
        self.assertEqual(cli.load_config(self.root), cli.config_with_preset(cfg, "enterprise"))
        self.assertIn("Proposed `enterprise`", output)
        self.assertEqual(len(cli.list_snapshots(self.root)), 1)

    def test_resume_with_posture_gaps_still_requires_review(self):
        self.existing_demo(mode="production")
        before = self.files()
        result = self.invoke("--yes")
        self.assertEqual(result.returncode, cli.EXIT_VALIDATION_FAILED, result.stdout + result.stderr)
        self.assertIn("Proposed `enterprise`", result.stdout)
        self.assertEqual(self.files(), before)

    def test_mode_change_can_reuse_compliant_settings_without_preset_replacement(self):
        cfg = cli.clean_config("enterprise")
        cli.write_config(self.root, cfg)
        cli.save_setup_state(self.root, cli.new_setup_state("production"))
        original = cli.config_path(self.root).read_bytes()
        result = self.invoke("--mode", "demo", "--yes", "--strict")
        self.assertEqual(result.returncode, cli.EXIT_OK, result.stdout + result.stderr)
        self.assertNotIn("Proposed", result.stdout)
        self.assertEqual(cli.config_path(self.root).read_bytes(), original)
        self.assertEqual(cli.load_setup_state(self.root)["mode"], "demo")
        self.assertFalse(cli.list_snapshots(self.root))
        self.assertFalse(self.trace.exists())

    def test_explicit_replacement_also_reviews_a_downgrade_without_posture_gaps(self):
        cli.write_config(self.root, cli.clean_config("enterprise"))
        cli.save_setup_state(self.root, cli.new_setup_state("production"))
        result = self.invoke("--mode", "demo", "--yes", "--apply-mode-preset", "--strict")
        self.assertEqual(result.returncode, cli.EXIT_OK, result.stdout + result.stderr)
        self.assertIn("Proposed `student-demo`", result.stdout)
        self.assertFalse(cli.load_config(self.root)["use_prod_approval_environment"])
        self.assertEqual(len(cli.list_snapshots(self.root)), 1)
        self.assertFalse(self.trace.exists())
