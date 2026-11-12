"""Exercise saved-plan boundaries and recovery without AWS resource creation."""

import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import deployment
from devsecops_cli import main as cli
from devsecops_cli.aws import aws_sigv4_headers

ACCOUNT = "123456789012"
REGION = "eu-north-1"
PROJECT = "kit-diploma-abcdef"
ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PROJECT}-dev-lambda"
REPOSITORY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{PROJECT}-dev-lambda-repo"
IMAGE_A, IMAGE_B, IMAGE_C = [REPOSITORY + "@sha256:" + char * 64 for char in "abc"]


class FakeDeployment(deployment.Deployment):
    def __init__(self, root, name="diploma"):
        super().__init__(root, name)
        self.calls = []
        self.live_image = None
        self.live_reserved = 0
        self.apply_error = False
        self.interrupt = False
        self.recovery_error = False
        self.account = ACCOUNT
        self.health_calls = 0
        self.destroy_plan = False

    def aws(self, args, *, secret=False):
        self.calls.append(("aws", args))
        if args[:2] == ["sts", "get-caller-identity"]:
            return {"Account": self.account, "Arn": f"arn:aws:iam::{self.account}:root"}
        if args[:2] == ["lambda", "get-account-settings"]:
            return {
                "AccountLimit": {
                    "ConcurrentExecutions": 1000,
                    "UnreservedConcurrentExecutions": 1000 - self.live_reserved,
                }
            }
        if args[:2] == ["lambda", "get-function-concurrency"]:
            return (
                {"ReservedConcurrentExecutions": self.live_reserved} if self.live_reserved else {}
            )
        if args[:2] == ["lambda", "get-function"]:
            return {
                "Configuration": {"FunctionArn": ARN},
                "Code": {"ResolvedImageUri": self.live_image},
            }
        if args[:2] == ["lambda", "update-function-code"]:
            if self.recovery_error:
                raise deployment.DeploymentError("Injected recovery failure")
            self.live_image = args[-1]
        return {}

    def init_tf(self):
        self.calls.append(("tf", ["init"]))

    def check_image(self, image):
        if not image.startswith(REPOSITORY + "@sha256:"):
            raise deployment.DeploymentError("Invalid fixture image")

    def request(self, method, path, body=None):
        self.health_calls += 1
        return {
            "status": 503 if self.live_image == IMAGE_C else 200,
            "body": "fixture",
            "method": method,
            "path": path,
        }

    def tf(self, args, *, check=True):
        self.calls.append(("tf", args))
        stdout = ""
        if args[0] == "plan":
            self.destroy_plan = "-destroy" in args
            target = Path(next(arg[5:] for arg in args if arg.startswith("-out=")))
            target.write_bytes(b"saved-plan")
        elif args[0] == "show":
            stdout = (
                json.dumps(
                    {
                        "resource_changes": [
                            {
                                "address": "module.ecr.aws_ecr_repository.lambda_repo",
                                "mode": "managed",
                                "change": {
                                    "actions": ["delete"] if self.destroy_plan else ["create"],
                                    "before": None,
                                    "after": {
                                        "tags": {
                                            "Project": PROJECT,
                                            "Environment": "dev",
                                            "Purpose": "Deployment",
                                        },
                                    },
                                },
                            }
                        ]
                    }
                )
                if "-json" in args
                else "Terraform reviewed fixture plan"
            )
        elif args[0] == "apply":
            plan_path = Path(args[-1])
            if plan_path.name == "recovery.tfplan":
                image = self.live_image
            else:
                variables = deployment.read_json(plan_path.parent / "inputs.tfvars.json")
                image = variables["lambda_image_uri"]
                review = deployment.read_json(plan_path.parent / "review.json")
                if review["stage"] == "destroy":
                    deployment.write_json(self.state, {"resources": [], "outputs": {}})
                    self.live_image = None
                    return subprocess.CompletedProcess(args, 0, "destroyed", "")
                if image:
                    self.live_image = image
                    self.live_reserved = max(0, variables["reserved_concurrency"])
            context = self.context(image) if image else {}
            if context:
                context["reserved_concurrency"] = self.live_reserved or -1
            deployment.write_json(
                self.state, {"resources": [], "outputs": {"deployment_context": {"value": context}}}
            )
            if self.interrupt:
                self.interrupt = False
                raise KeyboardInterrupt()
            if self.apply_error and plan_path.name != "recovery.tfplan":
                return subprocess.CompletedProcess(args, 1, "partial", "Injected apply failure")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    @staticmethod
    def context(image):
        return {
            "purpose": "Deployment",
            "environment": "dev",
            "account_id": ACCOUNT,
            "region": REGION,
            "project_name": PROJECT,
            "lambda_function_arn": ARN,
            "image_uri": image,
            "api_endpoint": f"https://abcdef.execute-api.{REGION}.amazonaws.com",
            "reserved_concurrency": 10,
        }


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "terraform").mkdir(parents=True)
        (self.root / "terraform/main.tf").write_text("# fixture source\n")
        (self.root / "terraform/.terraform.lock.hcl").write_text("# fixture lock\n")
        self.deployment = FakeDeployment(self.root)
        self.deployment.settings = {
            "schema_version": 2,
            "name": "diploma",
            "account_id": ACCOUNT,
            "region": REGION,
            "project_name": PROJECT,
            "profile": "named-source",
            "aws_binary": "/usr/bin/aws",
            "reserved_concurrency": 10,
            "purpose": "Deployment",
        }
        deployment.write_json(self.deployment.settings_path, self.deployment.settings)
        self.deployment.begin_event("test")

    def test_operation_metadata_marks_untracked_source_as_dirty(self):
        def git(*args):
            subprocess.run(
                ["git", *args], cwd=self.root, capture_output=True, text=True, check=True
            )

        git("init", "--quiet")
        (self.root / ".gitignore").write_text(".devsecops/\n")
        git("add", ".")
        git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        )
        self.deployment.begin_event("clean")
        metadata = deployment.read_json(self.deployment.event_dir / "operation.json")
        self.assertTrue(metadata["source_clean"])
        self.assertRegex(metadata["source_commit"], r"^[a-f0-9]{40}$")

        (self.root / "terraform/untracked.tf").write_text("# new source\n")
        self.deployment.begin_event("untracked")
        metadata = deployment.read_json(self.deployment.event_dir / "operation.json")
        self.assertFalse(metadata["source_clean"])

    def test_source_fingerprint_ignores_install_path_and_absolute_sort_order(self):
        source = self.root / "cli/devsecops_cli"
        source.mkdir(parents=True)
        installed = self.root.parent / (self.root.name + "z-installed")
        installed.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(installed))
        for folder in (source, installed):
            (folder / "deployment.py").write_text("# same installed bytes\n")
            (folder / "main.py").write_text("# another module\n")
        with patch.object(deployment, "__file__", str(source / "deployment.py")):
            expected = deployment.source_digest(self.root)
        with patch.object(deployment, "__file__", str(installed / "deployment.py")):
            self.assertEqual(deployment.source_digest(self.root), expected)
            (installed / "main.py").write_text("# substituted module\n")
            self.assertNotEqual(deployment.source_digest(self.root), expected)

    def seed(self, image=IMAGE_A):
        self.deployment.live_image = image
        self.deployment.live_reserved = max(0, self.deployment.settings["reserved_concurrency"])
        deployment.write_json(
            self.deployment.state,
            {
                "resources": [],
                "outputs": {"deployment_context": {"value": self.deployment.context(image)}},
            },
        )

    def planned(self, image=IMAGE_B, stage="workload"):
        return self.deployment.plan(stage, image)

    def apply(self, plan, yes=True):
        return self.deployment.apply(plan["plan_id"], plan["sha256"], yes)

    def test_wrong_account_blocks_before_terraform(self):
        self.deployment.account = "999999999999"
        with self.assertRaisesRegex(deployment.DeploymentError, "account differs"):
            self.planned()
        self.assertFalse(any(kind == "tf" for kind, _ in self.deployment.calls))

    def test_settings_are_dev_only_and_unique(self):
        with patch("devsecops_cli.deployment.shutil.which", return_value="/usr/bin/aws"):
            self.deployment.settings_path.unlink()
            result = self.deployment.initialize(ACCOUNT, REGION, "signed-in")
        self.assertEqual(result["status"], "initialized")
        self.assertRegex(self.deployment.settings["project_name"], "^kit-diploma-[a-f0-9]{6}$")
        self.assertFalse(self.deployment.state.exists())
        self.assertEqual(self.deployment.settings_path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(deployment.DeploymentError, "already exists"):
            self.deployment.initialize(ACCOUNT, REGION, "signed-in")
        with self.assertRaises(deployment.DeploymentError):
            deployment.Deployment(self.root, "../prod")

    def test_local_shared_pool_selection_invalidates_old_plan_without_aws_writes(self):
        plan = self.deployment.plan("registry")
        self.deployment.calls.clear()
        outcome = self.deployment.concurrency("unreserved", None)
        self.assertEqual(outcome["reserved_concurrency"], -1)
        self.assertFalse(self.deployment.calls)
        self.deployment.load()
        with self.assertRaisesRegex(deployment.DeploymentError, "stale, changed"):
            self.apply(plan)
        for mode, value in (
            ("reserved", None),
            ("reserved", 0),
            ("reserved", True),
            ("unreserved", 10),
        ):
            with (
                self.subTest(mode=mode, value=value),
                self.assertRaises(deployment.DeploymentError),
            ):
                self.deployment.concurrency(mode, value)

    def test_shared_pool_survives_plan_apply_readback_and_rollback(self):
        self.deployment.concurrency("unreserved", None)
        first = self.planned(IMAGE_A)
        self.assertEqual(self.apply(first)["status"], "healthy")
        self.assertEqual(self.deployment.outputs()["reserved_concurrency"], -1)
        second = self.planned(IMAGE_B)
        self.assertEqual(self.apply(second)["status"], "healthy")
        rollback = self.planned(IMAGE_A, "rollback")
        self.assertEqual(self.apply(rollback)["status"], "healthy")
        self.assertEqual(self.deployment.live_reserved, 0)

    def test_capacity_drift_after_plan_blocks_before_terraform_apply(self):
        plan = self.planned()
        self.deployment.calls.clear()
        with patch.object(
            self.deployment,
            "capacity",
            side_effect=deployment.DeploymentError("Shared capacity exhausted"),
        ):
            with self.assertRaisesRegex(deployment.DeploymentError, "exhausted"):
                self.apply(plan)
        self.assertFalse(any(kind == "tf" for kind, _ in self.deployment.calls))

    def test_live_reservation_mismatch_is_not_a_healthy_result(self):
        self.seed()
        self.deployment.live_reserved = 5
        with self.assertRaisesRegex(deployment.DeploymentError, "concurrency differ"):
            self.deployment.verify_capacity(self.deployment.outputs())

    def test_state_and_settings_scope_cannot_be_silently_changed(self):
        self.seed()
        state = deployment.read_json(self.deployment.state)
        state["outputs"]["deployment_context"]["value"]["environment"] = "prod"
        deployment.write_json(self.deployment.state, state)
        with self.assertRaisesRegex(deployment.DeploymentError, "context"):
            self.planned()
        self.deployment.settings["reserved_concurrency"] = 0
        deployment.write_json(self.deployment.settings_path, self.deployment.settings)
        with self.assertRaisesRegex(deployment.DeploymentError, "Invalid deployment settings"):
            self.deployment.load()

    def test_lock_prevents_parallel_mutation(self):
        other = FakeDeployment(self.root)
        with (
            self.deployment.locked(),
            self.assertRaisesRegex(deployment.DeploymentError, "Another deployment"),
        ):
            with other.locked():
                self.fail("Lock was bypassed")

    def test_image_requires_own_account_region_repository_and_digest(self):
        with patch("devsecops_cli.deployment.verify_ecr_lambda_image") as verify:
            deployment.Deployment.check_image(self.deployment, IMAGE_A)
            verify.assert_called_once()
            for image in (
                IMAGE_A.replace(ACCOUNT, "999999999999"),
                IMAGE_A.replace(REGION, "us-east-1"),
                IMAGE_A.replace(PROJECT, "other"),
                REPOSITORY + ":release-a",
            ):
                with self.subTest(image=image), self.assertRaises(deployment.DeploymentError):
                    deployment.Deployment.check_image(self.deployment, image)

    def test_plan_binds_image_source_state_and_settings(self):
        self.seed()
        result = self.planned()
        directory, review = self.deployment.reviewed(result["plan_id"], result["sha256"])
        self.assertEqual(review["previous"]["image_uri"], IMAGE_A)
        self.assertEqual(review["image_uri"], IMAGE_B)
        self.assertEqual(
            review["files"]["plan.tfplan"], deployment.digest(directory / "plan.tfplan")
        )
        self.assertGreater(self.deployment.health_calls, 0)
        self.assertEqual(result["kind"], "deployment")

    def test_changed_bundle_or_context_is_rejected_before_apply(self):
        for changed in (
            "plan.tfplan",
            "plan.json",
            "plan.txt",
            "inputs.tfvars.json",
            "source",
            "state",
            "settings",
        ):
            with self.subTest(changed=changed):
                self.seed()
                result = self.planned()
                directory = self.deployment.home / "plans" / result["plan_id"]
                path = {
                    "source": self.root / "terraform/main.tf",
                    "state": self.deployment.state,
                    "settings": self.deployment.settings_path,
                }.get(changed, directory / changed)
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                self.deployment.calls.clear()
                with self.assertRaisesRegex(deployment.DeploymentError, "stale, changed"):
                    self.apply(result)
                self.assertFalse(self.deployment.calls)
                path.write_bytes(original)

    def test_expired_wrong_hash_and_replayed_plan_are_rejected(self):
        result = self.planned()
        with self.assertRaisesRegex(deployment.DeploymentError, "SHA-256 differs"):
            self.deployment.apply(result["plan_id"], "0" * 64, True)
        directory = self.deployment.home / "plans" / result["plan_id"]
        path = directory / "review.json"
        review = deployment.read_json(path)
        review["expires_at"] = 0
        deployment.write_json(path, review)
        result["sha256"] = deployment.digest(path)
        with self.assertRaisesRegex(deployment.DeploymentError, "stale"):
            self.apply(result)
        result = self.planned()
        self.assertEqual(self.apply(result)["status"], "healthy")
        with self.assertRaisesRegex(deployment.DeploymentError, "stale"):
            self.apply(result)

    def test_noninteger_plan_schema_is_rejected_before_provider_calls(self):
        result = self.planned()
        path = self.deployment.home / "plans" / result["plan_id"] / "review.json"
        review = deployment.read_json(path)
        for value in (2.0, True, "2", None):
            with self.subTest(schema=value):
                deployment.write_json(path, {**review, "schema_version": value})
                self.deployment.calls.clear()
                with self.assertRaisesRegex(deployment.DeploymentError, "stale"):
                    self.deployment.apply(result["plan_id"], deployment.digest(path), True)
                self.assertFalse(self.deployment.calls)

    def test_preview_never_applies_and_saved_binary_is_used(self):
        result = self.planned()
        self.deployment.calls.clear()
        self.assertEqual(self.apply(result, yes=False)["status"], "review-required")
        self.assertFalse(self.deployment.calls)
        self.assertEqual(self.apply(result)["status"], "healthy")
        applied = [
            args for kind, args in self.deployment.calls if kind == "tf" and args[0] == "apply"
        ]
        self.assertEqual(len(applied), 1)
        self.assertTrue(applied[0][-1].endswith("/" + result["plan_id"] + "/plan.tfplan"))
        self.assertNotIn("-auto-approve", applied[0])

    def test_live_drift_blocks_saved_apply(self):
        self.seed()
        result = self.planned()
        self.deployment.live_image = IMAGE_B
        with self.assertRaisesRegex(deployment.DeploymentError, "Live Lambda changed"):
            self.apply(result)

    def test_registry_is_separate_and_low_quota_blocks_workload(self):
        result = self.deployment.plan("registry")
        self.assertEqual(self.apply(result)["status"], "registry-ready")

        def low_quota(args, **kwargs):
            return (
                {"AccountLimit": {"ConcurrentExecutions": 10, "UnreservedConcurrentExecutions": 10}}
                if args[1] == "get-account-settings"
                else {}
            )

        with patch.object(self.deployment, "aws", side_effect=low_quota):
            with self.assertRaisesRegex(deployment.DeploymentError, "maximum allocatable=0"):
                self.deployment.capacity()

    def test_failed_health_restores_previous_digest_and_state_but_remains_failure(self):
        self.seed()
        result = self.planned(IMAGE_C)
        with patch("devsecops_cli.deployment.time.sleep"):
            outcome = self.apply(result)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["recovery"]["status"], "recovered")
        self.assertEqual(self.deployment.live_image, IMAGE_A)
        self.assertEqual(self.deployment.outputs()["image_uri"], IMAGE_A)
        proof = deployment.read_json(self.deployment.event_dir / "result.json")
        self.assertEqual(proof["status"], "failed")
        self.assertTrue((self.deployment.event_dir / "SHA256SUMS.json").is_file())

    def test_apply_failure_and_interrupt_recover_known_function(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                self.seed()
                result = self.planned()
                self.deployment.interrupt = interrupted
                self.deployment.apply_error = not interrupted
                outcome = self.apply(result)
                self.assertEqual(outcome["status"], "failed")
                self.assertEqual(outcome["recovery"]["status"], "recovered")
                self.assertEqual(outcome["interrupted"], interrupted)
                self.deployment.apply_error = False

    def test_first_failure_keeps_state_and_failed_recovery_is_explicit(self):
        result = self.planned(IMAGE_C)
        with patch("devsecops_cli.deployment.time.sleep"):
            outcome = self.apply(result)
        self.assertEqual(outcome["recovery"]["status"], "manual-attention")
        self.assertTrue(self.deployment.state.exists())
        self.seed()
        result = self.planned(IMAGE_C)
        self.deployment.recovery_error = True
        with patch("devsecops_cli.deployment.time.sleep"):
            outcome = self.apply(result)
        self.assertEqual(outcome["recovery"]["status"], "recovery-failed")
        self.assertEqual(outcome["status"], "failed")

    def test_manual_rollback_is_a_reviewed_healthy_deploy(self):
        self.seed(IMAGE_B)
        result = self.planned(IMAGE_A, "rollback")
        self.assertEqual(self.apply(result)["status"], "healthy")
        self.assertEqual(self.deployment.live_image, IMAGE_A)

    def test_destroy_uses_explicit_plan_and_retains_evidence(self):
        self.seed()
        result = self.deployment.plan("destroy")
        self.assertIn(
            "-destroy",
            next(
                args for kind, args in self.deployment.calls if kind == "tf" and args[0] == "plan"
            ),
        )
        self.assertEqual(self.apply(result, yes=False)["status"], "review-required")
        self.assertEqual(self.apply(result)["status"], "destroyed")
        self.assertTrue(self.deployment.settings_path.is_file())
        self.assertTrue((self.deployment.event_dir / "result.json").is_file())

    def test_plan_scope_rejects_imports_foreign_tags_and_unreviewed_deletion(self):
        valid = {
            "address": "module.ecr.aws_ecr_repository.lambda_repo",
            "change": {"actions": ["create"]},
        }
        for change in (
            {**valid, "address": "aws_s3_bucket.production"},
            {**valid, "change": {"actions": ["delete", "create"]}},
            {**valid, "change": {"actions": ["create"], "importing": {"id": "foreign"}}},
            {**valid, "change": {"actions": ["create"], "after": {"tags": {"Project": "foreign"}}}},
        ):
            with self.subTest(change=change), self.assertRaises(deployment.DeploymentError):
                deployment.check_plan({"resource_changes": [change]}, "workload", PROJECT)
        workload = {**valid, "address": "module.lambda.aws_lambda_function.workload"}
        with self.assertRaises(deployment.DeploymentError):
            deployment.check_plan({"resource_changes": [workload]}, "registry", PROJECT)
        with self.assertRaises(deployment.DeploymentError):
            deployment.check_plan({"resource_changes": [valid]}, "destroy", PROJECT)

    def test_terraform_environment_cannot_inject_arguments_variables_or_credentials(self):
        with patch.dict(
            os.environ,
            {
                "TF_CLI_ARGS": "-destroy",
                "TF_VAR_project_name": "production",
                "AWS_ACCESS_KEY_ID": "sentinel-key",
                "AWS_SECRET_ACCESS_KEY": "sentinel-secret",
                "AWS_CONFIG_FILE": "/should-not-replace-saved-config",
            },
        ):
            env = self.deployment.tf_env()
        self.assertNotIn("TF_CLI_ARGS", env)
        self.assertNotIn("TF_VAR_project_name", env)
        self.assertNotIn("AWS_ACCESS_KEY_ID", env)
        self.assertEqual(env["TF_WORKSPACE"], "default")
        self.assertTrue(env["TF_DATA_DIR"].startswith(str(self.deployment.home)))
        helper = (self.deployment.home / "credentials.py").read_text()
        self.assertNotIn("sentinel-key", helper)
        self.assertNotIn("sentinel-secret", helper)
        self.assertIn("named-source", helper)
        self.assertNotIn("kit-runtime", helper)

    def test_secret_process_output_never_enters_evidence(self):
        completed = subprocess.CompletedProcess([], 0, '{"AccessKeyId":"sentinel-private-key"}', "")
        with patch("devsecops_cli.deployment.subprocess.run", return_value=completed):
            value = deployment.Deployment.aws(
                self.deployment,
                ["configure", "export-credentials", "--format", "process"],
                secret=True,
            )
        self.assertEqual(value["AccessKeyId"], "sentinel-private-key")
        self.assertFalse(
            any(
                "sentinel-private-key" in path.read_text()
                for path in self.deployment.event_dir.iterdir()
            )
        )

    def test_human_terraform_progress_is_real_and_preserved(self):
        output = []
        self.deployment.progress = output.append

        class Process:
            returncode = 0
            stdout = io.StringIO("Creating resource...\nCreation complete\n")

            def wait(self):
                return 0

        with patch("devsecops_cli.deployment.subprocess.Popen", return_value=Process()):
            result = self.deployment.run(
                ["terraform", "-chdir=fixture", "apply", "saved.tfplan"], {}
            )
        self.assertIn("Creation complete", output)
        self.assertIn("Creating resource...\n", result.stdout)
        record = deployment.read_json(self.deployment.event_dir / "command-001.json")
        self.assertEqual(record["stdout"], result.stdout)

    def test_request_rejects_arbitrary_paths_bodies_and_endpoint(self):
        for method, path, body in (
            ("GET", "https://evil.example", None),
            ("GET", "/version", "{}"),
            ("POST", "/analyze", "[]"),
            ("POST", "/analyze", "x" * 65537),
        ):
            with (
                self.subTest(method=method, path=path),
                self.assertRaises(deployment.DeploymentError),
            ):
                deployment.Deployment.request(self.deployment, method, path, body)
        self.seed()
        with patch.object(
            self.deployment, "outputs", return_value={"api_endpoint": "https://evil.example"}
        ):
            with self.assertRaisesRegex(deployment.DeploymentError, "regional deployment API"):
                deployment.Deployment.request(self.deployment, "GET", "/version")

    def test_signed_post_and_response_are_recorded_without_credentials(self):
        self.seed()

        class Response(io.BytesIO):
            code = 200

        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.method, "POST")
                self.assertEqual(request.data, b'{"text":"hi"}')
                self.assertIn("AWS4-HMAC-SHA256", request.headers["Authorization"])
                return Response(b'{"words":1}')

        def aws(args, **kwargs):
            if args[:2] == ["apigatewayv2", "get-api"]:
                return {"Name": PROJECT + "-dev-http-api", "Tags": {"Project": PROJECT}}
            if args[:2] == ["apigatewayv2", "get-routes"]:
                return {
                    "Items": [
                        {
                            "RouteKey": "$default",
                            "AuthorizationType": "AWS_IAM",
                            "Target": "integrations/abc",
                        }
                    ]
                }
            if args[:2] == ["apigatewayv2", "get-integration"]:
                return {
                    "IntegrationType": "AWS_PROXY",
                    "PayloadFormatVersion": "2.0",
                    "IntegrationUri": ARN,
                }
            self.assertTrue(kwargs.get("secret"))
            return {
                "AccessKeyId": "sentinel-access",
                "SecretAccessKey": "sentinel-secret",
                "SessionToken": "sentinel-token",
            }

        with (
            patch.object(self.deployment, "aws", side_effect=aws),
            patch("devsecops_cli.deployment.urllib.request.build_opener", return_value=Opener()),
        ):
            result = deployment.Deployment.request(
                self.deployment, "POST", "/analyze", '{"text":"hi"}'
            )
        self.assertEqual(result["status"], 200)
        for path in self.deployment.event_dir.iterdir():
            self.assertNotIn("sentinel-", path.read_text())

    def test_live_auth_or_integration_drift_blocks_signed_request(self):
        self.seed()
        for route, integration in (
            (
                {"RouteKey": "$default", "AuthorizationType": "NONE", "Target": "integrations/abc"},
                {},
            ),
            (
                {
                    "RouteKey": "$default",
                    "AuthorizationType": "AWS_IAM",
                    "Target": "integrations/abc",
                },
                {
                    "IntegrationType": "AWS_PROXY",
                    "PayloadFormatVersion": "2.0",
                    "IntegrationUri": "foreign",
                },
            ),
        ):

            def aws(args, **kwargs):
                if args[1] == "get-api":
                    return {"Name": PROJECT + "-dev-http-api", "Tags": {"Project": PROJECT}}
                if args[1] == "get-routes":
                    return {"Items": [route]}
                if args[1] == "get-integration":
                    return integration
                self.fail("Credentials must not be exported for a drifted API")

            with (
                patch.object(self.deployment, "aws", side_effect=aws),
                self.assertRaises(deployment.DeploymentError),
            ):
                deployment.Deployment.request(self.deployment, "GET", "/health")

    def test_sigv4_payload_changes_signature_and_does_not_use_ambient_keys(self):
        url = f"https://abc.execute-api.{REGION}.amazonaws.com/analyze"
        credentials = {"AccessKeyId": "named-access", "SecretAccessKey": "named-secret"}
        now = dt.datetime(2026, 11, 10, tzinfo=dt.UTC)
        a, error = aws_sigv4_headers(
            url, REGION, now, method="POST", payload=b"a", credentials=credentials
        )
        b, _ = aws_sigv4_headers(
            url, REGION, now, method="POST", payload=b"b", credentials=credentials
        )
        self.assertIsNone(error)
        self.assertNotEqual(a["Authorization"], b["Authorization"])
        self.assertIn("Credential=named-access/", a["Authorization"])

    def test_parser_and_json_failure_exit_are_available(self):
        args = cli.build_parser().parse_args(
            ["plan", "diploma", "--stage", "workload", "--image-uri", IMAGE_A]
        )
        self.assertEqual(args.command, "plan")
        self.assertEqual(args.stage, "workload")
        payload = {"kind": "deployment", "status": "failed", "error": "quota"}
        with (
            patch.object(cli.deployment, "execute", return_value=payload),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = cli.main(["status", "diploma", "--format", "json"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "quota")

    def test_missing_executable_has_documented_exit_code(self):
        with (
            patch("devsecops_cli.deployment.subprocess.run", side_effect=FileNotFoundError()),
            self.assertRaises(deployment.DeploymentToolError),
        ):
            self.deployment.run(["missing-terraform"], {})
        with (
            patch.object(
                cli.deployment,
                "execute",
                side_effect=deployment.DeploymentToolError("Install Terraform"),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = cli.main(["status", "diploma", "--format", "json"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
