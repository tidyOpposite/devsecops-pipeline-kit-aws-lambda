import argparse
import importlib
import os
import tempfile
import unittest
import json
import io
import subprocess
import sys
import tomllib
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

package = importlib.import_module("devsecops_cli")
cli = importlib.import_module("devsecops_cli.main")
ROOT_DIR = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(__file__).with_name("golden")
RENDERED_ARTIFACTS = [
    cli.GENERATED_TFVARS,
    cli.DIST_DIR / "backend.tf",
    cli.DIST_DIR / "github-variables.env",
    cli.DIST_DIR / "github-setup.sh",
    cli.DIST_DIR / "setup-checklist.md",
]


def golden_config() -> dict[str, object]:
    cfg = cli.preset_config("strict")
    cfg["project_name"] = "golden-pipeline"
    cfg["aws_region"] = "eu-central-1"
    cfg["lambda_image_uri"] = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/golden-pipeline:sha-abc123"
    cfg["terraform_admin_role_name"] = "golden-terraform-admin"
    cfg["backend"] = {
        "bucket": "golden-pipeline-tfstate",
        "key": "golden-pipeline/terraform.tfstate",
        "region": "eu-central-1",
        "lock_table": "golden-pipeline-locks",
        "workspace_key_prefix": "envs",
    }
    return cfg


def read_golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


def rendered_artifact_contents(root: Path) -> dict[str, str]:
    return {str(path): (root / path).read_text(encoding="utf-8") for path in RENDERED_ARTIFACTS}


def create_required_project_files(root: Path) -> None:
    for relative in cli.REQUIRED_PROJECT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test project file\n", encoding="utf-8")


def project_version(path: Path) -> str:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]


def project_requires_python(path: Path) -> str:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["requires-python"]


class DevSecOpsCliTests(unittest.TestCase):
    def test_version_metadata_is_consistent(self) -> None:
        self.assertEqual(cli.VERSION, "0.13.1")
        self.assertEqual(package.VERSION, cli.VERSION)
        self.assertEqual(package.__version__, cli.VERSION)
        self.assertEqual(project_version(ROOT_DIR / "pyproject.toml"), cli.VERSION)
        self.assertEqual(project_version(ROOT_DIR / "cli/pyproject.toml"), cli.VERSION)

    def test_python_support_metadata_matches_compatibility_matrix(self) -> None:
        distribution_doc = (ROOT_DIR / "docs/distribution.md").read_text(encoding="utf-8")
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")

        self.assertEqual(project_requires_python(ROOT_DIR / "pyproject.toml"), ">=3.11,<3.15")
        self.assertEqual(project_requires_python(ROOT_DIR / "cli/pyproject.toml"), ">=3.11,<3.15")
        self.assertIn("| Python | 3.11, 3.12, 3.13, and 3.14 |", distribution_doc)
        self.assertIn('requires-python = ">=3.11,<3.15"', distribution_doc)
        self.assertIn("Python 3.11, 3.12, 3.13, or 3.14", readme)

    def test_readme_opens_with_a_three_command_first_experience(self) -> None:
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        first_screen_sections = [
            "## What This Product Does",
            "## Who It Is For",
            "## Before You Start",
            "## What This Product Does Not Do",
            "## Quick Start",
        ]

        positions = [readme.index(section) for section in first_screen_sections]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(readme.index("## Quick Start"), readme.index("## Development Status"))
        self.assertLess(readme.index("## Quick Start"), readme.index("## Product Contract"))
        self.assertLess(readme.index("## Quick Start"), readme.index("## Architecture"))
        self.assertLess(readme.index("## Quick Start"), readme.index("## Repository Layout"))
        self.assertIn(
            """```bash
devsecops setup --preset balanced --yes
devsecops status
devsecops dry-run --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```""",
            readme,
        )
        self.assertIn("Expected result:", readme)

    def test_module_execution_does_not_emit_runtime_warning(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT_DIR / "cli")
        result = subprocess.run(
            [sys.executable, "-m", "devsecops_cli.main", "--version"],
            cwd=ROOT_DIR,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"devsecops {cli.VERSION}")
        self.assertNotIn("RuntimeWarning", result.stderr)

    def test_immutable_image_validation(self) -> None:
        self.assertTrue(cli.is_immutable_image("repo.example/app:sha-abc123"))
        self.assertTrue(cli.is_immutable_image("repo.example/app@sha256:" + "a" * 64))
        self.assertFalse(cli.is_immutable_image(""))
        self.assertFalse(cli.is_immutable_image("repo.example/app"))
        self.assertFalse(cli.is_immutable_image("repo.example/app:latest"))
        self.assertFalse(cli.is_immutable_image("repo.example/app:bootstrap"))

    def test_config_dump_load_roundtrip(self) -> None:
        cfg = cli.default_config()
        cfg["project_name"] = "abc-project"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cfg)
            loaded = cli.load_config(root)
            config_text = (root / cli.CONFIG_FILE).read_text(encoding="utf-8")
        self.assertEqual(loaded["schema_version"], cli.CONFIG_SCHEMA_VERSION)
        self.assertEqual(loaded["project_name"], "abc-project")
        self.assertEqual(loaded["environments"]["prod"]["lambda_timeout"], 240)
        self.assertIn("schema_version = 1", config_text)

    def test_load_legacy_config_without_schema_version_migrates_to_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / cli.CONFIG_FILE).write_text('project_name = "legacy-app"\n', encoding="utf-8")
            loaded = cli.load_config(root)

        self.assertEqual(loaded["schema_version"], cli.CONFIG_SCHEMA_VERSION)
        self.assertEqual(loaded["project_name"], "legacy-app")

    def test_future_config_schema_version_fails_closed_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / cli.CONFIG_FILE).write_text(
                f"schema_version = {cli.CONFIG_SCHEMA_VERSION + 1}\nproject_name = \"future-app\"\n",
                encoding="utf-8",
            )
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["render"])

            self.assertFalse((root / cli.GENERATED_TFVARS).exists())

        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertIn("Config migration error", buffer.getvalue())

    def test_config_schema_documents_migration_and_rollback_contract(self) -> None:
        schema = cli.config_schema()
        migration = schema["migration"]

        self.assertEqual(migration["current_schema_version"], cli.CONFIG_SCHEMA_VERSION)
        self.assertIn("future_schema_version", migration)
        self.assertTrue(any("snapshot restore" in item for item in migration["rollback_expectations"]))

        markdown = cli.config_schema_markdown()
        self.assertIn("Migration Contract", markdown)
        self.assertIn("future `schema_version`", markdown)
        self.assertIn("Snapshot restore", markdown)

    def test_clean_config_has_no_secret_fields(self) -> None:
        rendered = cli.dump_config_toml(cli.clean_config("balanced"))
        forbidden = ["AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID", "GITHUB_TOKEN", "SNYK_TOKEN", "PRIVATE_KEY"]
        for token in forbidden:
            self.assertNotIn(token, rendered)

    def test_config_new_show_schema_diff_and_reset_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.cmd_config(argparse.Namespace(config_command="new", preset="minimal", force=False, render=False)), 0)

                created = root / cli.CONFIG_FILE
                self.assertTrue(created.exists())
                self.assertIn("schema_version = 1", created.read_text(encoding="utf-8"))

                show_json = io.StringIO()
                with redirect_stdout(show_json):
                    self.assertEqual(cli.cmd_config(argparse.Namespace(config_command="show", format="json")), 0)
                self.assertEqual(json.loads(show_json.getvalue())["environments"]["dev"]["lambda_memory_size"], 512)

                schema_json = io.StringIO()
                with redirect_stdout(schema_json):
                    self.assertEqual(cli.cmd_config(argparse.Namespace(config_command="schema", format="json")), 0)
                self.assertEqual(json.loads(schema_json.getvalue())["schema_version"], cli.CONFIG_SCHEMA_VERSION)

                diff_output = io.StringIO()
                with redirect_stdout(diff_output):
                    self.assertEqual(cli.cmd_config(argparse.Namespace(config_command="diff", preset=None, exit_code=True)), 0)
                self.assertIn("No config diff detected", diff_output.getvalue())

                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.cmd_config(argparse.Namespace(config_command="reset", preset="balanced", render=False)), 0)
                reset = cli.load_config(root)
                self.assertEqual(reset["environments"]["dev"]["lambda_memory_size"], 1024)

    def test_config_new_refuses_existing_config_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.clean_config("minimal"))
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.cmd_config(argparse.Namespace(config_command="new", preset="balanced", force=False, render=False))

        self.assertEqual(result, 1)
        self.assertIn("already exists", buffer.getvalue())

    def test_config_diff_reports_canonical_drift_and_preset_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.clean_config("minimal"))
            config_file = root / cli.CONFIG_FILE
            config_file.write_text(config_file.read_text(encoding="utf-8") + "# manual note\n", encoding="utf-8")

            canonical_diff = cli.config_file_diff(root)
            preset_diff = cli.config_preset_diff(root, "balanced")

        self.assertIn("-# manual note", canonical_diff)
        self.assertIn("preset:balanced", preset_diff)
        self.assertIn("lambda_memory_size = 1024", preset_diff)

    def test_clean_config_and_render_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.cmd_config(argparse.Namespace(config_command="new", preset="balanced", force=False, render=True)), 0)
                first_config = (root / cli.CONFIG_FILE).read_text(encoding="utf-8")
                first_tfvars = (root / cli.GENERATED_TFVARS).read_text(encoding="utf-8")

                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.cmd_config(argparse.Namespace(config_command="reset", preset="balanced", render=True)), 0)
                second_config = (root / cli.CONFIG_FILE).read_text(encoding="utf-8")
                second_tfvars = (root / cli.GENERATED_TFVARS).read_text(encoding="utf-8")

        self.assertEqual(first_config, second_config)
        self.assertEqual(first_tfvars, second_tfvars)

    def test_rendered_artifacts_have_stable_diffs_across_repeated_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, golden_config())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.run_render(root, snapshot=False), 0)
            first = rendered_artifact_contents(root)

            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.run_render(root, snapshot=False), 0)
            second = rendered_artifact_contents(root)

        self.assertEqual(first, second)

    def test_generated_artifact_contract_matches_render_outputs_and_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outputs = cli.render_outputs(root, golden_config())

        rendered_paths = {str(path.relative_to(root)) for path in outputs}
        contract_paths = {item["path"] for item in cli.GENERATED_ARTIFACT_CONTRACTS if item["producer"].startswith("devsecops generate")}

        self.assertTrue(rendered_paths.issubset(contract_paths))
        self.assertIn(str(cli.GENERATED_TFVARS), contract_paths)
        self.assertIn(str(cli.DIST_DIR / "github-setup.sh"), contract_paths)
        self.assertTrue(rendered_paths.issubset(cli.SNAPSHOT_FILE_PATHS))
        for item in cli.GENERATED_ARTIFACT_CONTRACTS:
            self.assertTrue(item["rerender_required_when"])
            self.assertTrue(item["expected_diffs"])

    def test_e2e_config_validate_render_report_in_temp_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["config", "new", "--preset", "balanced"]), 0)
                    self.assertEqual(cli.main(["config", "validate"]), 0)
                    self.assertEqual(cli.main(["render"]), 0)
                    self.assertEqual(cli.main(["report"]), 0)

            self.assertTrue((root / cli.CONFIG_FILE).exists())
            self.assertTrue((root / cli.GENERATED_TFVARS).exists())
            self.assertTrue((root / cli.DIST_DIR / "github-setup.sh").exists())
            report = root / cli.DIST_DIR / "readiness-report.md"
            self.assertTrue(report.exists())
            self.assertIn("# DevSecOps Pipeline Readiness Report", report.read_text(encoding="utf-8"))

    def test_dry_run_preview_does_not_write_files_or_require_aws(self) -> None:
        image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["dry-run", "--preset", "balanced", "--image-uri", image_uri])

            output = buffer.getvalue()
            self.assertFalse((root / cli.CONFIG_FILE).exists())
            self.assertFalse((root / cli.GENERATED_TFVARS).exists())

        self.assertEqual(result, 0)
        self.assertIn("No files changed", output)
        self.assertIn("AWS credentials are not required", output)
        self.assertIn("Files that would be generated", output)

    def test_render_dry_run_previews_without_writing_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["render", "--dry-run"])

            self.assertFalse((root / cli.GENERATED_TFVARS).exists())

        self.assertEqual(result, 0)
        self.assertIn("Dry run only. No files changed.", buffer.getvalue())
        self.assertIn(str(cli.GENERATED_TFVARS), buffer.getvalue())

    def test_preflight_checks_image_shape_immutability_and_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.default_config()
            cfg["aws_region"] = "us-east-1"
            cli.write_config(root, cfg)
            bad_image = "123456789012.dkr.ecr.eu-west-1.amazonaws.com/app:latest"
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["preflight", "--image-uri", bad_image, "--format", "json"])

        payload = json.loads(buffer.getvalue())
        by_name = {check["name"]: check for check in payload["checks"]}
        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertEqual(by_name["Lambda image shape"]["status"], "OK")
        self.assertEqual(by_name["Lambda image immutability"]["status"], "FAIL")
        self.assertEqual(by_name["Lambda image region"]["status"], "FAIL")

    def test_nested_set_and_parse(self) -> None:
        cfg = cli.default_config()
        current = cli.nested_get(cfg, "environments.dev.lambda_timeout")
        cli.nested_set(cfg, "environments.dev.lambda_timeout", cli.parse_config_value("300", current))
        self.assertEqual(cfg["environments"]["dev"]["lambda_timeout"], 300)

        current_origins = cli.nested_get(cfg, "environments.dev.cors_allowed_origins")
        cli.nested_set(
            cfg,
            "environments.dev.cors_allowed_origins",
            cli.parse_config_value("https://example.com,https://app.example.com", current_origins),
        )
        self.assertEqual(
            cfg["environments"]["dev"]["cors_allowed_origins"],
            ["https://example.com", "https://app.example.com"],
        )

    def test_prompt_bool_zero_stays_false_outside_cancel_mode(self) -> None:
        with patch("builtins.input", return_value="0"):
            self.assertFalse(cli.prompt_bool("Flag", True))

    def test_tfvars_contains_environment_config(self) -> None:
        rendered = cli.terraform_tfvars(cli.default_config())
        self.assertIn("CLI-owned generated file", rendered)
        self.assertIn('project_name              = "devsecops-pipeline"', rendered)
        self.assertIn("environment_config = {", rendered)
        self.assertIn("prod = {", rendered)

    def test_generated_terraform_tfvars_matches_golden_fixture(self) -> None:
        self.assertEqual(cli.terraform_tfvars(golden_config()), read_golden("terraform_generated.auto.tfvars.golden"))

    def test_generated_github_artifacts_match_golden_fixtures(self) -> None:
        cfg = golden_config()
        self.assertEqual(cli.github_variables(cfg), read_golden("github-variables.env"))
        self.assertEqual(cli.github_setup_script(cfg), read_golden("github-setup.sh"))

    def test_generated_artifacts_carry_cli_owned_notice(self) -> None:
        cfg = cli.default_config()
        artifacts = [
            cli.terraform_tfvars(cfg),
            cli.backend_tf(cfg),
            cli.github_variables(cfg),
            cli.github_setup_script(cfg),
            cli.checklist(cfg),
            cli.markdown_report(cfg, []),
        ]

        for artifact in artifacts:
            self.assertIn("CLI-owned generated", artifact)
            self.assertIn("Do not edit directly", artifact)

    def test_production_evidence_docs_cover_milestone_eight_contract(self) -> None:
        evidence_doc = (ROOT_DIR / "docs/production-deployment-evidence.md").read_text(encoding="utf-8")
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        command_inventory = (ROOT_DIR / "docs/command-inventory.md").read_text(encoding="utf-8")
        release_checklist = (ROOT_DIR / "docs/release-checklist.md").read_text(encoding="utf-8")
        roadmap = (ROOT_DIR / "ROADMAP.md").read_text(encoding="utf-8")

        for required in [
            "release-install.txt",
            "workflow-run.json",
            "terraform-output.json",
            "aws-outputs.json",
            "health.json",
            "cloudwatch-tail.txt",
            "active-lambda-image.txt",
            "devsecops status --strict --format json",
            "devsecops doctor aws --environment prod --strict --format json",
            "Roll back Lambda image on failed deployment validation",
        ]:
            self.assertIn(required, evidence_doc)

        self.assertIn("[Production deployment evidence](docs/production-deployment-evidence.md)", readme)
        self.assertIn("Production Evidence Workflow", command_inventory)
        self.assertIn("Production Evidence Gate", release_checklist)
        self.assertIn("Status: in progress.", roadmap)
        self.assertIn("Full production deployment walkthrough executed", roadmap)

    def test_stability_contract_docs_cover_milestone_nine_contract(self) -> None:
        stability_doc = (ROOT_DIR / "docs/stability-contract.md").read_text(encoding="utf-8")
        generated_doc = (ROOT_DIR / "docs/generated-artifacts.md").read_text(encoding="utf-8")
        upgrade_doc = (ROOT_DIR / "docs/upgrade-guide.md").read_text(encoding="utf-8")
        command_inventory = (ROOT_DIR / "docs/command-inventory.md").read_text(encoding="utf-8")
        release_checklist = (ROOT_DIR / "docs/release-checklist.md").read_text(encoding="utf-8")
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        roadmap = (ROOT_DIR / "ROADMAP.md").read_text(encoding="utf-8")

        for required in [
            "devsecops inventory --format json",
            "devsecops terraform bootstrap --apply",
            "JSON Output Contract",
            "Deprecation Policy",
            "Config Migration Rules",
            "Generated Artifact Compatibility",
            "Configs with `schema_version` greater than the current CLI supports",
            "Rollback after migration is local only",
        ]:
            self.assertIn(required, stability_doc)

        self.assertIn("[Stability contract](stability-contract.md)", command_inventory)
        self.assertIn("devsecops inventory --format json", command_inventory)
        self.assertIn("Compatibility And Regeneration", generated_doc)
        self.assertIn("future `schema_version` greater than this CLI", upgrade_doc)
        self.assertIn("Stability Contract Gate", release_checklist)
        self.assertIn("[Stability contract](docs/stability-contract.md)", readme)
        self.assertIn("Milestone 9: Stability Contract And Migration Readiness", roadmap)
        self.assertIn("Status: implemented in `v0.11.0`.", roadmap)

    def test_release_candidate_docs_cover_milestone_ten_contract(self) -> None:
        rc_doc = (ROOT_DIR / "docs/v1.0.0-release-candidate-checklist.md").read_text(encoding="utf-8")
        limitations_doc = (ROOT_DIR / "docs/known-limitations.md").read_text(encoding="utf-8")
        release_checklist = (ROOT_DIR / "docs/release-checklist.md").read_text(encoding="utf-8")
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        command_inventory = (ROOT_DIR / "docs/command-inventory.md").read_text(encoding="utf-8")
        roadmap = (ROOT_DIR / "ROADMAP.md").read_text(encoding="utf-8")

        for criterion in [
            "CLI command groups and core flags are stable.",
            "Config schema versioning and migration behavior are implemented.",
            "Clean config generation, validation, rendering, and readiness are covered by end-to-end tests.",
            "Generated Terraform and GitHub artifacts are deterministic and documented.",
            "At least one full AWS/GitHub production deployment walkthrough is documented.",
            "Local rollback cannot overwrite files outside the CLI-owned file set.",
            "Security controls have documented behavior and regression tests.",
            "Release and upgrade flows are documented.",
            "Known limitations are explicit rather than hidden in implementation details.",
        ]:
            self.assertIn(criterion, rc_doc)

        for required in [
            "Compatibility Verification Pass",
            "Documentation Audit",
            "Security Review",
            "Version 1.0 Criteria Evidence Map",
            "Blocker Register For v1.0.0 Stable",
            "RC-B1",
            "devsecops inventory --format json",
            "devsecops criteria --strict --format json",
            "devsecops report --format json",
            "terraform -chdir=terraform validate -no-color",
        ]:
            self.assertIn(required, rc_doc)

        self.assertIn("Accepted Limitations", limitations_doc)
        self.assertIn("Blockers Before v1.0.0 Stable", limitations_doc)
        self.assertIn("v1.0 Release Candidate Hardening Gate", release_checklist)
        self.assertIn("[v1.0.0 release candidate checklist](docs/v1.0.0-release-candidate-checklist.md)", readme)
        self.assertIn("Release candidate checklist", command_inventory)
        self.assertIn("Status: release candidate shipped in `v0.11.0`.", roadmap)
        self.assertIn("docs/v1.0.0-release-candidate-checklist.md", roadmap)

    def test_help_documents_product_contract_and_first_run(self) -> None:
        help_text = cli.build_parser().format_help()
        self.assertIn("CLI product", help_text)
        self.assertIn("Product boundary:", help_text)
        self.assertIn("devsecops setup --preset balanced --yes", help_text)
        self.assertIn("devsecops dry-run --image-uri <immutable-ecr-image-uri>", help_text)
        self.assertIn("devsecops status", help_text)
        self.assertIn("without arguments shows compact status and one next action", help_text)
        self.assertIn("Human-readable commands finish with the same recommended next step", help_text)
        self.assertIn("devsecops inventory --format json", help_text)
        self.assertIn("Stability contract:", help_text)
        self.assertIn("docs/command-inventory.md", help_text)
        self.assertIn("docs/generated-artifacts.md", help_text)

    def test_top_level_help_is_grouped_and_legacy_aliases_are_not_primary_choices(self) -> None:
        help_text = cli.build_parser().format_help()
        self.assertIn(
            "{menu,setup,status,deploy,dry-run,image,generate,doctor,health,config,github,aws,terraform,snapshot,report,explain,completion}",
            help_text,
        )
        self.assertIn("protected production deployment", help_text)
        self.assertIn("Legacy aliases still work", help_text)
        self.assertIn("Stable exit codes", help_text)
        self.assertNotIn("==SUPPRESS==", help_text)
        self.assertNotIn("gh-doctor           ", help_text)
        self.assertNotIn("aws-doctor          ", help_text)
        for legacy in ["next                ", "start               ", "readiness           ", "dashboard           ", "preflight           ", "render              "]:
            self.assertNotIn(legacy, help_text)

        config_buffer = io.StringIO()
        with redirect_stdout(config_buffer), self.assertRaises(SystemExit):
            cli.main(["config", "--help"])
        config_help = config_buffer.getvalue()
        self.assertIn("{show,validate,diff,reset,set,schema}", config_help)
        self.assertNotIn("new                 ", config_help)
        self.assertNotIn("create              ", config_help)

    def test_completion_scripts_cover_common_shells(self) -> None:
        bash = cli.completion_script("bash")
        zsh = cli.completion_script("zsh")
        fish = cli.completion_script("fish")

        self.assertIn("complete -F _devsecops_completion devsecops", bash)
        self.assertIn("menu setup status deploy dry-run image generate", bash)
        self.assertIn("prod status logs rollback", bash)
        self.assertIn("show validate diff reset set schema", bash)
        self.assertIn("#compdef devsecops", zsh)
        self.assertIn("compadd 'menu' 'setup' 'status'", zsh)
        self.assertIn("complete -c devsecops", fish)
        self.assertIn("image validate", bash)
        self.assertNotIn("compgen -W \"next start", bash)
        self.assertIn("completion", fish)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = cli.main(["completion", "bash"])
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("bash completion for devsecops", buffer.getvalue())

    def test_command_inventory_json_exposes_stability_contract(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = cli.main(["inventory", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        by_command = {item["command"]: item for item in payload["commands"]}

        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "command-inventory")
        self.assertEqual(payload["schema_version"], cli.CONTRACT_SCHEMA_VERSION)
        self.assertEqual(by_command["devsecops terraform plan"]["status"], "stable")
        self.assertEqual(by_command["devsecops terraform bootstrap"]["status"], "stable")
        self.assertEqual(by_command["devsecops status"]["status"], "stable")
        self.assertEqual(by_command["devsecops setup"]["status"], "stable")
        self.assertEqual(by_command["devsecops deploy prod"]["status"], "stable")
        self.assertEqual(by_command["devsecops deploy status"]["json_kind"], "deployment-status")
        self.assertIn("--image-uri", by_command["devsecops deploy rollback"]["stable_flags"])
        self.assertIn("--mode", by_command["devsecops setup"]["stable_flags"])
        self.assertIn("--apply-github", by_command["devsecops setup"]["stable_flags"])
        self.assertIn("--strict", by_command["devsecops setup"]["stable_flags"])
        self.assertEqual(by_command["devsecops next"]["alias_for"], "devsecops status")
        self.assertEqual(by_command["devsecops start"]["alias_for"], "devsecops setup")
        self.assertEqual(by_command["devsecops criteria"]["status"], "stable")
        self.assertEqual(by_command["devsecops evidence collect"]["status"], "stable")
        self.assertEqual(by_command["devsecops rollback"]["alias_for"], "devsecops snapshot restore")
        self.assertEqual(by_command["devsecops compose"]["status"], "experimental")
        self.assertIn("aliases", payload["deprecation_policy"])
        self.assertTrue(any(item["kind"] == "readiness" for item in payload["json_outputs"]))
        self.assertTrue(any(item["path"] == str(cli.GENERATED_TFVARS) for item in payload["generated_artifacts"]))
        self.assertIn("future_schema_version", payload["config_migration"])

    def test_command_inventory_status_filter_and_markdown(self) -> None:
        json_buffer = io.StringIO()
        with redirect_stdout(json_buffer):
            result = cli.main(["inventory", "--status", "experimental", "--format", "json"])

        payload = json.loads(json_buffer.getvalue())
        self.assertEqual(result, cli.EXIT_OK)
        self.assertTrue(payload["commands"])
        self.assertTrue(all(item["status"] == "experimental" for item in payload["commands"]))

        markdown_buffer = io.StringIO()
        with redirect_stdout(markdown_buffer):
            self.assertEqual(cli.main(["inventory", "--status", "stable", "--format", "markdown"]), cli.EXIT_OK)
        self.assertIn("# DevSecOps Command Inventory", markdown_buffer.getvalue())
        self.assertIn("Generated Artifact Contract", markdown_buffer.getvalue())

    def test_new_ux_commands_have_help(self) -> None:
        for command in [
            ["setup", "--help"],
            ["status", "--help"],
            ["image", "validate", "--help"],
            ["generate", "--help"],
            # Compatibility aliases remain callable even though they are hidden.
            ["next", "--help"],
            ["start", "--help"],
            ["preflight", "--help"],
            ["render", "--help"],
        ]:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(command)
            self.assertEqual(raised.exception.code, 0)
            self.assertIn("usage:", buffer.getvalue())

        setup_buffer = io.StringIO()
        with redirect_stdout(setup_buffer), self.assertRaises(SystemExit):
            cli.main(["setup", "--help"])
        setup_help = setup_buffer.getvalue()
        for flag in [
            "--mode",
            "--image-uri",
            "--backend-bucket",
            "--apply-github",
            "--deploy-role-arn",
            "--plan-role-arn",
            "--yes",
            "--strict",
        ]:
            self.assertIn(flag, setup_help)
        self.assertIn("does not", setup_help)
        self.assertIn("imply --apply-github", setup_help)

    def test_next_action_decision_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(cli.next_action(root, cli.default_config())["id"], "missing_project_files")

            create_required_project_files(root)
            self.assertEqual(cli.next_action(root, cli.default_config())["id"], "missing_config")

            cfg = cli.default_config()
            cli.write_config(root, cfg)
            self.assertEqual(cli.next_action(root, cfg)["id"], "missing_image")

            cfg["lambda_image_uri"] = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123"
            cli.write_config(root, cfg)
            self.assertEqual(cli.next_action(root, cfg)["id"], "missing_backend")

            cfg["backend"]["bucket"] = "state-bucket"
            cfg["enable_http_validation"] = True
            cli.write_config(root, cfg)
            self.assertEqual(cli.next_action(root, cfg)["id"], "missing_github_setup")

            (root / cli.GENERATED_TFVARS).parent.mkdir(parents=True, exist_ok=True)
            (root / cli.GENERATED_TFVARS).write_text("project_name = \"devsecops-pipeline\"\n", encoding="utf-8")
            setup = root / cli.DIST_DIR / "github-setup.sh"
            setup.parent.mkdir(parents=True, exist_ok=True)
            setup.write_text("# setup\n", encoding="utf-8")
            with patch.object(cli, "command_exists", side_effect=lambda name: name == "gh"), patch.object(
                cli,
                "collect_github_checks",
                return_value=[cli.Check("GitHub auth", "WARN", "not authenticated")],
            ):
                self.assertEqual(cli.next_action(root, cfg)["id"], "missing_github_setup")

            with patch.object(cli, "command_exists", side_effect=lambda name: name == "gh"), patch.object(
                cli,
                "collect_github_checks",
                return_value=[
                    cli.Check("GitHub CLI", "OK", "Installed."),
                    cli.Check("GitHub auth", "OK", "Authenticated."),
                    cli.Check("GitHub repository", "OK", "owner/repo"),
                ],
            ):
                self.assertEqual(cli.next_action(root, cfg)["id"], "missing_aws_evidence")

            with patch.object(cli, "command_exists", return_value=True), patch.object(
                cli,
                "collect_github_checks",
                return_value=[
                    cli.Check("GitHub CLI", "OK", "Installed."),
                    cli.Check("GitHub auth", "OK", "Authenticated."),
                    cli.Check("GitHub repository", "OK", "owner/repo"),
                ],
            ), patch.object(
                cli,
                "collect_aws_checks",
                return_value=[cli.Check("Lambda function", "WARN", "not deployed")],
            ):
                self.assertEqual(cli.next_action(root, cfg)["id"], "ready_for_deploy")

            with patch.object(cli, "command_exists", return_value=True), patch.object(
                cli,
                "collect_github_checks",
                return_value=[
                    cli.Check("GitHub CLI", "OK", "Installed."),
                    cli.Check("GitHub auth", "OK", "Authenticated."),
                    cli.Check("GitHub repository", "OK", "owner/repo"),
                ],
            ), patch.object(
                cli,
                "collect_aws_checks",
                return_value=[cli.Check("AWS identity", "OK", "ok"), cli.Check("Lambda function", "OK", "deployed")],
            ):
                self.assertEqual(cli.next_action(root, cfg)["id"], "ready_for_release_evidence")

    def test_next_command_json_reports_context_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["next", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "next-action")
        self.assertEqual(payload["action"], "missing_project_files")
        self.assertIn("context", payload)
        self.assertIn("why", payload)
        self.assertIn("changes", payload)
        self.assertTrue(payload["blocked"])

    def test_no_arguments_show_status_and_shared_next_action_without_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch("builtins.input") as prompt:
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main([])

        output = buffer.getvalue()
        self.assertEqual(result, cli.EXIT_OK)
        prompt.assert_not_called()
        self.assertIn("Readiness", output)
        self.assertIn("Next Action", output)
        self.assertIn("What is not ready:", output)
        self.assertIn("Why it matters:", output)
        self.assertIn("What will change:", output)
        self.assertIn("Next command:", output)
        self.assertIn("Docs:", output)

    def test_human_commands_get_one_next_postlude_but_json_stays_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                human_buffer = io.StringIO()
                with redirect_stdout(human_buffer):
                    self.assertEqual(cli.main(["explain", "oidc"]), cli.EXIT_OK)

                json_buffer = io.StringIO()
                with redirect_stdout(json_buffer):
                    self.assertEqual(cli.main(["next", "--format", "json"]), cli.EXIT_OK)

                shell_buffer = io.StringIO()
                with redirect_stdout(shell_buffer):
                    self.assertEqual(cli.main(["github", "setup"]), cli.EXIT_OK)

        self.assertEqual(human_buffer.getvalue().count("Recommended Next Step"), 1)
        payload = json.loads(json_buffer.getvalue())
        self.assertEqual(payload["kind"], "next-action")
        self.assertIn("#!/usr/bin/env bash", shell_buffer.getvalue())
        self.assertNotIn("Recommended Next Step", shell_buffer.getvalue())

    def test_menu_dashboard_and_next_use_the_same_action_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            cfg = cli.default_config()
            cli.write_config(root, cfg)
            expected_command = cli.next_action(root, cfg)["command"]

            next_buffer = io.StringIO()
            menu_buffer = io.StringIO()
            dashboard_buffer = io.StringIO()
            with patch.object(cli, "repo_root", return_value=root):
                with redirect_stdout(next_buffer):
                    self.assertEqual(cli.main(["next"]), cli.EXIT_OK)
                with redirect_stdout(menu_buffer):
                    cli.print_main_menu(root)
                with redirect_stdout(dashboard_buffer):
                    cli.render_dashboard(root, mode="compact")

        for output in [next_buffer.getvalue(), menu_buffer.getvalue(), dashboard_buffer.getvalue()]:
            self.assertIn(f"Next command: {expected_command}", output)

    def test_start_creates_config_with_yes_after_project_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["start", "--yes"])

            self.assertTrue((root / cli.CONFIG_FILE).exists())
            self.assertIn("Project Setup", buffer.getvalue())
            self.assertIn("Next Action", buffer.getvalue())

        self.assertEqual(result, cli.EXIT_OK)

    def test_demo_setup_completes_locally_and_persists_resumable_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["setup", "--mode", "demo", "--yes", "--strict"])

            cfg = cli.load_config(root)
            state_path = root / cli.SETUP_STATE_FILE
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state_mode = state_path.stat().st_mode & 0o777

        self.assertEqual(result, cli.EXIT_OK)
        self.assertFalse(cfg["use_prod_approval_environment"])
        self.assertEqual(state["mode"], "demo")
        self.assertTrue(state["dry_run_fingerprint"])
        self.assertEqual(state["steps"]["summary"]["status"], "complete")
        self.assertEqual(state_mode, 0o600)
        self.assertIn("Guided setup complete", buffer.getvalue())
        self.assertIn("not required in demo mode", buffer.getvalue())

    def test_setup_resumes_at_saved_step_after_interactive_pause(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False):
                first = io.StringIO()
                with patch("builtins.input", side_effect=["1", "", "0"]), redirect_stdout(first):
                    first_result = cli.main(["setup"])

                saved = json.loads((root / cli.SETUP_STATE_FILE).read_text(encoding="utf-8"))
                second = io.StringIO()
                with patch("builtins.input") as prompt, redirect_stdout(second):
                    second_result = cli.main(["setup", "--yes", "--strict"])

            final_state = json.loads((root / cli.SETUP_STATE_FILE).read_text(encoding="utf-8"))

        self.assertEqual(first_result, cli.EXIT_OK)
        self.assertEqual(saved["mode"], "demo")
        self.assertEqual(saved["last_step"], "config")
        self.assertFalse("lambda_image_uri" in saved)
        self.assertIn("Setup paused at step `config`", first.getvalue())
        self.assertEqual(second_result, cli.EXIT_OK)
        prompt.assert_not_called()
        self.assertIn("Resuming saved demo setup from step `config`", second.getvalue())
        self.assertEqual(final_state["steps"]["summary"]["status"], "complete")

    def test_standard_setup_can_defer_config_without_crashing_cloud_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False), patch(
                "builtins.input",
                side_effect=["2", "n"],
            ):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["setup"])

        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("Config creation deferred", buffer.getvalue())
        self.assertIn("AWS identity: waiting for a valid local config", buffer.getvalue())
        self.assertIn("Guided Setup Summary", buffer.getvalue())

    def test_strict_standard_setup_uses_missing_tool_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False):
                with redirect_stdout(io.StringIO()):
                    result = cli.main(["setup", "--mode", "standard", "--yes", "--strict"])

        self.assertEqual(result, cli.EXIT_MISSING_EXTERNAL_TOOL)

    def test_setup_dry_run_progress_is_invalidated_when_config_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.clean_config("student-demo")
            cli.write_config(root, cfg)
            state = cli.new_setup_state("demo")
            state["dry_run_fingerprint"] = cli.setup_config_fingerprint(
                cfg,
                image_override=cli.demo_image_uri(cfg),
            )
            stages = cli.setup_stages(
                root,
                cfg,
                state,
                dependency_status={"git": False, "terraform": False, "aws": False, "gh": False},
                backend_checks=[],
                aws_identity=None,
                github_checks=[],
            )
            self.assertEqual(next(stage for stage in stages if stage.id == "dry_run").status, "complete")

            cfg["project_name"] = "changed-demo"
            cli.write_config(root, cfg)
            changed_stages = cli.setup_stages(
                root,
                cfg,
                state,
                dependency_status={"git": False, "terraform": False, "aws": False, "gh": False},
                backend_checks=[],
                aws_identity=None,
                github_checks=[],
            )

        self.assertEqual(next(stage for stage in changed_stages if stage.id == "dry_run").status, "pending")

    def test_setup_modes_enforce_their_config_posture_without_treating_image_as_config(self) -> None:
        demo_cfg = cli.clean_config("student-demo")
        balanced_cfg = cli.clean_config("balanced")
        enterprise_cfg = cli.clean_config("enterprise")

        self.assertEqual(cli.setup_config_blockers(demo_cfg, "demo"), [])
        self.assertTrue(cli.setup_config_blockers(demo_cfg, "standard"))
        self.assertEqual(cli.setup_config_blockers(balanced_cfg, "standard"), [])
        self.assertTrue(cli.setup_config_blockers(balanced_cfg, "production"))
        self.assertEqual(cli.setup_config_blockers(enterprise_cfg, "production"), [])

    def test_explicit_noninteractive_mode_switch_applies_its_preset_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            cli.write_config(root, cli.clean_config("student-demo"))
            cli.save_setup_state(root, cli.new_setup_state("demo"))
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False):
                with redirect_stdout(io.StringIO()):
                    result = cli.main(["setup", "--mode", "standard", "--yes"])
            cfg = cli.load_config(root)
            snapshots = cli.list_snapshots(root)

        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(cfg["api_authorization_type"], "AWS_IAM")
        self.assertTrue(cfg["use_prod_approval_environment"])
        self.assertTrue(cfg["use_separate_aws_plan_role"])
        self.assertTrue(snapshots)

    def test_setup_requires_backend_resources_not_only_configured_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.clean_config("balanced")
            cfg["lambda_image_uri"] = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123"
            cfg["backend"]["bucket"] = "devsecops-test-state"
            cli.write_config(root, cfg)
            state = cli.new_setup_state("standard")
            state["dry_run_fingerprint"] = cli.setup_config_fingerprint(cfg)
            github_ready = [
                cli.Check("GitHub CLI", "OK", "Installed."),
                cli.Check("GitHub auth", "OK", "Authenticated."),
                cli.Check("GitHub repository", "OK", "owner/repo"),
            ]
            stages = cli.setup_stages(
                root,
                cfg,
                state,
                dependency_status={"git": True, "terraform": True, "aws": True, "gh": True},
                backend_checks=[
                    cli.Check("State bucket", "WARN", "Bucket not found."),
                    cli.Check("Lock table", "WARN", "Table not found."),
                ],
                aws_identity=cli.Check("AWS identity", "OK", "123456789012"),
                github_checks=github_ready,
            )

        backend = next(stage for stage in stages if stage.id == "backend")
        self.assertEqual(backend.status, "pending")
        self.assertEqual(cli.setup_next_command(backend, "standard"), "devsecops terraform bootstrap")
        self.assertEqual(next(stage for stage in stages if stage.id == "summary").status, "pending")

    def test_setup_state_corruption_fails_closed_without_overwriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            state_path = root / cli.SETUP_STATE_FILE
            state_path.parent.mkdir(parents=True)
            state_path.write_text("not-json\n", encoding="utf-8")
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["setup", "--yes"])
            preserved = state_path.read_text(encoding="utf-8")

        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertEqual(preserved, "not-json\n")
        self.assertIn("Setup state error", buffer.getvalue())

    def test_setup_rejects_cloud_options_in_demo_and_github_values_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root):
                demo_buffer = io.StringIO()
                with redirect_stdout(demo_buffer):
                    demo_result = cli.main(
                        ["setup", "--mode", "demo", "--yes", "--backend-bucket", "demo-state"]
                    )
                role_buffer = io.StringIO()
                with redirect_stdout(role_buffer):
                    role_result = cli.main(
                        [
                            "setup",
                            "--mode",
                            "standard",
                            "--yes",
                            "--deploy-role-arn",
                            "arn:aws:iam::123456789012:role/deploy",
                        ]
                    )

        self.assertEqual(demo_result, cli.EXIT_VALIDATION_FAILED)
        self.assertIn("require --mode standard", demo_buffer.getvalue())
        self.assertEqual(role_result, cli.EXIT_VALIDATION_FAILED)
        self.assertIn("require --apply-github", role_buffer.getvalue())

    def test_backend_overrides_update_region_and_lock_table_without_reentering_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.clean_config("balanced")
            cfg["backend"]["bucket"] = "existing-state-bucket"
            cli.write_config(root, cfg)
            args = argparse.Namespace(
                backend_bucket=None,
                backend_region="eu-central-1",
                backend_lock_table="new-lock-table",
            )
            with redirect_stdout(io.StringIO()):
                updated, had_error = cli.configure_setup_backend(root, cfg, args, interactive=False)

        self.assertFalse(had_error)
        self.assertEqual(updated["backend"]["bucket"], "existing-state-bucket")
        self.assertEqual(updated["backend"]["region"], "eu-central-1")
        self.assertEqual(updated["backend"]["lock_table"], "new-lock-table")

    def test_standard_setup_never_applies_github_without_explicit_authorization(self) -> None:
        backend_ready = [
            cli.Check("State bucket", "OK", "devsecops-test-state"),
            cli.Check("Lock table", "OK", "devsecops-pipeline-terraform-locks"),
        ]
        github_ready = [
            cli.Check("GitHub CLI", "OK", "Installed."),
            cli.Check("GitHub auth", "OK", "Authenticated."),
            cli.Check("GitHub repository", "OK", "owner/repo"),
            cli.Check("GitHub variable PROJECT_NAME", "OK", "ready"),
            cli.Check("GitHub secret AWS_ROLE_TO_ASSUME_ARN", "OK", "present"),
            cli.Check("GitHub secret AWS_PLAN_ROLE_TO_ASSUME_ARN", "OK", "present"),
        ]
        image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=True), patch.object(
                cli,
                "setup_aws_identity",
                return_value=cli.Check("AWS identity", "OK", "arn:aws:iam::123456789012:user/test"),
            ), patch.object(cli, "setup_backend_resource_checks", return_value=backend_ready), patch.object(
                cli,
                "collect_github_checks",
                return_value=github_ready,
            ), patch.object(
                cli,
                "apply_github_setup",
            ) as apply_setup:
                with redirect_stdout(io.StringIO()):
                    result = cli.main(
                        [
                            "setup",
                            "--mode",
                            "standard",
                            "--yes",
                            "--strict",
                            "--image-uri",
                            image_uri,
                            "--backend-bucket",
                            "devsecops-test-state",
                        ]
                    )

        self.assertEqual(result, cli.EXIT_OK)
        apply_setup.assert_not_called()

    def test_setup_explicit_github_apply_does_not_persist_secret_values(self) -> None:
        backend_ready = [
            cli.Check("State bucket", "OK", "devsecops-test-state"),
            cli.Check("Lock table", "OK", "devsecops-pipeline-terraform-locks"),
        ]
        github_incomplete = [
            cli.Check("GitHub CLI", "OK", "Installed."),
            cli.Check("GitHub auth", "OK", "Authenticated."),
            cli.Check("GitHub repository", "OK", "owner/repo"),
            cli.Check("GitHub variables", "WARN", "missing"),
        ]
        github_ready = [
            cli.Check("GitHub CLI", "OK", "Installed."),
            cli.Check("GitHub auth", "OK", "Authenticated."),
            cli.Check("GitHub repository", "OK", "owner/repo"),
        ]
        image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123"
        secret_value = "never-write-this-token"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_required_project_files(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=True), patch.object(
                cli,
                "setup_aws_identity",
                return_value=cli.Check("AWS identity", "OK", "123456789012"),
            ), patch.object(cli, "setup_backend_resource_checks", return_value=backend_ready), patch.object(
                cli,
                "collect_github_checks",
                side_effect=[github_incomplete, github_ready, github_ready],
            ), patch.object(cli, "github_setup_precheck", return_value=github_ready), patch.object(
                cli,
                "apply_github_setup",
                return_value=cli.EXIT_OK,
            ) as apply_setup:
                with redirect_stdout(io.StringIO()):
                    result = cli.main(
                        [
                            "setup",
                            "--mode",
                            "standard",
                            "--yes",
                            "--strict",
                            "--image-uri",
                            image_uri,
                            "--backend-bucket",
                            "devsecops-test-state",
                            "--apply-github",
                            "--deploy-role-arn",
                            "arn:aws:iam::123456789012:role/deploy",
                            "--plan-role-arn",
                            "arn:aws:iam::123456789012:role/plan",
                            "--snyk-token",
                            secret_value,
                        ]
                    )
            saved_text = (root / cli.SETUP_STATE_FILE).read_text(encoding="utf-8")

        self.assertEqual(result, cli.EXIT_OK)
        apply_setup.assert_called_once()
        self.assertNotIn(secret_value, saved_text)

    def test_evidence_collect_rc_writes_release_candidate_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["evidence", "collect", "--rc"])

            evidence_dir = root / cli.RC_EVIDENCE_DIR
            manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
            inventory_exists = (evidence_dir / "inventory.json").exists()
            readiness_exists = (evidence_dir / "readiness.json").exists()
            criteria = json.loads((evidence_dir / "criteria.json").read_text(encoding="utf-8"))

        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(manifest["kind"], "release-candidate-evidence")
        self.assertTrue(inventory_exists)
        self.assertTrue(readiness_exists)
        self.assertEqual(criteria["kind"], "v1-criteria")
        self.assertIn("Release Candidate Evidence", buffer.getvalue())

    def test_criteria_command_json_reports_missing_stable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "evidence"
            with patch.object(cli, "repo_root", return_value=ROOT_DIR):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["criteria", "--format", "json", "--evidence-dir", str(evidence_dir)])

        payload = json.loads(buffer.getvalue())
        gate_statuses = {gate["id"]: gate["status"] for gate in payload["stable_release_gates"]}

        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "v1-criteria")
        self.assertFalse(payload["stable_ready"])
        self.assertTrue(all(item["status"] == "OK" for item in payload["criteria"]))
        self.assertEqual(gate_statuses["production-evidence-bundle-attached"], "BLOCKED")
        self.assertEqual(gate_statuses["wsl2-compatibility-transcript-attached"], "BLOCKED")
        self.assertTrue(any("production-deployment-evidence" in action for action in payload["next_actions"]))

    def test_criteria_strict_passes_when_required_external_evidence_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "evidence"
            (evidence_dir / "workflow-artifacts").mkdir(parents=True)
            for relative in [*cli.PRODUCTION_EVIDENCE_REQUIRED_FILES, *cli.WSL2_EVIDENCE_REQUIRED_FILES]:
                path = evidence_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n" if path.suffix == ".json" else "test evidence\n", encoding="utf-8")

            with patch.object(cli, "repo_root", return_value=ROOT_DIR):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["criteria", "--strict", "--format", "json", "--evidence-dir", str(evidence_dir)])

        payload = json.loads(buffer.getvalue())

        self.assertEqual(result, cli.EXIT_OK)
        self.assertTrue(payload["stable_ready"])
        self.assertTrue(all(item["status"] == "OK" for item in payload["criteria"]))
        self.assertTrue(all(item["status"] == "OK" for item in payload["stable_release_gates"]))

    def test_first_success_documented_commands_are_stable(self) -> None:
        first_success_doc = (ROOT_DIR / "docs/first-successful-pipeline.md").read_text(encoding="utf-8")
        command_status = {item["command"]: item["status"] for item in cli.command_contracts()}
        required_stable_commands = [
            "devsecops status",
            "devsecops setup",
            "devsecops config validate",
            "devsecops config diff",
            "devsecops dry-run",
            "devsecops generate",
            "devsecops image validate",
            "devsecops config set",
            "devsecops terraform bootstrap",
            "devsecops github setup",
            "devsecops doctor github",
            "devsecops doctor branch",
            "devsecops report",
            "devsecops deploy prod",
            "devsecops deploy status",
            "devsecops deploy logs",
            "devsecops deploy rollback",
            "devsecops doctor aws",
            "devsecops evidence collect",
        ]

        for command in required_stable_commands:
            self.assertIn(command, first_success_doc)
            self.assertEqual(command_status[command], "stable", command)
        self.assertNotIn("devsecops compose", first_success_doc)
        self.assertNotIn("devsecops tui", first_success_doc)

    def test_readiness_json_output_contains_checks_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.cmd_readiness(argparse.Namespace(deep=False, format="json"))

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["kind"], "readiness")
        self.assertIn("checks", payload)
        self.assertIn("gaps", payload)

    def test_status_json_has_one_score_and_includes_the_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["status", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "status")
        self.assertIn("score", payload)
        self.assertNotIn("overall_breakdown_score", payload)
        self.assertEqual(payload["next_action"]["action"], "missing_project_files")
        self.assertIn("command", payload["next_action"])

    def test_status_human_output_does_not_show_a_second_legacy_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["status"])

        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("Overall:", buffer.getvalue())
        self.assertNotIn("legacy score", buffer.getvalue())

    def test_image_validate_uses_plain_language_json_while_preflight_keeps_legacy_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root):
                preferred = io.StringIO()
                with redirect_stdout(preferred):
                    cli.main(["image", "validate", "--format", "json"])
                legacy = io.StringIO()
                with redirect_stdout(legacy):
                    cli.main(["preflight", "--format", "json"])

        preferred_payload = json.loads(preferred.getvalue())
        legacy_payload = json.loads(legacy.getvalue())
        self.assertEqual(preferred_payload["kind"], "image-validation")
        self.assertNotIn("overall_breakdown_score", preferred_payload)
        self.assertEqual(legacy_payload["kind"], "preflight")
        self.assertIn("overall_breakdown_score", legacy_payload)

    def test_doctor_group_json_and_legacy_alias_share_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root):
                grouped = io.StringIO()
                with redirect_stdout(grouped):
                    grouped_result = cli.main(["doctor", "local", "--format", "json"])
                legacy = io.StringIO()
                with redirect_stdout(legacy):
                    legacy_result = cli.main(["doctor", "--format", "json"])

        grouped_payload = json.loads(grouped.getvalue())
        legacy_payload = json.loads(legacy.getvalue())
        self.assertEqual(grouped_result, 0)
        self.assertEqual(legacy_result, 0)
        self.assertEqual(grouped_payload["kind"], "doctor-local")
        self.assertEqual(legacy_payload["kind"], "doctor-local")

    def test_grouped_config_set_updates_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root):
                with redirect_stdout(io.StringIO()):
                    result = cli.main(["config", "set", "backend.bucket", "state-bucket"])

            cfg = cli.load_config(root)

        self.assertEqual(result, 0)
        self.assertEqual(cfg["backend"]["bucket"], "state-bucket")

    def test_generate_flag_replaces_render_flag_without_breaking_compatibility(self) -> None:
        parser = cli.build_parser()
        preferred = parser.parse_args(["config", "set", "backend.bucket", "state-bucket", "--generate"])
        legacy = parser.parse_args(["config", "set", "backend.bucket", "state-bucket", "--render"])

        self.assertTrue(preferred.render)
        self.assertTrue(legacy.render)

    def test_grouped_snapshot_list_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.create_snapshot(root, "test", "Test snapshot")
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["snapshot", "list", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["kind"], "snapshots")
        self.assertEqual(len(payload["snapshots"]), 1)

    def test_grouped_terraform_plan_dispatches_legacy_plan_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "run_plan", return_value=0) as run_plan:
                result = cli.main(["terraform", "plan", "dev", "--create-workspace"])

        self.assertEqual(result, 0)
        run_plan.assert_called_once_with(root, "dev", no_init=False, create_workspace=True)

    def test_github_group_status_json_reports_missing_gh_without_failing_non_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["github", "status", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["kind"], "github-actions-status")
        self.assertIn("error", payload)

    def test_doctor_github_strict_returns_missing_tool_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=False):
                with redirect_stdout(io.StringIO()):
                    result = cli.main(["doctor", "github", "--strict", "--format", "json"])

        self.assertEqual(result, cli.EXIT_MISSING_EXTERNAL_TOOL)

    def test_collect_github_checks_warns_when_gh_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cli, "command_exists", return_value=False):
                checks = cli.collect_github_checks(Path(tmpdir), cli.default_config())

        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["GitHub CLI"].status, "WARN")
        self.assertIn("`gh` not found", by_name["GitHub CLI"].detail)

    def test_readiness_score_weights_warn_as_half_credit(self) -> None:
        checks = [
            cli.Check("one", "OK", "ok"),
            cli.Check("two", "WARN", "warn"),
            cli.Check("three", "FAIL", "fail"),
            cli.Check("info", "INFO", "ignored", scored=False),
        ]
        self.assertEqual(cli.readiness_score(checks), 50)

    def test_readiness_gap_rows_show_only_scored_gaps_with_fix(self) -> None:
        rows = cli.readiness_gap_rows(
            [
                cli.Check("Project name", "OK", "valid"),
                cli.Check("Lambda image URI", "WARN", "Required before production deploy."),
                cli.Check("HTTP validation", "INFO", "Disabled.", scored=False),
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Lambda image URI")
        self.assertIn("devsecops set lambda_image_uri", rows[0][3])
        self.assertIn("docs/troubleshooting.md#lambda-image-uri-is-missing-or-invalid", rows[0][3])

    def test_readiness_strict_fails_on_scored_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "load_config", return_value=cli.default_config()), patch.object(
                cli,
                "collect_checks",
                return_value=[cli.Check("Backend bucket", "WARN", "Set a real S3 state bucket name.")],
            ):
                with redirect_stdout(io.StringIO()):
                    result = cli.cmd_readiness(argparse.Namespace(deep=False, format="json", strict=True))

        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)

    def test_doctor_compact_output_links_troubleshooting_for_gaps(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli.print_compact_checks(
                [cli.Check("Lambda image region", "FAIL", "Image region `eu-west-1` does not match aws_region `us-east-1`.")],
                title="Doctor Local",
            )

        output = buffer.getvalue()
        self.assertIn("Fix:", output)
        self.assertIn("docs/troubleshooting.md#lambda-image-uri-is-missing-or-invalid", output)

    def test_config_validation_catches_bad_values(self) -> None:
        cfg = cli.default_config()
        cfg["environments"]["dev"]["lambda_timeout"] = 901
        failures = [check for check in cli.validate_config(cfg) if check.status == "FAIL"]
        self.assertTrue(any(check.name == "dev.lambda_timeout" for check in failures))

    def test_config_validation_surfaces_production_policy_risks(self) -> None:
        cfg = cli.default_config()
        cfg["lambda_image_uri"] = "repo.example/app:latest"
        cfg["use_prod_approval_environment"] = False
        cfg["use_separate_aws_plan_role"] = False
        cfg["enable_http_validation"] = False
        cfg["environments"]["prod"]["cors_allowed_origins"] = ["*"]

        by_name = {check.name: check for check in cli.validate_config(cfg)}

        self.assertEqual(by_name["Lambda image immutability policy"].status, "FAIL")
        self.assertEqual(by_name["Production CORS policy"].status, "WARN")
        self.assertEqual(by_name["Production approval gate policy"].status, "WARN")
        self.assertEqual(by_name["Separate plan role policy"].status, "WARN")
        self.assertEqual(by_name["Deployment validation policy"].status, "WARN")

    def test_config_validate_strict_fails_on_policy_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.default_config()
            cfg["lambda_image_uri"] = "123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-abc123"
            cfg["enable_http_validation"] = True
            cfg["environments"]["prod"]["cors_allowed_origins"] = ["*"]
            cli.write_config(root, cfg)
            with patch.object(cli, "repo_root", return_value=root):
                relaxed = io.StringIO()
                with redirect_stdout(relaxed):
                    relaxed_result = cli.main(["config", "validate", "--format", "json"])
                strict = io.StringIO()
                with redirect_stdout(strict):
                    strict_result = cli.main(["config", "validate", "--strict", "--format", "json"])

        relaxed_payload = json.loads(relaxed.getvalue())
        strict_payload = json.loads(strict.getvalue())
        self.assertEqual(relaxed_result, cli.EXIT_OK)
        self.assertEqual(strict_result, cli.EXIT_VALIDATION_FAILED)
        self.assertTrue(any(check["name"] == "Production CORS policy" and check["status"] == "WARN" for check in strict_payload["checks"]))
        self.assertEqual(relaxed_payload["kind"], "config")

    def test_config_validate_strict_human_shows_production_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["config", "validate", "--strict"])

        output = buffer.getvalue()
        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertIn("Production Blockers", output)
        self.assertIn("Warnings promoted to failures by --strict", output)
        self.assertIn("Next command:", output)

    def test_config_validate_command_fails_before_external_tools_on_bad_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.default_config()
            cfg["environments"]["dev"]["lambda_timeout"] = 901
            cli.write_config(root, cfg)
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.cmd_config(argparse.Namespace(config_command="validate"))

        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertIn("dev.lambda_timeout", buffer.getvalue())

    def test_doctor_local_strict_reports_unavailable_terraform_as_missing_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())

            def fake_command_exists(name: str) -> bool:
                return name not in {"git", "terraform", "aws"}

            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", side_effect=fake_command_exists):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["doctor", "local", "--strict", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        terraform_check = next(check for check in payload["checks"] if check["name"] == "`terraform` CLI")
        self.assertEqual(result, cli.EXIT_MISSING_EXTERNAL_TOOL)
        self.assertEqual(terraform_check["status"], "FAIL")
        self.assertIn("Not found on PATH", terraform_check["detail"])

    def test_preset_strict_enables_validation_controls(self) -> None:
        cfg = cli.preset_config("strict")
        self.assertTrue(cfg["enable_snyk_scan"])
        self.assertTrue(cfg["enable_http_validation"])
        self.assertTrue(cfg["enable_dast"])
        self.assertEqual(cfg["environments"]["prod"]["lambda_timeout"], 300)

    def test_preset_profiles_are_valid_and_include_phase_five_profiles(self) -> None:
        self.assertIn("enterprise", cli.PRESET_ORDER)
        self.assertIn("student-demo", cli.PRESET_ORDER)

        for preset_name in cli.PRESET_ORDER:
            cfg = cli.preset_config(preset_name)
            failures = [check for check in cli.validate_config(cfg) if check.status == "FAIL"]
            self.assertEqual(failures, [], preset_name)

        enterprise = cli.preset_config("enterprise")
        self.assertTrue(enterprise["enable_snyk_scan"])
        self.assertTrue(enterprise["enable_http_validation"])
        self.assertTrue(enterprise["enable_dast"])
        self.assertEqual(enterprise["environments"]["prod"]["log_retention_days"], 1095)
        self.assertNotIn("*", enterprise["environments"]["prod"]["cors_allowed_origins"])

        demo = cli.preset_config("student-demo")
        self.assertFalse(demo["enable_http_validation"])
        self.assertFalse(demo["enable_dast"])
        self.assertEqual(demo["environments"]["dev"]["lambda_memory_size"], 512)
        demo_preset = cli.preset_dict("student-demo")
        self.assertEqual(demo_preset["posture"], "demo-only")
        self.assertTrue(demo_preset["strict_policy_gaps"])

    def test_preset_list_show_apply_and_legacy_apply(self) -> None:
        list_output = io.StringIO()
        with redirect_stdout(list_output):
            self.assertEqual(cli.cmd_preset(argparse.Namespace(command="list", name=None, render=False)), 0)
        self.assertIn("enterprise", list_output.getvalue())
        self.assertIn("student-demo", list_output.getvalue())
        self.assertIn("Policy Preset Comparison", list_output.getvalue())
        self.assertIn("production-oriented", list_output.getvalue())

        show_output = io.StringIO()
        with redirect_stdout(show_output):
            self.assertEqual(cli.cmd_preset(argparse.Namespace(command="show", name="strict", render=False)), 0)
        self.assertIn("Preset: strict", show_output.getvalue())
        self.assertIn("prod.lambda_timeout", show_output.getvalue())

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.default_config()
            cfg["project_name"] = "kept-project"
            cli.write_config(root, cfg)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "run_render", return_value=0) as run_render:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.cmd_preset(argparse.Namespace(command="apply", name="enterprise", render=True)), 0)
                applied = cli.load_config(root)
                self.assertEqual(applied["project_name"], "kept-project")
                self.assertEqual(applied["environments"]["prod"]["log_retention_days"], 1095)
                run_render.assert_called_once()

                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.cmd_preset(argparse.Namespace(command="student-demo", name=None, render=False)), 0)
                legacy_applied = cli.load_config(root)
                self.assertEqual(legacy_applied["environments"]["prod"]["log_retention_days"], 30)

    def test_compose_config_applies_control_answers(self) -> None:
        cfg = cli.compose_config(
            cli.default_config(),
            {
                "enable_snyk_scan": True,
                "enable_dast": True,
                "enable_http_validation": True,
                "use_strict_cors": True,
                "use_prod_approval_environment": False,
                "use_separate_aws_plan_role": False,
            },
        )
        self.assertTrue(cfg["enable_snyk_scan"])
        self.assertTrue(cfg["enable_dast"])
        self.assertTrue(cfg["enable_http_validation"])
        self.assertFalse(cfg["use_prod_approval_environment"])
        self.assertFalse(cfg["use_separate_aws_plan_role"])
        self.assertTrue(cli.uses_strict_cors(cfg))
        self.assertEqual(cli.prod_approval_environment(cfg), cli.NO_APPROVAL_ENVIRONMENT)

    def test_compose_command_writes_config_artifacts_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            answers = [True, True, True, True, False, False]
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "prompt_bool", side_effect=answers):
                with redirect_stdout(io.StringIO()):
                    result = cli.cmd_compose(argparse.Namespace())

            self.assertEqual(result, 0)
            cfg = cli.load_config(root)
            self.assertTrue(cfg["enable_snyk_scan"])
            self.assertTrue(cfg["enable_dast"])
            self.assertTrue(cfg["enable_http_validation"])
            self.assertTrue(cli.uses_strict_cors(cfg))
            self.assertFalse(cfg["use_prod_approval_environment"])
            self.assertFalse(cfg["use_separate_aws_plan_role"])
            self.assertTrue((root / cli.CONFIG_FILE).exists())
            self.assertTrue((root / cli.GENERATED_TFVARS).exists())
            self.assertTrue((root / cli.DIST_DIR / "github-setup.sh").exists())
            report = root / cli.DIST_DIR / "readiness-report.md"
            self.assertTrue(report.exists())
            self.assertIn("Snyk container scan", report.read_text(encoding="utf-8"))

    def test_github_setup_script_contains_expected_commands(self) -> None:
        cfg = cli.default_config()
        cfg["lambda_image_uri"] = "123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-abc123"
        cfg["enable_snyk_scan"] = True
        cfg["use_separate_aws_plan_role"] = False
        script = cli.github_setup_script(cfg)
        self.assertIn("gh variable set PROJECT_NAME", script)
        self.assertIn("gh variable set ENABLE_SNYK_SCAN", script)
        self.assertIn("gh variable set PROD_APPROVAL_ENVIRONMENT", script)
        self.assertIn("gh secret set AWS_ROLE_TO_ASSUME_ARN", script)
        self.assertIn("gh secret set AWS_PLAN_ROLE_TO_ASSUME_ARN", script)
        self.assertNotIn("Optional: gh secret set AWS_PLAN_ROLE_TO_ASSUME_ARN", script)
        self.assertIn("gh secret set SNYK_TOKEN", script)
        self.assertIn("sha-abc123", script)

    def test_control_catalog_and_explain_map_generated_behavior(self) -> None:
        cfg = cli.default_config()
        control = cli.control_by_id("image")
        self.assertIsNotNone(control)
        self.assertEqual(control.id, "immutable-image")

        lines = "\n".join(cli.explain_text("image", cfg))
        self.assertIn("CLI: lambda_image_uri", lines)
        self.assertIn("Terraform:", lines)
        self.assertIn("GitHub:", lines)
        self.assertIn("AWS:", lines)
        self.assertIn("Scanners:", lines)
        self.assertIn("LAMBDA_IMAGE_URI", lines)

    def test_controls_json_output_contains_catalog_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["controls", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        immutable = next(control for control in payload["controls"] if control["id"] == "immutable-image")
        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "control-catalog")
        self.assertIn("lambda_image_uri", " ".join(immutable["cli_options"]))
        self.assertTrue(immutable["terraform"])
        self.assertTrue(immutable["github"])
        self.assertTrue(immutable["aws"])

    def test_markdown_report_contains_checks_and_actions(self) -> None:
        cfg = cli.default_config()
        checks = [cli.Check("Lambda image URI", "WARN", "Required before production deploy.")]
        report = cli.markdown_report(cfg, checks)
        self.assertIn("# DevSecOps Pipeline Readiness Report", report)
        self.assertIn("## Score Breakdown", report)
        self.assertIn("## Checks", report)
        self.assertIn("Set `LAMBDA_IMAGE_URI`", report)

    def test_report_json_writes_attachable_audit_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.default_config()
            cfg["lambda_image_uri"] = "123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-abc123"
            cli.write_config(root, cfg)
            with patch.object(cli, "repo_root", return_value=root):
                with redirect_stdout(io.StringIO()):
                    result = cli.main(["report", "--format", "json"])

            report_path = root / cli.AUDIT_REPORT
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "audit-evidence")
        self.assertIn("controls", payload)
        self.assertIn("policy_presets", payload)
        self.assertIn("least_privilege", payload)
        self.assertIn(str(cli.AUDIT_REPORT), payload["attachable_evidence"])

    def test_readiness_breakdown_groups_scores_by_area(self) -> None:
        checks = [
            cli.Check("Local config", "OK", "ok"),
            cli.Check("Terraform validate", "OK", "ok"),
            cli.Check("GitHub variable PROJECT_NAME", "WARN", "missing"),
            cli.Check("AWS identity", "FAIL", "missing"),
            cli.Check("DAST", "INFO", "disabled", scored=False),
            cli.Check("Lambda image URI", "WARN", "missing"),
        ]
        rows = cli.readiness_breakdown_rows(checks, compact=True)
        by_area = {row[0]: row for row in rows}
        self.assertEqual(by_area["Local"][1], "100%")
        self.assertEqual(by_area["Terraform"][1], "100%")
        self.assertEqual(by_area["GitHub"][1], "50%")
        self.assertEqual(by_area["AWS"][1], "0%")
        self.assertEqual(by_area["Security"][1], "50%")
        self.assertEqual(by_area["Deployment"][2], "1")

    def test_dashboard_renders_compact_and_full_modes(self) -> None:
        cfg = cli.default_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cfg)
            compact = io.StringIO()
            with redirect_stdout(compact):
                cli.render_dashboard(root, mode="compact")
            compact_output = compact.getvalue()
            self.assertIn("Readiness", compact_output)
            self.assertIn("Run `devsecops status --deep`", compact_output)

            full = io.StringIO()
            dashboard_checks = [
                cli.Check("Local config", "OK", "ok"),
                cli.Check("GitHub variable PROJECT_NAME", "WARN", "missing"),
            ]
            with patch.object(cli, "collect_dashboard_checks", return_value=dashboard_checks):
                with redirect_stdout(full):
                    cli.render_dashboard(root, mode="full")
            full_output = full.getvalue()
            self.assertIn("Pipeline Controls", full_output)
            self.assertIn("GitHub", full_output)

    def test_tui_falls_back_to_compact_dashboard_without_rich(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "render_rich_tui", return_value=False), patch.object(
                cli,
                "render_dashboard",
            ) as render_dashboard:
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.cmd_tui(argparse.Namespace())

        self.assertEqual(result, 0)
        self.assertIn("Rich/Textual UI is optional", buffer.getvalue())
        render_dashboard.assert_called_once_with(root, mode="compact", clear=False)

    def test_parse_gh_items_from_json(self) -> None:
        payload = json.dumps(
            [
                {"name": "PROJECT_NAME", "value": "devsecops-pipeline"},
                {"name": "ENABLE_DAST", "value": "false"},
            ]
        )
        parsed = cli.parse_gh_items(payload, value_key="value")
        self.assertEqual(parsed["PROJECT_NAME"], "devsecops-pipeline")
        self.assertEqual(parsed["ENABLE_DAST"], "false")

    def test_github_variable_checks_find_mismatch(self) -> None:
        cfg = cli.default_config()
        cfg["lambda_image_uri"] = "repo.example/app:sha-abc123"
        variables = {
            "PROJECT_NAME": "wrong",
            "LAMBDA_IMAGE_URI": "repo.example/app:latest",
            "ENABLE_SNYK_SCAN": "false",
            "ENABLE_HTTP_VALIDATION": "false",
            "ENABLE_DAST": "false",
            "PROD_APPROVAL_ENVIRONMENT": "prod",
        }
        checks = cli.github_variable_checks(cfg, variables)
        self.assertTrue(any(check.name.endswith("PROJECT_NAME") and check.status == "WARN" for check in checks))
        self.assertTrue(any(check.name.endswith("LAMBDA_IMAGE_URI") and check.status == "WARN" for check in checks))

    def test_github_secret_checks_mark_required_and_optional(self) -> None:
        cfg = cli.default_config()
        checks = cli.github_secret_checks(cfg, {"AWS_REGION": "", "AWS_ROLE_TO_ASSUME_ARN": ""})
        self.assertTrue(any(check.name.endswith("AWS_PLAN_ROLE_TO_ASSUME_ARN") and check.status == "WARN" for check in checks))
        self.assertTrue(any(check.name.endswith("SNYK_TOKEN") and check.status == "INFO" for check in checks))

        cfg["use_separate_aws_plan_role"] = False
        cfg["enable_snyk_scan"] = True
        checks = cli.github_secret_checks(cfg, {"AWS_REGION": "", "AWS_ROLE_TO_ASSUME_ARN": ""})
        self.assertTrue(any(check.name.endswith("AWS_PLAN_ROLE_TO_ASSUME_ARN") and check.status == "WARN" for check in checks))
        self.assertTrue(any(check.name.endswith("SNYK_TOKEN") and check.status == "WARN" for check in checks))

    def test_github_setup_apply_shows_precheck_before_applying(self) -> None:
        def fake_gh_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
            if args[:2] == ["auth", "status"]:
                return subprocess.CompletedProcess(args, 0, stdout="logged in", stderr="")
            if args[:2] == ["repo", "view"]:
                return subprocess.CompletedProcess(args, 0, stdout="owner/repo\n", stderr="")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="unexpected")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=True), patch.object(
                cli,
                "gh_command",
                side_effect=fake_gh_command,
            ), patch.object(cli, "apply_github_setup", return_value=0) as apply_setup:
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(
                        [
                            "github",
                            "setup",
                            "--apply",
                            "--deploy-role-arn",
                            "arn:aws:iam::123456789012:role/deploy",
                            "--plan-role-arn",
                            "arn:aws:iam::123456789012:role/plan",
                        ]
                    )

        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("GitHub Setup Precheck", buffer.getvalue())
        self.assertIn("Deploy role ARN argument", buffer.getvalue())
        apply_setup.assert_called_once()

    def test_workflow_security_hardening_contract(self) -> None:
        deploy_workflow = (ROOT_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        ci_workflow = (ROOT_DIR / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        release_workflow = (ROOT_DIR / ".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", deploy_workflow)
        self.assertIn("Require separate AWS plan role", deploy_workflow)
        self.assertIn("role-to-assume: ${{ secrets.AWS_PLAN_ROLE_TO_ASSUME_ARN }}", deploy_workflow)
        self.assertNotIn("AWS_PLAN_ROLE_TO_ASSUME_ARN || secrets.AWS_ROLE_TO_ASSUME_ARN", deploy_workflow)
        self.assertIn("environment: ${{ vars.PROD_APPROVAL_ENVIRONMENT || 'prod' }}", deploy_workflow)
        self.assertIn("LAMBDA_IMAGE_URI must use an immutable tag or digest", deploy_workflow)
        self.assertIn("Smoke test Lambda health endpoint", deploy_workflow)
        self.assertIn("if: env.ENABLE_HTTP_VALIDATION == 'true'", deploy_workflow)
        self.assertIn("zaproxy/action-baseline", deploy_workflow)
        self.assertIn("id-token: write", deploy_workflow)
        self.assertIn("pull-requests: write", deploy_workflow)
        self.assertIn("API_AUTHORIZATION_TYPE: ${{ vars.API_AUTHORIZATION_TYPE || 'AWS_IAM' }}", deploy_workflow)
        self.assertIn("--aws-sigv4", deploy_workflow)
        self.assertIn("env.API_AUTHORIZATION_TYPE == 'NONE'", deploy_workflow)
        self.assertIn("cp install.sh dist/install.sh", release_workflow)
        self.assertIn("sha256sum install.sh *.whl *.tar.gz > SHA256SUMS", release_workflow)
        self.assertIn("sha256sum -c SHA256SUMS", release_workflow)
        self.assertIn("dist/install.sh", release_workflow)
        self.assertIn("dist/SHA256SUMS", release_workflow)
        self.assertNotIn("@v4", deploy_workflow)
        self.assertNotIn("@v5", ci_workflow)
        self.assertIn("build==1.5.0", release_workflow)

        for workflow in [deploy_workflow, ci_workflow, release_workflow]:
            self.assertIn("persist-credentials: false", workflow)

    def test_terraform_security_hardening_contract(self) -> None:
        variables_tf = (ROOT_DIR / "terraform/variables.tf").read_text(encoding="utf-8")
        module_variables_tf = (ROOT_DIR / "terraform/modules/lambda/variables.tf").read_text(encoding="utf-8")
        api_gateway_variables_tf = (ROOT_DIR / "terraform/modules/api-gateway/variables.tf").read_text(encoding="utf-8")
        api_gateway_tf = (ROOT_DIR / "terraform/modules/api-gateway/main.tf").read_text(encoding="utf-8")
        lambda_tf = (ROOT_DIR / "terraform/modules/lambda/main.tf").read_text(encoding="utf-8")
        storage_tf = (ROOT_DIR / "terraform/modules/storage/main.tf").read_text(encoding="utf-8")
        kms_tf = (ROOT_DIR / "terraform/modules/kms/main.tf").read_text(encoding="utf-8")
        bootstrap_tf = (ROOT_DIR / "terraform/bootstrap/main.tf").read_text(encoding="utf-8")

        self.assertIn("lambda_image_uri must be empty for validation-only runs or an immutable ECR image URI", variables_tf)
        self.assertIn("api_authorization_type must be AWS_IAM or NONE", variables_tf)
        self.assertIn("environment_config.prod.cors_allowed_origins must not contain wildcard", variables_tf)
        self.assertIn("environment_config values must stay within Lambda/API limits", variables_tf)
        self.assertIn("cors_allowed_origins must contain at least one non-empty origin", api_gateway_variables_tf)
        self.assertIn("authorization_type must be AWS_IAM or NONE", api_gateway_variables_tf)
        self.assertIn("authorization_type = var.authorization_type", api_gateway_tf)
        self.assertIn("lambda_image_uri must be empty for validation-only runs or an immutable ECR image URI", module_variables_tf)
        self.assertIn("precondition", lambda_tf)
        self.assertIn("latest|bootstrap", lambda_tf)
        self.assertNotIn(":bootstrap", lambda_tf)
        self.assertIn("kms_key_arn", lambda_tf)
        self.assertIn("reserved_concurrent_executions", lambda_tf)
        self.assertIn("DenyInsecureTransport", storage_tf)
        self.assertIn("aws:SecureTransport", storage_tf)
        self.assertIn("kms:ViaService", kms_tf)
        self.assertIn("kms:EncryptionContext:aws:s3:arn", kms_tf)
        self.assertIn("aws_kms_key\" \"terraform_state", bootstrap_tf)
        self.assertIn("aws_s3_bucket_logging\" \"terraform_state", bootstrap_tf)
        self.assertIn("aws_s3_bucket_lifecycle_configuration", bootstrap_tf)

    def test_branch_protection_checks_required_statuses(self) -> None:
        protection = {
            "required_pull_request_reviews": {"required_approving_review_count": 1},
            "required_status_checks": {
                "contexts": ["Security and Terraform Validate"],
                "checks": [{"context": "Terraform Plan"}],
            },
        }
        checks = cli.branch_protection_checks("main", True, protection)
        self.assertTrue(any(check.name == "Branch `main` protection" and check.status == "OK" for check in checks))
        self.assertTrue(any(check.name == "Required check `Terraform Plan`" and check.status == "OK" for check in checks))

    def test_branch_protection_checks_missing_required_status(self) -> None:
        protection = {
            "required_pull_request_reviews": None,
            "required_status_checks": {"contexts": ["Security and Terraform Validate"]},
        }
        checks = cli.branch_protection_checks("main", True, protection)
        self.assertTrue(any(check.name == "Pull request requirement" and check.status == "WARN" for check in checks))
        self.assertTrue(any(check.name == "Required check `Terraform Plan`" and check.status == "WARN" for check in checks))

    def test_actions_run_rows_and_failed_jobs(self) -> None:
        runs = cli.parse_gh_runs(
            json.dumps(
                [
                    {
                        "databaseId": 10,
                        "workflowName": "Deploy",
                        "headBranch": "main",
                        "status": "completed",
                        "conclusion": "failure",
                        "createdAt": "2026-06-05T00:00:00Z",
                    }
                ]
            )
        )
        self.assertEqual(cli.actions_run_rows(runs)[0][0], "Deploy")

        failed = cli.failed_job_rows(
            "Deploy",
            json.dumps(
                {
                    "jobs": [
                        {"name": "Terraform Plan", "status": "completed", "conclusion": "success"},
                        {"name": "Apply", "status": "completed", "conclusion": "failure"},
                    ]
                }
            ),
        )
        self.assertEqual(failed, [["Deploy", "Apply", "completed", "failure"]])

        failed_steps = cli.failed_step_rows(
            "Deploy",
            json.dumps(
                {
                    "jobs": [
                        {
                            "name": "Manual Apply and Deploy Production",
                            "status": "completed",
                            "conclusion": "failure",
                            "steps": [
                                {"name": "Terraform apply workload with configured Lambda image", "conclusion": "failure"},
                            ],
                        }
                    ]
                }
            ),
        )
        self.assertEqual(failed_steps[0][2], "Terraform apply workload with configured Lambda image")
        self.assertEqual(failed_steps[0][4], cli.RUNBOOK_FAILED_APPLY)

    def test_github_actions_status_json_includes_failed_steps_and_next_actions(self) -> None:
        def fake_gh_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
            if args[:2] == ["run", "list"]:
                return subprocess.CompletedProcess(
                    ["gh", *args],
                    0,
                    stdout=json.dumps(
                        [
                            {
                                "databaseId": 10,
                                "workflowName": "Secure Serverless DevSecOps Pipeline",
                                "headBranch": "main",
                                "status": "completed",
                                "conclusion": "failure",
                                "createdAt": "2026-06-05T00:00:00Z",
                                "url": "https://github.example/runs/10",
                            }
                        ]
                    ),
                    stderr="",
                )
            if args[:3] == ["run", "view", "10"]:
                return subprocess.CompletedProcess(
                    ["gh", *args],
                    0,
                    stdout=json.dumps(
                        {
                            "jobs": [
                                {
                                    "name": "Manual Apply and Deploy Production",
                                    "status": "completed",
                                    "conclusion": "failure",
                                    "steps": [
                                        {"name": "Terraform apply workload with configured Lambda image", "conclusion": "failure"}
                                    ],
                                }
                            ]
                        }
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(["gh", *args], 1, stdout="", stderr="unexpected")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=True), patch.object(
                cli,
                "gh_command",
                side_effect=fake_gh_command,
            ):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["github", "status", "--format", "json", "--strict"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertEqual(payload["failed_steps"][0][4], cli.RUNBOOK_FAILED_APPLY)
        self.assertIn("devsecops deploy logs --run-id 10 --failed", payload["next_actions"][0])

    def test_health_command_validates_explicit_url_without_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cli.default_config())
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "fetch_health_url", return_value=(200, "ok")):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["health", "--url", "https://api.example/health", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "health")
        self.assertEqual(payload["checks"][1]["name"], "Health response")
        self.assertEqual(payload["checks"][1]["status"], "OK")

    def test_health_fetch_rejects_non_http_schemes(self) -> None:
        status, detail = cli.fetch_health_url("file:///etc/passwd")
        self.assertIsNone(status)
        self.assertIn("http or https", detail)

    def test_health_fetch_requires_sigv4_credentials_when_enabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            status, detail = cli.fetch_health_url("https://api.example/health", aws_sigv4=True)
        self.assertIsNone(status)
        self.assertIn("AWS SigV4 health checks require", detail)

    def test_parse_ecr_image_uri_tag_and_digest(self) -> None:
        tagged = cli.parse_ecr_image_uri("123456789012.dkr.ecr.us-east-1.amazonaws.com/app/service:sha-abc123")
        self.assertIsNotNone(tagged)
        self.assertEqual(tagged.region, "us-east-1")
        self.assertEqual(tagged.repository, "app/service")
        self.assertEqual(tagged.tag, "sha-abc123")

        digest = "sha256:" + "a" * 64
        digested = cli.parse_ecr_image_uri(f"123456789012.dkr.ecr.eu-central-1.amazonaws.com/app@{digest}")
        self.assertIsNotNone(digested)
        self.assertEqual(digested.digest, digest)
        self.assertIsNone(cli.parse_ecr_image_uri("repo.example/app:sha-abc123"))

    def test_collect_aws_checks_warns_when_aws_cli_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cli, "command_exists", return_value=False):
                checks = cli.collect_aws_checks(Path(tmpdir), cli.default_config(), env_name="prod")

        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].name, "AWS CLI")
        self.assertEqual(checks[0].status, "WARN")
        self.assertIn("skipped AWS identity", checks[0].detail)

    def test_collect_aws_checks_warns_when_credentials_are_missing(self) -> None:
        def fake_run_command(command: list[str], root: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 255, stdout="", stderr="Unable to locate credentials")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cli, "command_exists", side_effect=lambda name: name == "aws"), patch.object(
                cli,
                "run_command",
                side_effect=fake_run_command,
            ):
                checks = cli.collect_aws_checks(Path(tmpdir), cli.default_config(), env_name="prod")

        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["AWS CLI"].status, "OK")
        self.assertEqual(by_name["AWS identity"].status, "WARN")
        self.assertIn("Unable to locate credentials", by_name["AWS identity"].detail)
        self.assertIn("without valid AWS credentials", by_name["State bucket"].detail)

    def test_collect_aws_checks_successful_resources(self) -> None:
        cfg = cli.default_config()
        cfg["backend"]["bucket"] = "state-bucket"
        cfg["lambda_image_uri"] = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123"

        def completed(command: list[str], stdout: str = "{}") -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        def fake_run_command(command: list[str], root: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
            command_text = " ".join(command)
            if "sts get-caller-identity" in command_text:
                return completed(command, json.dumps({"Arn": "arn:aws:iam::123456789012:user/test", "Account": "123456789012"}))
            if "s3api head-bucket" in command_text:
                return completed(command)
            if "dynamodb describe-table" in command_text:
                return completed(command, json.dumps({"Table": {"TableStatus": "ACTIVE"}}))
            if "ecr describe-repositories" in command_text:
                return completed(command, json.dumps({"repositories": [{"repositoryName": "devsecops-pipeline-prod-lambda-repo"}]}))
            if "iam get-role" in command_text:
                return completed(command, json.dumps({"Role": {"Arn": "arn:aws:iam::123456789012:role/devsecops-pipeline-prod-lambda-exec-role"}}))
            if "lambda get-function-configuration" in command_text:
                return completed(command, json.dumps({"FunctionName": "devsecops-pipeline-prod-lambda", "State": "Active"}))
            if "apigatewayv2 get-apis" in command_text:
                return completed(
                    command,
                    json.dumps({"Items": [{"Name": "devsecops-pipeline-prod-http-api", "ApiEndpoint": "https://api.example"}]}),
                )
            if "logs describe-log-groups" in command_text:
                return completed(
                    command,
                    json.dumps({"logGroups": [{"logGroupName": "/aws/lambda/devsecops-pipeline-prod-lambda", "retentionInDays": 365}]}),
                )
            if "ecr describe-images" in command_text:
                return completed(command, json.dumps({"imageDetails": [{"imageTags": ["sha-abc123"]}]}))
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="unexpected command")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cli, "command_exists", return_value=True), patch.object(cli, "run_command", side_effect=fake_run_command):
                checks = cli.collect_aws_checks(Path(tmpdir), cfg, env_name="prod")

        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["AWS identity"].status, "OK")
        self.assertEqual(by_name["State bucket"].status, "OK")
        self.assertEqual(by_name["Lock table"].status, "OK")
        self.assertEqual(by_name["ECR repository"].status, "OK")
        self.assertEqual(by_name["Lambda execution role"].status, "OK")
        self.assertEqual(by_name["Lambda function"].status, "OK")
        self.assertEqual(by_name["API Gateway"].status, "OK")
        self.assertEqual(by_name["CloudWatch log group"].status, "OK")
        self.assertEqual(by_name["Configured ECR image"].status, "OK")

    def test_aws_outputs_reports_deployed_lambda_api_and_logs(self) -> None:
        cfg = cli.default_config()

        def completed(command: list[str], stdout: str = "{}") -> tuple[object, subprocess.CompletedProcess[str]]:
            return json.loads(stdout), subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        def fake_aws_json(root: Path, args: list[str], timeout: int = 30) -> tuple[object, subprocess.CompletedProcess[str]]:
            command_text = " ".join(args)
            if "sts get-caller-identity" in command_text:
                return completed(args, json.dumps({"Arn": "arn:aws:iam::123456789012:user/test"}))
            if "lambda get-function" in command_text:
                return completed(
                    args,
                    json.dumps(
                        {
                            "Configuration": {"State": "Active", "LastUpdateStatus": "Successful"},
                            "Code": {"ImageUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-abc123"},
                        }
                    ),
                )
            if "apigatewayv2 get-apis" in command_text:
                return completed(
                    args,
                    json.dumps({"Items": [{"Name": "devsecops-pipeline-prod-http-api", "ApiEndpoint": "https://api.example"}]}),
                )
            if "logs describe-log-groups" in command_text:
                return completed(
                    args,
                    json.dumps({"logGroups": [{"logGroupName": "/aws/lambda/devsecops-pipeline-prod-lambda", "retentionInDays": 365}]}),
                )
            return {}, subprocess.CompletedProcess(args, 1, stdout="", stderr="unexpected")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cfg)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "command_exists", return_value=True), patch.object(
                cli,
                "aws_json",
                side_effect=fake_aws_json,
            ):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.main(["aws", "outputs", "--environment", "prod", "--format", "json", "--strict"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(payload["kind"], "aws-outputs")
        self.assertEqual(payload["outputs"]["lambda_state"], "Active")
        self.assertEqual(payload["outputs"]["api_gateway_health_url"], "https://api.example/health")

    def test_collect_checks_deep_includes_aws_resource_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            aws_checks = [cli.Check("Lambda execution role", "OK", "deployed")]
            with patch.object(cli, "command_exists", return_value=False), patch.object(
                cli,
                "collect_aws_checks",
                return_value=aws_checks,
            ) as collect_aws:
                checks = cli.collect_checks(root, cli.default_config(), deep=True)

        self.assertIn(aws_checks[0], checks)
        collect_aws.assert_called_once()

    def test_collect_checks_deep_skips_terraform_cascade_when_project_files_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "command_exists", return_value=True), patch.object(cli, "collect_aws_checks", return_value=[]):
                checks = cli.collect_checks(root, cli.default_config(), deep=True)

        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["Project files"].status, "FAIL")
        self.assertNotIn("Terraform validate", by_name)
        self.assertNotIn("Bootstrap validate", by_name)
        self.assertEqual(by_name["Terraform deep checks"].status, "INFO")

    def test_aws_doctor_strict_fails_on_scored_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "load_config", return_value=cli.default_config()), patch.object(
                cli,
                "collect_aws_checks",
                return_value=[cli.Check("AWS CLI", "WARN", "`aws` not found on PATH.")],
            ):
                with redirect_stdout(io.StringIO()):
                    result = cli.cmd_aws_doctor(argparse.Namespace(environment="prod", strict=True))

        self.assertEqual(result, cli.EXIT_MISSING_EXTERNAL_TOOL)

    def test_snapshots_are_listed_newest_first_and_selectable_by_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(
                cli,
                "snapshot_id",
                side_effect=["20260101T000000Z-old", "20260102T000000Z-new"],
            ):
                cli.create_snapshot(root, "old", "Older snapshot")
                cli.create_snapshot(root, "new", "Newer snapshot")

            snapshots = cli.list_snapshots(root)
            self.assertEqual(
                [snapshot["id"] for snapshot in snapshots],
                ["20260102T000000Z-new", "20260101T000000Z-old"],
            )
            self.assertEqual(cli.resolve_snapshot_selection(root, "1")["id"], "20260102T000000Z-new")
            self.assertEqual(
                cli.resolve_snapshot_selection(root, "20260101T000000Z-old")["operation"],
                "old",
            )

    def test_snapshot_changes_and_restore_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.default_config()
            cfg["project_name"] = "before-app"
            cli.write_config(root, cfg)

            snapshot_path = cli.create_snapshot(root, "set", "Before project rename")
            snapshot = cli.read_snapshot_manifest(snapshot_path)
            snapshot["_path"] = str(snapshot_path)

            cfg["project_name"] = "after-app"
            cli.write_config(root, cfg)

            changes = cli.snapshot_changes(root, snapshot)
            self.assertTrue(any(change["path"] == cli.CONFIG_FILE for change in changes))

            cli.restore_snapshot(root, snapshot)
            restored = cli.load_config(root)
            self.assertEqual(restored["project_name"], "before-app")

    def test_rollback_output_distinguishes_local_restore_from_cloud_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = cli.default_config()
            cfg["project_name"] = "before-app"
            cli.write_config(root, cfg)

            snapshot_path = cli.create_snapshot(root, "set", "Before project rename")
            snapshot_id = snapshot_path.name

            cfg["project_name"] = "after-app"
            cli.write_config(root, cfg)

            with patch.object(cli, "repo_root", return_value=root):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = cli.cmd_rollback(argparse.Namespace(to=snapshot_id, last=False, dry_run=True, yes=False))

        output = buffer.getvalue()
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("Local snapshot restore only", output)
        self.assertIn("It does not change AWS Lambda", output)

    def test_snapshot_restore_reverts_overwritten_cli_owned_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, golden_config())
            with redirect_stdout(io.StringIO()):
                cli.run_render(root, snapshot=False)
            original_tfvars = (root / cli.GENERATED_TFVARS).read_text(encoding="utf-8")

            snapshot_path = cli.create_snapshot(root, "render", "Before generated overwrite")
            snapshot = cli.read_snapshot_manifest(snapshot_path)
            snapshot["_path"] = str(snapshot_path)

            (root / cli.GENERATED_TFVARS).write_text('project_name = "manually-overwritten"\n', encoding="utf-8")
            cli.restore_snapshot(root, snapshot)

            self.assertEqual((root / cli.GENERATED_TFVARS).read_text(encoding="utf-8"), original_tfvars)

    def test_snapshot_restore_removes_file_created_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_path = cli.create_snapshot(root, "render", "Before generated files")
            snapshot = cli.read_snapshot_manifest(snapshot_path)
            snapshot["_path"] = str(snapshot_path)

            generated = root / cli.GENERATED_TFVARS
            generated.parent.mkdir(parents=True)
            generated.write_text('project_name = "after-app"\n', encoding="utf-8")

            changes = cli.snapshot_changes(root, snapshot)
            self.assertTrue(any(change["path"] == str(cli.GENERATED_TFVARS) for change in changes))

            cli.restore_snapshot(root, snapshot)
            self.assertFalse(generated.exists())

    def test_snapshot_restore_does_not_overwrite_user_owned_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unmanaged = root / "README.md"
            unmanaged.write_text("user version before snapshot\n", encoding="utf-8")
            snapshot_path = cli.create_snapshot(root, "render", "Before generated files")
            snapshot = cli.read_snapshot_manifest(snapshot_path)
            snapshot["_path"] = str(snapshot_path)

            unmanaged.write_text("user version after snapshot\n", encoding="utf-8")
            cli.restore_snapshot(root, snapshot)

            self.assertEqual(unmanaged.read_text(encoding="utf-8"), "user version after snapshot\n")

    def test_snapshot_restore_ignores_paths_outside_cli_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_path = cli.create_snapshot(root, "render", "Before generated files")
            snapshot = cli.read_snapshot_manifest(snapshot_path)
            snapshot["_path"] = str(snapshot_path)
            snapshot["files"].append({"path": "README.md", "present": False})

            unmanaged = root / "README.md"
            unmanaged.write_text("unmanaged file\n", encoding="utf-8")

            cli.restore_snapshot(root, snapshot)
            self.assertTrue(unmanaged.exists())

    def test_init_cancel_from_menu_mode_does_not_write_config_or_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            buffer = io.StringIO()
            with patch("builtins.input", return_value="0"), redirect_stdout(buffer):
                result = cli.run_init(root, force=True, allow_cancel=True)

            self.assertEqual(result, 0)
            self.assertFalse((root / cli.CONFIG_FILE).exists())
            self.assertEqual(cli.list_snapshots(root), [])
            self.assertIn("Configuration cancelled", buffer.getvalue())

    def test_main_menu_has_only_six_product_sections_and_exit(self) -> None:
        cfg = cli.default_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cli.write_config(root, cfg)
            status = cli.menu_status(root, cfg)
            self.assertTrue(any("Readiness:" in line for line in status))

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli.print_main_menu(root)
            output = buffer.getvalue()
            readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        self.assertTrue(any("[i] details" in line for line in status))
        expected_items = [
            "[1] Continue setup",
            "[2] Status",
            "[3] Deploy",
            "[4] Diagnose problems",
            "[5] Configuration",
            "[6] Advanced",
            "[0] Exit",
        ]
        self.assertEqual(
            cli.MAIN_MENU_ITEMS,
            [
                ("1", "Continue setup"),
                ("2", "Status"),
                ("3", "Deploy"),
                ("4", "Diagnose problems"),
                ("5", "Configuration"),
                ("6", "Advanced"),
                ("0", "Exit"),
            ],
        )
        self.assertEqual([line for line in output.splitlines() if line.startswith("[")], expected_items)
        for item in expected_items:
            self.assertIn(item, readme)
        for old_item in ["[7] Composer", "[12] Terraform plan", "[18] Snapshots / rollback"]:
            self.assertNotIn(old_item, output)

    def test_advanced_menu_keeps_technical_capabilities_nested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            buffer = io.StringIO()
            with patch("builtins.input", return_value="0"), redirect_stdout(buffer):
                cli.menu_advanced_hub(root)

        output = buffer.getvalue()
        for item in [
            "[1] Deployment files",
            "[2] Terraform",
            "[3] GitHub connection",
            "[4] Reports and release evidence",
            "[5] Security and reference",
            "[6] Snapshots / local rollback",
        ]:
            self.assertIn(item, output)

    def test_advanced_menu_routes_every_nested_capability(self) -> None:
        route_patches = {
            "1": "menu_generated_files_hub",
            "2": "menu_terraform_hub",
            "3": "menu_github_hub",
            "4": "menu_reports_hub",
            "5": "menu_reference_hub",
            "6": "menu_rollback_section",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for choice, handler_name in route_patches.items():
                with self.subTest(choice=choice), patch.object(cli, handler_name) as handler, patch(
                    "builtins.input", return_value=choice
                ), redirect_stdout(io.StringIO()):
                    cli.menu_advanced_hub(root)
                    handler.assert_called_once()

    def test_deploy_menu_explains_side_effects_without_starting_workflow(self) -> None:
        buffer = io.StringIO()
        with patch("builtins.input", side_effect=["2", ""]), redirect_stdout(buffer):
            cli.menu_deploy_hub()

        output = buffer.getvalue()
        self.assertIn("Opening this section does not change GitHub or AWS", output)
        self.assertIn("does not execute it automatically", output)
        self.assertIn(cli.PRODUCTION_DEPLOY_COMMAND, output)

    def test_main_menu_routes_each_primary_choice(self) -> None:
        route_patches = {
            "1": "menu_continue_setup",
            "3": "menu_deploy_hub",
            "4": "menu_doctor_hub",
            "5": "menu_config_hub",
            "6": "menu_advanced_hub",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for choice, handler_name in route_patches.items():
                with self.subTest(choice=choice), patch.object(cli, "repo_root", return_value=root), patch.object(
                    cli, "print_main_menu"
                ), patch.object(cli, "clear_screen"), patch.object(cli, handler_name) as handler, patch(
                    "builtins.input", side_effect=[choice, "0"]
                ):
                    self.assertEqual(cli.cmd_menu(argparse.Namespace()), cli.EXIT_OK)
                    handler.assert_called_once()

            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "print_main_menu"
            ), patch.object(cli, "clear_screen"), patch.object(cli, "open_menu_section") as section, patch(
                "builtins.input", side_effect=["2", "0"]
            ):
                self.assertEqual(cli.cmd_menu(argparse.Namespace()), cli.EXIT_OK)
                self.assertEqual(section.call_args.args[0], "Status")

    def test_continue_setup_routes_from_the_shared_next_action(self) -> None:
        cases = [
            ("missing_project_files", "cd /project", "blocked"),
            ("missing_config", "devsecops setup --preset balanced --yes", "setup"),
            ("missing_config", "devsecops config new --preset balanced", "setup"),
            ("missing_config", "devsecops config validate", "configuration"),
            ("missing_image", "devsecops config set lambda_image_uri value", "configuration"),
            ("missing_backend", "devsecops config set backend.bucket value", "configuration"),
            ("missing_github_setup", "devsecops generate", "deployment_files"),
            ("missing_github_setup", "devsecops render", "deployment_files"),
            ("missing_github_setup", "devsecops github setup --apply", "github"),
            ("missing_aws_evidence", "aws sts get-caller-identity", "diagnostics"),
            ("ready_for_deploy", cli.PRODUCTION_DEPLOY_COMMAND, "deploy"),
            ("ready_for_release_evidence", "devsecops evidence collect --rc", "reports"),
        ]
        for action_id, command, expected in cases:
            with self.subTest(action_id=action_id, command=command):
                self.assertEqual(
                    cli.continue_setup_destination({"id": action_id, "command": command}),
                    expected,
                )

    def test_pause_for_menu_clears_screen_before_returning_to_main_menu(self) -> None:
        with patch("builtins.input", return_value=""), patch.object(cli, "clear_screen") as clear_screen:
            cli.pause_for_menu()

        clear_screen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
