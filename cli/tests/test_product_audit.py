"""Regression coverage for the product audit, without cloud mutations."""

import argparse
import copy
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import aws, config, context, doctor, github, main as cli, render, workflow
from devsecops_cli.models import Check, ConfigValidationError
from devsecops_cli.readiness import PRODUCTION_EVIDENCE_CHECKS

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/customer-prod-lambda-repo:sha-abc123"


def customer_config():
    cfg = config.preset_config("enterprise")
    cfg.update(project_name="customer", aws_region="eu-central-1", lambda_image_uri=IMAGE)
    cfg["backend"].update(bucket="customer-state-bucket", region="eu-central-1", lock_table="customer-locks")
    cfg["environments"]["prod"].update(lambda_memory_size=4096, lambda_timeout=300,
                                    log_retention_days=731, cors_allowed_origins=["https://customer.example"])
    return cfg


def project(root, cfg=None):
    cfg = cfg or customer_config()
    config.write_config(root, cfg)
    for relative in cli.REQUIRED_PROJECT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n")
    for path, value in render.render_outputs(root, cfg).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return cfg


def invoke(root, args):
    output = io.StringIO()
    with patch.object(cli, "repo_root", return_value=root), redirect_stdout(output):
        result = cli.main(args)
    return result, output.getvalue()


class PipelineTransportTests(unittest.TestCase):
    def test_customer_settings_reach_a_clean_runner_without_source_config(self):
        cfg = customer_config()
        variables = github.github_expected_variables(cfg)
        with tempfile.TemporaryDirectory() as directory:
            runner = Path(directory)
            exported = workflow.write_workflow_inputs(runner, variables[config.PIPELINE_CONFIG_VARIABLE])
            tfvars = (runner / cli.GENERATED_TFVARS).read_text()
            backend = (runner / cli.DIST_DIR / "backend.hcl").read_text()
            self.assertFalse(config.config_path(runner).exists())
        self.assertEqual(exported, cfg)
        for value in ['"eu-central-1"', "4096", "300", "731", '"https://customer.example"']:
            self.assertIn(value, tfvars)
        self.assertIn('"customer-state-bucket"', backend)
        self.assertIn('"customer-locks"', backend)

    def test_only_schema_owned_settings_are_exported(self):
        cfg = customer_config()
        cfg["aws_secret_access_key"] = "DO-NOT-EXPORT"
        cfg["backend"]["token"] = "DO-NOT-EXPORT"
        payload = config.pipeline_config_json(cfg)
        self.assertNotIn("DO-NOT-EXPORT", payload)
        self.assertNotIn("aws_secret_access_key", payload)
        self.assertEqual(workflow.decode_pipeline_config(payload), customer_config())

    def test_missing_invalid_or_unknown_runner_config_writes_nothing(self):
        invalid = customer_config()
        invalid["token"] = "not-a-setting"
        for payload in ["", "{", "[]", json.dumps(invalid)]:
            with self.subTest(payload=payload[:30]), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ConfigValidationError):
                    workflow.write_workflow_inputs(Path(directory), payload)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_runner_exports_matching_region_flags_and_exact_dispatch_image(self):
        cfg = customer_config()
        target = IMAGE.replace("sha-abc123", "sha-reviewed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = os.environ | {"PYTHONPATH": str(ROOT / "cli"),
                                       config.PIPELINE_CONFIG_VARIABLE: config.pipeline_config_json(cfg),
                                       "GITHUB_ENV": str(root / "github-env"), "DISPATCH_IMAGE_URI": target,
                                       "DEPLOY_MODE": "deploy"}
            result = subprocess.run([sys.executable, "-m", "devsecops_cli.workflow"], cwd=root,
                                    env=environment, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            env_values = dict(line.split("=", 1) for line in (root / "github-env").read_text().splitlines())
        self.assertEqual(env_values["AWS_REGION"], cfg["aws_region"])
        self.assertEqual(env_values["ENABLE_HTTP_VALIDATION"], "true")
        self.assertEqual(env_values["LAMBDA_IMAGE_URI"], target)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env_values)

    def test_workflow_materializes_settings_before_cloud_access(self):
        source = (ROOT / ".github/workflows/deploy.yml").read_text()
        for name in ["terraform-plan", "deploy-main"]:
            section = source.split(f"  {name}:", 1)[1].split("\n  deploy-main:")[0]
            self.assertLess(section.index("python3 -m devsecops_cli.workflow"), section.index("- name: Configure AWS credentials"))
            self.assertIn("-backend-config=../dist/devsecops/backend.hcl", section)
            self.assertIn("aws-region: ${{ env.AWS_REGION }}", section)
        self.assertIn("environment: prod", source)

    def test_remote_config_drift_is_detected_without_dumping_payload(self):
        cfg = customer_config()
        remote = github.github_expected_variables(cfg)
        cfg["environments"]["prod"]["lambda_memory_size"] = 8192
        check = next(c for c in github.github_variable_checks(cfg, remote) if c.name.endswith(config.PIPELINE_CONFIG_VARIABLE))
        self.assertEqual(check.status, "WARN")
        self.assertIn("synchronize", check.detail)
        self.assertNotIn("customer-state-bucket", check.detail)

    def test_exact_image_dispatch_tolerates_only_image_drift_in_pipeline_payload(self):
        cfg = customer_config()
        remote = github.github_expected_variables(cfg)
        cfg["lambda_image_uri"] = IMAGE.replace("sha-abc123", "sha-next")
        checks = cli.exact_image_dispatch_github_checks(github.github_variable_checks(cfg, remote))
        payload = next(c for c in checks if c.name.endswith(config.PIPELINE_CONFIG_VARIABLE))
        self.assertFalse(payload.scored)
        cfg["environments"]["prod"]["lambda_memory_size"] = 8192
        checks = cli.exact_image_dispatch_github_checks(github.github_variable_checks(cfg, remote))
        payload = next(c for c in checks if c.name.endswith(config.PIPELINE_CONFIG_VARIABLE))
        self.assertTrue(payload.scored)
        self.assertEqual(payload.status, "WARN")


class ReadinessRegressionTests(unittest.TestCase):
    def test_local_status_cannot_claim_production_ready_without_github(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            with patch.object(cli, "command_exists", side_effect=lambda name: name != "gh"), patch.object(
                cli, "run_command", return_value=subprocess.CompletedProcess([], 0, "main\n", "")
            ), patch.object(cli, "collect_github_checks") as github_calls, patch.object(cli, "collect_aws_checks") as aws_calls:
                result, text = invoke(root, ["status", "--strict", "--format", "json"])
            payload = json.loads(text)
            self.assertNotEqual(result, 0)
            self.assertLess(payload["score"], 100)
            self.assertTrue(payload["next_action"]["blocked"])
            self.assertNotEqual(next(g for g in payload["gates"] if g["gate"] == "Production readiness")["status"], "OK")
            github_calls.assert_not_called()
            aws_calls.assert_not_called()

    def test_human_status_collects_once_and_exits_using_displayed_observations(self):
        observations = [Check(name, "OK", "Verified") for name in sorted(PRODUCTION_EVIDENCE_CHECKS)]
        observations.append(Check("Terraform validate", "FAIL", "Invalid configuration"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            with patch.object(cli, "command_exists", return_value=True), patch.object(
                cli, "collect_dashboard_checks", return_value=observations
            ) as collect, patch.object(cli, "collect_github_checks") as gh, patch.object(cli, "collect_aws_checks") as aws_check:
                result, text = invoke(root, ["status", "--deep", "--strict"])
            collect.assert_called_once()
            gh.assert_not_called()
            aws_check.assert_not_called()
            self.assertNotEqual(result, 0)
            self.assertIn("Invalid configuration", text)
            self.assertNotIn("Production readiness is complete", text)

    def test_fully_observed_healthy_production_can_pass_strict(self):
        observations = [Check(name, "OK", "Verified") for name in sorted(PRODUCTION_EVIDENCE_CHECKS)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            with patch.object(cli, "command_exists", return_value=True), patch.object(cli, "collect_dashboard_checks", return_value=observations):
                result, text = invoke(root, ["status", "--deep", "--strict", "--format", "json"])
        self.assertEqual(result, 0, text)
        self.assertEqual(json.loads(text)["score"], 100)

    def test_failed_pending_and_unknown_lambda_are_not_ok(self):
        for state, update, expected in [("Failed", "Failed", "FAIL"), ("Active", "Failed", "FAIL"),
                                        ("Pending", "InProgress", "WARN"), (None, None, "WARN"),
                                        ("Active", "Successful", "OK")]:
            with self.subTest(state=state, update=update):
                self.assertEqual(aws.lambda_readiness_status({"State": state, "LastUpdateStatus": update}), expected)

    def test_provider_collectors_surface_failed_lambda(self):
        def response(root, args, **kwargs):
            payload = {"State": "Failed", "LastUpdateStatus": "Failed"}
            if args[:2] == ["lambda", "get-function"]:
                payload = {"Configuration": payload, "Code": {"ImageUri": IMAGE}}
            return payload, subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        kwargs = dict(command_exists_fn=lambda name: True, aws_json_fn=response)
        checks = aws.collect_aws_checks(ROOT, customer_config(), **kwargs,
                                        aws_command_fn=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""))
        _, output_checks = aws.inspect_aws_outputs(ROOT, customer_config(), **kwargs)
        for observed in [checks, output_checks]:
            self.assertEqual(next(c for c in observed if c.name == "Lambda function").status, "FAIL")

    def test_missing_backend_recommends_bootstrap_before_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = project(root)
            action = context.next_action(root, cfg, command_exists_fn=lambda name: True,
                github_checks_fn=lambda *a, **k: [Check("GitHub auth", "OK", "Verified")],
                aws_checks_fn=lambda *a, **k: [Check("AWS identity", "OK", "Verified"), Check("State bucket", "WARN", "Not found")])
        self.assertEqual(action["command"], "devsecops terraform bootstrap")

    def test_config_change_invalidates_local_and_deployment_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = project(root)
            cfg["environments"]["prod"]["lambda_memory_size"] = 8192
            config.write_config(root, cfg)
            with patch.object(cli, "command_exists", return_value=False), patch.object(cli, "collect_github_checks", return_value=[]), patch.object(cli, "collect_branch_checks", return_value=[]):
                checks = cli.collect_checks(root, cfg)
                deploy_checks = cli.production_deployment_preflight_checks(root, cfg, [], None, "", None)
                action = cli.next_action(root, cfg)
            self.assertNotEqual(next(c for c in checks if c.name == "Rendered tfvars").status, "OK")
            self.assertEqual(next(c for c in deploy_checks if c.name == "Generated deployment helpers").status, "FAIL")
            self.assertEqual(action["command"], "devsecops generate")

    def test_actual_github_environment_reviewers_are_required(self):
        for payload in [{}, {"protection_rules": []}, {"protection_rules": [{"type": "wait_timer"}]},
                        {"protection_rules": [{"type": "required_reviewers", "reviewers": []}]}]:
            self.assertEqual(github.environment_approval_checks(payload)[0].status, "FAIL")
        protected = {"protection_rules": [{"type": "required_reviewers", "reviewers": [{"reviewer": {"id": 123}}]}]}
        self.assertEqual(github.environment_approval_checks(protected)[0].status, "OK")

    def test_github_collector_checks_environment_and_fails_when_unobservable(self):
        commands = []
        def run(root, args, **kwargs):
            commands.append(args)
            output = "owner/deployment" if args[:2] == ["repo", "view"] else "[]"
            return subprocess.CompletedProcess(args, 1 if "api" == args[0] else 0, output, "Access denied")
        checks = github.collect_github_checks(ROOT, customer_config(), command_exists_fn=lambda name: True, gh_command_fn=run)
        self.assertIn(["api", "repos/owner/deployment/environments/prod"], commands)
        self.assertEqual(next(c for c in checks if c.name == "GitHub environment approvals").status, "FAIL")


class ValidationAndUiTests(unittest.TestCase):
    def test_dry_run_and_strict_setup_do_not_report_false_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for args in [["dry-run", "--image-uri", "invalid-image"], ["setup", "--mode", "demo", "--yes", "--strict"]]:
                result, _ = invoke(root, args)
                self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
            self.assertEqual(list(root.iterdir()), [])

    def test_cli_and_workflow_reject_the_same_malformed_image_shapes(self):
        source = (ROOT / ".github/workflows/deploy.yml").read_text()
        pattern = re.search(r"grep -Eq '([^']+)'", source).group(1)
        for candidate in [IMAGE, IMAGE.replace("customer-prod", "App Repo"), IMAGE.replace("sha-abc123", "sha bad"),
                          IMAGE + "\n", IMAGE + "@sha256:" + "a" * 64, IMAGE.rsplit(":", 1)[0] + "@sha256:" + "b" * 64]:
            with self.subTest(candidate=candidate):
                self.assertEqual(cli.parse_ecr_image_uri(candidate) is not None, re.fullmatch(pattern, candidate) is not None)

    def test_empty_and_invalid_cors_are_rejected_before_generation(self):
        for origins in [[], [""], [" "], ["not-an-origin"], ["https://customer.example/path"]]:
            cfg = customer_config()
            cfg["environments"]["prod"]["cors_allowed_origins"] = origins
            self.assertEqual(next(c for c in config.validate_config(cfg) if c.name == "prod.cors_allowed_origins").status, "FAIL")

    def test_invalid_config_set_leaves_config_and_snapshots_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            before = config.config_path(root).read_bytes()
            result, text = invoke(root, ["config", "set", "project_name", "INVALID PROJECT"])
            self.assertEqual(result, 1)
            self.assertEqual(config.config_path(root).read_bytes(), before)
            self.assertFalse((root / cli.SNAPSHOT_DIR).exists())
            self.assertIn("not saved", text)

    def test_malformed_config_errors_remain_json(self):
        for bad_config in ["project_name = [\n", "project_name = 7\n", "backend = 7\n", "environments = []\n"]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config.config_path(root).write_text(bad_config)
                result, text = invoke(root, ["config", "validate", "--format", "json"])
            payload = json.loads(text)
            self.assertEqual(result, 1)
            self.assertEqual(payload["kind"], "command-error")
            self.assertIn("Fix", payload["error"])

    @unittest.skipUnless(importlib.util.find_spec("rich"), "Optional Rich renderer is not installed")
    def test_real_rich_renderer_with_readiness_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            result, text = invoke(Path(directory), ["tui"])
        self.assertEqual(result, 0, text)
        self.assertIn("Next Action", text)
        self.assertNotIn("Unexpected error", text)

    def test_wide_tables_preserve_text_at_narrow_terminal_widths(self):
        value = "https://example.test/" + "a" * 140
        for width in [40, 80, 120]:
            output = io.StringIO()
            with patch.object(cli.shutil, "get_terminal_size", return_value=os.terminal_size((width, 24))), redirect_stdout(output):
                cli.draw_table(["Name", "Detail"], [["Customer", value]])
                cli.draw_box("Status", [value])
            self.assertTrue(all(len(line) <= width for line in output.getvalue().splitlines()))
            self.assertIn(value, "".join(line.strip() for line in output.getvalue().splitlines()))

    def test_deployment_menu_keeps_preview_and_confirmation_inside_menu(self):
        for choice, handler, dry_run in [("2", "cmd_deploy_prod", False), ("6", "cmd_deploy_rollback", False),
                                         ("7", "cmd_deploy_prod", True), ("8", "cmd_deploy_rollback", True)]:
            with patch("builtins.input", side_effect=[choice, ""]), patch.object(cli, handler) as command, redirect_stdout(io.StringIO()):
                cli.menu_deploy_hub()
            self.assertFalse(command.call_args.args[0].yes)
            self.assertEqual(command.call_args.args[0].dry_run, dry_run)

    def test_step_failure_overrides_broad_deployment_job_name(self):
        for step, expected in [("Smoke test Lambda health endpoint", cli.RUNBOOK_FAILED_VALIDATION),
                               ("Run DAST scan with OWASP ZAP", cli.RUNBOOK_FAILED_VALIDATION),
                               ("Terraform apply workload with configured Lambda image", cli.RUNBOOK_FAILED_APPLY),
                               ("Roll back Lambda image on failed deployment validation", cli.RUNBOOK_FAILED_ROLLBACK)]:
            self.assertEqual(github.runbook_for_failure("Secure Serverless DevSecOps Pipeline", "Manual Apply, Deploy, or Roll Back Production", step), expected)

    def test_postlude_does_not_call_cloud_or_change_success_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            with patch.object(cli, "collect_github_checks", side_effect=AssertionError("Unexpected cloud call")), patch.object(cli, "collect_aws_checks", side_effect=AssertionError("Unexpected cloud call")):
                result, _ = invoke(root, ["generate"])
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
