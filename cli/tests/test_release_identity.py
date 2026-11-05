"""Release identities and pinned instructions must fail closed on drift."""

import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import VERSION, main as cli, release_version

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = """ec84584d8c5f0c3ca1a9a84b1b2daeafefd264eb840b9ba73c98a4cf2743ac0c  install.sh
58d3dfb2986f1a398a8cb359fdcbd6d017425c8995d08017c6fd954092c82428  devsecops_pipeline_cli-0.15.0-py3-none-any.whl
e56f52c4ff0316a6cc68e205c87f15f7b49d25914b1314d1be9bbe122d32ee5d  devsecops_pipeline_cli-0.15.0.tar.gz
"""


class ReleaseIdentityTests(unittest.TestCase):
    def fixture(self, root, version):
        for name in ("pyproject.toml", "cli/pyproject.toml"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'[project]\nversion = "{version}"\n')
        (root / "docs").mkdir(exist_ok=True)
        (root / f"docs/release-v{version}.md").write_text("Release notes\n")

    def test_tags_cli_both_packages_and_notes_must_match_before_publication(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(release_version, "VERSION", "2.3.4"):
            root = Path(folder)
            self.fixture(root, "2.3.4")
            notes = release_version.validate_release_version(root, "v2.3.4")
            self.assertEqual(notes.name, "release-v2.3.4.md")
            with self.assertRaisesRegex(ValueError, "requires CLI version"):
                release_version.validate_release_version(root, "v2.3.5")
            for name in ("pyproject.toml", "cli/pyproject.toml"):
                path = root / name
                original = path.read_bytes()
                path.write_text('[project]\nversion = "2.3.3"\n')
                with self.assertRaisesRegex(ValueError, "must declare version"):
                    release_version.validate_release_version(root, "v2.3.4")
                path.write_bytes(original)
            notes.unlink()
            (root / "docs/release-v0.14.0.md").write_text("Old notes\n")
            with self.assertRaisesRegex(ValueError, "Missing current version release notes"):
                release_version.validate_release_version(root, "v2.3.4")

    def test_development_and_malformed_tags_are_not_publishable(self):
        for tag in (f"v{VERSION}", "v01.2.3", "v1.2", "v1.2.3-rc.01", "v1.2.3-preview.1"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_version.validate_release_version(ROOT, tag)
        result = subprocess.run([sys.executable, "-m", "devsecops_cli.release_version", f"v{VERSION}", str(ROOT)],
                                env=dict(os.environ, PYTHONPATH=str(ROOT / "cli")), text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("development versions cannot be published", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_semantic_prerelease_tags_match_canonical_python_package_versions(self):
        for label, suffix in (("a", "a"), ("alpha", "a"), ("b", "b"), ("beta", "b"), ("rc", "rc")):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                version = "2.3.4" + suffix + "1"
                root = Path(folder)
                self.fixture(root, version)
                with patch.object(release_version, "VERSION", version):
                    self.assertEqual(release_version.validate_release_version(root, f"v2.3.4-{label}.1").name,
                                     f"release-v{version}.md")

    def test_criteria_uses_current_notes_and_never_falls_back_to_old_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "docs").mkdir()
            for name in ("distribution.md", "release-checklist.md", "upgrade-guide.md", "release-v0.14.0.md"):
                (root / "docs" / name).write_text("Historical or supporting documentation\n")
            criterion = lambda: next(item for item in cli.v1_criteria_payload(root)["criteria"] if item["id"] == "release-upgrade-documented")
            self.assertEqual(criterion()["status"], "BLOCKED")
            (root / f"docs/release-v{VERSION}.md").write_text("Current notes\n")
            current = criterion()
            self.assertEqual(current["status"], "OK")
            self.assertIn(f"docs/release-v{VERSION}.md", current["evidence"])

    def test_current_source_status_and_package_metadata_are_consistent(self):
        for name in ("pyproject.toml", "cli/pyproject.toml"):
            metadata = tomllib.loads((ROOT / name).read_text())["project"]
            self.assertEqual(metadata["version"], VERSION)
            self.assertIn("Development Status :: 4 - Beta", metadata["classifiers"])
        for name in ("README.md", "ROADMAP.md", "docs/distribution.md", "docs/stability-contract.md",
                     "docs/v1.0.0-release-candidate-checklist.md", "docs/production-deployment-evidence.md"):
            text = (ROOT / name).read_text()
            self.assertIn(VERSION, text, name)
            self.assertIn("v0.15.0", text, name)
        self.assertTrue((ROOT / f"docs/release-v{VERSION}.md").is_file())

    def test_publication_checks_identity_before_build_evidence_download_or_publish(self):
        text = (ROOT / ".github/workflows/release.yml").read_text()
        position = text.index("python -m devsecops_cli.release_version")
        for operation in ("gh release download", "python -m build", "Create GitHub release"):
            self.assertLess(position, text.index(operation))
        self.assertNotIn('notes_path="CHANGELOG.md"', text)

    def test_pinned_install_rejects_tampered_downloads_before_executing_installer(self):
        text = (ROOT / "docs/distribution.md").read_text().split("## Pinned Published Baseline", 1)[1]
        block = re.search(r"```bash\n(.*?)\n```", text, re.S).group(1)
        for corrupt_manifest in (True, False):
            with self.subTest(corrupt_manifest=corrupt_manifest), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                binaries = root / "bin"
                binaries.mkdir()
                manifest = root / "fixture-manifest"
                manifest.write_text("tampered" if corrupt_manifest else MANIFEST)
                scripts = {
                    "git": "from pathlib import Path\nimport sys\nif sys.argv[1] == 'clone': Path('devsecops-release-demo').mkdir()\n"
                           "else: print('438902e02565e535f0b6ebc85576692c6bf51e95')\n",
                    "curl": "import os,sys\nfrom pathlib import Path\nout=Path(sys.argv[sys.argv.index('-o')+1])\n"
                            "url=next(v for v in sys.argv if v.startswith('https://'))\n"
                            "out.write_bytes(Path(os.environ['PIN_MANIFEST']).read_bytes() if url.endswith('SHA256SUMS') else b'tampered installer')\n",
                    "sh": "import os\nfrom pathlib import Path\nPath(os.environ['PIN_EXECUTED']).touch()\nraise SystemExit(99)\n",
                }
                for name, script in scripts.items():
                    path = binaries / name
                    path.write_text(f"#!{sys.executable}\n" + script)
                    path.chmod(0o755)
                marker = root / "installer-executed"
                environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                                   PIN_MANIFEST=str(manifest), PIN_EXECUTED=str(marker), TMPDIR=str(root))
                result = subprocess.run(["/bin/bash", "-c", block], cwd=root, env=environment,
                                        text=True, capture_output=True, timeout=20, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("manifest differs" if corrupt_manifest else "Installer checksum verification failed", result.stderr)
                self.assertFalse(marker.exists())
