"""Human CLI output and closed input must remain usable without providers."""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import aws, main as cli
from devsecops_cli.formatting import display_width

ROOT = Path(__file__).resolve().parents[2]


class TerminalJourneyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name in cli.REQUIRED_PROJECT_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# terminal fixture\n")
        binaries = self.root / "provider-stubs"
        binaries.mkdir()
        self.trace = self.root / "provider-calls"
        for name in ("aws", "gh", "terraform"):
            path = binaries / name
            path.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$TERMINAL_PROVIDER_TRACE"\nexit 99\n')
            path.chmod(0o755)
        self.environment = dict(os.environ, PYTHONPATH=str(ROOT / "cli"), NO_COLOR="1",
                                PATH=str(binaries) + os.pathsep + os.environ["PATH"], TERMINAL_PROVIDER_TRACE=str(self.trace))

    def invoke(self, *arguments, width=55, input=""):
        return subprocess.run([sys.executable, "-m", "devsecops_cli", *arguments], cwd=self.root,
                              env=dict(self.environment, COLUMNS=str(width)), input=input, text=True,
                              capture_output=True, timeout=20, check=False)

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def start_demo(self, width=55):
        result = self.invoke("setup", "--yes", "--strict", width=width)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def assert_fits(self, output, width, *, literal_commands=()):
        oversized = [line for line in output.splitlines() if display_width(line) > width and line not in literal_commands]
        self.assertEqual(oversized, [])

    def test_local_journey_fits_narrow_terminals_with_one_next_command_and_real_menu_hint(self):
        for width in (40, 55, 80):
            with self.subTest(width=width):
                setup = self.start_demo(width)
                self.assert_fits(setup.stdout, width)
                self.assertEqual(setup.stdout.count("Next command:"), 1)
                for arguments in ((), ("status",), ("status", "--format", "compact"), ("dry-run",), ("menu",)):
                    result = self.invoke(*arguments, width=width, input="0\n")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assert_fits(result.stdout, width)
                    self.assertEqual(result.stdout.count("Next command:"), 1)
                    if arguments == ("menu",):
                        self.assertIn("[i] Readiness details", result.stdout)
                    else:
                        self.assertNotIn("[i]", result.stdout)
        self.assertFalse(self.trace.exists())

    def test_production_guidance_wraps_but_keeps_its_shell_command_intact(self):
        cli.write_config(self.root, cli.clean_config("balanced"))
        command = "devsecops config set lambda_image_uri <immutable-ecr-image-uri>"
        for width in (40, 55, 80):
            for arguments in (("status",), ("dry-run",)):
                with self.subTest(width=width, arguments=arguments):
                    result = self.invoke(*arguments, width=width)
                    self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
                    self.assertNotIn("[i]", result.stdout)
                    self.assertNotIn("Unexpected error", result.stdout)
                    self.assertEqual(result.stdout.count("Next command:"), 1)
                    if len(command) + len("Next command: ") > width:
                        self.assertIn(command, result.stdout.splitlines())
                    self.assert_fits(result.stdout, width, literal_commands=(command,))

    def test_boxes_tables_and_prose_account_for_color_wide_and_combining_characters(self):
        value = "\033[32m" + "界е\u0301" * 35 + "\033[0m"
        strip_ansi = lambda text: re.sub(r"\x1b\[[0-9;]*m", "", text)
        for width in (40, 55, 80):
            output = io.StringIO()
            with patch.dict(os.environ, {"COLUMNS": str(width)}), redirect_stdout(output):
                cli.draw_box("Terminal status", [value])
                cli.draw_table(["Name", "Detail"], [["Customer", value]], title="Check results")
                cli.print_text("A diagnostic message " + value, subsequent_indent="  ")
            self.assert_fits(output.getvalue(), width)
            self.assertEqual(strip_ansi(output.getvalue()).count("界"), 35 * 3)
            self.assertEqual(strip_ansi(output.getvalue()).count("е\u0301"), 35 * 3)
        for width in (4, 8, 12):
            output = io.StringIO()
            with patch.dict(os.environ, {"COLUMNS": str(width)}), redirect_stdout(output):
                cli.draw_box("Status", ["long-path-without-spaces" * 4])
                cli.draw_table(["Check", "Result"], [["Long check", "Details " * 10]])
            self.assert_fits(output.getvalue(), width)

    def test_long_prompt_fits_without_losing_the_default_value(self):
        with patch.dict(os.environ, {"COLUMNS": "40"}), patch("builtins.input", return_value="") as read:
            self.assertTrue(cli.prompt_bool("Replace existing policy and environment settings with these changes", True, allow_cancel=True))
        prompt = read.call_args.args[0]
        self.assert_fits(prompt, 40)
        self.assertIn("default y", prompt)
        self.assertIn("b/back/0", prompt)

    def test_shell_command_with_quotes_and_spaces_is_printed_once_without_hard_wrapping(self):
        command = "devsecops config set backend.key 'my project/immutable path.tfstate'"
        action = dict(title="Review config", why="Check the current values.", changes="Update one value.",
                      command=command, docs="docs/troubleshooting.md", blocked=True)
        output = io.StringIO()
        with patch.dict(os.environ, {"COLUMNS": "40"}), redirect_stdout(output):
            cli.print_next_action(action)
        self.assertEqual(output.getvalue().splitlines().count(command), 1)
        self.assertEqual(output.getvalue().count("Next command:"), 1)

    def test_eof_exits_top_level_menu_submenu_and_details_without_writes(self):
        self.start_demo()
        before = self.files()
        for input in ("", "5\n", "2\n", "i\n"):
            with self.subTest(input=input):
                result = self.invoke("menu", input=input)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Input closed. Exiting menu.", result.stdout)
                self.assertNotIn("Unexpected error", result.stdout)
                self.assertNotIn("Blocked", result.stdout)
                self.assertEqual(self.files(), before)
        self.assertFalse(self.trace.exists())

    def test_setup_eof_pauses_before_creation_or_at_the_current_step_and_resumes(self):
        before = self.files()
        result = self.invoke("setup")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.files(), before)
        result = self.invoke("setup", input="1\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_fits(result.stdout, 55)
        self.assertFalse(cli.config_path(self.root).exists())
        self.assertEqual(cli.load_setup_state(self.root)["last_step"], "config")
        self.start_demo()
        self.assertEqual(cli.load_setup_state(self.root)["steps"]["summary"]["status"], "complete")
        before = self.files()
        result = self.invoke("setup", "--mode", "production")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.files(), before)
        self.assertFalse(self.trace.exists())

    def test_eof_during_a_direct_configuration_prompt_is_expected_and_does_not_save(self):
        self.start_demo()
        before = self.files()
        result = self.invoke("compose")
        self.assertEqual(result.returncode, cli.EXIT_INTERRUPTED, result.stdout + result.stderr)
        self.assertIn("Input closed", result.stdout)
        self.assertNotIn("Unexpected error", result.stdout)
        self.assert_fits(result.stdout, 55)
        self.assertEqual(self.files(), before)

    def test_invalid_urls_fail_validation_before_signing_or_network_access(self):
        urls = ("http://[broken", "https://example.org:bad/health", "http://example.org:65536/",
                "http://example.org:0/", "http://:80/health", "http:///health", "file:///etc/passwd",
                "http://[::1]oops/health", "http://example.org:/health",
                "https://example.org/with space", "https://example.org/\nhealth", "https://example.org/\\health",
                "https://example.org/\u0000health", "https://example.org/\u00e9", "http://user:password@example.org/health")
        with patch.object(urllib.request, "urlopen") as request, patch.object(urllib.request, "build_opener") as opener, \
             patch.object(aws, "aws_sigv4_headers") as sign:
            for url in urls:
                for signed in (False, True):
                    with self.subTest(url=url, signed=signed):
                        status, detail = aws.fetch_health_url(url, aws_sigv4=signed)
                        self.assertIsNone(status)
                        self.assertTrue(detail)
            request.assert_not_called()
            opener.assert_not_called()
            sign.assert_not_called()
        for url in (*urls[:7], ""):
            for format in ("human", "compact", "json"):
                with self.subTest(url=url, format=format):
                    result = self.invoke("health", "--url", url, "--format", format)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertNotIn("Unexpected error", result.stdout)
                    if format == "json":
                        payload = json.loads(result.stdout)
                        endpoint = next(c for c in payload["checks"] if c["name"] == "Health endpoint URL")
                        self.assertEqual(endpoint["status"], "FAIL")
        self.assertFalse(self.trace.exists())

    def test_valid_local_ipv6_and_encoded_urls_are_not_rejected(self):
        for url in ("http://127.0.0.1:8123/health", "http://[::1]:8123/health", "https://api.example.org:443/health",
                    "https://api.example.org/with%20space?q=%C3%A9"):
            with self.subTest(url=url):
                self.assertIsNone(aws.health_url_error(url))

    def test_json_status_remains_unwrapped_and_parseable_at_narrow_width(self):
        self.start_demo()
        results = [self.invoke("status", "--format", "json", width=width) for width in (40, 80)]
        self.assertEqual(json.loads(results[0].stdout), json.loads(results[1].stdout))
        self.assertTrue(json.loads(results[0].stdout)["demo_complete"])
        self.assertNotIn("Next command:", results[0].stdout)
