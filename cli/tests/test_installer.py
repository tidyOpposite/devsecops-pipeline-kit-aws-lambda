"""Exercise installer upgrades offline with real virtual environments and wheels."""

import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from devsecops_cli import VERSION


ROOT = Path(__file__).resolve().parents[2]


class InstallerUpgradeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="installer paths ' with spaces ")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.install = self.root / "private install"
        self.bin = self.root / "bin directory"
        self.launcher = self.bin / "devsecops"
        fixtures = self.root / "fixtures"
        fixtures.mkdir()
        self.wheel_name = f"devsecops_pipeline_cli-{VERSION}-py3-none-any.whl"
        wheel = fixtures / self.wheel_name
        metadata = f"devsecops_pipeline_cli-{VERSION}.dist-info"
        with zipfile.ZipFile(wheel, "w") as archive:
            files = {
                "devsecops_cli/__init__.py": "",
                "devsecops_cli/main.py": (
                    "import os\n"
                    "if os.environ.get('INSTALLER_TEST_FAILURE') == 'startup': raise SystemExit(2)\n"
                    f"print('devsecops ' + ('0.0.0' if os.environ.get('INSTALLER_TEST_FAILURE') == 'version' else '{VERSION}'))\n"
                ),
                f"{metadata}/METADATA": f"Metadata-Version: 2.1\nName: devsecops-pipeline-cli\nVersion: {VERSION}\n",
                f"{metadata}/WHEEL": "Wheel-Version: 1.0\nGenerator: installer-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            }
            for name, content in files.items():
                archive.writestr(name, content)
            archive.writestr(f"{metadata}/RECORD", "".join(f"{name},,\n" for name in [*files, f"{metadata}/RECORD"]))
        (fixtures / "SHA256SUMS").write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {self.wheel_name}\n")
        release = {"tag_name": f"v{VERSION}", "assets": [
            {"name": name, "browser_download_url": f"https://installer.test/{name}"}
            for name in (self.wheel_name, "SHA256SUMS")
        ]}
        (fixtures / "release.json").write_text(json.dumps(release))
        hooks = self.root / "test hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text('''
import io
import os
from pathlib import Path
import subprocess
import urllib.request

fixtures = Path(os.environ["INSTALLER_TEST_FIXTURES"])
failure = os.environ.get("INSTALLER_TEST_FAILURE", "")

def offline_open(request, **kwargs):
    url = request.full_url
    if url.startswith("https://api.github.com/repos/"):
        return io.BytesIO((fixtures / "release.json").read_bytes())
    if url.startswith("https://installer.test/"):
        return io.BytesIO((fixtures / url.rsplit("/", 1)[1]).read_bytes())
    raise AssertionError("Installer test attempted unexpected network access")

urllib.request.urlopen = offline_open
original_run = subprocess.run

def controlled_run(command, **kwargs):
    mode = failure
    wheel_install = len(command) > 5 and command[1:5] == ["-I", "-m", "pip", "install"]
    if ((mode == "venv" and command[1:4] == ["-I", "-m", "venv"])
            or (mode == "pip" and wheel_install)
            or (mode == "tui" and wheel_install and "rich>=13.7" in command)
            or (mode == "launcher" and Path(command[0]).name.startswith(".devsecops-install-"))):
        raise subprocess.CalledProcessError(17, command)
    return original_run(command, **kwargs)

subprocess.run = controlled_run
original_replace = os.replace

def controlled_replace(source, destination, *args, **kwargs):
    if failure == "activation" and Path(source).name.startswith(".devsecops-install-"):
        raise OSError("Simulated activation failure")
    return original_replace(source, destination, *args, **kwargs)

os.replace = controlled_replace
''')
        self.environment = dict(os.environ, PYTHONPATH=str(hooks), INSTALLER_TEST_FIXTURES=str(fixtures),
                                PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_CONFIG_FILE=os.devnull)
        for name in ("DEVSECOPS_INSTALL_DIR", "DEVSECOPS_BIN_DIR", "DEVSECOPS_VERSION", "DEVSECOPS_WITH_TUI",
                     "PYTHON", "GITHUB_TOKEN"):
            self.environment.pop(name, None)

    def install_release(self, failure="", *options):
        return subprocess.run(
            ["sh", str(ROOT / "install.sh"), "--python", sys.executable, "--version", f"v{VERSION}",
             "--install-dir", str(self.install), "--bin-dir", str(self.bin), *options],
            env=self.environment | {"INSTALLER_TEST_FAILURE": failure},
            capture_output=True, text=True, timeout=60, check=False,
        )

    def legacy_install(self):
        python = self.install / "venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\nprintf 'devsecops 0.14.0\\n'\n")
        python.chmod(0o755)
        (self.install / "venv/keep.txt").write_text("existing environment")
        (self.install / ".devsecops-installer-managed").touch()
        self.bin.mkdir()
        self.launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(str(python))} -m devsecops_cli.main "$@"\n')
        self.launcher.chmod(0o755)
        return self.launcher.read_bytes()

    def version(self, launcher=None):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        return subprocess.check_output([str(launcher or self.launcher), "--version"], env=environment, text=True).strip()

    def test_successful_upgrade_keeps_legacy_and_previous_versioned_environments(self):
        original = self.legacy_install()
        result = self.install_release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.launcher.read_bytes(), original)
        self.assertEqual(self.version(), f"devsecops {VERSION}")
        first_environment = next((self.install / "environments").iterdir())
        first_launcher = self.root / "previous launcher"
        first_launcher.write_bytes(self.launcher.read_bytes())
        first_launcher.chmod(0o755)
        result = self.install_release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), f"devsecops {VERSION}")
        self.assertEqual(self.version(first_launcher), f"devsecops {VERSION}")
        self.assertTrue(first_environment.exists())
        self.assertEqual(len(list((self.install / "environments").iterdir())), 2)
        self.assertEqual((self.install / "venv/keep.txt").read_text(), "existing environment")
        shadow = self.root / "shadow imports/devsecops_cli"
        shadow.mkdir(parents=True)
        (shadow / "__init__.py").write_text("")
        (shadow / "main.py").write_text("print('wrong CLI from PYTHONPATH')\n")
        version = subprocess.check_output([str(self.launcher), "--version"], text=True,
                                          env=dict(os.environ, PYTHONPATH=str(shadow.parent)))
        self.assertEqual(version.strip(), f"devsecops {VERSION}")

    def test_first_install_creates_a_verified_managed_launcher(self):
        result = self.install_release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), f"devsecops {VERSION}")
        self.assertTrue((self.install / ".devsecops-installer-managed").is_file())
        self.assertEqual(len(list((self.install / "environments").iterdir())), 1)
        self.assertFalse(list(self.bin.glob(".devsecops-install-*")))

    def test_semantic_prerelease_tag_uses_the_canonical_python_wheel_version(self):
        fixtures = Path(self.environment["INSTALLER_TEST_FIXTURES"])
        version = "9.8.7rc1"
        name = f"devsecops_pipeline_cli-{version}-py3-none-any.whl"
        wheel = fixtures / name
        with zipfile.ZipFile(fixtures / self.wheel_name) as original, zipfile.ZipFile(wheel, "w") as candidate:
            for entry in original.infolist():
                candidate.writestr(entry.filename.replace(VERSION, version),
                                  original.read(entry).replace(VERSION.encode(), version.encode()))
        (fixtures / "SHA256SUMS").write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {name}\n")
        (fixtures / "release.json").write_text(json.dumps({"tag_name": "v9.8.7-rc.1", "assets": [
            {"name": asset, "browser_download_url": f"https://installer.test/{asset}"}
            for asset in (name, "SHA256SUMS")
        ]}))
        result = self.install_release("", "--version", "v9.8.7-rc.1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), f"devsecops {version}")

    def test_failed_upgrade_preserves_working_launcher_and_cleans_only_candidate(self):
        original = self.legacy_install()
        for failure in ("venv", "pip", "tui", "startup", "version", "launcher", "activation"):
            with self.subTest(failure=failure):
                options = ("--with-tui",) if failure == "tui" else ()
                result = self.install_release(failure, *options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("previous CLI was preserved", result.stderr)
                phase = {"venv": "creating the replacement", "pip": "installing the release wheel",
                         "tui": "installing optional TUI", "startup": "verifying the replacement CLI",
                         "version": "version does not match", "launcher": "verifying the replacement launcher",
                         "activation": "activating the verified CLI"}[failure]
                self.assertIn(phase, result.stderr)
                self.assertEqual(self.launcher.read_bytes(), original)
                self.assertEqual(self.version(), "devsecops 0.14.0")
                self.assertEqual(list((self.install / "environments").iterdir()), [])
                self.assertFalse(list(self.bin.glob(".devsecops-install-*")))
                self.assertEqual((self.install / "venv/keep.txt").read_text(), "existing environment")

    def test_failed_first_install_leaves_no_launcher_or_ownership_marker(self):
        result = self.install_release("activation")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.launcher.exists())
        self.assertFalse((self.install / ".devsecops-installer-managed").exists())
        self.assertEqual(list((self.install / "environments").iterdir()), [])

    def test_unrelated_launcher_and_unmanaged_venv_are_preserved(self):
        self.bin.mkdir()
        self.launcher.write_text("#!/bin/sh\nprintf 'another tool\\n'\n")
        original = self.launcher.read_bytes()
        result = self.install_release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrelated launcher", result.stderr)
        self.assertEqual(self.launcher.read_bytes(), original)
        self.launcher.unlink()
        venv = self.install / "venv"
        venv.mkdir()
        (venv / "unrelated.txt").write_text("unmanaged environment")
        result = self.install_release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not created by this installer", result.stderr)
        self.assertEqual((venv / "unrelated.txt").read_text(), "unmanaged environment")

    def test_concurrent_upgrade_is_rejected_without_changing_active_cli(self):
        original = self.legacy_install()
        for lock_path in (self.install / ".install.lock", self.bin / ".devsecops.install.lock"):
            with self.subTest(lock_path=lock_path), lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = self.install_release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Another installation is running", result.stderr)
                self.assertEqual(self.launcher.read_bytes(), original)
                self.assertEqual(self.version(), "devsecops 0.14.0")
