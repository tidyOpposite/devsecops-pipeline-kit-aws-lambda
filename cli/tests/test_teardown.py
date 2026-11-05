"""Decommission cleanup stays scoped to a reviewed immutable inventory."""

import argparse
import copy
import datetime as dt
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import main as cli, teardown

ACCOUNT = "123456789012"
BUCKET = "demo-workload-data-123456789012"
REGION = "us-east-1"


def version(index, version_id=None):
    return dict(Key=f"folder/object-{index}", VersionId=str(index) if version_id is None else version_id,
                ETag=f'"etag-{index}"', Size=index, LastModified="2026-11-05T10:00:00+00:00")


class FakeS3:
    def __init__(self):
        self.account = ACCOUNT
        self.versions = [version(1, "null"), version(2)]
        self.markers = [dict(Key="deleted", VersionId="marker-1", LastModified="2026-11-05T10:00:00+00:00")]
        self.uploads = [dict(Key="--upload/key with spaces", UploadId="upload-1", Initiated="2026-11-05T10:00:00+00:00")]
        self.calls = []
        self.status = "Enabled"
        self.region = REGION
        self.mfa = "Disabled"
        self.partial_error = False
        self.new_write = False

    def __call__(self, arguments, region, payload=None):
        self.calls.append((arguments, region, payload))
        operation = tuple(arguments[:2])
        if operation == ("sts", "get-caller-identity"):
            return {"Account": self.account}
        assert arguments[arguments.index("--expected-bucket-owner") + 1] == ACCOUNT
        assert arguments[arguments.index("--bucket") + 1] == BUCKET
        assert region == REGION
        if operation == ("s3api", "head-bucket"):
            return {"BucketRegion": self.region}
        if operation == ("s3api", "get-bucket-versioning"):
            return {"Status": self.status, "MFADelete": self.mfa}
        if operation == ("s3api", "list-object-versions"):
            return dict(IsTruncated=False, Versions=copy.deepcopy(self.versions), DeleteMarkers=copy.deepcopy(self.markers))
        if operation == ("s3api", "list-multipart-uploads"):
            return dict(IsTruncated=False, Uploads=copy.deepcopy(self.uploads))
        if operation == ("s3api", "delete-objects"):
            assert arguments[-2:] == ["--delete", "file:///dev/stdin"]
            assert payload["Quiet"] and 0 < len(payload["Objects"]) <= 1000
            targets = {(item["Key"], item["VersionId"]) for item in payload["Objects"]}
            if self.partial_error:
                targets = {next(iter(targets))}
            self.versions = [item for item in self.versions if (item["Key"], item["VersionId"]) not in targets]
            self.markers = [item for item in self.markers if (item["Key"], item["VersionId"]) not in targets]
            if self.new_write:
                self.versions.append(version(9999))
            return {"Errors": [{"Code": "AccessDenied"}]} if self.partial_error else {}
        if operation == ("s3api", "abort-multipart-upload"):
            assert "--key=--upload/key with spaces" in arguments
            self.uploads = []
            return {}
        raise AssertionError(f"Unexpected operation (including bucket deletion): {arguments}")

    def mutations(self):
        return [call for call in self.calls if call[0][1] in {"delete-objects", "abort-multipart-upload"}]


class TeardownTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "inventory.json"
        self.s3 = FakeS3()
        mocked = patch.object(teardown, "aws_json", side_effect=self.s3)
        mocked.start()
        self.addCleanup(mocked.stop)

    def plan(self, purpose="workload-data"):
        return teardown.bucket_plan(BUCKET, ACCOUNT, REGION, purpose, self.path)

    def purge(self, digest, **options):
        return teardown.bucket_purge(self.path, digest, options.get("bucket", BUCKET), options.get("account", ACCOUNT),
                                     options.get("region", REGION), options.get("ack", True), options.get("backend", False))

    def rewrite(self, update):
        value = json.loads(self.path.read_text())
        update(value)
        self.path.write_text(json.dumps(value))
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_plan_is_read_only_private_bounded_and_never_overwrites_an_approved_file(self):
        plan = self.plan()
        self.assertEqual(plan["object_versions"], 3)
        self.assertEqual(plan["multipart_uploads"], 1)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), plan["sha256"])
        self.assertFalse(self.s3.mutations())
        previous = self.path.read_bytes()
        with self.assertRaisesRegex(teardown.TeardownError, "already exists"):
            self.plan()
        self.assertEqual(self.path.read_bytes(), previous)

    def test_reviewed_purge_removes_explicit_versions_markers_and_uploads_and_verifies_empty(self):
        digest = self.plan()["sha256"]
        output = self.purge(digest)
        self.assertEqual(output["status"], "empty")
        self.assertEqual(output["deleted_versions"], 3)
        self.assertEqual(output["aborted_uploads"], 1)
        self.assertFalse(self.s3.versions or self.s3.markers or self.s3.uploads)
        self.assertEqual(self.s3.calls[-1][0][1], "list-multipart-uploads")
        self.assertEqual({item["VersionId"] for item in self.s3.mutations()[0][2]["Objects"]}, {"null", "2", "marker-1"})

    def test_wrong_account_acknowledgment_scope_and_manifest_digest_never_delete(self):
        digest = self.plan()["sha256"]
        for options in ({"ack": False}, {"bucket": "other-bucket"}, {"account": "999999999999"}, {"region": "eu-central-1"}):
            with self.subTest(options=options), self.assertRaises(teardown.TeardownError):
                self.purge(digest, **options)
        with self.assertRaisesRegex(teardown.TeardownError, "SHA-256"):
            self.purge("0" * 64)
        self.s3.account = "999999999999"
        with self.assertRaisesRegex(teardown.TeardownError, "Current AWS account differs"):
            self.purge(digest)
        self.assertFalse(self.s3.mutations())

    def test_changed_and_expired_inventories_require_a_fresh_review(self):
        digest = self.plan()["sha256"]
        self.s3.versions[0]["ETag"] = '"changed-null-version"'
        with self.assertRaisesRegex(teardown.TeardownError, "changed after review"):
            self.purge(digest)
        expired = self.rewrite(lambda value: value.update(created_at=(dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)).isoformat()))
        with self.assertRaisesRegex(teardown.TeardownError, "older than one hour"):
            self.purge(expired)
        malformed = self.rewrite(lambda value: value.update(objects=[None]))
        with self.assertRaises(teardown.TeardownError):
            self.purge(malformed)
        self.assertFalse(self.s3.mutations())

    def test_backend_purpose_has_a_separate_authorization_boundary(self):
        digest = self.plan("backend-state")["sha256"]
        self.s3.calls.clear()
        with self.assertRaisesRegex(teardown.TeardownError, "allow-backend-cleanup"):
            self.purge(digest)
        self.assertEqual(self.s3.calls, [])
        self.assertEqual(self.purge(digest, backend=True)["status"], "empty")

    def test_large_batches_partial_errors_and_new_writes_never_claim_success(self):
        self.s3.versions = [version(index) for index in range(1, 1502)]
        digest = self.plan()["sha256"]
        self.purge(digest)
        batches = [call[2]["Objects"] for call in self.s3.mutations() if call[0][1] == "delete-objects"]
        self.assertEqual([len(batch) for batch in batches], [1000, 502])
        self.path.unlink()
        self.s3.versions = [version(1), version(2)]
        self.s3.partial_error = True
        digest = self.plan()["sha256"]
        with self.assertRaisesRegex(teardown.TeardownError, "partial deletion"):
            self.purge(digest)
        with self.assertRaisesRegex(teardown.TeardownError, "changed after review"):
            self.purge(digest)
        self.path.unlink()
        self.s3.partial_error, self.s3.new_write = False, True
        digest = self.plan()["sha256"]
        with self.assertRaisesRegex(teardown.TeardownError, "Cleanup is incomplete"):
            self.purge(digest)

    def test_unsupported_retention_and_inventory_errors_fail_before_deletion(self):
        self.s3.mfa = "Enabled"
        with self.assertRaisesRegex(teardown.TeardownError, "MFA Delete"):
            self.plan()
        self.s3.mfa = "Disabled"
        self.s3.versions.append(copy.deepcopy(self.s3.versions[0]))
        with self.assertRaisesRegex(teardown.TeardownError, "duplicate"):
            self.plan()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.s3.mutations())

    def test_wrong_actual_bucket_region_is_rejected_before_planning(self):
        self.s3.region = "eu-central-1"
        with self.assertRaisesRegex(teardown.TeardownError, "Bucket region differs"):
            self.plan()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.s3.mutations())
        with patch.object(teardown, "aws_json", side_effect=[{"Account": ACCOUNT}, {}, {"LocationConstraint": "EU"}]):
            teardown.check_owner(BUCKET, ACCOUNT, "eu-west-1")
        with patch.object(teardown, "aws_json", side_effect=[{"Account": ACCOUNT}, {}, {}]):
            with self.assertRaisesRegex(teardown.TeardownError, "Cannot establish"):
                teardown.check_owner(BUCKET, ACCOUNT, REGION)

    def test_explicit_service_pagination_and_incomplete_marker_detection(self):
        pages = [dict(IsTruncated=True, Versions=[version(1)], NextKeyMarker="key", NextVersionIdMarker="version"),
                 dict(IsTruncated=False, DeleteMarkers=self.s3.markers)]
        with patch.object(teardown, "aws_json", side_effect=pages) as call:
            entries = teardown.list_pages(BUCKET, ACCOUNT, REGION, "list-object-versions")
            self.assertEqual(len(entries), 2)
            self.assertEqual(call.call_args.args[0][-4:], ["--key-marker", "key", "--version-id-marker", "version"])
        with patch.object(teardown, "aws_json", return_value=dict(IsTruncated=True)):
            with self.assertRaisesRegex(teardown.TeardownError, "pagination markers"):
                teardown.list_pages(BUCKET, ACCOUNT, REGION, "list-object-versions")
        with patch.object(teardown, "aws_json", side_effect=[dict(IsTruncated=True, Uploads=[], NextKeyMarker="key", NextUploadIdMarker="upload"),
                                                            dict(IsTruncated=False, Uploads=self.s3.uploads)]) as call:
            self.assertEqual(len(teardown.list_pages(BUCKET, ACCOUNT, REGION, "list-multipart-uploads")), 1)
            self.assertEqual(call.call_args.args[0][-4:], ["--key-marker", "key", "--upload-id-marker", "upload"])

    def test_cli_guide_is_local_menu_routes_and_json_errors_do_not_mutate(self):
        with patch.object(cli, "repo_root", return_value=self.root), patch.object(cli, "command_exists", return_value=True):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli.main(["terraform", "teardown", "--format", "json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["kind"], "teardown-guide")
            self.assertFalse(self.s3.calls)
            for handler, choice in ((cli.menu_deploy_hub, "10"), (lambda: cli.menu_terraform_hub(self.root), "6")):
                with patch("builtins.input", side_effect=[choice, ""]), redirect_stdout(io.StringIO()):
                    handler()
            self.assertFalse(self.s3.calls)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["terraform", "teardown", "bucket-plan", "--bucket", BUCKET,
                    "--region", REGION, "--expected-account-id", ACCOUNT, "--purpose", "workload-data", "--output", str(self.path)]), 0)
            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(["terraform", "teardown", "bucket-purge", "--bucket", BUCKET, "--region", REGION,
                    "--expected-account-id", ACCOUNT, "--manifest", str(self.path), "--sha256", "0" * 64, "--format", "json"])
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(output.getvalue())["kind"], "command-error")
            self.assertFalse(self.s3.mutations())

    def test_aws_boundary_passes_delete_json_on_stdin_and_disables_prompts(self):
        payload = {"Objects": [{"Key": "private key with spaces", "VersionId": "explicit-id"}], "Quiet": True}
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            # Invoke the real boundary despite this class's fake AWS client.
            with patch.object(teardown, "aws_json", new=ORIGINAL_AWS_JSON):
                teardown.aws_json(["s3api", "delete-objects", "--delete", "file:///dev/stdin"], REGION, payload)
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
        self.assertNotIn("private key with spaces", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["env"]["AWS_CLI_AUTO_PROMPT"], "off")

    def test_configured_backend_cannot_be_mislabeled_as_workload_cleanup(self):
        cfg = cli.clean_config("student-demo")
        cfg["backend"]["bucket"] = BUCKET
        cli.write_config(self.root, cfg)
        output = io.StringIO()
        with patch.object(cli, "repo_root", return_value=self.root), patch.object(cli, "command_exists", return_value=True), redirect_stdout(output):
            result = cli.main(["terraform", "teardown", "bucket-plan", "--bucket", BUCKET, "--region", REGION,
                               "--expected-account-id", ACCOUNT, "--purpose", "workload-data", "--output", str(self.path), "--format", "json"])
        self.assertEqual(result, 1)
        self.assertIn("backend purpose", json.loads(output.getvalue())["error"])
        self.assertEqual(self.s3.calls, [])
        self.assertFalse(self.path.exists())


ORIGINAL_AWS_JSON = teardown.aws_json
