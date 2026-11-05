"""Deployment journey tests from domain contracts through workflow integration.

Fixtures model GitHub and AWS responses locally.  The tests verify pure run
selection and journal behavior, CLI orchestration boundaries, and the tracked
workflow contract without dispatching a workflow or contacting cloud services.
"""

import argparse
import copy
import hashlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import urllib.request
import urllib.response
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import aws as aws_provider, config, deploy, recovery
from devsecops_cli import main as cli


ROOT_DIR = Path(__file__).resolve().parents[2]
IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-new"
IMAGE_DIGEST = IMAGE.rsplit(":", 1)[0] + "@sha256:" + "b" * 64
PREVIOUS_IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-old"
PREVIOUS_DIGEST = PREVIOUS_IMAGE.rsplit(":", 1)[0] + "@sha256:" + "a" * 64
COMMIT_SHA = "a" * 40
REQUEST_ID = "a" * 32
FUNCTION_ARN = "arn:aws:lambda:us-east-1:123456789012:function:devsecops-pipeline-prod-lambda"


def deployment_config() -> dict[str, object]:
    """Return a production-ready config with deterministic deployment inputs."""

    cfg = cli.preset_config("enterprise")
    cfg["lambda_image_uri"] = IMAGE
    cfg["backend"]["bucket"] = "devsecops-pipeline-tfstate"
    cfg["backend"]["lock_table"] = "devsecops-pipeline-locks"
    return cfg


def fixture_intent(image_uri, cfg=None):
    cfg = cfg if cfg is not None else deployment_config()
    digest_uri = IMAGE_DIGEST if image_uri == IMAGE else image_uri
    return deploy.DeploymentIntent("acme/pipeline", COMMIT_SHA, config.deployment_config_sha256(cfg, digest_uri), digest_uri, REQUEST_ID), cfg


def create_deployment_project(root: Path) -> dict[str, object]:
    """Create the minimum complete checkout signals needed by preflight tests."""

    cfg = deployment_config()
    cli.write_config(root, cfg)
    for relative in cli.REQUIRED_PROJECT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# project file\n", encoding="utf-8")
    for path, content in cli.render_outputs(root, cfg).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return cfg


def workflow_run(
    run_id: int = 42,
    *,
    operation: str = "deploy",
    request_id: str = "",
    status: str = "completed",
    conclusion: str = "success",
) -> dict[str, object]:
    """Build a normalized GitHub Actions run fixture for one operation."""

    return {
        "databaseId": run_id,
        "workflowName": deploy.DEPLOYMENT_WORKFLOW_NAME,
        "displayTitle": f"DevSecOps {operation} prod" + (f" [{request_id}]" if request_id else ""),
        "event": "workflow_dispatch",
        "headBranch": "main",
        "headSha": COMMIT_SHA,
        "attempt": 1,
        "status": status,
        "conclusion": conclusion,
        "createdAt": "2026-08-29T10:00:00Z",
        "updatedAt": "2026-08-29T10:05:00Z",
        "url": f"https://github.com/acme/pipeline/actions/runs/{run_id}",
        "jobs": [
            {
                "name": "Manual Apply, Deploy, or Roll Back Production",
                "status": status,
                "conclusion": conclusion,
                "startedAt": "2026-08-29T10:00:00Z",
                "completedAt": "2026-08-29T10:05:00Z",
                "steps": [{"name": step, "conclusion": conclusion} for step in (
                    ("Terraform apply workload with configured Lambda image", "Smoke test Lambda health endpoint")
                    if operation == "deploy" else ("Restore requested Lambda image",)
                )],
            }
        ],
    }


class DeploymentDomainTests(unittest.TestCase):
    """Verify provider-independent dispatch, journal, and run-selection rules."""

    def test_dispatch_contract_binds_exact_image_and_protected_ref(self) -> None:
        intent, _ = fixture_intent(IMAGE)
        args = deploy.workflow_dispatch_args("deploy", intent)

        self.assertEqual(args[:5], ["workflow", "run", "deploy.yml", "--ref", "main"])
        self.assertEqual(deploy.DEPLOYMENT_WORKFLOW_PATH, ".github/workflows/deploy.yml")
        self.assertIn("mode=deploy", args)
        self.assertIn("environment=prod", args)
        self.assertIn(f"image_uri={IMAGE_DIGEST}", args)
        self.assertIn(f"commit_sha={intent.commit_sha}", args)
        self.assertIn(f"config_sha256={intent.config_sha256}", args)
        self.assertEqual(args[args.index("--repo") + 1], intent.repository)
        self.assertIn("gh workflow run", deploy.display_gh_command(args))
        list_args = deploy.workflow_run_list_args()
        self.assertEqual(list_args[list_args.index("--event") + 1], "workflow_dispatch")
        self.assertEqual(list_args[list_args.index("--branch") + 1], "main")

    def test_deployment_state_is_schema_versioned_non_secret_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            deploy.record_deployment(
                root,
                {
                    "operation": "deploy",
                    "requested_image_uri": IMAGE,
                    "previous_image_uri": PREVIOUS_IMAGE,
                    "run_id": "42",
                    "run_url": "https://github.com/acme/pipeline/actions/runs/42",
                    "token": "must-not-be-written",
                },
            )

            state = deploy.load_deployment_state(root)
            text = deploy.deployment_state_path(root).read_text(encoding="utf-8")
            mode = stat.S_IMODE(os.stat(deploy.deployment_state_path(root)).st_mode)

        self.assertEqual(state["schema_version"], deploy.DEPLOYMENT_STATE_SCHEMA_VERSION)
        self.assertEqual(state["deployments"][0]["run_id"], "42")
        self.assertNotIn("token", text)
        self.assertNotIn("must-not-be-written", text)
        self.assertEqual(mode, 0o600)

    def test_future_deployment_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = deploy.deployment_state_path(root)
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"schema_version": deploy.DEPLOYMENT_STATE_SCHEMA_VERSION + 1, "deployments": []}),
                encoding="utf-8",
            )
            with self.assertRaises(deploy.DeploymentStateError):
                deploy.load_deployment_state(root)

    def test_run_url_and_named_run_selection_ignore_unrelated_manual_runs(self) -> None:
        output = "Created workflow dispatch: https://github.com/acme/pipeline/actions/runs/987\n"
        unrelated = workflow_run(11)
        unrelated["displayTitle"] = "Manual plan"
        matching = workflow_run(12, operation="rollback", status="queued", conclusion="")

        self.assertEqual(deploy.parse_run_url(output), ("987", output.strip().split()[-1]))
        self.assertEqual(deploy.newest_deployment_run([unrelated, matching]), matching)
        self.assertEqual(deploy.parse_run_url(output, "another/repository"), ("", ""))

    def test_dispatched_run_fallback_matches_only_one_exact_request(self) -> None:
        record = {"operation": "deploy", "request_id": REQUEST_ID, "repository": "acme/pipeline", "commit_sha": COMMIT_SHA}
        matching = workflow_run(12, request_id=REQUEST_ID)
        other_request = workflow_run(13, request_id="b" * 32)
        wrong_commit = dict(workflow_run(14, request_id=REQUEST_ID), headSha="b" * 40)
        self.assertEqual(deploy.select_dispatched_run([other_request, wrong_commit, matching], record), matching)
        self.assertIsNone(deploy.select_dispatched_run([other_request, wrong_commit], record))
        self.assertIsNone(deploy.select_dispatched_run([matching, workflow_run(15, request_id=REQUEST_ID)], record))

    def test_json_status_infers_operation_without_local_journal(self) -> None:
        payload = deploy.deployment_status_payload(workflow_run(operation="rollback"))

        self.assertEqual(payload["operation"], "rollback")

    def test_active_run_detection_is_conservative_for_old_workflow_titles(self) -> None:
        old_run = workflow_run(21, status="in_progress", conclusion="")
        old_run["displayTitle"] = "Legacy manual dispatch"

        self.assertEqual(deploy.active_deployment_runs([old_run]), [old_run])

    def test_parallel_journal_updates_preserve_all_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, ThreadPoolExecutor(max_workers=8) as pool:
            root = Path(tmpdir)
            records = [{"operation": "deploy", "request_id": f"{index:032x}"} for index in range(12)]
            list(pool.map(lambda record: deploy.record_deployment(root, record), records))
            deploy.record_deployment(root, dict(records[0], run_id="42"))
            saved = deploy.load_deployment_state(root)["deployments"]
            self.assertEqual(len(saved), len(records))
            self.assertEqual(deploy.latest_deployment(root, "42")["request_id"], records[0]["request_id"])


class DeploymentCommandTests(unittest.TestCase):
    """Verify CLI orchestration while replacing every external provider call."""

    def setUp(self):
        review = patch.object(cli, "review_deployment_intent", side_effect=lambda root, image, cfg=None: fixture_intent(image, cfg))
        review.start()
        self.addCleanup(review.stop)

    # Provider inspection and public parser surface.
    def test_active_image_inspection_uses_resolved_digest(self) -> None:
        cfg = deployment_config()
        completed = subprocess.CompletedProcess(["aws"], 0, "", "")
        with patch.object(cli, "command_exists", return_value=True), patch.object(
            cli,
            "aws_json",
            return_value=({"Code": {"ImageUri": PREVIOUS_IMAGE, "ResolvedImageUri": PREVIOUS_DIGEST}}, completed),
        ) as aws_json:
            image_uri, error = cli.inspect_active_lambda_image(Path("/tmp/project"), cfg)

        self.assertEqual(image_uri, PREVIOUS_DIGEST)
        self.assertIsNone(error)
        self.assertEqual(aws_json.call_args.args[1][:2], ["lambda", "get-function"])

    def test_deploy_group_and_subcommands_have_public_help(self) -> None:
        for argv in (
            ["deploy", "--help"],
            ["deploy", "prod", "--help"],
            ["deploy", "status", "--help"],
            ["deploy", "logs", "--help"],
            ["deploy", "rollback", "--help"],
        ):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(argv)
            self.assertEqual(raised.exception.code, 0)

    # Production preflight, confirmation, dispatch, and optional watch flow.
    def test_production_preflight_can_be_ready_and_blocks_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = create_deployment_project(root)
            connected = [
                cli.Check("GitHub CLI", "OK", "Installed."),
                cli.Check("GitHub auth", "OK", "Authenticated."),
                cli.Check("GitHub repository", "OK", "acme/pipeline"),
                cli.Check("GitHub variable LAMBDA_IMAGE_URI", "WARN", "Expected an older image."),
            ]
            protected = [cli.Check("Branch `main` protection", "OK", "Enabled.")]
            with patch.object(cli, "collect_github_checks", return_value=connected), patch.object(
                cli, "collect_branch_checks", return_value=protected
            ):
                ready = cli.production_deployment_preflight_checks(root, cfg, [], None, PREVIOUS_IMAGE, None)
                blocked = cli.production_deployment_preflight_checks(
                    root,
                    cfg,
                    [workflow_run(7, status="in_progress", conclusion="")],
                    None,
                    PREVIOUS_IMAGE,
                    None,
                )

        self.assertFalse([check for check in ready if check.scored and check.status != "OK"])
        image_variable = next(check for check in ready if check.name == "GitHub variable LAMBDA_IMAGE_URI")
        self.assertEqual(image_variable.status, "INFO")
        self.assertFalse(image_variable.scored)
        self.assertEqual(
            next(check for check in blocked if check.name == "Concurrent production run").status,
            "FAIL",
        )

    def test_deploy_prod_dry_run_never_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "list_deployment_runs", return_value=([], None)
            ), patch.object(cli, "inspect_active_lambda_image", return_value=(PREVIOUS_IMAGE, None)), patch.object(
                cli,
                "production_deployment_preflight_checks",
                return_value=[cli.Check("Ready", "OK", "Ready.")],
            ), patch.object(cli, "dispatch_deployment_workflow") as dispatch, redirect_stdout(io.StringIO()) as buffer:
                result = cli.main(["deploy", "prod", "--dry-run"])

        self.assertEqual(result, cli.EXIT_OK)
        dispatch.assert_not_called()
        self.assertIn("No workflow was dispatched", buffer.getvalue())

    def test_deploy_prod_dispatches_records_and_never_hides_underlying_command(self) -> None:
        url = "https://github.com/acme/pipeline/actions/runs/42"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            completed = subprocess.CompletedProcess(["gh"], 0, url + "\n", "")
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "list_deployment_runs", return_value=([], None)
            ), patch.object(cli, "inspect_active_lambda_image", return_value=(PREVIOUS_IMAGE, None)), patch.object(
                cli,
                "production_deployment_preflight_checks",
                return_value=[cli.Check("Ready", "OK", "Ready.")],
            ), patch.object(cli, "dispatch_deployment_workflow", return_value=completed) as dispatch, redirect_stdout(
                io.StringIO()
            ) as buffer:
                result = cli.main(["deploy", "prod", "--yes"])
            state = deploy.load_deployment_state(root)

        self.assertEqual(result, cli.EXIT_OK)
        intent, _ = fixture_intent(IMAGE)
        dispatch.assert_called_once_with(root, "deploy", intent)
        self.assertEqual(state["deployments"][0]["requested_image_uri"], IMAGE_DIGEST)
        self.assertEqual(state["deployments"][0]["commit_sha"], intent.commit_sha)
        self.assertEqual(state["deployments"][0]["config_sha256"], intent.config_sha256)
        self.assertEqual(state["deployments"][0]["previous_image_uri"], "")
        self.assertEqual(state["deployments"][0]["request_id"], REQUEST_ID)
        self.assertEqual(state["deployments"][0]["run_id"], "42")
        self.assertIn("Underlying GitHub command", buffer.getvalue())
        self.assertIn("image_uri=", buffer.getvalue())

    def test_deploy_prod_watch_accepts_streamed_completed_process(self) -> None:
        url = "https://github.com/acme/pipeline/actions/runs/42"
        dispatch_result = subprocess.CompletedProcess(["gh"], 0, url + "\n", "")
        streamed_watch = subprocess.CompletedProcess(["gh"], 0, None, None)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "list_deployment_runs", return_value=([], None)
            ), patch.object(cli, "inspect_active_lambda_image", return_value=(PREVIOUS_IMAGE, None)), patch.object(
                cli,
                "production_deployment_preflight_checks",
                return_value=[cli.Check("Ready", "OK", "Ready.")],
            ), patch.object(cli, "dispatch_deployment_workflow", return_value=dispatch_result), patch.object(
                cli, "watch_deployment_run", return_value=streamed_watch
            ) as watch, patch.object(cli, "view_deployment_run", return_value=(workflow_run(request_id=REQUEST_ID), None)), redirect_stdout(
                io.StringIO()
            ):
                result = cli.main(["deploy", "prod", "--yes", "--watch"])

        self.assertEqual(result, cli.EXIT_OK)
        watch.assert_called_once_with(root, "42", 5, stream=True, repository="acme/pipeline")

    def test_deploy_prod_requires_confirmation_without_yes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "list_deployment_runs", return_value=([], None)
            ), patch.object(cli, "inspect_active_lambda_image", return_value=(PREVIOUS_IMAGE, None)), patch.object(
                cli,
                "production_deployment_preflight_checks",
                return_value=[cli.Check("Ready", "OK", "Ready.")],
            ), patch("builtins.input", return_value="no"), patch.object(
                cli, "dispatch_deployment_workflow"
            ) as dispatch, redirect_stdout(io.StringIO()):
                result = cli.main(["deploy", "prod"])

        self.assertEqual(result, cli.EXIT_OK)
        dispatch.assert_not_called()

    # Status and log commands must remain correlated with the journaled run and
    # must not mix streamed human progress into machine-readable JSON.
    def test_deploy_status_uses_recorded_run_and_emits_clean_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            deploy.record_deployment(
                root,
                {
                    "operation": "deploy",
                    "requested_image_uri": IMAGE,
                    "previous_image_uri": PREVIOUS_IMAGE,
                    "run_id": "42",
                    "run_url": "https://github.com/acme/pipeline/actions/runs/42",
                },
            )
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "view_deployment_run", return_value=(workflow_run(), None)
            ) as view, patch.object(cli, "inspect_active_lambda_image", return_value=(IMAGE, None)), redirect_stdout(
                io.StringIO()
            ) as buffer:
                result = cli.main(["deploy", "status", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, cli.EXIT_OK)
        view.assert_called_once_with(root, "42")
        self.assertEqual(payload["kind"], "deployment-status")
        self.assertEqual(payload["operation"], "deploy")
        self.assertEqual(payload["run"]["databaseId"], 42)
        self.assertEqual(payload["active_image_uri"], IMAGE)

    def test_deploy_status_watch_keeps_json_clean(self) -> None:
        active = workflow_run(status="in_progress", conclusion="")
        completed_run = workflow_run(status="completed", conclusion="success")
        watched = subprocess.CompletedProcess(["gh"], 0, "interactive progress that must stay hidden\n", "")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            deploy.record_deployment(
                root,
                {"operation": "deploy", "requested_image_uri": IMAGE, "run_id": "42"},
            )
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "view_deployment_run", side_effect=[(active, None), (completed_run, None)]
            ), patch.object(cli, "watch_deployment_run", return_value=watched) as watch, patch.object(
                cli, "inspect_active_lambda_image", return_value=(IMAGE, None)
            ), redirect_stdout(io.StringIO()) as buffer:
                result = cli.main(["deploy", "status", "--watch", "--format", "json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, cli.EXIT_OK)
        watch.assert_called_once_with(root, "42", 5, stream=False)
        self.assertEqual(payload["run"]["status"], "completed")
        self.assertNotIn("interactive progress", buffer.getvalue())

    def test_failed_status_points_to_logs_for_the_exact_run(self) -> None:
        failed = workflow_run(status="completed", conclusion="failure")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            deploy.record_deployment(
                root,
                {
                    "operation": "deploy",
                    "requested_image_uri": IMAGE,
                    "previous_image_uri": PREVIOUS_IMAGE,
                    "run_id": "42",
                },
            )
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "view_deployment_run", return_value=(failed, None)
            ), patch.object(cli, "inspect_active_lambda_image", return_value=(PREVIOUS_IMAGE, None)), redirect_stdout(
                io.StringIO()
            ) as buffer:
                result = cli.main(["deploy", "status"])

        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertIn("devsecops deploy logs --run-id 42 --failed", buffer.getvalue())

    def test_deploy_logs_selects_same_run_and_failed_log_scope(self) -> None:
        logs = subprocess.CompletedProcess(["gh"], 0, "failed log\n", "")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "resolve_deployment_run", return_value=(workflow_run(), None, None)
            ), patch.object(cli, "read_deployment_logs", return_value=logs) as read, redirect_stdout(
                io.StringIO()
            ) as buffer:
                result = cli.main(["deploy", "logs", "--failed"])

        self.assertEqual(result, cli.EXIT_OK)
        read.assert_called_once_with(root, "42", failed_only=True)
        self.assertIn("gh run view 42 --log-failed", buffer.getvalue())
        self.assertIn("failed log", buffer.getvalue())
        self.assertIn("Next command: devsecops health --aws-sigv4", buffer.getvalue())

    def test_failed_deploy_logs_require_a_reviewed_rollback_image(self) -> None:
        logs = subprocess.CompletedProcess(["gh"], 0, "failed log\n", "")
        record = {"previous_image_uri": PREVIOUS_IMAGE}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli,
                "resolve_deployment_run",
                return_value=(workflow_run(status="completed", conclusion="failure"), record, None),
            ), patch.object(cli, "read_deployment_logs", return_value=logs), redirect_stdout(io.StringIO()) as buffer:
                result = cli.main(["deploy", "logs", "--failed"])

        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("Next command: devsecops deploy rollback --image-uri", buffer.getvalue())

    # Rollback reuses the protected workflow and requires either journaled or
    # explicit immutable target evidence before any provider call.
    def test_deploy_rollback_uses_previous_image_through_protected_workflow(self) -> None:
        url = "https://github.com/acme/pipeline/actions/runs/43"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            deploy.record_deployment(
                root,
                {
                    "operation": "deploy",
                    "requested_image_uri": IMAGE,
                    "previous_image_uri": "wrong-local-observation",
                    "run_id": "42",
                },
            )
            point = {"repository": "acme/pipeline", "run_id": "42", "deployed_image_uri": IMAGE_DIGEST,
                     "previous_image_uri": PREVIOUS_DIGEST, "function_arn": FUNCTION_ARN}
            completed = subprocess.CompletedProcess(["gh"], 0, url + "\n", "")
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "list_deployment_runs", return_value=([], None)
            ), patch.object(cli, "inspect_active_lambda_image", return_value=(IMAGE_DIGEST, None)), patch.object(
                cli, "view_deployment_run", return_value=(workflow_run(), None)
            ), patch.object(cli, "read_deployment_recovery_point", return_value=point), patch.object(
                cli,
                "rollback_deployment_preflight_checks",
                return_value=[cli.Check("Ready", "OK", "Ready.")],
            ), patch.object(cli, "dispatch_deployment_workflow", return_value=completed) as dispatch, redirect_stdout(
                io.StringIO()
            ):
                result = cli.main(["deploy", "rollback", "--yes"])
            state = deploy.load_deployment_state(root)

        self.assertEqual(result, cli.EXIT_OK)
        dispatch.assert_called_once_with(root, "rollback", replace(
            fixture_intent(PREVIOUS_DIGEST)[0], rollback_from_image_uri=IMAGE_DIGEST, rollback_function_arn=FUNCTION_ARN,
        ))
        self.assertEqual(state["deployments"][0]["source_run_id"], "42")
        self.assertEqual(state["deployments"][0]["requested_image_uri"], PREVIOUS_DIGEST)

    def test_implicit_rollback_rejects_legacy_tag_before_provider_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_deployment_project(root)
            deploy.record_deployment(root, {"operation": "deploy", "previous_image_uri": PREVIOUS_IMAGE})
            with patch.object(cli, "repo_root", return_value=root), patch.object(cli, "list_deployment_runs") as runs, \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["deploy", "rollback", "--yes"]), cli.EXIT_VALIDATION_FAILED)
            runs.assert_not_called()
            self.assertIn("no confirmed run", output.getvalue())

    def test_deploy_rollback_without_record_or_explicit_image_fails_before_provider_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "list_deployment_runs"
            ) as runs, redirect_stdout(io.StringIO()) as buffer:
                result = cli.main(["deploy", "rollback", "--yes"])

        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        runs.assert_not_called()
        self.assertIn("No rollback target", buffer.getvalue())

    def test_explicit_status_rejects_a_run_from_another_workflow(self) -> None:
        unrelated = workflow_run()
        unrelated["workflowName"] = "Release"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "view_deployment_run", return_value=(unrelated, None)
            ), redirect_stdout(io.StringIO()) as buffer:
                result = cli.main(["deploy", "status", "--run-id", "42"])

        self.assertEqual(result, cli.EXIT_VALIDATION_FAILED)
        self.assertIn("does not belong to the protected deployment workflow", buffer.getvalue())


class DeploymentIntentTests(unittest.TestCase):
    def test_review_resolves_tag_before_producing_dispatch_inputs(self) -> None:
        cfg = deployment_config()
        gh_reads = [subprocess.CompletedProcess([], 0, text, "") for text in ("acme/pipeline\n", COMMIT_SHA + "\n")]
        with patch.object(cli, "gh_command", side_effect=gh_reads) as gh, \
             patch.object(cli, "command_exists", return_value=True), \
             patch.object(cli, "verify_ecr_lambda_image", return_value=IMAGE_DIGEST) as verify:
            intent, reviewed = cli.review_deployment_intent(ROOT_DIR, IMAGE, cfg)
        self.assertRegex(intent.request_id, r"^[a-f0-9]{32}$")
        self.assertEqual(replace(intent, request_id=REQUEST_ID), fixture_intent(IMAGE, cfg)[0])
        self.assertIs(reviewed, cfg)
        self.assertIn("repos/acme/pipeline/git/ref/heads/main", gh.call_args.args[1])
        verify.assert_called_once_with(ROOT_DIR, IMAGE, cfg["aws_region"], aws_json_fn=cli.aws_json)
        self.assertIn(f"image_uri={IMAGE_DIGEST}", deploy.workflow_dispatch_args("deploy", intent))

    def test_rollback_uses_remote_settings_for_the_reviewed_digest(self) -> None:
        remote = deployment_config()
        remote["backend"]["key"] = "state-from-github.tfstate"
        values = ("acme/pipeline", COMMIT_SHA, config.pipeline_config_json(remote))
        gh_reads = [subprocess.CompletedProcess([], 0, value, "") for value in values]
        with patch.object(cli, "gh_command", side_effect=gh_reads) as gh, \
             patch.object(cli, "command_exists", return_value=True), \
             patch.object(cli, "verify_ecr_lambda_image", return_value=PREVIOUS_DIGEST) as verify:
            intent, reviewed = cli.review_deployment_intent(ROOT_DIR, PREVIOUS_DIGEST)
        verify.assert_called_once_with(ROOT_DIR, PREVIOUS_DIGEST, remote["aws_region"], aws_json_fn=cli.aws_json)
        self.assertEqual(replace(intent, request_id=REQUEST_ID), fixture_intent(PREVIOUS_DIGEST, remote)[0])
        self.assertEqual(reviewed["backend"]["key"], "state-from-github.tfstate")
        self.assertIn("repos/acme/pipeline/actions/variables/PIPELINE_CONFIG_JSON", gh.call_args.args[1])

    def test_missing_pinned_digest_stops_deploy_before_confirmation_or_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = create_deployment_project(root)
            cfg["lambda_image_uri"] = IMAGE_DIGEST
            cli.write_config(root, cfg)
            gh_reads = [subprocess.CompletedProcess([], 0, value, "") for value in ("acme/pipeline", COMMIT_SHA)]
            with patch.object(cli, "repo_root", return_value=root), \
                 patch.object(cli, "list_deployment_runs", return_value=([], None)), \
                 patch.object(cli, "inspect_active_lambda_image", return_value=("", None)), \
                 patch.object(cli, "production_deployment_preflight_checks", return_value=[]), \
                 patch.object(cli, "command_exists", return_value=True), \
                 patch.object(cli, "gh_command", side_effect=gh_reads), \
                 patch.object(cli, "aws_json", return_value=({"images": []}, subprocess.CompletedProcess([], 0, "", ""))), \
                 patch.object(cli, "confirm_cloud_deployment") as confirm, \
                 patch.object(cli, "dispatch_cloud_deployment") as dispatch, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["deploy", "prod"]), cli.EXIT_VALIDATION_FAILED)
            self.assertIn("unavailable in ECR", output.getvalue())
            confirm.assert_not_called()
            dispatch.assert_not_called()


class DeploymentCorrelationTests(unittest.TestCase):
    def test_empty_gitHub_listing_is_valid_during_dispatch_propagation(self) -> None:
        with patch.object(cli, "command_exists", return_value=True), patch.object(
            cli, "gh_command", return_value=subprocess.CompletedProcess(["gh"], 0, "[]", ""),
        ):
            self.assertEqual(cli.list_deployment_runs(ROOT_DIR, repository="acme/pipeline"), ([], None))

    def test_unconfirmed_watch_fails_and_later_status_reconciles_only_its_request(self) -> None:
        intent, _ = fixture_intent(IMAGE)
        unrelated = workflow_run(55, request_id="b" * 32)
        matched = workflow_run(56, request_id=REQUEST_ID)
        accepted = subprocess.CompletedProcess(["gh"], 0, "", "")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            root = Path(directory)
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "dispatch_deployment_workflow", return_value=accepted,
            ) as dispatch, patch.object(cli, "list_deployment_runs", return_value=([unrelated], None)) as runs, patch.object(
                cli.time, "sleep",
            ), patch.object(cli, "watch_deployment_run") as watch:
                code = cli.dispatch_cloud_deployment(root, "deploy", intent, "", watch=True, interval=3)
                self.assertEqual(code, 1)
                self.assertIn("Dispatched, run unconfirmed", output.getvalue())
                watch.assert_not_called()
                dispatch.assert_called_once()
                self.assertEqual(deploy.latest_deployment(root)["run_id"], "")

                output.seek(0)
                output.truncate()
                self.assertEqual(cli.main(["deploy", "status", "--format", "json"]), 0)
                payload = json.loads(output.getvalue())
                self.assertEqual(payload["run_confirmation"], "dispatched, run unconfirmed")
                self.assertIsNone(payload["run"])
                self.assertEqual(payload["request_id"], REQUEST_ID)

                runs.return_value = ([unrelated, matched], None)
                with patch.object(cli, "view_deployment_run", return_value=(matched, None)) as view:
                    run, _, error = cli.resolve_deployment_run(root)
                view.assert_called_once_with(root, "56", repository="acme/pipeline")
                self.assertIsNone(error)
                self.assertEqual(run["databaseId"], 56)
                self.assertEqual(deploy.latest_deployment(root)["run_id"], "56")
                self.assertEqual(len(deploy.load_deployment_state(root)["deployments"]), 1)

    def test_recovery_point_is_bound_to_a_successful_run_and_attempt(self) -> None:
        point = {"repository": "acme/pipeline", "run_id": "42", "attempt": "1", "commit_sha": COMMIT_SHA,
                 "previous_image_uri": PREVIOUS_DIGEST, "deployed_image_uri": IMAGE_DIGEST, "function_arn": FUNCTION_ARN}
        source = {"id": 42, "path": deploy.DEPLOYMENT_WORKFLOW_PATH, "run_attempt": 1, "head_sha": COMMIT_SHA,
                  "head_branch": "main", "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}

        def gh(root, args):
            if args[0] == "api":
                self.assertIn("repos/acme/pipeline/actions/runs/42", args)
                return subprocess.CompletedProcess(args, 0, json.dumps(source), "")
            self.assertEqual(args[:7], ["run", "download", "42", "--repo", "acme/pipeline", "--name", "deployment-recovery-1"])
            (Path(args[-1]) / "deployment-recovery.json").write_text(json.dumps(point))
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch.object(cli, "gh_command", side_effect=gh) as provider:
            with self.assertRaisesRegex(cli.ConfigValidationError, "successful production deployment"):
                cli.read_deployment_recovery_point(ROOT_DIR, workflow_run(conclusion="cancelled"))
            provider.assert_not_called()
            self.assertEqual(cli.read_deployment_recovery_point(ROOT_DIR, workflow_run()), point)
            point["attempt"] = "2"
            with self.assertRaisesRegex(cli.ConfigValidationError, "selected run and attempt"):
                cli.read_deployment_recovery_point(ROOT_DIR, workflow_run())
            source["run_attempt"] = 2
            with self.assertRaisesRegex(cli.ConfigValidationError, "successful source run and attempt"):
                cli.read_deployment_recovery_point(ROOT_DIR, workflow_run())


class DeploymentResultTests(unittest.TestCase):
    def test_status_requires_the_production_job_and_the_selected_operation(self) -> None:
        valid = workflow_run()
        rollback = workflow_run(operation="rollback")
        skipped_job = copy.deepcopy(valid)
        skipped_job["jobs"][0]["conclusion"] = "skipped"
        skipped_apply = copy.deepcopy(valid)
        skipped_apply["jobs"][0]["steps"][0]["conclusion"] = "skipped"
        skipped_health = copy.deepcopy(valid)
        skipped_health["jobs"][0]["steps"][1]["conclusion"] = "skipped"
        skipped_restore = copy.deepcopy(rollback)
        skipped_restore["jobs"][0]["steps"][0]["conclusion"] = "skipped"
        cases = [
            ("deploy", valid, 0, "success"),
            ("rollback", rollback, 0, "success"),
            ("queued", workflow_run(status="queued", conclusion=""), 0, "pending"),
            ("skipped workflow", workflow_run(conclusion="skipped"), 1, "failed"),
            ("neutral workflow", workflow_run(conclusion="neutral"), 1, "failed"),
            ("missing job", dict(valid, jobs=[]), 1, "failed"),
            ("missing job details", {key: value for key, value in valid.items() if key != "jobs"}, 1, "failed"),
            ("skipped job", skipped_job, 1, "failed"),
            ("skipped apply", skipped_apply, 1, "failed"),
            ("skipped health", skipped_health, 1, "failed"),
            ("skipped restore", skipped_restore, 1, "failed"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, run, code, result in cases:
                with self.subTest(name=name), patch.object(cli, "repo_root", return_value=root), patch.object(
                    cli, "view_deployment_run", return_value=(run, None),
                ), patch.object(cli, "inspect_active_lambda_image", return_value=("", None)), redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cli.main(["deploy", "status", "--run-id", "42", "--format", "json"]), code)
                payload = json.loads(output.getvalue())
                self.assertEqual(payload["deployment_result"], result)
                self.assertTrue(payload["deployment_detail"])
                self.assertEqual(payload["run"]["conclusion"], run["conclusion"])

    def test_explicit_plan_is_rejected_and_discovery_fetches_job_details(self) -> None:
        plan = workflow_run(operation="plan")
        invalid = workflow_run()
        invalid["jobs"][0]["conclusion"] = "skipped"
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, "repo_root", return_value=Path(directory)), patch.object(
            cli, "inspect_active_lambda_image", return_value=("", None),
        ) as inspect:
            with patch.object(cli, "view_deployment_run", return_value=(plan, None)), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["deploy", "status", "--run-id", "42"]), 1)
                self.assertIn("does not belong", output.getvalue())
            inspect.assert_not_called()
            candidate = {key: value for key, value in invalid.items() if key != "jobs"}
            with patch.object(cli, "list_deployment_runs", return_value=([plan, candidate], None)), patch.object(
                cli, "view_deployment_run", return_value=(invalid, None),
            ) as view, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["deploy", "status", "--format", "json"]), 1)
            view.assert_called_once_with(Path(directory), "42")
            self.assertEqual(json.loads(output.getvalue())["deployment_result"], "failed")

    def test_dispatch_watch_fails_when_github_reports_success_with_a_skipped_job(self) -> None:
        intent, _ = fixture_intent(IMAGE)
        skipped = workflow_run(request_id=REQUEST_ID)
        skipped["jobs"][0]["conclusion"] = "skipped"
        response = subprocess.CompletedProcess(["gh"], 0, skipped["url"], "")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            cli, "list_deployment_runs", return_value=([], None),
        ), patch.object(cli, "dispatch_deployment_workflow", return_value=response), patch.object(
            cli, "watch_deployment_run", return_value=subprocess.CompletedProcess(["gh"], 0, "", ""),
        ), patch.object(cli, "view_deployment_run", return_value=(skipped, None)), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.dispatch_cloud_deployment(Path(directory), "deploy", intent, "", watch=True, interval=3), 1)
        self.assertIn("production job did not complete successfully", output.getvalue())


class EcrImageVerificationTests(unittest.TestCase):
    registry = "210987654321.dkr.ecr.us-east-1.amazonaws.com"
    image_uri = registry + "/external/lambda:sha-abc123"
    layer_digest = "sha256:" + "f" * 64

    def test_validates_stored_manifest_and_platform_with_the_image_registry(self) -> None:
        cases = [
            ("application/vnd.oci.image.manifest.v1+json", "application/vnd.oci.image.config.v1+json", "amd64", None),
            ("application/vnd.docker.distribution.manifest.v2+json", "application/vnd.docker.container.image.v1+json", "amd64", None),
            ("application/vnd.oci.image.manifest.v1+json", "application/vnd.oci.image.config.v1+json", "arm64", "linux/amd64"),
            ("application/vnd.oci.image.manifest.v1+json", "application/vnd.oci.image.config.v1+json", "amd64", "Cannot pull"),
            ("application/vnd.oci.image.index.v1+json", "", "amd64", "single-platform"),
        ]
        for media_type, config_type, architecture, error in cases:
            with self.subTest(media_type=media_type, architecture=architecture, error=error):
                blob = json.dumps({"os": "linux", "architecture": architecture}).encode()
                config_digest = "sha256:" + hashlib.sha256(blob).hexdigest()
                manifest = json.dumps({
                    "schemaVersion": 2, "mediaType": media_type,
                    "config": {"mediaType": config_type, "digest": config_digest, "size": len(blob)},
                    "layers": [{"digest": self.layer_digest}],
                })
                digest = "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()
                identity = {"imageId": {"imageDigest": digest}, "registryId": "210987654321", "repositoryName": "external/lambda"}
                responses = [
                    {"images": [identity]},
                    {"images": [{**identity, "imageManifest": manifest}]},
                    {"layerDigest": self.layer_digest, "downloadUrl": "https://s3.example.test/layer"},
                    {"authorizationData": [{"authorizationToken": "ZmFrZQ=="}]},
                ]
                completed = subprocess.CompletedProcess([], 0, "", "")
                results = [(response, completed) for response in responses]
                if error == "Cannot pull":
                    results[2] = ({}, subprocess.CompletedProcess([], 254, "", "AccessDeniedException"))
                with patch.object(aws_provider, "_read_ecr_config", return_value=blob) as read_blob, \
                     patch.object(aws_provider, "_aws_json", side_effect=results) as aws:
                    args = (ROOT_DIR, self.image_uri, "us-east-1")
                    if error:
                        with self.assertRaisesRegex(cli.ConfigValidationError, error):
                            aws_provider.verify_ecr_lambda_image(*args, aws_json_fn=aws)
                    else:
                        self.assertEqual(aws_provider.verify_ecr_lambda_image(*args, aws_json_fn=aws),
                                         self.registry + "/external/lambda@" + digest)
                    self.assertIn("imageTag=sha-abc123", aws.call_args_list[0].args[1])
                    self.assertIn("imageDigest=" + digest, aws.call_args_list[1].args[1])
                    for call in aws.call_args_list:
                        command = call.args[1]
                        if "--registry-id" in command:
                            self.assertEqual(command[command.index("--registry-id") + 1], "210987654321")
                    if config_type and error != "Cannot pull":
                        read_blob.assert_called_once_with(aws_provider.parse_ecr_image_uri(self.image_uri),
                                                          config_digest, len(blob), "ZmFrZQ==")
                    else:
                        read_blob.assert_not_called()

    def test_registry_blob_redirect_omits_authorization(self) -> None:
        requests = []
        target = "https://s3.example.test/blob"

        def respond(handler, request):
            requests.append(request)
            headers = Message()
            if len(requests) == 1:
                headers["Location"] = target
                response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, 307)
                response.msg = "Temporary Redirect"
                return response
            response = urllib.response.addinfourl(io.BytesIO(b"config"), headers, request.full_url, 200)
            response.msg = "OK"
            return response

        ref = aws_provider.parse_ecr_image_uri(self.image_uri)
        with patch.object(urllib.request.HTTPSHandler, "https_open", autospec=True, side_effect=respond):
            self.assertEqual(aws_provider._read_ecr_config(ref, self.layer_digest, 6, "ZmFrZQ=="), b"config")
        self.assertEqual(requests[0].get_header("Authorization"), "Basic ZmFrZQ==")
        self.assertEqual(requests[1].full_url, target)
        self.assertIsNone(requests[1].get_header("Authorization"))


class RecoveryTests(unittest.TestCase):
    function = "devsecops-pipeline-prod-lambda"
    region = "us-east-1"
    arn = f"arn:aws:lambda:{region}:123456789012:function:{function}"
    health_url = "https://abc123.execute-api.us-east-1.amazonaws.com/health"

    def test_capture_records_actual_previous_digest_and_blocks_stale_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            artifact = Path(directory) / "deployment-recovery.json"
            environment = {"PROJECT_NAME": "devsecops-pipeline", "DEPLOY_ENVIRONMENT": "prod", "DEPLOY_MODE": "deploy",
                           "AWS_REGION": self.region, "GITHUB_REPOSITORY": "acme/pipeline", "GITHUB_RUN_ID": "42",
                           "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": COMMIT_SHA, "LAMBDA_IMAGE_URI": IMAGE_DIGEST,
                           "RECOVERY_POINT_FILE": str(artifact), "GITHUB_OUTPUT": str(output)}
            current = recovery.LambdaImage(PREVIOUS_DIGEST, PREVIOUS_IMAGE, self.arn, "rev", "Active", "Successful")
            with patch.dict(os.environ, environment, clear=True), patch.object(recovery.sys, "argv", ["recovery", "capture"]), \
                 patch.object(recovery, "lambda_image", return_value=current), \
                 patch.object(recovery, "resolve_ecr_image_digest", return_value=PREVIOUS_DIGEST), redirect_stdout(io.StringIO()):
                self.assertEqual(recovery.main(), 0)
                point = json.loads(artifact.read_text())
                self.assertEqual(point["previous_image_uri"], PREVIOUS_DIGEST)
                self.assertEqual(point["attempt"], "2")
                self.assertEqual(point["deployed_image_uri"], IMAGE_DIGEST)
                os.environ.update(DEPLOY_MODE="rollback", ROLLBACK_FROM_IMAGE_URI=IMAGE_DIGEST, ROLLBACK_FUNCTION_ARN=self.arn)
                with patch.object(recovery.sys, "stderr", new=io.StringIO()) as stderr:
                    self.assertEqual(recovery.main(), 1)
                    self.assertIn("no longer matches", stderr.getvalue())

    def test_only_lambda_resource_not_found_is_first_deployment(self) -> None:
        missing = subprocess.CompletedProcess([], 254, "", "An error occurred (ResourceNotFoundException) when calling the GetFunction operation: missing")
        denied = subprocess.CompletedProcess([], 254, "", "An error occurred (AccessDeniedException) when calling the GetFunction operation: denied")
        with patch.object(recovery, "_aws_json", side_effect=[({}, missing), ({}, denied), ({}, subprocess.CompletedProcess([], 0, "", ""))]):
            self.assertIsNone(recovery.lambda_image(ROOT_DIR, self.function, self.region))
            with self.assertRaisesRegex(recovery.RecoveryError, "AccessDeniedException"):
                recovery.lambda_image(ROOT_DIR, self.function, self.region)
            with self.assertRaisesRegex(recovery.RecoveryError, "resolved image digest"):
                recovery.lambda_image(ROOT_DIR, self.function, self.region)

    def test_ecr_resolves_legacy_tag_and_rejects_deleted_recovery_image(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        image = {"images": [{"imageId": {"imageDigest": "sha256:" + "a" * 64}}]}
        with patch.object(cli, "aws_json", side_effect=[(image, completed), ({"images": []}, completed)]) as aws:
            self.assertEqual(aws_provider.resolve_ecr_image_digest(ROOT_DIR, PREVIOUS_IMAGE, self.region, aws_json_fn=aws), PREVIOUS_DIGEST)
            self.assertIn("imageTag=sha-old", aws.call_args.args[1])
            self.assertIn("123456789012", aws.call_args.args[1])
            with self.assertRaisesRegex(cli.ConfigValidationError, "unavailable in ECR"):
                aws_provider.resolve_ecr_image_digest(ROOT_DIR, PREVIOUS_DIGEST, self.region, aws_json_fn=aws)
            self.assertIn("imageDigest=sha256:" + "a" * 64, aws.call_args.args[1])

    def test_restore_updates_only_code_and_requires_state_and_health(self) -> None:
        active = recovery.LambdaImage(PREVIOUS_DIGEST, PREVIOUS_DIGEST, self.arn, "restored", "Active", "Successful")
        current = recovery.LambdaImage(IMAGE, IMAGE, self.arn, "current-revision", "Active", "Successful")
        completed = subprocess.CompletedProcess([], 0, "", "")
        for recorded, status, error in [(PREVIOUS_DIGEST, 200, None), (PREVIOUS_DIGEST, 302, "/health failed"), (IMAGE, 200, "Terraform state")]:
            with self.subTest(recorded=recorded, status=status), \
                 patch.object(recovery, "resolve_ecr_image_digest", return_value=PREVIOUS_DIGEST), \
                 patch.object(recovery, "lambda_image", side_effect=[current, active]), \
                 patch.object(recovery, "_aws_command", return_value=completed) as aws, \
                 patch.object(recovery, "terraform", side_effect=["", recorded]) as tf, \
                 patch.object(recovery, "fetch_health_url", return_value=(status, "fixture")) as health, \
                 redirect_stdout(io.StringIO()) as output:
                args = (ROOT_DIR, self.function, self.arn, PREVIOUS_DIGEST, self.region, self.health_url, "AWS_IAM")
                if error:
                    with self.assertRaisesRegex(recovery.RecoveryError, error):
                        recovery.restore(*args)
                    self.assertNotIn("Verified Lambda recovery", output.getvalue())
                else:
                    recovery.restore(*args)
                    self.assertIn("Verified Lambda recovery", output.getvalue())
                update = aws.call_args_list[0].args[1]
                self.assertEqual(update[:2], ["lambda", "update-function-code"])
                self.assertEqual(update[update.index("--revision-id") + 1], "current-revision")
                self.assertEqual(update[update.index("--image-uri") + 1], PREVIOUS_DIGEST)
                self.assertEqual(tf.call_args_list[0].args[1:4], ("apply", "-refresh-only", f"-target={recovery.LAMBDA_RESOURCE}"))
                self.assertEqual(health.called, recorded == PREVIOUS_DIGEST)

    def test_recovery_state_rejects_a_different_aws_account(self) -> None:
        state = {"values": {
            "outputs": {"lambda_function_name": {"value": self.function},
                        "api_gateway_health_url": {"value": self.health_url},
                        "api_gateway_authorization_type": {"value": "AWS_IAM"}},
            "root_module": {"child_modules": [{"address": "module.lambda", "resources": [
                {"address": recovery.LAMBDA_RESOURCE, "values": {"arn": self.arn}},
            ]}]},
        }}
        with patch.object(recovery, "terraform", side_effect=["{}", json.dumps(state), json.dumps(state)]):
            self.assertEqual(recovery.recovery_state(ROOT_DIR, self.function, ""), {})
            self.assertEqual(recovery.recovery_state(ROOT_DIR, self.function, self.arn),
                             {"health_url": self.health_url, "auth_type": "AWS_IAM"})
            with self.assertRaisesRegex(recovery.RecoveryError, "workspace disagree"):
                recovery.recovery_state(ROOT_DIR, self.function, self.arn.replace("123456789012", "210987654321"))

    def test_manual_rollback_blocks_a_changed_revision_before_aws_write(self) -> None:
        current = recovery.LambdaImage(IMAGE, IMAGE, self.arn, "new-revision", "Active", "Successful")
        with patch.object(recovery, "resolve_ecr_image_digest", return_value=PREVIOUS_DIGEST), \
             patch.object(recovery, "lambda_image", return_value=current), patch.object(recovery, "_aws_command") as aws:
            with self.assertRaisesRegex(recovery.RecoveryError, "changed after recovery capture"):
                recovery.restore(ROOT_DIR, self.function, self.arn, PREVIOUS_DIGEST, self.region, self.health_url,
                                 "AWS_IAM", expected_revision="old-revision")
            aws.assert_not_called()

    def test_retry_syncs_state_without_rewriting_already_restored_code(self) -> None:
        active = recovery.LambdaImage(PREVIOUS_DIGEST, PREVIOUS_DIGEST, self.arn, "restored", "Active", "Successful")
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(recovery, "resolve_ecr_image_digest", return_value=PREVIOUS_DIGEST), \
             patch.object(recovery, "lambda_image", return_value=active), \
             patch.object(recovery, "_aws_command", return_value=completed) as aws, \
             patch.object(recovery, "terraform", side_effect=["", PREVIOUS_DIGEST]) as tf, \
             patch.object(recovery, "fetch_health_url", return_value=(200, "ok")), redirect_stdout(io.StringIO()):
            recovery.restore(ROOT_DIR, self.function, self.arn, PREVIOUS_DIGEST, self.region, self.health_url, "NONE")
        aws.assert_called_once()
        self.assertEqual(aws.call_args.args[1][:3], ["lambda", "wait", "function-updated"])
        self.assertIn("-refresh-only", tf.call_args_list[0].args)


class DeploymentWorkflowContractTests(unittest.TestCase):
    """Pin security-sensitive behavior in the tracked deployment workflow."""

    def test_workflow_supports_serialized_protected_manual_rollback(self) -> None:
        workflow = (ROOT_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

        self.assertIn("run-name: DevSecOps", workflow)
        self.assertIn("          - rollback", workflow)
        self.assertIn("      image_uri:", workflow)
        self.assertNotIn("github.event.inputs.image_uri || vars.LAMBDA_IMAGE_URI", workflow)
        self.assertIn("github.event.inputs.mode == 'rollback'", workflow)
        self.assertIn("      commit_sha:", workflow)
        self.assertIn("      config_sha256:", workflow)
        self.assertIn("--verify-intent", workflow)
        self.assertIn("-out=workload.tfplan", workflow)
        self.assertIn("apply -input=false -no-color workload.tfplan", workflow)
        concurrency = workflow.split("concurrency:\n", 1)[1].split("\nenv:\n", 1)[0]
        self.assertIn("format('terraform-{0}', inputs.environment)", concurrency)
        self.assertIn("format('pr-validation-{0}', github.event.pull_request.number)", concurrency)
        self.assertNotIn("inputs.mode", concurrency)
        self.assertNotIn("request_id", concurrency)
        self.assertIn("queue: max", workflow)
        self.assertIn("name: deployment-recovery-${{ github.run_attempt }}", workflow)
        self.assertNotIn("group: terraform-${{ github.event.inputs.environment || 'dev' }}-${{", workflow)
        image_gate = workflow.index("recovery verify-image")
        self.assertLess(workflow.index("role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME_ARN }}"), image_gate)
        self.assertLess(image_gate, workflow.index("recovery capture"))
        self.assertLess(image_gate, workflow.index("workspace select -or-create"))
        self.assertLess(image_gate, workflow.index("apply -input=false -no-color workload.tfplan"))
        self.assertNotIn("-target=module.ecr", workflow)
        self.assertIn("registries: ${{ steps.verify-image.outputs.registry_id }}", workflow)
        self.assertIn("id: apply-workload\n        if: env.DEPLOY_MODE == 'deploy'", workflow)
        self.assertIn("name: Restore requested Lambda image\n        if: env.DEPLOY_MODE == 'rollback'", workflow)
        self.assertIn("failure() && env.DEPLOY_MODE == 'deploy' && (steps.apply-workload.outcome", workflow)
        self.assertIn("environment: prod", workflow)

    def test_next_action_uses_cli_deployment_surface(self) -> None:
        self.assertEqual(cli.PRODUCTION_DEPLOY_COMMAND, "devsecops deploy prod")


if __name__ == "__main__":
    unittest.main()
