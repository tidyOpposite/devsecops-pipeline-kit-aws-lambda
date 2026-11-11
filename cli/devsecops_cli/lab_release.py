"""Validate single-operator release proof without claiming production acceptance.

A release proof binds the installed wheel and one clean source commit to raw
lab operations. Checksums establish bundle integrity, not an AWS attestation.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from . import VERSION
from .lab import source_digest

REQUIRED_FILES = ["release-proof.json", "release-install.txt", "release-checksums.txt",
                  "lab-scenario.json", "cleanup.json", "manifest.json", "notes.md"]
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
SCOPE = "single-operator-dev"


def checked_path(directory: Path, name: str) -> Path:
    rel = Path(name)
    if not name or rel.is_absolute() or ".." in rel.parts or "\\" in name:
        raise ValueError("Unsafe evidence path")
    path = directory / rel
    if any((directory / Path(*rel.parts[:i])).is_symlink() for i in range(len(rel.parts) + 1)):
        raise ValueError("Evidence symlinks are not allowed")
    if not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError(f"Missing or oversized evidence: {name}")
    return path


def read_json(directory: Path, name: str) -> Any:
    return json.loads(checked_path(directory, name).read_text())


def require(value: Any, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_manifest(directory: Path) -> set[str]:
    manifest = read_json(directory, "manifest.json")
    require(manifest.get("schema_version") == 1 and isinstance(manifest.get("files"), dict), "Invalid manifest")
    files = manifest["files"]
    require(0 < len(files) <= 10000 and "manifest.json" not in files, "Invalid manifest file set")
    total = 0
    for name, checksum in files.items():
        path = checked_path(directory, name)
        total += path.stat().st_size
        require(total <= MAX_TOTAL and re.fullmatch(r"[a-f0-9]{64}", str(checksum))
                and sha(path) == checksum, f"Evidence checksum mismatch: {name}")
    require(set(REQUIRED_FILES) - {"manifest.json"} <= files.keys(), "Required evidence is not covered by the manifest")
    return set(files)


def ci_identity(root: Path, proof: dict, repository: str) -> None:
    require(repository.lower() == proof["repository"].lower(), "Wrong release repository")
    result = subprocess.run(["gh", "api", f"repos/{repository}/actions/runs/{proof['ci_run_id']}"],
                            cwd=root, capture_output=True, text=True, timeout=45, check=False)
    require(result.returncode == 0, "Cannot verify candidate CI")
    run = json.loads(result.stdout)
    require(run.get("head_sha") == proof["commit_sha"] and run.get("head_branch") == "main"
            and run.get("path", "").split("@", 1)[0] == ".github/workflows/ci.yml"
            and run.get("event") in {"push", "workflow_dispatch"}
            and run.get("status") == "completed" and run.get("conclusion") == "success", "Candidate CI identity or outcome mismatch")


def lab_evidence_checks(root: Path, directory: Path, *, repository: str | None = None,
                        artifacts_dir: Path | None = None) -> list[dict[str, str]]:
    try:
        covered = verify_manifest(directory)

        def document(name: str) -> Any:
            require(name in covered, f"Evidence is not in the manifest: {name}")
            return read_json(directory, name)

        proof = document("release-proof.json")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10, check=False)
        require(proof.get("schema_version") == 2 and proof.get("scope") == SCOPE
                and proof.get("production_acceptance") is False and proof.get("version") == VERSION
                and head.returncode == 0 and re.fullmatch(r"[a-f0-9]{40}", head.stdout.strip())
                and proof.get("commit_sha") == head.stdout.strip(), "Release scope, version or commit mismatch")
        require(re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", str(proof.get("repository", "")))
                and type(proof.get("ci_run_id")) is int and proof["ci_run_id"] > 0, "Candidate CI run identity missing")
        require(proof.get("source_sha256") == source_digest(root), "Running CLI/Terraform source differs from the candidate")
        wheel = f"devsecops_pipeline_cli-{VERSION}-py3-none-any.whl"
        wheel_name = "artifacts/" + wheel
        require(wheel_name in covered and sha(checked_path(directory, wheel_name)) == proof.get("wheel_sha256"), "Candidate wheel mismatch")
        require(checked_path(directory, "release-install.txt").read_text().strip() == f"devsecops {VERSION}", "Installed version mismatch")
        checksums = checked_path(directory, "release-checksums.txt").read_text().splitlines()
        require(f"{proof['wheel_sha256']}  {wheel}" in checksums and f"{wheel}: OK" in checksums, "Wheel verification transcript missing")
        if artifacts_dir is not None:
            require(sha(artifacts_dir / wheel) == proof["wheel_sha256"], "Publication wheel differs from the accepted wheel")
        account, region, project = proof["account_id"], proof["region"], proof["project_name"]
        require(re.fullmatch(r"\d{12}", account) and re.fullmatch(r"[a-z]{2}-[a-z]+-\d+", region)
                and re.fullmatch(r"kit-lab-[a-z0-9-]+-[a-f0-9]{6}", project), "Invalid lab scope")
        images = proof["images"]
        prefix = f"{account}.dkr.ecr.{region}.amazonaws.com/{project}-dev-lambda-repo@sha256:"
        require(set(images) == {"a", "b", "c"} and len(set(images.values())) == 3
                and all(value.startswith(prefix) and re.fullmatch(r"[a-f0-9]{64}", value[len(prefix):]) for value in images.values()), "Three distinct immutable lab images required")
        function = f"arn:aws:lambda:{region}:{account}:function:{project}-dev-lambda"
        stages = document("lab-scenario.json")["operations"]
        require([step["stage"] for step in stages] == ["a", "b", "c", "rollback", "destroy"], "Incomplete or reordered lab scenario")
        previous_time = ""
        for step in stages:
            directory_name = step["event"]
            operation = document(directory_name + "/operation.json")
            result = document(directory_name + "/result.json")
            review = document(step["review"])
            require(operation.get("operation") == "apply" and operation.get("cli_version") == VERSION
                    and operation.get("source_commit") == proof["commit_sha"] and operation.get("source_clean") is True
                    and operation.get("source_sha256") == proof["source_sha256"]
                    and operation.get("production_acceptance") is False, "Operation is not from the clean release candidate")
            settings = operation["settings"]
            require((settings["account_id"], settings["region"], settings["project_name"]) == (account, region, project)
                    and result.get("kind") == "single-operator-lab" and result.get("production_acceptance") is False
                    and (result.get("account_id"), result.get("region")) == (account, region), "Operation scope mismatch")
            require(operation["started_at"] > previous_time, "Operations are not chronological")
            previous_time = operation["started_at"]
            require(review.get("account_id") == account and review.get("region") == region
                    and review.get("source_sha256") == proof["source_sha256"], "Plan scope/source mismatch")
            plan_dir = str(Path(step["review"]).parent)
            for name, checksum in review["files"].items():
                path = plan_dir + "/" + name
                require(path in covered and sha(checked_path(directory, path)) == checksum, "Reviewed plan bytes changed")
            commands = [document(name) for name in sorted(covered) if name.startswith(directory_name + "/command-") and name.endswith(".json")]
            require(any(c.get("returncode") == 0 and c.get("argv", [""])[0] == "terraform"
                        and "apply" in c["argv"] and c["argv"][-1].endswith("/plan.tfplan") for c in commands), "Saved Terraform apply was not successful")
            stage = step["stage"]
            require(step.get("exit_code") == (1 if stage == "c" else 0), "Unexpected CLI exit code")
            if stage == "destroy":
                require(review["stage"] == "destroy" and result.get("status") == "destroyed", "Destroy was not completed")
                continue
            target = images["a" if stage == "rollback" else stage]
            require(review.get("image_uri") == target and review.get("stage") == ("rollback" if stage == "rollback" else "workload"), "Reviewed image/stage mismatch")
            expected_previous = None if stage == "a" else images["a" if stage == "b" else "b"]
            require((review.get("previous") or {}).get("image_uri") == expected_previous, "Recovery target mismatch")
            active = images["b"] if stage == "c" else target
            outcome = result.get("recovery", {}) if stage == "c" else result
            require((stage != "c" and result.get("status") == "healthy") or
                    (stage == "c" and result.get("status") == "failed" and outcome.get("status") == "recovered"
                     and step.get("exit_code") == 1), "Failure/recovery semantics mismatch")
            require(outcome.get("function") == {"arn": function, "image_uri": active}
                    and type(outcome.get("health", {}).get("status")) is int
                    and 200 <= outcome["health"]["status"] < 300
                    and outcome["health"]["url"] == f"https://{proof['api_id']}.execute-api.{region}.amazonaws.com/health"
                    and re.fullmatch(r"[a-f0-9]{64}", str(outcome.get("state_sha256", ""))), "Live digest, state or signed health proof missing")
            if stage == "c":
                require(any(document(name).get("status") == 503 for name in covered if name.startswith(directory_name + "/http-") and name.endswith(".json")), "Intentional failed health was not observed")
        cleanup = document("cleanup.json")
        require(cleanup.get("account_id") == account and cleanup.get("region") == region
                and cleanup.get("project_name") == project and cleanup.get("managed_resources_after") == 0
                and cleanup.get("backup_restore_verified") is True and cleanup.get("backend") == "local-retained"
                and cleanup.get("billing_followup") in {"pending", "verified"}, "Cleanup/restore/retention proof incomplete")
        state = document(cleanup["final_state"])
        require(not state.get("resources"), "Final state is not empty")
        inventory = document(cleanup["inventory"])
        require(isinstance(inventory.get("resources"), list) and len(inventory["resources"]) == 12, "Physical resource inventory missing")
        require(Counter(item["arn"].split(":")[2] for item in inventory["resources"]) ==
                Counter({"lambda":1,"apigateway":2,"logs":2,"s3":2,"ecr":1,"sqs":1,"kms":2,"iam":1}),
                "Physical inventory service coverage mismatch")
        require({item["arn"] for item in inventory["resources"]} == {item["arn"] for item in cleanup["checks"]}, "Cleanup inventory coverage mismatch")
        for item in cleanup["checks"]:
            command = document(item["evidence"])
            service = item["arn"].split(":")[2]
            if item["status"] == "pending-deletion":
                key = json.loads(command["stdout"])["KeyMetadata"]
                require(service == "kms" and key["Arn"] == item["arn"] and key["KeyState"] == "PendingDeletion"
                        and key.get("DeletionDate"), "KMS deletion schedule not verified")
            else:
                require(item["status"] == "absent", "Resource absence unverified")
                if command["returncode"]:
                    require(any(code in command.get("stderr", "") for code in (
                        "ResourceNotFoundException", "NotFoundException", "RepositoryNotFoundException",
                        "NoSuchEntity", "(404)", "QueueDoesNotExist", "NonExistentQueue")), "Absence request failed without explicit not-found")
                else:
                    value = json.loads(command["stdout"])
                    require(value in ([], {"logGroups": []}, {"Aliases": []}), "Absence list is not empty")
                identifier = item["arn"].split(":", 5)[5]
                require(item.get("query_id") and item["query_id"] in command["argv"]
                        and (item["query_id"] in identifier or identifier in item["query_id"]), "Absence request does not target the inventoried resource")
        if repository is not None:
            ci_identity(root, proof, repository)
        return [{"name":"Single-operator release evidence", "status":"OK", "detail":"Candidate wheel, source, A/B/failed-C/recovery/rollback and cleanup match. Production remains experimental; delayed billing may be pending."}]
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.TimeoutExpired) as exc:
        return [{"name":"Single-operator release evidence", "status":"BLOCKED", "detail":str(exc)}]
