"""Reviewed S3 cleanup for the decommission runbook; never deletes a bucket."""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

AWS_REGION_RE = re.compile(r"[a-z]{2}-[a-z]+-[0-9]\Z")
S3_BUCKET_RE = re.compile(
    r"(?!\d+\.\d+\.\d+\.\d+$)(?!.*\.\.)(?!.*\.-|.*-\.)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z"
)
_CLIENT = ContextVar("cleanup_aws_client", default=None)


@contextmanager
def using_aws_client(client):
    token = _CLIENT.set(client)
    try:
        yield
    finally:
        _CLIENT.reset(token)


PURPOSES = ("workload-data", "workload-logs")
MAX_ENTRIES = 100_000
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


class TeardownError(ValueError):
    """An unsafe scope, changed inventory or incomplete cleanup."""


def aws_json(arguments: list[str], region: str, payload: dict | None = None) -> dict[str, Any]:
    client = _CLIENT.get()
    if client is not None:
        return client(arguments, payload=payload)
    result = subprocess.run(
        ["aws", *arguments, "--region", region, "--output", "json", "--no-cli-pager"],
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
        env=dict(os.environ, AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off"),
    )
    if result.returncode:
        raise TeardownError(
            f"AWS {arguments[0]} {arguments[1]} failed; cleanup is not verified. {result.stderr.strip()}"
        )
    try:
        value = json.loads(result.stdout or "{}")
    except ValueError:
        raise TeardownError("AWS returned invalid JSON; cleanup is not verified.") from None
    if not isinstance(value, dict):
        raise TeardownError("AWS returned an invalid response object.")
    return value


def validate_scope(bucket: str, account: str, region: str, purpose: str) -> None:
    if not S3_BUCKET_RE.fullmatch(bucket) or not re.fullmatch(r"[0-9]{12}", account):
        raise TeardownError(
            "Supply an exact bucket name and independently confirmed 12-digit AWS account ID."
        )
    if not AWS_REGION_RE.fullmatch(region) or purpose not in PURPOSES:
        raise TeardownError("Supply a valid AWS region and an explicit bucket purpose.")


def check_owner(bucket: str, account: str, region: str) -> None:
    identity = aws_json(["sts", "get-caller-identity"], region)
    if identity.get("Account") != account:
        raise TeardownError(
            "Current AWS account differs from the confirmed account; no S3 changes were made."
        )
    head = aws_json(
        ["s3api", "head-bucket", "--bucket", bucket, "--expected-bucket-owner", account], region
    )
    actual_region = head.get("BucketRegion")
    if actual_region is None:
        location = aws_json(
            [
                "s3api",
                "get-bucket-location",
                "--bucket",
                bucket,
                "--expected-bucket-owner",
                account,
            ],
            region,
        )
        if "LocationConstraint" not in location:
            raise TeardownError("Cannot establish the bucket's actual region.")
        actual_region = location["LocationConstraint"] or "us-east-1"
        actual_region = "eu-west-1" if actual_region == "EU" else actual_region
    if actual_region != region:
        raise TeardownError(
            "Bucket region differs from the confirmed region; no S3 changes were made."
        )


def list_pages(bucket: str, account: str, region: str, operation: str) -> list[dict]:
    """Use service pagination explicitly, including the version/upload marker."""

    arguments = [
        "s3api",
        operation,
        "--bucket",
        bucket,
        "--expected-bucket-owner",
        account,
        "--no-paginate",
    ]
    marker_names = (
        ("KeyMarker", "VersionIdMarker")
        if operation == "list-object-versions"
        else ("KeyMarker", "UploadIdMarker")
    )
    marker_flags = (
        ("--key-marker", "--version-id-marker")
        if operation == "list-object-versions"
        else ("--key-marker", "--upload-id-marker")
    )
    fields = ("Versions", "DeleteMarkers") if operation == "list-object-versions" else ("Uploads",)
    result, cursor, seen = [], [], set()
    while True:
        page = aws_json([*arguments, *cursor], region)
        if type(page.get("IsTruncated")) is not bool:
            raise TeardownError(
                "AWS pagination status is missing; refusing an incomplete inventory."
            )
        for field in fields:
            entries = page.get(field, [])
            if not isinstance(entries, list) or any(
                not isinstance(entry, dict) for entry in entries
            ):
                raise TeardownError("AWS returned an invalid inventory list.")
            result.extend(dict(entry, entry_type=field) for entry in entries)
        if len(result) > MAX_ENTRIES:
            raise TeardownError(
                "Inventory exceeds 100000 entries. Use a separately reviewed bulk-deletion process."
            )
        if not page["IsTruncated"]:
            return result
        markers = tuple(page.get("Next" + name) for name in marker_names)
        if any(not isinstance(marker, str) or not marker for marker in markers) or markers in seen:
            raise TeardownError(
                "AWS pagination markers are missing or repeated; inventory is incomplete."
            )
        seen.add(markers)
        cursor = [value for flag, marker in zip(marker_flags, markers) for value in (flag, marker)]


def normalize_entries(entries: list[dict]) -> list[dict]:
    result, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise TeardownError("Inventory entry must be an object.")
        kind = entry.get("entry_type")
        if kind not in {"Versions", "DeleteMarkers", "Uploads"}:
            raise TeardownError("Unrecognized inventory entry.")
        fields = (
            ("Key", "UploadId", "Initiated")
            if kind == "Uploads"
            else ("Key", "VersionId", "LastModified")
        )
        if any(not isinstance(entry.get(field), str) or not entry[field] for field in fields):
            raise TeardownError("Inventory entries need explicit keys, IDs and timestamps.")
        item = {field: entry[field] for field in fields}
        item["entry_type"] = kind
        if kind == "Versions":
            if (
                not isinstance(entry.get("ETag"), str)
                or not entry["ETag"]
                or type(entry.get("Size")) is not int
                or entry["Size"] < 0
            ):
                raise TeardownError("Object version metadata is incomplete.")
            item.update(ETag=entry["ETag"], Size=entry["Size"])
        identity = (entry["Key"], entry["UploadId"] if kind == "Uploads" else entry["VersionId"])
        if identity in seen:
            raise TeardownError("Inventory contains duplicate IDs; refusing ambiguous cleanup.")
        seen.add(identity)
        result.append(item)
    return sorted(result, key=lambda item: json.dumps(item, sort_keys=True))


def inventory(bucket: str, account: str, region: str) -> dict:
    check_owner(bucket, account, region)
    versioning = aws_json(
        ["s3api", "get-bucket-versioning", "--bucket", bucket, "--expected-bucket-owner", account],
        region,
    )
    status = versioning.get("Status")
    if status not in {"Enabled", "Suspended"} or versioning.get("MFADelete") == "Enabled":
        raise TeardownError(
            "This helper requires a versioned general-purpose bucket without MFA Delete; use a separately reviewed process."
        )
    return {
        "versioning": status,
        "objects": normalize_entries(list_pages(bucket, account, region, "list-object-versions")),
        "uploads": normalize_entries(list_pages(bucket, account, region, "list-multipart-uploads")),
    }


def bucket_plan(bucket: str, account: str, region: str, purpose: str, output: Path) -> dict:
    validate_scope(bucket, account, region, purpose)
    if output.exists():
        raise TeardownError(
            "Plan output already exists. Use a new file; reviewed plans are never overwritten."
        )
    contents = inventory(bucket, account, region)
    if len(contents["objects"]) + len(contents["uploads"]) > MAX_ENTRIES:
        raise TeardownError("Combined inventory exceeds 100000 entries.")
    manifest = dict(
        schema_version=1,
        bucket=bucket,
        account_id=account,
        region=region,
        purpose=purpose,
        created_at=dt.datetime.now(dt.UTC).isoformat(),
        **contents,
    )
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if len(data) > MAX_MANIFEST_BYTES:
        raise TeardownError("Inventory exceeds the manifest size limit.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(data)
    return dict(
        kind="teardown-bucket-plan",
        schema_version=1,
        manifest=str(output),
        sha256=hashlib.sha256(data).hexdigest(),
        bucket=bucket,
        purpose=purpose,
        object_versions=len(contents["objects"]),
        multipart_uploads=len(contents["uploads"]),
        message="Read-only inventory saved. Review every entry and preserve required data before approving deletion.",
    )


def bucket_purge(
    path: Path,
    digest: str,
    bucket: str,
    account: str,
    region: str,
    backup_acknowledged: bool,
    *,
    expected_purpose: str | None = None,
) -> dict:
    if not backup_acknowledged or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise TeardownError(
            "Acknowledge the backup/retention decision and supply the reviewed plan SHA-256 before deletion."
        )
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise TeardownError("Expected a regular, bounded inventory manifest.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise TeardownError("Manifest differs from the approved SHA-256; nothing was deleted.")
    try:
        manifest = json.loads(data)
        if (
            not isinstance(manifest, dict)
            or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
        ):
            raise ValueError("Unsupported manifest schema")
        if (manifest["bucket"], manifest["account_id"], manifest["region"]) != (
            bucket,
            account,
            region,
        ):
            raise ValueError("Manifest scope differs from the repeated bucket/account/region")
        purpose = manifest["purpose"]
        validate_scope(bucket, account, region, purpose)
        if expected_purpose is not None and purpose != expected_purpose:
            raise ValueError("Manifest purpose differs from the selected bucket role")
        created = dt.datetime.fromisoformat(manifest["created_at"])
        age = (dt.datetime.now(dt.UTC) - created).total_seconds()
        if not 0 <= age <= 3600:
            raise ValueError(
                "Plan is older than one hour or has a future timestamp; create a fresh inventory"
            )
        if not isinstance(manifest["objects"], list) or not isinstance(manifest["uploads"], list):
            raise ValueError("Invalid inventory lists")
        if len(manifest["objects"]) + len(manifest["uploads"]) > MAX_ENTRIES:
            raise ValueError("Inventory exceeds the entry limit")
        approved = {
            "versioning": manifest["versioning"],
            "objects": normalize_entries(manifest["objects"]),
            "uploads": normalize_entries(manifest["uploads"]),
        }
        if any(
            item["entry_type"] not in {"Versions", "DeleteMarkers"} for item in approved["objects"]
        ) or any(item["entry_type"] != "Uploads" for item in approved["uploads"]):
            raise ValueError("Inventory entries are in the wrong list")
    except (KeyError, TypeError, ValueError) as error:
        raise TeardownError(f"Invalid approved manifest: {error}") from None
    if inventory(bucket, account, region) != approved:
        raise TeardownError(
            "Bucket inventory changed after review. Nothing was deleted; stop writers and review a fresh plan."
        )
    objects = [{"Key": item["Key"], "VersionId": item["VersionId"]} for item in approved["objects"]]
    for offset in range(0, len(objects), 1000):
        response = aws_json(
            [
                "s3api",
                "delete-objects",
                "--bucket",
                bucket,
                "--expected-bucket-owner",
                account,
                "--delete",
                "file:///dev/stdin",
            ],
            region,
            {"Objects": objects[offset : offset + 1000], "Quiet": True},
        )
        if response.get("Errors"):
            errors = response["Errors"]
            codes = (
                sorted(
                    {
                        str(error.get("Code", "Unknown"))
                        for error in errors
                        if isinstance(error, dict)
                    }
                )
                if isinstance(errors, list)
                else []
            )
            raise TeardownError(
                "S3 reported partial deletion errors ("
                + ", ".join(codes[:8])
                + "). Keep the bucket/state/key; resolve retention/permissions and review a fresh plan."
            )
    for upload in approved["uploads"]:
        aws_json(
            [
                "s3api",
                "abort-multipart-upload",
                "--bucket",
                bucket,
                "--expected-bucket-owner",
                account,
                "--key=" + upload["Key"],
                "--upload-id=" + upload["UploadId"],
            ],
            region,
        )
    remaining = inventory(bucket, account, region)
    if remaining["objects"] or remaining["uploads"]:
        raise TeardownError(
            "New versions or in-flight uploads remain. Cleanup is incomplete; stop writers and review a fresh plan."
        )
    return dict(
        kind="teardown-bucket-purge",
        schema_version=1,
        bucket=bucket,
        status="empty",
        deleted_versions=len(objects),
        aborted_uploads=len(approved["uploads"]),
        message="Version and multipart inventories are empty. Bucket, ECR, KMS and Terraform backend were not deleted.",
    )


def configure_parser(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="teardown_command", required=True)
    plan = commands.add_parser(
        "bucket-plan", help="Save a read-only inventory of an owned versioned bucket."
    )
    purge = commands.add_parser("bucket-purge", help="Delete only reviewed versions and uploads.")
    for child in (plan, purge):
        child.add_argument("--bucket", required=True)
        child.add_argument("--purpose", required=True, choices=PURPOSES)
        child.add_argument("--format", choices=("human", "json"), default=argparse.SUPPRESS)
    plan.add_argument("--output", type=Path, required=True)
    purge.add_argument("--manifest", type=Path, required=True)
    purge.add_argument("--sha256", required=True)
    purge.add_argument("--acknowledge-backup", action="store_true")
