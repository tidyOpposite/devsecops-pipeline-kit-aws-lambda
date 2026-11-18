"""Project discovery and the local first-run journey from real subprocesses."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from devsecops_cli import config
from devsecops_cli.paths import CONFIG_FILE, REQUIRED_PROJECT_FILES, find_project_root

ROOT = Path(__file__).resolve().parents[2]


def checkout(root):
    for name in REQUIRED_PROJECT_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# project fixture\n")


class ProjectDiscoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="kit project ' with spaces ")
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)
        self.root = self.directory / "checkout"
        checkout(self.root)
        self.trace = self.directory / "unexpected-provider-calls"
        binaries = self.directory / "provider stubs"
        binaries.mkdir()
        for name in ("aws", "gh", "terraform"):
            path = binaries / name
            path.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$DISCOVERY_PROVIDER_TRACE"\nexit 99\n')
            path.chmod(0o755)
        self.environment = dict(os.environ, PYTHONPATH=str(ROOT / "cli"),
                                PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                                DISCOVERY_PROVIDER_TRACE=str(self.trace), NO_COLOR="1")

    def invoke(self, cwd, *arguments):
        return subprocess.run([sys.executable, "-m", "devsecops_cli", *arguments], cwd=cwd,
                              env=self.environment, text=True, capture_output=True, timeout=20, check=False)

    def test_demo_from_subdirectory_writes_config_progress_and_snapshots_at_root(self):
        child = self.root / "terraform/modules/lambda"
        result = self.invoke(child, "setup", "--mode", "demo", "--yes", "--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / CONFIG_FILE).is_file())
        self.assertTrue((self.root / ".devsecops/setup-state.json").is_file())
        self.assertFalse((child / CONFIG_FILE).exists())
        self.assertFalse((child / ".devsecops").exists())
        result = self.invoke(child, "generate", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "terraform/generated.auto.tfvars").exists())
        result = self.invoke(child, "config", "set", "project_name", "nested-demo", "--render")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(config.load_config(self.root)["project_name"], "nested-demo")
        self.assertTrue((self.root / "terraform/generated.auto.tfvars").is_file())
        self.assertTrue(list((self.root / ".devsecops/snapshots").iterdir()))
        result = self.invoke(child, "config", "show", "--format", "json")
        self.assertEqual(json.loads(result.stdout)["project_name"], "nested-demo")
        result = self.invoke(child, "report", "--output", "reports/nested.md")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "reports/nested.md").is_file())
        self.assertFalse((child / "reports").exists())
        external = self.directory / "explicit report.md"
        result = self.invoke(child, "report", "--output", str(external))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(external.is_file())
        self.assertFalse((child / "dist").exists())
        self.assertFalse(self.trace.exists(), self.trace.read_text() if self.trace.exists() else "")

    def test_complete_checkout_is_found_without_a_config_or_git_metadata(self):
        child = self.root / "docs/nested"
        child.mkdir(parents=True)
        self.assertEqual(find_project_root(child), self.root.resolve())
        alias = self.directory / "checkout alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(find_project_root(alias / "docs/nested"), self.root.resolve())

    def test_closer_config_keeps_an_incomplete_nested_project_independent(self):
        config.write_config(self.root, config.default_config())
        nested = self.root / "nested project"
        nested.mkdir()
        cfg = config.default_config()
        cfg["project_name"] = "inner-project"
        config.write_config(nested, cfg)
        child = nested / "src/deep"
        child.mkdir(parents=True)
        self.assertEqual(find_project_root(child), nested.resolve())
        result = self.invoke(child, "config", "show", "--format", "json")
        self.assertEqual(json.loads(result.stdout)["project_name"], "inner-project")
        result = self.invoke(child, "setup", "--mode", "demo", "--yes", "--strict")
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / ".devsecops").exists())
        self.assertFalse((nested / ".devsecops").exists())
        self.assertEqual(config.load_config(self.root)["project_name"], "devsecops-pipeline")

    def test_nested_git_directory_and_worktree_marker_stop_ancestor_discovery(self):
        for marker_type in ("directory", "file"):
            with self.subTest(marker_type=marker_type):
                nested = self.root / marker_type
                child = nested / "src"
                child.mkdir(parents=True)
                if marker_type == "directory":
                    (nested / ".git").mkdir()
                else:
                    (nested / ".git").write_text("gitdir: ../worktree-metadata\n")
                self.assertEqual(find_project_root(child), child.resolve())
                result = self.invoke(child, "setup", "--mode", "demo", "--yes", "--strict")
                self.assertEqual(result.returncode, 1)
                self.assertFalse((self.root / CONFIG_FILE).exists())
                self.assertFalse((nested / CONFIG_FILE).exists())
                self.assertFalse((child / ".devsecops").exists())

    def test_nested_complete_checkout_wins_over_outer_config(self):
        config.write_config(self.root, config.default_config())
        nested = self.root / "another kit"
        checkout(nested)
        (nested / ".git").mkdir()
        self.assertEqual(find_project_root(nested / "terraform"), nested.resolve())

    def test_unrelated_directory_remains_unchanged_after_setup_failure(self):
        unrelated = self.directory / "unrelated"
        unrelated.mkdir()
        before = set(unrelated.iterdir())
        self.assertEqual(find_project_root(unrelated), unrelated.resolve())
        result = self.invoke(unrelated, "setup", "--mode", "demo", "--yes", "--strict")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Required project files are missing", result.stdout)
        self.assertEqual(set(unrelated.iterdir()), before)
        self.assertFalse((self.root / CONFIG_FILE).exists())
        self.assertFalse(self.trace.exists())
