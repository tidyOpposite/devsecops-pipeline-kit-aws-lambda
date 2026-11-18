"""Local demo completion must remain separate from production verification."""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import config, main as cli, setup
from devsecops_cli.paths import REQUIRED_PROJECT_FILES

ROOT = Path(__file__).resolve().parents[2]


class DemoJourneyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name in REQUIRED_PROJECT_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# demo fixture\n")
        binaries = self.root / "provider-stubs"
        binaries.mkdir()
        self.trace = self.root / "provider-calls"
        for name in ("aws", "gh", "terraform"):
            path = binaries / name
            path.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$DEMO_PROVIDER_TRACE"\nexit 99\n')
            path.chmod(0o755)
        self.environment = dict(os.environ, PYTHONPATH=str(ROOT / "cli"), NO_COLOR="1",
                                PATH=str(binaries) + os.pathsep + os.environ["PATH"], DEMO_PROVIDER_TRACE=str(self.trace))

    def invoke(self, *arguments, input=None):
        return subprocess.run([sys.executable, "-m", "devsecops_cli", *arguments], cwd=self.root, env=self.environment,
                              input=input, text=True, capture_output=True, timeout=20, check=False)

    def start_demo(self):
        result = self.invoke("setup", "--yes", "--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_new_default_demo_completes_without_tools_or_cloud_and_uses_dev_preview(self):
        output = self.start_demo()
        state = setup.load_setup_state(self.root)
        self.assertEqual(state["mode"], "demo")
        self.assertEqual(state["preset"], "student-demo")
        self.assertEqual(state["steps"]["summary"]["status"], "complete")
        self.assertIn("Demo complete", output)
        self.assertIn("Demo preview environment: dev", output)
        self.assertIn("dev-lambda-repo", output.replace("\n", ""))
        self.assertNotIn("Environment target: prod", output)
        self.assertNotIn("Production blockers", output)
        self.assertNotIn("WARN", output)
        self.assertEqual(output.count("Next command:"), 1)
        self.assertIn(setup.PRODUCTION_SETUP_COMMAND, output)
        self.assertFalse(config.load_config(self.root)["lambda_image_uri"])
        failed = self.invoke("setup", "--yes", "--strict", "--image-uri", "invalid-image")
        self.assertNotEqual(failed.returncode, 0)
        self.assertNotIn("Demo complete", failed.stdout)
        self.assertFalse(config.load_config(self.root)["lambda_image_uri"])
        (self.root / setup.SETUP_STATE_FILE).write_text("{invalid state")
        updated = self.invoke("config", "set", "project_name", "repaired-demo")
        self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
        advice = self.invoke("generate", "--dry-run")
        self.assertEqual(advice.returncode, 0, advice.stdout + advice.stderr)
        self.assertIn("Next step unavailable", advice.stdout)
        self.assertEqual(config.load_config(self.root)["project_name"], "repaired-demo")
        self.assertFalse(self.trace.exists())

    def test_overview_status_preview_and_menu_keep_the_completed_local_scope(self):
        self.start_demo()
        for arguments in ((), ("status",), ("status", "--format", "compact"), ("dashboard",), ("dry-run",), ("menu",)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments, input="0\n" if arguments == ("menu",) else None)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("Environment target: prod", result.stdout)
                self.assertNotIn("Backend bucket", result.stdout)
                self.assertNotIn("Production security policy gaps", result.stdout)
                self.assertNotIn("Blocked", result.stdout)
                if arguments != ("dry-run",):
                    self.assertIn("Demo complete", result.stdout)
        payload = json.loads(self.invoke("status", "--format", "json").stdout)
        self.assertEqual(payload["context"]["scope"], "demo")
        self.assertTrue(payload["demo_complete"])
        self.assertEqual(payload["score"], 100)
        self.assertEqual(payload["gaps"], [])
        self.assertEqual(payload["next_action"]["action"], "demo_complete")
        self.assertNotEqual(next(g for g in payload["gates"] if g["gate"] == "Ready to deploy")["status"], "OK")
        self.assertFalse(self.trace.exists())

    def test_demo_completion_is_rechecked_after_config_drift_and_can_be_resumed(self):
        self.start_demo()
        cfg = config.load_config(self.root)
        cfg["project_name"] = "updated-demo"
        config.write_config(self.root, cfg)
        payload = json.loads(self.invoke("status", "--format", "json").stdout)
        self.assertFalse(payload["demo_complete"])
        self.assertEqual(payload["next_action"]["action"], "demo_needs_refresh")
        self.assertEqual(payload["next_action"]["command"], "devsecops setup --yes")
        self.start_demo()
        self.assertTrue(json.loads(self.invoke("status", "--format", "json").stdout)["demo_complete"])
        source = self.root / "terraform/main.tf"
        source.unlink()
        source.mkdir()
        self.assertFalse(json.loads(self.invoke("status", "--format", "json").stdout)["demo_complete"])
        self.assertNotEqual(self.invoke("setup", "--yes", "--strict").returncode, 0)
        self.assertFalse(self.trace.exists())

    def test_strict_status_still_requires_production_and_deep_is_explicit(self):
        self.start_demo()
        result = self.invoke("status", "--strict", "--format", "json")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertNotEqual(payload["context"].get("scope"), "demo")
        self.assertNotEqual(next(g for g in payload["gates"] if g["gate"] == "Ready to deploy")["status"], "OK")
        self.assertFalse(self.trace.exists())
        before = (self.root / config.CONFIG_FILE).read_bytes()
        for option in ("--pre-deploy", "--deep"):
            result = self.invoke("status", option, "--strict", "--format", "json")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotEqual(json.loads(result.stdout)["context"].get("scope"), "demo")
            self.assertTrue(self.trace.exists())
        self.assertEqual((self.root / config.CONFIG_FILE).read_bytes(), before)

    def test_interactive_default_is_demo_and_saved_or_explicit_modes_are_preserved(self):
        with patch("builtins.input", return_value=""), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.choose_setup_mode(argparse.Namespace(), None), ("demo", "student-demo"))
        for mode in ("standard", "production"):
            state = setup.new_setup_state(mode)
            self.assertEqual(cli.choose_setup_mode(argparse.Namespace(yes=True), state), (mode, state["preset"]))
        self.assertEqual(cli.choose_setup_mode(argparse.Namespace(yes=True, preset="balanced"), None), ("standard", "balanced"))

    def test_menu_production_transition_is_a_separate_interactive_action(self):
        self.start_demo()
        original = (self.root / config.CONFIG_FILE).read_bytes()
        with patch.object(cli, "repo_root", return_value=self.root), patch.object(cli, "cmd_setup", return_value=0) as transition, \
             patch("builtins.input", side_effect=["7", "", "0"]), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["menu"]), 0)
        transition.assert_called_once()
        arguments = transition.call_args.args[0]
        self.assertEqual(arguments.mode, "production")
        self.assertFalse(arguments.yes)
        self.assertEqual((self.root / config.CONFIG_FILE).read_bytes(), original)
