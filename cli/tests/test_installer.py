"""The source installer never replaces an existing environment or starts AWS."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[2] / "install.sh"


class InstallerTests(unittest.TestCase):
    def test_help_and_unknown_options_do_not_install(self):
        result = subprocess.run(["sh", str(INSTALLER), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("current checkout", result.stdout)
        for arguments in (["--with-tui"], ["--python"], ["--venv"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    ["sh", str(INSTALLER), *arguments], capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 2)

    def test_existing_destination_is_preserved_with_literal_spaced_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing ' environment"
            target.mkdir()
            sentinel = target / "keep"
            sentinel.write_text("unchanged")
            result = subprocess.run(
                ["sh", str(INSTALLER), "--python", sys.executable, "--venv", str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("already exists", result.stderr)
            self.assertEqual(sentinel.read_text(), "unchanged")
            self.assertEqual(list(target.iterdir()), [sentinel])
