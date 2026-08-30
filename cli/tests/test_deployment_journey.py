import argparse
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import deploy
from devsecops_cli import main as cli


ROOT_DIR = Path(__file__).resolve().parents[2]
IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-new"
PREVIOUS_IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-old"


def deployment_config() -> dict[str, object]:
    cfg = cli.preset_config("enterprise")
    cfg["lambda_image_uri"] = IMAGE
    cfg["backend"]["bucket"] = "devsecops-pipeline-tfstate"
    cfg["backend"]["lock_table"] = "devsecops-pipeline-locks"
    return cfg


def create_deployment_project(root: Path) -> dict[str, object]:
    cfg = deployment_config()
    cli.write_config(root, cfg)
    for relative in cli.REQUIRED_PROJECT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# project file\n", encoding="utf-8")
    for relative in (cli.GENERATED_TFVARS, cli.DIST_DIR / "github-setup.sh"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# generated\n", encoding="utf-8")
    return cfg


def workflow_run(
    run_id: int = 42,
    *,
    operation: str = "deploy",
    status: str = "completed",
    conclusion: str = "success",
) -> dict[str, object]:
    return {
        "databaseId": run_id,
        "workflowName": deploy.DEPLOYMENT_WORKFLOW_NAME,
        "displayTitle": f"DevSecOps {operation} prod",
        "event": "workflow_dispatch",
        "headBranch": "main",
        "headSha": "abcdef1234567890",
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
            }
        ],
    }


class DeploymentDomainTests(unittest.TestCase):
    def test_dispatch_contract_binds_exact_image_and_protected_ref(self) -> None:
        args = deploy.workflow_dispatch_args("deploy", IMAGE)

        self.assertEqual(args[:5], ["workflow", "run", "deploy.yml", "--ref", "main"])
        self.assertEqual(deploy.DEPLOYMENT_WORKFLOW_PATH, ".github/workflows/deploy.yml")
        self.assertIn("mode=deploy", args)
        self.assertIn("environment=prod", args)
        self.assertIn(f"image_uri={IMAGE}", args)
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
        self.assertEqual(deploy.select_dispatched_run({"11"}, [unrelated, matching]), matching)

    def test_dispatched_run_fallback_matches_the_requested_operation(self) -> None:
        rollback = workflow_run(13, operation="rollback", status="queued", conclusion="")
        deployment = workflow_run(12, operation="deploy", status="queued", conclusion="")

        self.assertEqual(deploy.select_dispatched_run(set(), [rollback, deployment], "deploy"), deployment)
        self.assertEqual(deploy.select_dispatched_run(set(), [deployment, rollback], "rollback"), rollback)

    def test_json_status_infers_operation_without_local_journal(self) -> None:
        payload = deploy.deployment_status_payload(workflow_run(operation="rollback"))

        self.assertEqual(payload["operation"], "rollback")

    def test_active_run_detection_is_conservative_for_old_workflow_titles(self) -> None:
        old_run = workflow_run(21, status="in_progress", conclusion="")
        old_run["displayTitle"] = "Legacy manual dispatch"

        self.assertEqual(deploy.active_deployment_runs([old_run]), [old_run])

    def test_rollback_target_can_be_selected_by_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            deploy.record_deployment(
                root,
                {
                    "operation": "deploy",
                    "requested_image_uri": IMAGE,
                    "previous_image_uri": PREVIOUS_IMAGE,
                    "run_id": "42",
                },
            )

            target, record = deploy.rollback_target(root, "42")

        self.assertEqual(target, PREVIOUS_IMAGE)
        self.assertEqual(record["requested_image_uri"], IMAGE)


class DeploymentCommandTests(unittest.TestCase):
    def test_active_image_inspection_uses_get_function_code_uri(self) -> None:
        cfg = deployment_config()
        completed = subprocess.CompletedProcess(["aws"], 0, "", "")
        with patch.object(cli, "command_exists", return_value=True), patch.object(
            cli,
            "aws_json",
            return_value=({"Code": {"ImageUri": PREVIOUS_IMAGE}}, completed),
        ) as aws_json:
            image_uri, error = cli.inspect_active_lambda_image(Path("/tmp/project"), cfg)

        self.assertEqual(image_uri, PREVIOUS_IMAGE)
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
        dispatch.assert_called_once_with(root, "deploy", IMAGE)
        self.assertEqual(state["deployments"][0]["previous_image_uri"], PREVIOUS_IMAGE)
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
            ) as watch, patch.object(cli, "view_deployment_run", return_value=(workflow_run(), None)), redirect_stdout(
                io.StringIO()
            ):
                result = cli.main(["deploy", "prod", "--yes", "--watch"])

        self.assertEqual(result, cli.EXIT_OK)
        watch.assert_called_once_with(root, "42", 5, stream=True)

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

    def test_failed_status_returns_validation_failure_and_recovery_command(self) -> None:
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
        self.assertIn("devsecops deploy logs --failed", buffer.getvalue())
        self.assertIn("devsecops deploy rollback", buffer.getvalue())

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

    def test_failed_deploy_logs_recommend_a_rollback_preview(self) -> None:
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
        self.assertIn("Next command: devsecops deploy rollback --dry-run", buffer.getvalue())

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
                    "previous_image_uri": PREVIOUS_IMAGE,
                    "run_id": "42",
                },
            )
            completed = subprocess.CompletedProcess(["gh"], 0, url + "\n", "")
            with patch.object(cli, "repo_root", return_value=root), patch.object(
                cli, "list_deployment_runs", return_value=([], None)
            ), patch.object(cli, "inspect_active_lambda_image", return_value=(IMAGE, None)), patch.object(
                cli,
                "rollback_deployment_preflight_checks",
                return_value=[cli.Check("Ready", "OK", "Ready.")],
            ), patch.object(cli, "dispatch_deployment_workflow", return_value=completed) as dispatch, redirect_stdout(
                io.StringIO()
            ):
                result = cli.main(["deploy", "rollback", "--yes"])
            state = deploy.load_deployment_state(root)

        self.assertEqual(result, cli.EXIT_OK)
        dispatch.assert_called_once_with(root, "rollback", PREVIOUS_IMAGE)
        self.assertEqual(state["deployments"][0]["source_run_id"], "42")
        self.assertEqual(state["deployments"][0]["previous_image_uri"], IMAGE)

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
        self.assertIn("not the deployment workflow", buffer.getvalue())


class DeploymentWorkflowContractTests(unittest.TestCase):
    def test_workflow_supports_serialized_protected_manual_rollback(self) -> None:
        workflow = (ROOT_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

        self.assertIn("run-name: DevSecOps", workflow)
        self.assertIn("          - rollback", workflow)
        self.assertIn("      image_uri:", workflow)
        self.assertIn("github.event.inputs.image_uri || vars.LAMBDA_IMAGE_URI", workflow)
        self.assertIn("github.event.inputs.mode == 'rollback'", workflow)
        self.assertIn("Rollback requires an explicit immutable image_uri input", workflow)
        self.assertIn("LAMBDA_IMAGE_URI must be a complete Amazon ECR image URI", workflow)
        self.assertIn("group: terraform-${{ github.event.inputs.environment || 'dev' }}", workflow)
        self.assertNotIn("group: terraform-${{ github.event.inputs.environment || 'dev' }}-${{", workflow)
        self.assertIn("previous_image_uri=\"$(aws lambda get-function \\", workflow)
        self.assertIn("environment: ${{ vars.PROD_APPROVAL_ENVIRONMENT || 'prod' }}", workflow)

    def test_next_action_uses_cli_deployment_surface(self) -> None:
        self.assertEqual(cli.PRODUCTION_DEPLOY_COMMAND, "devsecops deploy prod")


if __name__ == "__main__":
    unittest.main()
