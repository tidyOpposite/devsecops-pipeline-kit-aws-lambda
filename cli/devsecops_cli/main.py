"""One CLI workflow: configure, review, deploy, inspect, recover and remove."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from . import VERSION, deployment, teardown
from .migration import migrate
from .paths import REQUIRED_PROJECT_FILES, find_project_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devsecops",
        description="Operate an account-bound AWS Lambda container using reviewed Terraform plans.",
    )
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "init": "Save account, region and named AWS profile; create no AWS resources.",
        "plan": "Save a registry, workload, rollback or destroy plan for review.",
        "apply": "Verify and apply the exact reviewed saved plan.",
        "status": "Verify live image, state, signed health and capacity.",
        "request": "Send an IAM-signed GET or POST to the deployment API.",
        "logs": "Read the latest 50 Lambda events from the last 15 minutes.",
        "concurrency": "Inspect or change local concurrency policy; requires a new plan.",
        "config": "Inspect and validate deployment settings and state scope.",
        "cleanup": "Inventory or purge reviewed data in an owned S3 bucket.",
        "migrate": "Move legacy local state into the core deployment layout.",
    }
    for command, description in descriptions.items():
        child = commands.add_parser(command, help=description, description=description)
        child.add_argument(
            "name", help="Deployment name: 3–16 lowercase letters, digits or hyphens."
        )
        child.add_argument("--format", choices=("human", "json"), default="human")
        if command == "init":
            child.add_argument("--expected-account-id", required=True)
            child.add_argument("--region", required=True)
            child.add_argument("--profile", required=True)
        elif command == "plan":
            child.add_argument(
                "--stage", choices=("registry", "workload", "rollback", "destroy"), required=True
            )
            child.add_argument(
                "--image-uri", help="Digest URI in this deployment's ECR repository."
            )
        elif command == "apply":
            child.add_argument("--plan-id", required=True)
            child.add_argument("--sha256", required=True, help="Reviewed SHA-256 of review.json.")
            child.add_argument(
                "--yes", action="store_true", help="Authorize this saved plan's AWS changes."
            )
        elif command == "request":
            child.add_argument("--method", choices=("GET", "POST"), default="GET")
            child.add_argument(
                "--path", default="/health", help="Absolute API path without query or fragment."
            )
            child.add_argument("--body", help="JSON object for POST; at most 64 KiB.")
        elif command == "concurrency":
            child.add_argument("--mode", choices=("reserved", "unreserved"))
            child.add_argument("--reserved-executions", type=int)
        elif command == "migrate":
            child.add_argument(
                "--yes",
                action="store_true",
                help="Move validated local state; AWS is not contacted.",
            )
        elif command == "cleanup":
            teardown.configure_parser(child)
    return parser


def cleanup(root: Path, args: argparse.Namespace) -> dict:
    instance = deployment.Deployment(root, args.name)
    with instance.locked():
        instance.load()
        instance.outputs()
        state = deployment.read_json(instance.state)
        resource_name = "output_bucket" if args.purpose == "workload-data" else "log_bucket"
        buckets = [
            item.get("attributes", {}).get("bucket")
            for resource in state.get("resources", [])
            if resource.get("module") == "module.storage"
            and resource.get("type") == "aws_s3_bucket"
            and resource.get("name") == resource_name
            for item in resource.get("instances", [])
        ]
        if buckets != [args.bucket]:
            raise deployment.DeploymentError(
                "Bucket and purpose must match the selected deployment's Terraform state."
            )
        instance.begin_event("cleanup-" + args.teardown_command)
        instance.identity()
        with teardown.using_aws_client(instance.aws):
            if args.teardown_command == "bucket-plan":
                output = args.output if args.output.is_absolute() else root / args.output
                result = teardown.bucket_plan(
                    args.bucket,
                    instance.settings["account_id"],
                    instance.settings["region"],
                    args.purpose,
                    output,
                )
            else:
                path = args.manifest if args.manifest.is_absolute() else root / args.manifest
                result = teardown.bucket_purge(
                    path,
                    args.sha256,
                    args.bucket,
                    instance.settings["account_id"],
                    instance.settings["region"],
                    args.acknowledge_backup,
                    expected_purpose=args.purpose,
                )
        return instance.finish("ok", cleanup=result)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = find_project_root()
        if any(not (root / name).is_file() for name in REQUIRED_PROJECT_FILES):
            raise deployment.DeploymentError(
                "Run from a complete matching checkout; the wheel does not contain Terraform."
            )
        if args.command == "migrate":
            result = migrate(root, args.name, args.yes)
        elif args.command == "cleanup":
            result = cleanup(root, args)
        else:
            result = deployment.execute(root, args)
        code = result.get("exit_code", 1 if result["status"] == "failed" else 0)
        if result.get("interrupted"):
            code = 130
    except (
        deployment.DeploymentError,
        teardown.TeardownError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        code = 2 if isinstance(error, (deployment.DeploymentToolError, FileNotFoundError)) else 1
        result = {
            "kind": "command-error",
            "schema_version": deployment.SCHEMA,
            "command": args.command,
            "error": str(error),
            "exit_code": code,
        }
    except (KeyboardInterrupt, EOFError):
        code = 130
        result = {
            "kind": "command-error",
            "schema_version": deployment.SCHEMA,
            "command": args.command,
            "error": "Interrupted; inspect state and evidence before retrying.",
            "exit_code": code,
        }
    except Exception as error:
        code = 70
        result = {
            "kind": "command-error",
            "schema_version": deployment.SCHEMA,
            "command": args.command,
            "error": f"Unexpected internal error ({type(error).__name__}); preserve state and evidence.",
            "exit_code": code,
        }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
