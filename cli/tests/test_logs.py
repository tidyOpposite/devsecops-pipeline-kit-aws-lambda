"""Exercise CloudWatch pagination through a real, unsigned local AWS CLI."""

import contextlib
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from devsecops_cli.deployment import Deployment, DeploymentError

AWS = os.environ.get("DEVSECOPS_TEST_AWS_CLI") or shutil.which("aws")


@unittest.skipUnless(AWS, "AWS CLI is required for the offline pagination integration")
class DeploymentLogPaginationTests(unittest.TestCase):
    def exercise(self, fail_last_page=False):
        requests = []
        events = [
            {
                "timestamp": 1_100_000 + i,
                "ingestionTime": 1_100_000 + i,
                "eventId": str(i),
                "logStreamName": "old" if i < 44 else "new",
                "message": "old release" if i < 44 else "current release",
            }
            for i in range(88)
        ]

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(data)
                token = data.get("nextToken")
                if token == "page-3" and fail_last_page:
                    self.send_response(400)
                    result = {"__type": "AccessDeniedException", "message": "fixture page denied"}
                else:
                    self.send_response(200)
                    result = (
                        {"events": events[:44], "nextToken": "page-2"}
                        if token is None
                        else {"events": [], "nextToken": "page-3"}
                        if token == "page-2"
                        else {"events": events[44:]}
                    )
                self.send_header("Content-Type", "application/x-amz-json-1.1")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "aws-config"
            config.write_text("[profile fixture]\nregion = us-east-1\n")
            credentials = root / "aws-credentials"
            credentials.write_text("")
            env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
            env.update(
                AWS_CONFIG_FILE=str(config),
                AWS_SHARED_CREDENTIALS_FILE=str(credentials),
                AWS_EC2_METADATA_DISABLED="true",
                AWS_MAX_ATTEMPTS="1",
                AWS_PAGER="",
                AWS_CLI_AUTO_PROMPT="off",
            )
            instance = Deployment(root, "fixture")
            instance.settings = {
                "aws_binary": str(AWS),
                "profile": "fixture",
                "region": "us-east-1",
                "account_id": "123456789012",
                "project_name": "fixture-dev",
            }
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original_run = instance.run

            def local_run(argv, _env, *, secret=False):
                return original_run(
                    [
                        *argv,
                        "--endpoint-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--no-sign-request",
                        "--cli-read-timeout",
                        "3",
                        "--cli-connect-timeout",
                        "3",
                    ],
                    env,
                    secret=secret,
                )

            try:
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.object(instance, "identity", return_value={}))
                    stack.enter_context(patch.object(instance, "outputs", return_value={}))
                    stack.enter_context(
                        patch.object(instance, "live_function", return_value={"arn": "fixture"})
                    )
                    stack.enter_context(patch.object(instance, "run", side_effect=local_run))
                    stack.enter_context(
                        patch("devsecops_cli.deployment.time.time", return_value=2000.0)
                    )
                    if fail_last_page:
                        with self.assertRaisesRegex(DeploymentError, "fixture page denied"):
                            instance.logs()
                        result = None
                    else:
                        result = instance.logs()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
        return result, requests, events

    def test_latest_events_include_short_and_empty_pages(self):
        result, requests, events = self.exercise()
        self.assertEqual(result["log_events"], events[-50:])
        self.assertEqual([r.get("nextToken") for r in requests], [None, "page-2", "page-3"])
        self.assertTrue(
            all(r["startTime"] == 1_100_000 and r["endTime"] == 2_000_000 for r in requests)
        )
        self.assertTrue(
            all(r["logGroupName"] == "/aws/lambda/fixture-dev-dev-lambda" for r in requests)
        )

    def test_later_page_failure_does_not_report_partial_success(self):
        _, requests, _ = self.exercise(fail_last_page=True)
        self.assertEqual(len(requests), 3)
