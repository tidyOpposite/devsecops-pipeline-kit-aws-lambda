"""Regression coverage for the product audit, without cloud mutations."""

import argparse
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
import urllib.request
import urllib.response
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import aws, config, context, deploy, doctor, github, main as cli, oidc, render, workflow
from devsecops_cli.models import Check, ConfigValidationError
from devsecops_cli.readiness import PRE_DEPLOY_CHECKS, WORKLOAD_CHECKS

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/customer-prod-lambda-repo:sha-abc123"
IMAGE_DIGEST = IMAGE.rsplit(":", 1)[0] + "@sha256:" + "b" * 64
COMMIT_SHA = "c" * 40


def customer_config():
    cfg = config.preset_config("enterprise")
    cfg.update(project_name="customer", aws_region="eu-central-1", lambda_image_uri=IMAGE)
    cfg["backend"].update(bucket="customer-state-bucket", region="eu-central-1", lock_table="customer-locks")
    cfg["environments"]["prod"].update(lambda_memory_size=4096, lambda_timeout=300,
                                    log_retention_days=731, cors_allowed_origins=["https://customer.example"])
    return cfg


def sandbox_backend():
    return {"bucket": "customer-sandbox-state", "region": "eu-central-1", "key": "sandbox.tfstate",
            "lock_table": "customer-sandbox-locks", "workspace_key_prefix": "sandbox-environments"}


def reviewed_environment(cfg, image=IMAGE_DIGEST):
    return {config.PIPELINE_CONFIG_VARIABLE: config.pipeline_config_json(cfg), "DEPLOY_MODE": "deploy",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main", "DEPLOY_ENVIRONMENT": "prod",
            "GITHUB_REPOSITORY": "owner/deployment", "DISPATCH_IMAGE_URI": image, "GITHUB_SHA": COMMIT_SHA,
            "DISPATCH_COMMIT_SHA": COMMIT_SHA, "DISPATCH_CONFIG_SHA256": config.deployment_config_sha256(cfg, image)}


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
        cfg["lambda_image_uri"] = ""
        target = IMAGE_DIGEST
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = reviewed_environment(cfg, target) | {"GITHUB_ENV": str(root / "github-env")}
            with patch.dict(os.environ, environment, clear=True), patch.object(workflow.Path, "cwd", return_value=root), \
                 patch.object(workflow, "production_environment_check", return_value=Check("Approval", "OK", "Protected")) as approval, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(workflow.main(), 0)
            approval.assert_called_once_with(root, "owner/deployment")
            env_values = dict(line.split("=", 1) for line in (root / "github-env").read_text().splitlines())
            self.assertIn(target, (root / cli.GENERATED_TFVARS).read_text())
        self.assertEqual(env_values["AWS_REGION"], cfg["aws_region"])
        self.assertEqual(env_values["ENABLE_HTTP_VALIDATION"], "true")
        self.assertEqual(env_values["LAMBDA_IMAGE_URI"], target)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env_values)

    def test_runner_rejects_production_policy_gaps_before_writing(self):
        for mode in ("deploy", "rollback"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cfg = customer_config()
                cfg.update(enable_http_validation=False, use_separate_aws_plan_role=False)
                environment = os.environ | reviewed_environment(cfg) | {"PYTHONPATH": str(ROOT / "cli"),
                    "GITHUB_ENV": str(root / "github-env"), "DEPLOY_MODE": mode}
                result = subprocess.run([sys.executable, "-m", "devsecops_cli.workflow"], cwd=root,
                                        env=environment, text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Deployment validation policy", result.stderr)
                self.assertIn("Separate plan role policy", result.stderr)
                self.assertEqual(list(root.iterdir()), [])

    def test_runner_blocks_unverified_protection_but_plan_can_render(self):
        cfg = customer_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = reviewed_environment(cfg)
            with patch.dict(os.environ, environment, clear=True), patch.object(workflow.Path, "cwd", return_value=root), \
                 patch.object(workflow, "production_environment_check", return_value=Check("Approval", "FAIL", "No reviewers")) as approval, \
                 redirect_stderr(io.StringIO()) as errors, redirect_stdout(io.StringIO()):
                self.assertEqual(workflow.main(), 1)
                self.assertIn("No reviewers", errors.getvalue())
                self.assertEqual(list(root.iterdir()), [])
                approval.assert_called_once_with(root, "owner/deployment")
                approval.reset_mock()
                cfg["enable_http_validation"] = False
                os.environ.update(DEPLOY_MODE="plan", DEPLOY_ENVIRONMENT="dev", ENABLE_AWS_PLAN="true",
                                  PLAN_BACKEND_JSON=json.dumps(sandbox_backend()), PIPELINE_CONFIG_JSON=config.pipeline_config_json(cfg))
                self.assertEqual(workflow.main(), 0)
                approval.assert_not_called()
                self.assertTrue((root / cli.GENERATED_TFVARS).exists())

    def test_runner_rejects_drift_before_writing_or_inspecting_protection(self):
        cfg = customer_config()
        changed_backend = copy.deepcopy(cfg)
        changed_backend["backend"]["bucket"] = "different-state-bucket"
        changed_image = IMAGE_DIGEST.replace("b" * 64, "a" * 64)
        for override, message in [
            ({"GITHUB_SHA": "a" * 40}, "commit_sha"),
            ({"DISPATCH_COMMIT_SHA": ""}, "commit_sha"),
            ({config.PIPELINE_CONFIG_VARIABLE: config.pipeline_config_json(changed_backend)}, "config_sha256"),
            ({"DISPATCH_IMAGE_URI": changed_image}, "config_sha256"),
            ({"DISPATCH_IMAGE_URI": IMAGE}, "explicit ECR image @sha256 digest"),
            ({"DISPATCH_IMAGE_URI": ""}, "explicit ECR image @sha256 digest"),
        ]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                environment = reviewed_environment(cfg) | {"GITHUB_ENV": str(root / "github-env")} | override
                with patch.dict(os.environ, environment, clear=True), patch.object(workflow.Path, "cwd", return_value=root), \
                     patch.object(workflow, "production_environment_check") as approval, redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(workflow.main(), 1)
                    self.assertIn(message, errors.getvalue())
                approval.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_preapproval_verifies_effective_config_without_rendering(self):
        cfg = customer_config()
        remote = dict(cfg, lambda_image_uri="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary"
            environment = reviewed_environment(cfg) | {config.PIPELINE_CONFIG_VARIABLE: json.dumps(remote, indent=2),
                                                        "GITHUB_STEP_SUMMARY": str(summary)}
            with patch.dict(os.environ, environment, clear=True), patch.object(workflow.Path, "cwd", return_value=root), \
                 patch.object(sys, "argv", ["workflow", "--verify-intent"]), \
                 patch.object(workflow, "production_environment_check") as approval, redirect_stdout(io.StringIO()):
                self.assertEqual(workflow.main(), 0)
            approval.assert_not_called()
            self.assertEqual(list(root.iterdir()), [summary])
            for value in (COMMIT_SHA, IMAGE_DIGEST, environment["DISPATCH_CONFIG_SHA256"]):
                self.assertIn(value, summary.read_text())

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


class GitHubSetupTests(unittest.TestCase):
    deploy_arn = "arn:aws:iam::123456789012:role/deploy"
    plan_arn = "arn:aws:iam::123456789012:role/plan"
    timestamp = "2026-11-05T00:00:00Z"

    def provider(self, cfg):
        state = {
            "variables": github.github_expected_variables(cfg),
            "repository": {"AWS_PLAN_ROLE_TO_ASSUME_ARN": self.plan_arn},
            "prod": {"AWS_ROLE_TO_ASSUME_ARN": self.deploy_arn, "SNYK_TOKEN": "never-log-token"},
            "fail": None,
            "writes": [],
        }

        def call(root, args, **kwargs):
            output = ""
            if args[:2] == ["auth", "status"]:
                pass
            elif args[:2] == ["repo", "view"]:
                output = "owner/deployment"
            elif args[:2] == ["variable", "list"]:
                self.assertEqual(args[args.index("--repo") + 1], "owner/deployment")
                output = json.dumps([{"name": name, "value": value} for name, value in state["variables"].items()])
            elif args[:2] == ["secret", "list"]:
                self.assertEqual(args[args.index("--repo") + 1], "owner/deployment")
                scope = "prod" if "--env" in args else "repository"
                output = json.dumps([{"name": name, "updatedAt": self.timestamp} for name in state[scope]])
            elif args[0] in {"variable", "secret"} and args[1] == "set":
                self.assertEqual(args[args.index("--repo") + 1], "owner/deployment")
                kind, _, name = args[:3]
                state["writes"].append(args)
                if name == state["fail"]:
                    state["fail"] = None
                    return subprocess.CompletedProcess(args, 1, "", "never-log-token")
                if kind == "variable":
                    state["variables"][name] = args[args.index("--body") + 1]
                else:
                    self.assertNotIn("--body", args)
                    scope = "prod" if "--env" in args else "repository"
                    state[scope][name] = kwargs["input_data"]
            else:
                raise AssertionError(f"Unexpected provider call {args}")
            return subprocess.CompletedProcess(args, 0, output, "")
        return state, call

    def test_partial_setup_blocks_configuration_and_retry_completes_the_same_repository(self):
        cfg = customer_config()
        state, provider = self.provider(cfg)
        state["fail"] = "AWS_PLAN_ROLE_TO_ASSUME_ARN"
        command = ["github", "setup", "--apply", "--repo", "owner/deployment",
                   "--deploy-role-arn", self.deploy_arn, "--plan-role-arn", self.plan_arn, "--snyk-token", "never-log-token"]
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, "command_exists", return_value=True), patch.object(
            cli, "gh_command", side_effect=provider,
        ):
            root = Path(directory)
            config.write_config(root, cfg)
            code, text = invoke(root, command)
            self.assertEqual(code, 1, text)
            self.assertEqual(state["variables"]["PIPELINE_CONFIG_JSON"], github.SETUP_IN_PROGRESS_CONFIG)
            self.assertIn("Not attempted", text)
            self.assertNotIn("never-log-token", text)
            self.assertIn("--repo owner/deployment", text)
            with self.assertRaises(ConfigValidationError):
                workflow.decode_pipeline_config(state["variables"]["PIPELINE_CONFIG_JSON"], production=True)
            code, text = invoke(root, command)
            self.assertEqual(code, 0, text)
            self.assertIn("Unchanged", text)
            self.assertNotIn("never-log-token", text)
            self.assertEqual(state["variables"], github.github_expected_variables(cfg))
            self.assertEqual(state["prod"]["AWS_ROLE_TO_ASSUME_ARN"], self.deploy_arn)
            deploy_write = next(args for args in state["writes"] if args[:3] == ["secret", "set", "AWS_ROLE_TO_ASSUME_ARN"])
            self.assertIn("--env", deploy_write)
            self.assertNotIn("never-log-token", "".join(path.read_text() for path in root.rglob("*") if path.is_file()))

    def test_invalid_or_equal_role_arguments_fail_before_provider_calls(self):
        for deploy_role, plan_role in [
            ("not-an-arn", self.plan_arn), (self.deploy_arn, self.deploy_arn), (self.deploy_arn, None),
            (self.deploy_arn, self.deploy_arn.replace("role/deploy", "role/team/Deploy")),
            ("arn:aws:iam::123456789012:role/" + "r" * 65, self.plan_arn),
        ]:
            with self.subTest(deploy_role=deploy_role, plan_role=plan_role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config.write_config(root, customer_config())
                args = argparse.Namespace(deploy_role_arn=deploy_role, plan_role_arn=plan_role, snyk_token=None)
                with patch.object(cli, "gh_command") as provider, redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.apply_github_setup(root, customer_config(), args), 1)
                provider.assert_not_called()

    def test_guided_setup_honors_explicit_apply_even_when_settings_are_ready(self):
        cfg = customer_config()
        ready = [Check("GitHub repository", "OK", "owner/deployment"), Check("GitHub OIDC roles", "OK", "Verified")]
        args = argparse.Namespace(apply_github=True, deploy_role_arn=self.deploy_arn,
                                  plan_role_arn=self.plan_arn, snyk_token=None)
        with patch.object(cli, "collect_github_checks", return_value=ready), patch.object(
            cli, "github_setup_precheck", return_value=ready,
        ), patch.object(cli, "apply_github_setup", return_value=0) as apply, redirect_stdout(io.StringIO()):
            checks, failed = cli.setup_github_connection(ROOT, cfg, args, False, "production")
        self.assertFalse(failed)
        self.assertEqual(checks, ready)
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[2].repo, "owner/deployment")
        self.assertEqual(apply.call_args.args[2].deploy_role_arn, self.deploy_arn)

    def test_secret_write_timeout_reports_an_unconfirmed_partial_result(self):
        cfg = customer_config()
        state, provider = self.provider(cfg)
        def timeout(root, args, **kwargs):
            if args[:3] == ["secret", "set", "AWS_ROLE_TO_ASSUME_ARN"]:
                raise subprocess.TimeoutExpired(args, 30, stderr="never-log-token")
            return provider(root, args, **kwargs)
        command = ["github", "setup", "--apply", "--repo", "owner/deployment",
                   "--deploy-role-arn", self.deploy_arn, "--plan-role-arn", self.plan_arn]
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, "command_exists", return_value=True), patch.object(
            cli, "gh_command", side_effect=timeout,
        ):
            root = Path(directory)
            config.write_config(root, cfg)
            code, text = invoke(root, command)
        self.assertEqual(code, 1)
        self.assertEqual(state["variables"]["PIPELINE_CONFIG_JSON"], github.SETUP_IN_PROGRESS_CONFIG)
        self.assertIn("Unconfirmed", text)
        self.assertNotIn("never-log-token", text)

    def test_configuration_only_update_retains_scoped_secrets_and_missing_roles_block_all_writes(self):
        cfg = customer_config()
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                state, provider = self.provider(cfg)
                if missing:
                    state["repository"].clear()
                args = argparse.Namespace(repo="owner/deployment", deploy_role_arn=None, plan_role_arn=None, snyk_token=None)
                with patch.object(cli, "command_exists", return_value=True), patch.object(
                    cli, "gh_command", side_effect=provider,
                ), redirect_stdout(io.StringIO()):
                    code = cli.apply_github_setup(Path(directory), cfg, args)
                self.assertEqual(code, 1 if missing else 0)
                self.assertFalse([args for args in state["writes"] if args[0] == "secret"])
                if missing:
                    self.assertFalse(state["writes"])
        checks = github.github_secret_checks(cfg, {"AWS_PLAN_ROLE_TO_ASSUME_ARN": ""}, {"AWS_ROLE_TO_ASSUME_ARN": "", "SNYK_TOKEN": ""})
        self.assertEqual(next(check for check in checks if check.name.endswith("AWS_ROLE_TO_ASSUME_ARN")).status, "OK")
        self.assertIn("prod environment", next(check.detail for check in checks if check.name.endswith("AWS_ROLE_TO_ASSUME_ARN")))

    def test_oidc_evidence_requires_both_jobs_and_current_secret_revisions(self):
        run = {"databaseId": 42, "headSha": COMMIT_SHA, "status": "completed", "conclusion": "success",
               "createdAt": "2026-11-05T01:00:00Z"}
        jobs = [{"name": f"Verify {role} OIDC role", "status": "completed", "conclusion": "success",
                 "steps": [{"name": name, "conclusion": "success"} for name in (
                     f"Validate {role} role settings", f"Verify assumed {role} identity",
                 )]} for role in ("plan", "deploy")]
        def provider(root, args):
            output = json.dumps([run]) if args[:2] == ["run", "list"] else COMMIT_SHA if args[0] == "api" else json.dumps({"jobs": jobs})
            return subprocess.CompletedProcess(args, 0, output, "")
        secrets = {"AWS_PLAN_ROLE_TO_ASSUME_ARN": self.timestamp}
        production = {"AWS_ROLE_TO_ASSUME_ARN": self.timestamp}
        inspect = lambda: github.oidc_verification_check(ROOT, "owner/deployment", secrets, production, gh_command_fn=provider)
        self.assertEqual(inspect().status, "OK")
        production["AWS_ROLE_TO_ASSUME_ARN"] = "2026-11-05T02:00:00Z"
        self.assertEqual(inspect().status, "WARN")
        production["AWS_ROLE_TO_ASSUME_ARN"] = self.timestamp
        jobs[1]["conclusion"] = "skipped"
        self.assertEqual(inspect().status, "WARN")

    def test_oidc_verifies_the_assumed_role_and_enforces_role_separation(self):
        environment = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
                       "EXPECTED_ROLE_ARN": self.deploy_arn, "PLAN_ROLE_FINGERPRINT": oidc.role_fingerprint(self.plan_arn)}
        self.assertEqual(oidc.validate_role_settings("deploy", environment), self.deploy_arn)
        with self.assertRaisesRegex(ConfigValidationError, "different"):
            oidc.validate_role_settings("deploy", environment | {"PLAN_ROLE_FINGERPRINT": oidc.role_fingerprint(self.deploy_arn)})
        oidc.verify_identity(self.deploy_arn, {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/deploy/session"})
        with self.assertRaisesRegex(ConfigValidationError, "intended OIDC"):
            oidc.verify_identity(self.deploy_arn, {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/plan/session"})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            identity = {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/deploy/session"}
            with patch.dict(os.environ, environment | {"GITHUB_OUTPUT": str(output)}, clear=True), patch.object(
                oidc.sys, "argv", ["oidc", "verify", "deploy"],
            ), patch.object(oidc, "_aws_json", return_value=(identity, subprocess.CompletedProcess([], 0, "", ""))), redirect_stdout(io.StringIO()):
                self.assertEqual(oidc.main(), 0)
            self.assertIn(oidc.role_fingerprint(self.deploy_arn), output.read_text())
            self.assertNotIn(self.deploy_arn, output.read_text())


class AwsConstraintTests(unittest.TestCase):
    def test_retention_schema_validation_and_presets_use_supported_values(self):
        schema = config.config_schema()["fields"]["environments"]["fields"]["prod"]["log_retention_days"]
        self.assertEqual(schema["type"], "integer")
        self.assertIn(1096, schema["enum"])
        self.assertNotIn(1095, schema["enum"])
        for days in [*schema["enum"], 0, 2, 1095, 3654]:
            with self.subTest(days=days):
                cfg = customer_config()
                cfg["environments"]["prod"]["log_retention_days"] = days
                check = next(check for check in config.validate_config(cfg) if check.name == "prod.log_retention_days")
                expected = "OK" if type(days) is int and days in schema["enum"] else "FAIL"
                self.assertEqual(check.status, expected)
        for preset in config.PRESET_ORDER:
            with self.subTest(preset=preset):
                self.assertFalse([check for check in config.validate_config(config.clean_config(preset)) if check.status == "FAIL"])

    def test_invalid_retention_write_is_rejected_and_legacy_enterprise_value_can_be_corrected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = project(root)
            original = config.config_path(root).read_text()
            code, text = invoke(root, ["config", "set", "environments.prod.log_retention_days", "2"])
            self.assertEqual(code, 1, text)
            self.assertEqual(config.config_path(root).read_text(), original)

            cfg["environments"]["prod"]["log_retention_days"] = 1095
            config.write_config(root, cfg)
            code, text = invoke(root, ["config", "validate", "--format", "json"])
            self.assertEqual(code, 1, text)
            self.assertEqual(config.load_config(root)["environments"]["prod"]["log_retention_days"], 1095)
            code, text = invoke(root, ["config", "set", "environments.prod.log_retention_days", "1096", "--render"])
            self.assertEqual(code, 0, text)
            self.assertEqual(config.load_config(root)["environments"]["prod"]["log_retention_days"], 1096)
            self.assertIn("log_retention_days         = 1096", (root / cli.GENERATED_TFVARS).read_text())

    def test_retention_prompt_retries_until_the_value_is_supported(self):
        with patch("builtins.input", side_effect=["2", "1095", "1096"]), redirect_stdout(io.StringIO()) as output:
            days = cli.prompt_int("Log retention days", 1095, choices=config.LOG_RETENTION_DAYS)
        self.assertEqual(days, 1096)
        self.assertEqual(output.getvalue().count("Choose one of"), 2)


class WorkflowRequestTests(unittest.TestCase):
    def test_documented_plan_trust_accepts_main_and_rejects_pr_and_other_refs(self):
        policy = (ROOT / "AWS_policy.md").read_text().split("## Plan Trust Policy Example", 1)[1].split("```json\n", 1)[1].split("```", 1)[0]
        condition = json.loads(policy)["Statement"][0]["Condition"]["StringEquals"]
        self.assertEqual(condition["token.actions.githubusercontent.com:aud"], "sts.amazonaws.com")
        subject = condition["token.actions.githubusercontent.com:sub"].replace("<GITHUB_REPOSITORY_SUBJECT>", "owner/repository")
        self.assertEqual(subject, "repo:owner/repository:ref:refs/heads/main")
        for denied in ("repo:owner/repository:pull_request", "repo:owner/repository:ref:refs/heads/feature",
                       "repo:owner/repository:environment:prod", "repo:other/fork:ref:refs/heads/main"):
            self.assertNotEqual(subject, denied)

    def test_runner_rejects_unsupported_manual_requests_before_configuration(self):
        cases = [
            ("deploy", "dev", "refs/heads/main", 1, "only environment prod"),
            ("rollback", "staging", "refs/heads/main", 1, "only environment prod"),
            ("deploy", "prod", "refs/heads/feature", 1, "requires branch main"),
            ("rollback", "prod", "refs/tags/v0.15.0", 1, "requires branch main"),
            ("destroy", "prod", "refs/heads/main", 1, "mode plan, deploy, or rollback"),
            ("plan", "test", "refs/heads/main", 1, "Choose dev for a sandbox"),
            ("plan", "dev", "refs/heads/main", 0, ""),
            ("plan", "staging", "refs/heads/main", 1, "only environment dev"),
            ("plan", "prod", "refs/heads/main", 1, "only environment dev"),
            ("plan", "dev", "refs/heads/feature", 1, "requires branch main"),
            ("deploy", "prod", "refs/heads/main", 0, ""),
            ("rollback", "prod", "refs/heads/main", 0, ""),
        ]
        for mode, target, ref, code, error in cases:
            with self.subTest(mode=mode, target=target, ref=ref), tempfile.TemporaryDirectory() as directory:
                environment = {"PYTHONPATH": str(ROOT / "cli"), "GITHUB_EVENT_NAME": "workflow_dispatch",
                               "GITHUB_REF": ref, "DEPLOY_MODE": mode, "DEPLOY_ENVIRONMENT": target,
                               "ENABLE_AWS_PLAN": "true", "PLAN_BACKEND_JSON": json.dumps(sandbox_backend()),
                               "PIPELINE_CONFIG_JSON": config.pipeline_config_json(customer_config())}
                result = subprocess.run(
                    [sys.executable, "-m", "devsecops_cli.workflow", "--validate-request"],
                    cwd=directory, env=environment, text=True, capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, code, result.stderr)
                if error:
                    self.assertIn(error, result.stderr)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_sandbox_plan_requires_opt_in_and_isolated_valid_backend_before_writes(self):
        cfg = customer_config()
        environment = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
                       "DEPLOY_MODE": "plan", "DEPLOY_ENVIRONMENT": "dev", "ENABLE_AWS_PLAN": "true",
                       "PLAN_BACKEND_JSON": json.dumps(sandbox_backend()), "PIPELINE_CONFIG_JSON": config.pipeline_config_json(cfg)}
        for overrides in (
            {"ENABLE_AWS_PLAN": "false"}, {"PLAN_BACKEND_JSON": ""},
            {"PLAN_BACKEND_JSON": json.dumps(cfg["backend"])},
            *({"PLAN_BACKEND_JSON": json.dumps(sandbox_backend() | change)} for change in (
                {"lock_table": cfg["backend"]["lock_table"]}, {"bucket": "invalid bucket"}, {"bucket": " " + cfg["backend"]["bucket"]},
                {"region": "bad-region"}, {"lock_table": ""}, {"key": ""}, {"workspace_key_prefix": "bad\nvalue"},
                {"access_key": "must-not-be-accepted"},
            )),
        ):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.dict(os.environ, environment | overrides, clear=True), patch.object(workflow.Path, "cwd", return_value=root), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.object(workflow, "production_environment_check") as provider:
                    self.assertEqual(workflow.main(), 1)
                self.assertEqual(list(root.iterdir()), [])
                provider.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, environment, clear=True), patch.object(workflow.Path, "cwd", return_value=root), redirect_stdout(io.StringIO()):
                self.assertEqual(workflow.main(), 0)
            backend = (root / "dist/devsecops/backend.hcl").read_text()
            self.assertIn(sandbox_backend()["bucket"], backend)
            self.assertIn(sandbox_backend()["lock_table"], backend)
            self.assertNotIn(cfg["backend"]["bucket"], backend)
            self.assertNotIn(cfg["backend"]["lock_table"], backend)

    def test_pull_requests_need_no_deployment_settings_and_cannot_materialize_aws_inputs(self):
        for fork in (False, True):
            with self.subTest(fork=fork), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                environment = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/1/merge",
                               "GITHUB_HEAD_REF": "external" if fork else "internal"}
                workflow.validate_workflow_request(environment)
                with patch.dict(os.environ, environment, clear=True), patch.object(workflow.Path, "cwd", return_value=root), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(workflow.main(), 1)
                self.assertEqual(list(root.iterdir()), [])


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
            self.assertNotEqual(next(g for g in payload["gates"] if g["gate"] == "Ready to deploy")["status"], "OK")
            github_calls.assert_not_called()
            aws_calls.assert_not_called()

    def test_human_status_collects_once_and_exits_using_displayed_observations(self):
        observations = [Check(name, "OK", "Verified") for name in sorted(PRE_DEPLOY_CHECKS | WORKLOAD_CHECKS)]
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
            self.assertEqual(text.count("Readiness Gates"), 1)
            self.assertNotIn("AWS workload resources were verified", text)

    def test_fully_observed_healthy_production_can_pass_strict(self):
        observations = [Check(name, "OK", "Verified") for name in sorted(PRE_DEPLOY_CHECKS | WORKLOAD_CHECKS)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            with patch.object(cli, "command_exists", return_value=True), patch.object(cli, "collect_dashboard_checks", return_value=observations):
                result, text = invoke(root, ["status", "--deep", "--strict", "--format", "json"])
        self.assertEqual(result, 0, text)
        self.assertEqual(json.loads(text)["score"], 100)

    def test_pre_deploy_checks_prerequisites_without_reading_workload(self):
        github_checks = [Check(name, "OK", "Verified") for name in PRE_DEPLOY_CHECKS if name.startswith("GitHub")]
        cloud_responses = {
            ("sts", "get-caller-identity"): {"Account": "123456789012"},
            ("dynamodb", "describe-table"): {"Table": {"TableStatus": "ACTIVE"}},
            ("ecr", "describe-images"): {"imageDetails": [{"imageTags": ["sha-abc123"]}]},
        }

        def aws_json(root, args):
            return cloud_responses[tuple(args[:2])], subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as directory, ExitStack() as mocks:
            root = Path(directory)
            project(root)
            for name, value in {
                "command_exists": True,
                "run_command": subprocess.CompletedProcess([], 0, "main\n", ""),
                "aws_command": subprocess.CompletedProcess([], 0, "", ""),
                "collect_github_checks": github_checks,
                "collect_branch_checks": [Check("Branch `main` protection", "OK", "Verified")],
            }.items():
                mocks.enter_context(patch.object(cli, name, return_value=value))
            mocks.enter_context(patch.object(cli, "aws_json", side_effect=aws_json))
            health = mocks.enter_context(patch.object(cli, "fetch_health_url"))

            args = ["status", "--pre-deploy", "--strict", "--format", "json"]
            result, text = invoke(root, args)
            self.assertEqual(result, 0, text)
            payload = json.loads(text)
            gates = {gate["gate"]: gate["status"] for gate in payload["gates"]}
            self.assertEqual(gates["Ready to deploy"], "OK")
            self.assertEqual(gates["Deployed and healthy"], "Unverified")
            self.assertEqual(gates["Release evidence complete"], "Unverified")
            self.assertEqual(payload["next_action"]["command"], "devsecops deploy prod --dry-run")
            self.assertTrue(WORKLOAD_CHECKS.isdisjoint(check["name"] for check in payload["checks"]))

            cloud_responses[("ecr", "describe-images")] = {"imageDetails": []}
            result, text = invoke(root, args)
            self.assertEqual(result, 1, text)
            self.assertNotEqual(json.loads(text)["next_action"]["action"], "ready_for_deploy")
            health.assert_not_called()

    def test_deep_status_requires_http_2xx_and_distinguishes_workload_absence(self):
        endpoint = "https://api123.execute-api.eu-central-1.amazonaws.com"
        observations = [
            Check(name, "OK", endpoint if name == "API Gateway" else "Verified")
            for name in sorted((PRE_DEPLOY_CHECKS | WORKLOAD_CHECKS) - {"Health response"})
        ]
        args = ["status", "--deep", "--strict", "--format", "json"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project(root)
            with patch.object(cli, "command_exists", return_value=True), patch.object(
                doctor, "collect_dashboard_checks", side_effect=lambda *a, **k: observations.copy(),
            ), patch.object(cli, "fetch_health_url") as health:
                for code, expected in [(204, 0), (302, 1), (500, 1)]:
                    with self.subTest(code=code):
                        health.return_value = code, ""
                        result, text = invoke(root, args)
                        self.assertEqual(result, expected, text)
                        payload = json.loads(text)
                        gates = {gate["gate"]: gate["status"] for gate in payload["gates"]}
                        self.assertEqual(gates["Ready to deploy"], "OK")
                        self.assertEqual(gates["Deployed and healthy"], "OK" if code == 204 else "Blocked")
                        self.assertEqual(gates["Release evidence complete"], "Unverified")
                        self.assertNotEqual(payload["next_action"]["action"], "ready_for_deploy")
                health.assert_called_with(endpoint + "/health", aws_sigv4=True, aws_region="eu-central-1",
                                          allow_redirects=False)
                health.reset_mock()
                observations[:] = [check for check in observations if check.name not in WORKLOAD_CHECKS]
                for detail, expected_action in [(aws.LAMBDA_NOT_DEPLOYED, "ready_for_deploy"),
                                                ("Access denied", "readiness_gaps")]:
                    observations.append(Check("Lambda function", "WARN", detail))
                    result, text = invoke(root, args)
                    self.assertEqual(result, 1, text)
                    self.assertEqual(json.loads(text)["next_action"]["action"], expected_action)
                    observations.pop()
                health.assert_not_called()

    def test_deploy_menu_exposes_the_read_only_pre_deploy_gate(self):
        with patch("builtins.input", side_effect=["9", ""]), patch.object(cli, "cmd_status") as status, \
             patch.object(cli, "cmd_deploy_prod") as deploy_command, redirect_stdout(io.StringIO()):
            cli.menu_deploy_hub()
        status.assert_called_once()
        self.assertTrue(status.call_args.args[0].pre_deploy)
        self.assertTrue(status.call_args.args[0].strict)
        deploy_command.assert_not_called()

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

    def test_actual_github_environment_protections_are_required(self):
        protected = {
            "protection_rules": [{"type": "required_reviewers", "prevent_self_review": True,
                                  "reviewers": [{"reviewer": {"id": 123}}]}],
            "can_admins_bypass": False,
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
        }
        main = {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}

        def inspect(environment, branches):
            def run(root, args):
                payload = branches if args[1].endswith("/deployment-branch-policies") else environment
                return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
            return github.production_environment_check(ROOT, "owner/deployment", gh_command_fn=run)

        self.assertEqual(inspect(protected, main).status, "OK")
        self_review = copy.deepcopy(protected)
        self_review["protection_rules"][0]["prevent_self_review"] = False
        for environment, branches, detail in [
            (protected | {"protection_rules": []}, main, "required reviewer"),
            (self_review, main, "Prevent self-review"),
            (protected | {"can_admins_bypass": True}, main, "bypass"),
            (protected | {"can_admins_bypass": None}, main, "bypass"),
            (protected | {"deployment_branch_policy": None}, main, "exact main branch"),
            (protected, main | {"total_count": 31}, "exact main branch"),
            (protected, main | {"branch_policies": [{"name": "main", "type": "tag"}]}, "exact main branch"),
            (protected, main | {"branch_policies": [{"name": "*", "type": "branch"}]}, "exact main branch"),
        ]:
            with self.subTest(detail=detail):
                check = inspect(environment, branches)
                self.assertEqual(check.status, "FAIL")
                self.assertIn(detail, check.detail)

    def test_github_collector_checks_environment_and_fails_when_unobservable(self):
        commands = []
        def run(root, args, **kwargs):
            commands.append(args)
            output = "owner/deployment" if args[:2] == ["repo", "view"] else "[]"
            return subprocess.CompletedProcess(args, 1 if "api" == args[0] else 0, output, "Access denied")
        checks = github.collect_github_checks(ROOT, customer_config(), command_exists_fn=lambda name: True, gh_command_fn=run)
        self.assertIn(["api", "repos/owner/deployment/environments/prod"], commands)
        self.assertEqual(next(c for c in checks if c.name == "GitHub environment approvals").status, "FAIL")


class SignedHealthTests(unittest.TestCase):
    def test_unsafe_signed_urls_are_rejected_before_signing(self):
        default_host = "abc123.execute-api.us-east-1.amazonaws.com"
        cases = [
            (f"http://{default_host}/health", None),
            (f"https://{default_host}.example.org/health", None),
            (f"https://user@{default_host}/health", None),
            (f"https://{default_host}:8443/health", None),
            ("https://[broken", None),
            ("https://api.example.org/health", None),
            ("https://api.example.org/health", "other.example.org"),
            ("http://api.example.org/health", "api.example.org"),
        ]
        with patch.object(aws, "aws_sigv4_headers") as sign, \
             patch.object(urllib.request, "urlopen") as unsigned_request, \
             patch.object(urllib.request, "build_opener") as signed_opener:
            for url, trusted_host in cases:
                with self.subTest(url=url, trusted_host=trusted_host):
                    status, detail = aws.fetch_health_url(url, aws_sigv4=True, trusted_host=trusted_host)
                    self.assertIsNone(status)
                    self.assertTrue(detail)
            sign.assert_not_called()
            unsigned_request.assert_not_called()
            signed_opener.assert_not_called()

    def test_signed_redirects_fail_without_contacting_target(self):
        source = "https://abc123.execute-api.us-east-1.amazonaws.com/health"
        target = "https://redirect.example.org/health"
        requests = []

        def respond(handler, request):
            requests.append(request)
            headers = Message()
            if request.full_url == source:
                headers["Location"] = target
                response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
                response.msg = "Found"
                return response
            response = urllib.response.addinfourl(io.BytesIO(b"ok"), headers, request.full_url, 200)
            response.msg = "OK"
            return response

        credentials = {"AWS_ACCESS_KEY_ID": "fixture-id", "AWS_SECRET_ACCESS_KEY": "fixture-key",
                       "AWS_SESSION_TOKEN": "fixture-session", "AWS_REGION": "us-east-1"}
        with patch.dict(os.environ, credentials, clear=True), \
             patch.object(urllib.request.HTTPSHandler, "https_open", autospec=True, side_effect=respond):
            code, output = invoke(ROOT, ["health", "--url", source, "--aws-sigv4", "--format", "json"])
            self.assertEqual(code, cli.EXIT_VALIDATION_FAILED)
            response = json.loads(output)["checks"][1]
            self.assertEqual(response["status"], "FAIL")
            self.assertIn("HTTP 302", response["detail"])
            self.assertIn("reject HTTP redirects", response["detail"])
            self.assertEqual([request.full_url for request in requests], [source])
            self.assertTrue(requests[0].get_header("Authorization").startswith("AWS4-HMAC-SHA256"))
            self.assertEqual(requests[0].get_header("X-amz-security-token"), "fixture-session")

            requests.clear()
            status, detail = aws.fetch_health_url(source)
            self.assertEqual(status, 302)
            self.assertIn("reject HTTP redirects", detail)
            self.assertEqual([request.full_url for request in requests], [source])
            self.assertIsNone(requests[-1].get_header("Authorization"))
            self.assertIsNone(requests[-1].get_header("X-amz-security-token"))

            requests.clear()
            code, output = invoke(ROOT, ["health", "--url", target, "--aws-sigv4", "--trusted-host",
                                         "redirect.example.org", "--format", "json"])
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual([request.full_url for request in requests], [target])
            self.assertEqual(requests[0].get_header("X-amz-security-token"), "fixture-session")

    def test_signed_and_public_health_require_2xx_and_use_a_positive_timeout(self):
        for signed in (False, True):
            for status in (200, 204, 302, 500, None):
                with self.subTest(signed=signed, status=status), patch.object(
                    cli, "fetch_health_url", return_value=(status, "fixture response"),
                ) as fetch:
                    command = ["health", "--url", "https://abc123.execute-api.us-east-1.amazonaws.com/health",
                               "--timeout", "20", "--format", "json"] + (["--aws-sigv4"] if signed else [])
                    code, output = invoke(ROOT, command)
                    self.assertEqual(code, 0 if status in (200, 204) else 1, output)
                    self.assertEqual(fetch.call_args.kwargs["timeout"], 20)
        with patch.object(urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError
            self.assertEqual(aws.fetch_health_url("https://example.org/health", timeout=20), (None, "Timed out after 20s."))
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 20)
            opener.reset_mock()
            for timeout in (0, -1):
                self.assertIn("positive", aws.fetch_health_url("https://example.org/health", timeout=timeout)[1])
            opener.assert_not_called()

    def test_workflow_smoke_script_rejects_redirects_and_errors_on_a_local_server(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                status = int(self.path.strip("/"))
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", "/200")
                self.end_headers()
                if status != 204:
                    self.wfile.write(b"health fixture")

            def log_message(self, *args):
                pass

        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        step = workflow.split("      - name: Smoke test Lambda health endpoint\n", 1)[1].split("\n      # The baseline", 1)[0]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        self.assertIn("timeout-minutes: 1", step)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config.write_config(root, customer_config())
                (root / "cli").symlink_to(ROOT / "cli", target_is_directory=True)
                for status in (200, 204, 302, 500):
                    with self.subTest(status=status):
                        requests.clear()
                        environment = dict(os.environ, API_AUTHORIZATION_TYPE="NONE",
                                           HEALTH_URL=f"http://127.0.0.1:{server.server_port}/{status}")
                        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=root,
                                                env=environment, text=True, capture_output=True, timeout=10, check=False)
                        self.assertEqual(result.returncode, 0 if status < 300 else 1, result.stdout + result.stderr)
                        self.assertEqual(requests, [f"/{status}"])
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_evidence_health_runbook_rejects_non_2xx_and_supports_public_and_signed_apis(self):
        document = (ROOT / "docs/production-deployment-evidence.md").read_text()
        script = "set -euo pipefail\n" + document.split("## 6. Prove Health And Logs", 1)[1].split("```bash\n", 1)[1].split("```", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            binaries.mkdir()
            for interpreter in ("python", "python3"):
                (binaries / interpreter).symlink_to(sys.executable)
            for name, body in {
                "devsecops": 'printf \'{"kind":"health"}\\n\'\n',
                "curl": ('while [ "$#" -gt 0 ]; do\n'
                         '  if [ "$1" = --output ]; then shift; : > "$1"; fi\n'
                         '  shift\n'
                         'done\n'
                         'printf "%s" "$TEST_HTTP_STATUS"\n'),
            }.items():
                path = binaries / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(0o755)
            (root / "terraform-context.json").write_text(json.dumps({"aws_region": "us-east-1"}))
            for auth_type in ("NONE", "AWS_IAM"):
                (root / "terraform-output.json").write_text(json.dumps({
                    "api_gateway_health_url": {"value": "https://abc123.execute-api.us-east-1.amazonaws.com/health"},
                    "api_gateway_authorization_type": {"value": auth_type},
                }))
                for status in (200, 204, 302, 500):
                    with self.subTest(auth_type=auth_type, status=status):
                        environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                                           EVIDENCE_DIR=str(root), TEST_HTTP_STATUS=str(status),
                                           AWS_ACCESS_KEY_ID="fixture", AWS_SECRET_ACCESS_KEY="fixture")
                        environment.pop("AWS_SESSION_TOKEN", None)
                        result = subprocess.run(["/bin/bash", "-c", script], env=environment,
                                                capture_output=True, text=True, timeout=10, check=False)
                        if status < 300:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual((root / "health-status.txt").read_text().strip(), str(status))
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertEqual((root / "health-status.txt").read_text().strip(), str(status))


class ValidationAndUiTests(unittest.TestCase):
    def test_dry_run_and_strict_setup_do_not_report_false_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for args in [["dry-run", "--image-uri", "invalid-image"], ["setup", "--mode", "demo", "--yes", "--strict"]]:
                result, _ = invoke(root, args)
                self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
            self.assertEqual(list(root.iterdir()), [])

    def test_production_intent_rejects_malformed_or_unpinned_images(self):
        payload = config.pipeline_config_json(customer_config())
        for candidate in [IMAGE, IMAGE_DIGEST.replace("customer-prod", "App Repo"),
                          IMAGE_DIGEST + "\n", IMAGE + "@sha256:" + "a" * 64]:
            with self.subTest(candidate=candidate):
                intent = deploy.DeploymentIntent("owner/deployment", COMMIT_SHA, "", candidate)
                with self.assertRaisesRegex(ConfigValidationError, "explicit ECR image @sha256 digest"):
                    workflow.verify_production_intent(payload, intent, COMMIT_SHA)

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
