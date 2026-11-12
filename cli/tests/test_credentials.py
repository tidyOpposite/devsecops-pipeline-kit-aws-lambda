"""Exercise the credential bridge, including the actual pinned AWS provider."""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from devsecops_cli.deployment import Deployment

ROOT = Path(__file__).resolve().parents[2]
FAKE = {
    "Version": 1,
    "AccessKeyId": "AKIAFAKELOCALTESTONLY",
    "SecretAccessKey": "fake-local-secret",
    "SessionToken": "fake-local-token",
}


@unittest.skipIf(sys.platform == "win32", "Current support target is macOS and Debian.")
class DeploymentCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kit credential test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "work's $(touch PWNED) space"
        self.root.mkdir()
        self.deployment = Deployment(self.root, "diploma")
        self.deployment.home.mkdir(parents=True)
        self.python = self.root / "Python with spaces"
        self.python.symlink_to(sys.executable)
        fake_aws = self.root / "fake aws"
        fake_aws.write_text(
            "#!/usr/bin/env python3\nimport json, sys\n"
            "assert sys.argv[1:] == ['configure','export-credentials','--profile','source-test','--format','process']\n"
            + "print("
            + repr(json.dumps(FAKE))
            + ")\n"
        )
        fake_aws.chmod(0o700)
        self.deployment.settings = {
            "profile": "source-test",
            "region": "us-east-1",
            "aws_binary": str(fake_aws),
        }

    def environment(self):
        with patch("devsecops_cli.deployment.sys.executable", str(self.python)):
            return self.deployment.tf_env()

    def test_shell_arguments_are_literal_and_credentials_not_persisted(self):
        env = self.environment()
        command = Path(env["AWS_CONFIG_FILE"]).read_text().split("credential_process = ")[1].strip()
        result = subprocess.run(
            ["/bin/sh", "-c", command], cwd=self.root, env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), FAKE)
        self.assertFalse((self.root / "PWNED").exists())
        for file in self.deployment.home.iterdir():
            if file.is_file():
                self.assertNotIn(FAKE["SecretAccessKey"], file.read_text())
                self.assertNotIn(FAKE["SessionToken"], file.read_text())

    @unittest.skipUnless(
        os.environ.get("DEVSECOPS_TEST_TERRAFORM")
        and os.environ.get("DEVSECOPS_TEST_AWS_PROVIDER_DIR"),
        "Run the credential-free provider integration in the Terraform CI job.",
    )
    def test_real_provider_loads_process_credentials_from_spaced_python_path(self):
        requests = []

        class STS(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                requests.append((body, self.headers.get("Authorization", "")))
                response = (
                    b'<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
                    b"<GetCallerIdentityResult><Arn>arn:aws:iam::123456789012:root</Arn>"
                    b"<UserId>FAKELOCALUSER</UserId><Account>123456789012</Account>"
                    b"</GetCallerIdentityResult><ResponseMetadata><RequestId>local-test</RequestId>"
                    b"</ResponseMetadata></GetCallerIdentityResponse>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *_):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), STS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.deployment.source.mkdir(parents=True)
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        (self.deployment.source / "main.tf").write_text(
            """terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}
provider "aws" {
  region = "us-east-1"
  allowed_account_ids = ["123456789012"]
  endpoints { sts = """
            + json.dumps(endpoint)
            + """ }
}
data "aws_caller_identity" "current" {}
output "account_id" { value = data.aws_caller_identity.current.account_id }
"""
        )
        shutil.copyfile(
            ROOT / "terraform/.terraform.lock.hcl", self.deployment.source / ".terraform.lock.hcl"
        )
        env = self.environment()
        env.update(NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        binary = os.environ["DEVSECOPS_TEST_TERRAFORM"]
        provider_dir = str(Path(os.environ["DEVSECOPS_TEST_AWS_PROVIDER_DIR"]).resolve())
        for arguments in (
            [
                "init",
                "-backend=false",
                "-lockfile=readonly",
                "-input=false",
                "-no-color",
                f"-plugin-dir={provider_dir}",
            ],
            ["plan", "-input=false", "-no-color", "-out=proof.tfplan"],
        ):
            result = subprocess.run(
                [binary, f"-chdir={self.deployment.source}", *arguments],
                cwd=self.root,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            requests, "The real provider must retrieve process credentials and call local STS."
        )
        self.assertTrue(all(b"Action=GetCallerIdentity" in body for body, _ in requests))
        self.assertTrue(
            all("Credential=" + FAKE["AccessKeyId"] + "/" in auth for _, auth in requests)
        )
        self.assertFalse((self.root / "PWNED").exists())
