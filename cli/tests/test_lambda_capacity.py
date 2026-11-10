"""Capacity is checked under the actual provider role before mutation."""
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import aws, recovery, render
from devsecops_cli.config import default_config
from devsecops_cli.lambda_capacity import DEFAULT_RESERVED_EXECUTIONS, evaluate_capacity
from devsecops_cli.models import ConfigValidationError

ROOT = Path(__file__).resolve().parents[2]


class CapacityTests(unittest.TestCase):
    @staticmethod
    def limits(total=1000, unreserved=1000):
        return {"ConcurrentExecutions": total, "UnreservedConcurrentExecutions": unreserved}

    def test_new_account_cannot_allocate_one_or_ten_reserved_units(self):
        for requested in (1, 10):
            with self.subTest(requested=requested), self.assertRaisesRegex(ConfigValidationError, "maximum allocatable=0"):
                evaluate_capacity(self.limits(10, 10), requested)

    def test_explicit_dev_shared_pool_uses_account_quota(self):
        report = evaluate_capacity(self.limits(10, 10), -1, allow_unreserved=True)
        self.assertEqual(report["mode"], "unreserved")
        self.assertEqual(report["available_after_release"], 10)
        self.assertIn("no dedicated function cap", report["message"])
        with self.assertRaises(ConfigValidationError):
            evaluate_capacity(self.limits(10, 10), -1)

    def test_boundary_leaves_required_pool_available(self):
        self.assertEqual(evaluate_capacity(self.limits(110, 110), 10)["maximum_reservation"], 10)
        with self.assertRaises(ConfigValidationError):
            evaluate_capacity(self.limits(109, 109), 10)

    def test_existing_function_reservation_is_counted_once(self):
        report = evaluate_capacity(self.limits(1000, 100), 20, 20)
        self.assertEqual(report["maximum_reservation"], 20)
        with self.assertRaises(ConfigValidationError):
            evaluate_capacity(self.limits(1000, 100), 21, 20)
        # An existing reservation is not a new capacity allocation.
        self.assertEqual(evaluate_capacity(self.limits(1000, 20), 10, 10)["requested_reserved"], 10)

    def test_releasing_own_reservation_restores_shared_capacity(self):
        self.assertEqual(evaluate_capacity(self.limits(10, 0), -1, 10, allow_unreserved=True)["available_after_release"], 10)
        with self.assertRaisesRegex(ConfigValidationError, "no shared capacity"):
            evaluate_capacity(self.limits(10, 0), -1, allow_unreserved=True)

    def test_malformed_limits_and_disabled_or_fractional_requests_fail_closed(self):
        for limits in (None, {}, self.limits(10, 11), self.limits(0, 0), self.limits(True, 1), self.limits(10, -1)):
            with self.subTest(limits=limits), self.assertRaises(ConfigValidationError):
                evaluate_capacity(limits, 1)
        for requested in (0, -2, True, 1.5, 1001, "10"):
            with self.subTest(requested=requested), self.assertRaises(ConfigValidationError):
                evaluate_capacity(self.limits(), requested, allow_unreserved=True)
        with self.assertRaises(ConfigValidationError):
            evaluate_capacity(self.limits(10, 10), 1, 5)

    def test_missing_function_is_first_deploy_but_access_denied_is_not(self):
        def adapter(error):
            def call(root, args):
                if args[1] == "get-account-settings":
                    return {"AccountLimit": self.limits()}, subprocess.CompletedProcess(args, 0, "", "")
                return {}, subprocess.CompletedProcess(args, 255, "", error)
            return call
        result = aws.get_lambda_capacity(ROOT, "new-function", "eu-north-1", aws_json_fn=adapter("ResourceNotFoundException"))
        self.assertEqual(result["current_reserved"], 0)
        for error in ("AccessDeniedException", "ExpiredTokenException", "EndpointConnectionError"):
            with self.subTest(error=error), self.assertRaises(ConfigValidationError):
                aws.get_lambda_capacity(ROOT, "new-function", "eu-north-1", aws_json_fn=adapter(error))

    def test_diagnostics_report_capacity_failure_before_workload_inspection(self):
        def call(root, args):
            data = ({"Account": "123456789012"} if args[0] == "sts" else
                    {"AccountLimit": self.limits(10, 10)} if args[1] == "get-account-settings" else {})
            return data, subprocess.CompletedProcess(args, 0, json.dumps(data), "")
        checks = aws.collect_aws_checks(ROOT, default_config(), include_workload=False,
                                        command_exists_fn=lambda _: True, aws_json_fn=call)
        check = next(item for item in checks if item.name == "Lambda concurrency")
        self.assertEqual(check.status, "FAIL")
        self.assertIn("quota=10", check.detail)

    def test_production_runner_rejects_low_capacity(self):
        with patch.dict(os.environ, {"PROJECT_NAME": "example", "DEPLOY_ENVIRONMENT": "prod", "AWS_REGION": "eu-north-1"}), \
             patch("sys.argv", ["recovery", "capacity"]), \
             patch.object(recovery, "get_lambda_capacity", side_effect=ConfigValidationError("insufficient capacity")), \
             contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(recovery.main(), 1)
        self.assertIn("insufficient capacity", error.getvalue())

    def test_workflow_capacity_checks_bracket_saved_apply_and_skip_code_rollback(self):
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        production = workflow.split("  deploy-main:")[1]
        first = production.index("Check production Lambda capacity")
        plan = production.index("Plan production workload from reviewed inputs")
        recheck = production.index("Recheck Lambda capacity before saved-plan apply")
        apply = production.index("Terraform apply workload with configured Lambda image")
        self.assertLess(first, plan)
        self.assertLess(plan, recheck)
        self.assertLess(recheck, apply)
        self.assertIn("if: env.DEPLOY_MODE == 'deploy'", production[first:plan])
        self.assertIn("if: env.DEPLOY_MODE == 'deploy'", production[recheck:apply])
        self.assertIn(f'-var="lambda_reserved_concurrent_executions={DEFAULT_RESERVED_EXECUTIONS}"', production[plan:recheck])
        self.assertIn(f"lambda_reserved_concurrent_executions = {DEFAULT_RESERVED_EXECUTIONS}", render.terraform_tfvars(default_config()))
        variable = (ROOT / "terraform/variables.tf").read_text().split('variable "lambda_reserved_concurrent_executions" {')[1].split("validation")[0]
        self.assertEqual(int(re.search(r"default\s*=\s*(\d+)", variable)[1]), DEFAULT_RESERVED_EXECUTIONS)


if __name__ == "__main__":
    unittest.main()
