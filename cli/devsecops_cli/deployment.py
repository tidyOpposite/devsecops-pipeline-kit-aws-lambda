"""Account-bound AWS deployment with reviewed saved plans and verified recovery."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

from . import VERSION
from .aws import (
    _NoRedirectResponseProcessor,
    aws_sigv4_headers,
    get_lambda_capacity,
    verify_ecr_lambda_image,
)
from .models import ConfigValidationError


class DeploymentError(ValueError):
    """Expected scope, review, provider or health failure."""


class DeploymentToolError(DeploymentError):
    """Required external executable is unavailable (CLI exit code 2)."""


NAME = re.compile(r"[a-z][a-z0-9-]{2,15}\Z")
PLAN_ID = re.compile(r"[a-f0-9]{32}\Z")
PREFIXES = (
    "module.kms.",
    "module.ecr.",
    "module.storage.",
    "module.lambda.",
    "module.api_gateway.",
)
PERMISSION = "aws_lambda_permission.api_gw_permission"
SCHEMA = 2


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value
    except (OSError, ValueError) as error:
        raise DeploymentError(f"Cannot read {path.name}: {error}") from error


def utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def source_digest(root: Path) -> str:
    """Bind source modules, provider selection and the actually running CLI."""
    paths = list((root / "terraform").glob("*.tf"))
    paths += list((root / "terraform").glob("*.tf.json"))
    paths += list((root / "terraform" / "modules").rglob("*.tf"))
    paths += list((root / "terraform" / "modules").rglob("*.tf.json"))
    paths += [root / "terraform" / ".terraform.lock.hcl"]
    paths += list(Path(__file__).parent.glob("*.py"))
    value = hashlib.sha256()
    labelled = [
        (
            str(path.relative_to(root))
            if path.is_relative_to(root)
            else "cli/devsecops_cli/" + path.name,
            path,
        )
        for path in paths
    ]
    # Sort canonical labels, not absolute paths: an installed package can sort
    # before or after the Terraform checkout on another host or in another venv.
    for label, path in sorted(labelled):
        value.update(label.encode() + b"\0" + path.read_bytes() + b"\0")
    return value.hexdigest()


def allowed_address(address: str) -> bool:
    return address == PERMISSION or address.startswith(PREFIXES)


def check_plan(
    plan: dict[str, Any], stage: str, project: str, purpose: str = "Deployment"
) -> list[dict[str, Any]]:
    if plan.get("errored") or plan.get("deferred_changes"):
        raise DeploymentError("An errored or deferred Terraform plan cannot be approved.")
    changes = []
    for item in plan.get("resource_changes", []):
        if item.get("mode") == "data":
            continue
        address = item.get("address", "")
        change = item.get("change", {})
        actions = change.get("actions", [])
        if not allowed_address(address) or change.get("importing"):
            raise DeploymentError(
                f"Plan contains a resource/import outside the deployment: {address}"
            )
        if (
            stage == "registry"
            and actions != ["no-op"]
            and not address.startswith(("module.kms.", "module.ecr."))
        ):
            raise DeploymentError(f"Registry plan includes workload changes: {address}")
        if "delete" in actions and stage != "destroy":
            raise DeploymentError(
                f"Deletion/replacement needs an explicit destroy review: {address}"
            )
        if stage == "destroy" and actions not in (["delete"], ["no-op"]):
            raise DeploymentError(f"Destroy plan also creates or updates resources: {address}")
        for values in (change.get("before"), change.get("after")):
            tags = (values or {}).get("tags") or {}
            if tags and any(
                tags.get(key) != value
                for key, value in {
                    "Project": project,
                    "Environment": "dev",
                    "Purpose": purpose,
                }.items()
            ):
                raise DeploymentError(f"Resource ownership tags differ: {address}")
        if actions != ["no-op"]:
            changes.append({"address": address, "actions": actions})
    return changes


class Deployment:
    def __init__(self, root: Path, name: str):
        if not NAME.fullmatch(name):
            raise DeploymentError(
                "Deployment name must be 3–16 lowercase letters, digits or hyphens, starting with a letter."
            )
        self.root = root.resolve()
        self.name = name
        self.home = self.root / ".devsecops" / "deployments" / name
        self.settings_path = self.home / "settings.json"
        self.state = self.home / "state.tfstate"
        self.source = self.root / "terraform"
        self.settings: dict[str, Any] = {}
        self.event_dir: Path | None = None
        self.sequence = 0
        self.progress: Callable[[str], None] | None = None

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.home, 0o700)
        fd = os.open(self.home / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise DeploymentError(
                    "Another deployment operation is running; wait for it to finish."
                ) from error
            yield

    def load(self) -> None:
        self.settings = read_json(self.settings_path)
        self.validate_settings()

    def validate_settings(self) -> None:
        s = self.settings
        if not isinstance(s, dict):
            raise DeploymentError("Deployment settings must be a JSON object.")
        if any(
            not isinstance(s.get(key), str)
            for key in (
                "name",
                "account_id",
                "region",
                "project_name",
                "profile",
                "aws_binary",
                "purpose",
            )
        ):
            raise DeploymentError("Deployment settings contain invalid field types.")
        if (
            type(s.get("schema_version")) is not int
            or s.get("schema_version") != SCHEMA
            or s.get("name") != self.name
            or not re.fullmatch(r"[0-9]{12}", s.get("account_id", ""))
            or not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]", s.get("region", ""))
            or not re.fullmatch(
                r"kit-(?:lab-)?" + re.escape(self.name) + r"-[a-f0-9]{6}", s.get("project_name", "")
            )
            or s.get("purpose") not in {"Deployment", "SingleOperatorLab"}
            or not re.fullmatch(r"[A-Za-z0-9_+=,.@-]{1,128}", s["profile"])
            or not s["aws_binary"]
            or type(s.get("reserved_concurrency")) is not int
            or not (s["reserved_concurrency"] == -1 or 1 <= s["reserved_concurrency"] <= 1000)
        ):
            raise DeploymentError(
                "Invalid deployment settings; restore the original settings instead of editing deployment scope."
            )

    def base_env(self) -> dict[str, str]:
        env = {
            key: value for key, value in os.environ.items() if not key.startswith(("TF_", "AWS_"))
        }
        for key in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
            if self.settings.get(key):
                env[key] = self.settings[key]
        env.update(
            AWS_PROFILE=self.settings["profile"],
            AWS_REGION=self.settings["region"],
            AWS_DEFAULT_REGION=self.settings["region"],
            AWS_EC2_METADATA_DISABLED="true",
            AWS_PAGER="",
            AWS_CLI_AUTO_PROMPT="off",
        )
        return env

    def begin_event(self, operation: str) -> None:
        self.event_dir = (
            self.home
            / "evidence"
            / (dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
        )
        self.event_dir.mkdir(parents=True, mode=0o700)
        self.sequence = 0
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=False
        )
        clean = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        write_json(
            self.event_dir / "operation.json",
            {
                "kind": "deployment",
                "schema_version": SCHEMA,
                "operation": operation,
                "started_at": utc(),
                "cli_version": VERSION,
                "source_commit": commit.stdout.strip() if commit.returncode == 0 else None,
                "source_clean": commit.returncode == 0
                and clean.returncode == 0
                and not clean.stdout,
                "settings": self.settings,
                "source_sha256": source_digest(self.root),
            },
        )

    def run(
        self,
        argv: list[str],
        env: dict[str, str],
        *,
        secret: bool = False,
        input_data: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        interrupted = False
        try:
            if self.progress and not secret:
                self.progress("[deployment] " + shlex.join(argv[:3]))
            if (
                self.progress
                and not secret
                and argv[0] == "terraform"
                and argv[2] in {"init", "plan", "apply"}
            ):
                # Human-readable callers see real provider progress; JSON remains
                # one clean final payload. The merged stream is saved verbatim.
                process = subprocess.Popen(
                    argv,
                    cwd=self.root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                lines: list[str] = []
                try:
                    for line in process.stdout:
                        lines.append(line)
                        self.progress(line.rstrip("\n"))
                    process.wait()
                except KeyboardInterrupt:
                    interrupted = True
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                    try:
                        tail, _ = process.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        tail, _ = process.communicate()
                    lines.append(tail or "")
                finally:
                    process.stdout.close()
                result = subprocess.CompletedProcess(
                    argv, 130 if interrupted else process.returncode, "".join(lines), ""
                )
            else:
                try:
                    result = subprocess.run(
                        argv,
                        cwd=self.root,
                        env=env,
                        stdin=subprocess.DEVNULL if input_data is None else None,
                        input=input_data,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                except KeyboardInterrupt:
                    interrupted = True
                    result = subprocess.CompletedProcess(
                        argv, 130, "", "Interrupted; output capture incomplete."
                    )
        except FileNotFoundError as error:
            raise DeploymentToolError(f"Required executable is unavailable: {argv[0]}") from error
        if not secret and self.event_dir:
            self.sequence += 1
            write_json(
                self.event_dir / f"command-{self.sequence:03}.json",
                {
                    "utc": utc(),
                    "argv": argv,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        if interrupted:
            raise KeyboardInterrupt()
        return result

    def aws(self, args: list[str], *, secret: bool = False, payload: dict | None = None) -> Any:
        result = self.run(
            [
                self.settings["aws_binary"],
                *args,
                "--profile",
                self.settings["profile"],
                "--region",
                self.settings["region"],
                "--output",
                "json",
                "--no-cli-pager",
            ],
            self.base_env(),
            secret=secret,
            **({"input_data": json.dumps(payload)} if payload is not None else {}),
        )
        if result.returncode:
            # Credential exports are never included in diagnostics or evidence.
            raise DeploymentError(
                f"Sensitive AWS operation {' '.join(args[:2])} failed; credentials/tokens omitted."
                if secret
                else f"AWS {' '.join(args[:2])} failed: {result.stderr.strip()}"
            )
        try:
            value = json.loads(result.stdout or "{}")
            if not isinstance(value, dict):
                raise ValueError("expected an AWS response object")
            return value
        except ValueError as error:
            raise DeploymentError("AWS CLI returned invalid JSON.") from error

    def identity(self) -> dict[str, Any]:
        result = self.aws(["sts", "get-caller-identity"])
        if result.get("Account") != self.settings["account_id"]:
            raise DeploymentError(
                "AWS account differs from the explicitly selected deployment account. No Terraform action allowed."
            )
        return result

    def initialize(self, account: str, region: str, profile: str) -> dict[str, Any]:
        if (self.root / ".devsecops" / "labs" / self.name / "settings.json").exists():
            raise DeploymentError(
                "Legacy state exists for this name. Review devsecops migrate NAME before initialization."
            )
        if self.settings_path.exists() or self.state.exists():
            raise DeploymentError(
                "Deployment already exists; use status, preserving its settings and state."
            )
        if not re.fullmatch(r"[0-9]{12}", account) or not re.fullmatch(
            r"[a-z]{2}-[a-z]+-[0-9]", region
        ):
            raise DeploymentError(
                "Supply a 12-digit account ID and an explicit commercial AWS region."
            )
        if not re.fullmatch(r"[A-Za-z0-9_+=,.@-]{1,128}", profile):
            raise DeploymentError(
                "Supply a named AWS CLI profile, without spaces or shell characters."
            )
        binary = shutil.which("aws")
        if not binary:
            candidate = Path.home() / ".local" / "bin" / "aws"
            binary = str(candidate) if candidate.is_file() else None
        if not binary:
            raise DeploymentToolError("Install AWS CLI v2 and sign in to a named profile first.")
        self.settings = {
            "schema_version": SCHEMA,
            "name": self.name,
            "account_id": account,
            "region": region,
            "profile": profile,
            "aws_binary": binary,
            "project_name": f"kit-{self.name}-{uuid.uuid4().hex[:6]}",
            "reserved_concurrency": 10,
            "purpose": "Deployment",
            "created_at": utc(),
            **{
                key: str(Path(os.environ[key]).expanduser().resolve())
                for key in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE")
                if os.environ.get(key)
            },
        }
        identity = self.identity()
        write_json(self.settings_path, self.settings)
        self.begin_event("init")
        return self.finish(
            "initialized",
            identity=identity,
            message="Local deployment scope saved. No AWS resources created.",
        )

    def tf_env(self) -> dict[str, str]:
        """Bridge AWS CLI login/SSO to the pinned provider via credential_process.

        Only this short helper and source profile paths are persisted, never its
        output. Export uses the original user config, preventing recursive use
        of the Terraform-only runtime profile.
        """
        bridge = self.home / "credentials.py"
        # Do not serialize inherited environment values (tokens may live there).
        original = {key: value for key, value in self.base_env().items() if key.startswith("AWS_")}
        code = "import os, subprocess, sys\nenv = dict(os.environ)\n"
        code += "for key in list(env):\n    if key.startswith('AWS_'): env.pop(key)\n"
        code += f"env.update({original!r})\n"
        code += f"sys.exit(subprocess.call({[self.settings['aws_binary'], 'configure', 'export-credentials', '--profile', self.settings['profile'], '--format', 'process']!r}, env=env))\n"
        bridge.write_text(code)
        os.chmod(bridge, 0o600)
        config = self.home / "aws-runtime-config"
        # AWS shared-config readers can remove matching outer quotes from a
        # value. Start with an unquoted, fixed launcher so a Python path with
        # spaces is not mistaken for a quote around the entire command. Keep
        # the exact interpreter and helper arguments shell-quoted and literal.
        config.write_text(
            "[profile kit-runtime]\nregion = "
            + self.settings["region"]
            + "\ncredential_process = "
            + shlex.join(["/usr/bin/env", sys.executable, "-I", str(bridge)])
            + "\n"
        )
        os.chmod(config, 0o600)
        empty = self.home / "aws-empty-credentials"
        empty.touch(mode=0o600)
        env = self.base_env()
        env.update(
            AWS_CONFIG_FILE=str(config),
            AWS_SHARED_CREDENTIALS_FILE=str(empty),
            AWS_PROFILE="kit-runtime",
            AWS_SDK_LOAD_CONFIG="1",
            TF_WORKSPACE="default",
            TF_DATA_DIR=str(self.home / "terraform-data"),
            TF_IN_AUTOMATION="true",
            TF_INPUT="0",
        )
        return env

    def tf(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = self.run(["terraform", f"-chdir={self.source}", *args], self.tf_env())
        if check and result.returncode:
            raise DeploymentError(
                f"Terraform {args[0]} failed (exit {result.returncode}). "
                f"See private evidence: {self.event_dir}\n{result.stderr.strip()}"
            )
        return result

    def init_tf(self) -> None:
        lock = self.root / "terraform" / ".terraform.lock.hcl"
        if not lock.is_file() or not (self.source / "main.tf").is_file():
            raise DeploymentError(
                "Run from a complete matching source checkout, including the provider lock file."
            )
        self.tf(
            [
                "init",
                "-reconfigure",
                "-input=false",
                "-lockfile=readonly",
                "-no-color",
                f"-backend-config=path={self.state}",
            ]
        )

    def outputs(self) -> dict[str, Any]:
        if not self.state.exists():
            return {}
        state = read_json(self.state)
        for item in state.get("resources", []):
            if item.get("mode") == "data":
                continue
            address = (
                (item.get("module", "") + "." if item.get("module") else "")
                + item.get("type", "")
                + "."
                + item.get("name", "")
            )
            if not allowed_address(address):
                raise DeploymentError(
                    "Local state contains resources outside the deployment modules."
                )
            for instance in item.get("instances", []):
                tags = instance.get("attributes", {}).get("tags") or {}
                if tags and (
                    tags.get("Project") != self.settings["project_name"]
                    or tags.get("Environment") != "dev"
                    or tags.get("Purpose") != self.settings["purpose"]
                ):
                    raise DeploymentError("Local state ownership differs from this deployment.")
        result = (
            state.get("outputs", {})
            .get("deployment_context", state.get("outputs", {}).get("lab_context", {}))
            .get("value", {})
        )
        if result and any(
            result.get(key) != value
            for key, value in {
                "account_id": self.settings["account_id"],
                "region": self.settings["region"],
                "project_name": self.settings["project_name"],
                "environment": "dev",
                "purpose": self.settings["purpose"],
            }.items()
        ):
            raise DeploymentError("State context does not match the selected deployment.")
        return result

    @property
    def repository(self) -> str:
        return (
            f"{self.settings['account_id']}.dkr.ecr.{self.settings['region']}.amazonaws.com/"
            f"{self.settings['project_name']}-dev-lambda-repo"
        )

    def check_image(self, image: str) -> None:
        if not re.fullmatch(re.escape(self.repository) + r"@sha256:[a-f0-9]{64}", image):
            raise DeploymentError(
                "Use a SHA-256 digest in this deployment's own ECR repository, account and region."
            )

        def adapter(_root: Path, args: list[str]) -> tuple[Any, subprocess.CompletedProcess[str]]:
            value = self.aws(
                args,
                secret=args[:2]
                in (["ecr", "get-authorization-token"], ["ecr", "get-download-url-for-layer"]),
            )
            return value, subprocess.CompletedProcess(args, 0, json.dumps(value), "")

        try:
            verify_ecr_lambda_image(self.root, image, self.settings["region"], aws_json_fn=adapter)
        except ConfigValidationError as error:
            raise DeploymentError(str(error)) from error

    def live_function(self, context: dict[str, Any]) -> dict[str, str] | None:
        arn = context.get("lambda_function_arn")
        if not arn:
            return None
        expected = f"arn:aws:lambda:{self.settings['region']}:{self.settings['account_id']}:function:{self.settings['project_name']}-dev-lambda"
        if arn != expected:
            raise DeploymentError("Function ARN is outside this deployment.")
        try:
            value = self.aws(["lambda", "get-function", "--function-name", arn])
        except DeploymentError as error:
            if "ResourceNotFoundException" in str(error):
                return None
            raise
        image = value.get("Code", {}).get("ResolvedImageUri", "")
        if value.get("Configuration", {}).get("FunctionArn") != arn or not image.startswith(
            self.repository + "@sha256:"
        ):
            raise DeploymentError("Live Lambda identity/image does not match this deployment.")
        return {"arn": arn, "image_uri": image}

    def capacity(self) -> dict[str, Any]:
        def adapter(_root: Path, args: list[str]) -> tuple[Any, subprocess.CompletedProcess[str]]:
            try:
                value = self.aws(args)
                return value, subprocess.CompletedProcess(args, 0, json.dumps(value), "")
            except DeploymentError as error:
                if args[:2] == [
                    "lambda",
                    "get-function-concurrency",
                ] and "ResourceNotFoundException" in str(error):
                    return {}, subprocess.CompletedProcess(args, 255, "", str(error))
                raise

        try:
            report = get_lambda_capacity(
                self.root,
                self.settings["project_name"] + "-dev-lambda",
                self.settings["region"],
                self.settings["reserved_concurrency"],
                allow_unreserved=True,
                aws_json_fn=adapter,
            )
        except ConfigValidationError as error:
            raise DeploymentError(str(error)) from error
        if self.event_dir:
            write_json(self.event_dir / ("capacity-" + uuid.uuid4().hex[:8] + ".json"), report)
        return report

    def concurrency(self, mode: str | None, reserved: int | None) -> dict[str, Any]:
        """Change only local deployment policy; existing plan hashes become invalid."""
        if mode is None:
            if reserved is not None:
                raise DeploymentError("--reserved-executions requires --mode reserved.")
            return self.finish(
                "configured",
                reserved_concurrency=self.settings["reserved_concurrency"],
                message="Reserved values allocate dedicated capacity; -1 uses the shared account pool (dev only).",
            )
        if mode == "unreserved" and reserved is None:
            requested = -1
        elif mode == "reserved" and type(reserved) is int and 1 <= reserved <= 1000:
            requested = reserved
        else:
            raise DeploymentError(
                "Choose --mode unreserved without a value, or --mode reserved --reserved-executions 1..1000."
            )
        previous = self.settings["reserved_concurrency"]
        self.settings["reserved_concurrency"] = requested
        write_json(self.settings_path, self.settings)
        return self.finish(
            "configured",
            previous_reserved_concurrency=previous,
            reserved_concurrency=requested,
            mode=mode,
            message="Local policy saved; no AWS changes. Create a new reviewed plan before apply. "
            + (
                "Uses the shared account pool, with no dedicated function cap or guarantee."
                if requested == -1
                else "Account capacity will be checked before plan/apply."
            ),
        )

    def verify_capacity(self, context: dict[str, Any]) -> dict[str, Any]:
        report = self.capacity()
        requested = self.settings["reserved_concurrency"]
        if context.get("reserved_concurrency") != requested or report["current_reserved"] != max(
            0, requested
        ):
            raise DeploymentError(
                "Configured, Terraform-state and live function concurrency differ; inspect drift before proceeding."
            )
        return report

    def plan(self, stage: str, image: str | None = None) -> dict[str, Any]:
        self.identity()
        context = self.outputs()
        previous = self.live_function(context)
        if stage in {"workload", "rollback"}:
            self.capacity()
            if not image:
                raise DeploymentError("Supply --image-uri with the immutable image to deploy.")
            self.check_image(image)
            if previous:
                self.check_image(previous["image_uri"])
                self.health()  # Only a verified healthy image is an automatic recovery target.
        elif stage == "destroy":
            if not self.state.exists():
                raise DeploymentError("No deployment state to destroy.")
            image = context.get("image_uri", "")
        elif stage != "registry":
            raise DeploymentError("Unknown deployment stage.")
        if stage == "registry" and previous:
            raise DeploymentError("Registry preparation is only for the initial deployment.")
        if stage == "rollback" and not previous:
            raise DeploymentError("Manual rollback requires an existing deployment function.")
        self.init_tf()
        plan_id = uuid.uuid4().hex
        directory = self.home / "plans" / plan_id
        directory.mkdir(parents=True, mode=0o700)
        variables = {
            "expected_account_id": self.settings["account_id"],
            "aws_region": self.settings["region"],
            "project_name": self.settings["project_name"],
            "lambda_image_uri": image or "",
            "reserved_concurrency": self.settings["reserved_concurrency"],
            "purpose": self.settings["purpose"],
        }
        write_json(directory / "inputs.tfvars.json", variables)
        before_state = digest(self.state)
        args = [
            "plan",
            "-input=false",
            "-no-color",
            "-lock-timeout=30s",
            f"-var-file={directory / 'inputs.tfvars.json'}",
            f"-out={directory / 'plan.tfplan'}",
        ]
        if stage == "registry":
            args += ["-target=module.ecr", "-target=module.kms"]
        if stage == "destroy":
            args += ["-destroy"]
        self.tf(args)
        readable = self.tf(["show", "-no-color", str(directory / "plan.tfplan")]).stdout
        (directory / "plan.txt").write_text(readable)
        os.chmod(directory / "plan.txt", 0o600)
        plan = json.loads(self.tf(["show", "-json", str(directory / "plan.tfplan")]).stdout)
        changes = check_plan(plan, stage, self.settings["project_name"], self.settings["purpose"])
        write_json(directory / "plan.json", plan)
        review = {
            "kind": "deployment-plan",
            "schema_version": SCHEMA,
            "plan_id": plan_id,
            "stage": stage,
            "settings_sha256": digest(self.settings_path),
            "state_sha256": before_state,
            "source_sha256": source_digest(self.root),
            "created_at": utc(),
            "expires_at": time.time() + 3600,
            "account_id": self.settings["account_id"],
            "region": self.settings["region"],
            "image_uri": image,
            "previous": previous,
            "changes": changes,
            "files": {
                name: digest(directory / name)
                for name in ("plan.tfplan", "plan.json", "plan.txt", "inputs.tfvars.json")
            },
        }
        write_json(directory / "review.json", review)
        return self.finish(
            "planned",
            plan_id=plan_id,
            sha256=digest(directory / "review.json"),
            review=str(directory / "plan.txt"),
            changes=changes,
            message="Read the full saved plan before approving its review SHA-256.",
        )

    def reviewed(self, plan_id: str, sha256: str) -> tuple[Path, dict[str, Any]]:
        if not PLAN_ID.fullmatch(plan_id) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise DeploymentError(
                "Supply the complete plan ID and review SHA-256 shown by deployment plan."
            )
        directory = self.home / "plans" / plan_id
        path = directory / "review.json"
        if digest(path) != sha256:
            raise DeploymentError("Review SHA-256 differs from the saved plan review.")
        review = read_json(path)
        if (
            review.get("kind") != "deployment-plan"
            or type(review.get("schema_version")) is not int
            or review.get("schema_version") != SCHEMA
            or review.get("plan_id") != plan_id
            or review.get("stage") not in {"registry", "workload", "rollback", "destroy"}
            or review.get("expires_at", 0) < time.time()
            or review.get("account_id") != self.settings["account_id"]
            or review.get("region") != self.settings["region"]
            or review.get("settings_sha256") != digest(self.settings_path)
            or review.get("state_sha256") != digest(self.state)
            or review.get("source_sha256") != source_digest(self.root)
            or set(review.get("files", {}))
            != {"plan.tfplan", "plan.json", "plan.txt", "inputs.tfvars.json"}
            or any(digest(directory / name) != value for name, value in review["files"].items())
            or (directory / "applied.json").exists()
        ):
            raise DeploymentError(
                "Plan is stale, changed or already attempted. Create and review a new plan."
            )
        check_plan(
            read_json(directory / "plan.json"),
            review["stage"],
            self.settings["project_name"],
            self.settings["purpose"],
        )
        return directory, review

    def request(self, method: str, path: str, body: str | None = None) -> dict[str, Any]:
        if (
            method not in {"GET", "POST"}
            or not re.fullmatch(r"/[A-Za-z0-9/_.~-]*", path)
            or ".." in path.split("/")
        ):
            raise DeploymentError(
                "Use GET or POST with an absolute API path without a query, fragment or traversal."
            )
        if (method == "GET" and body is not None) or len((body or "").encode()) > 65536:
            raise DeploymentError("GET takes no body; POST JSON must be at most 64 KiB.")
        if method == "POST":
            try:
                if not isinstance(json.loads(body or ""), dict):
                    raise ValueError("object required")
            except ValueError as error:
                raise DeploymentError("POST requires --body containing a JSON object.") from error
        context = self.outputs()
        endpoint = context.get("api_endpoint", "")
        if not re.fullmatch(
            r"https://[a-z0-9]+\.execute-api\."
            + re.escape(self.settings["region"])
            + r"\.amazonaws\.com",
            endpoint,
        ):
            raise DeploymentError("No valid regional deployment API endpoint in state.")
        api_id = endpoint.split("//")[1].split(".")[0]
        api = self.aws(["apigatewayv2", "get-api", "--api-id", api_id])
        if (
            api.get("Name") != self.settings["project_name"] + "-dev-http-api"
            or api.get("Tags", {}).get("Project") != self.settings["project_name"]
        ):
            raise DeploymentError(
                "API identity differs from this deployment; refusing to send signed credentials."
            )
        routes = self.aws(["apigatewayv2", "get-routes", "--api-id", api_id]).get("Items", [])
        # The shared module owns exactly one IAM-protected $default route.
        # Extra routes could override it, so they also require investigation.
        if (
            len(routes) != 1
            or routes[0].get("RouteKey") != "$default"
            or routes[0].get("AuthorizationType") != "AWS_IAM"
            or not re.fullmatch(r"integrations/[a-zA-Z0-9]+", routes[0].get("Target", ""))
        ):
            raise DeploymentError("Live API routes differ from the IAM-protected deployment route.")
        integration = self.aws(
            [
                "apigatewayv2",
                "get-integration",
                "--api-id",
                api_id,
                "--integration-id",
                routes[0]["Target"].split("/")[1],
            ]
        )
        function_arn = f"arn:aws:lambda:{self.settings['region']}:{self.settings['account_id']}:function:{self.settings['project_name']}-dev-lambda"
        invoke_arn = f"arn:aws:apigateway:{self.settings['region']}:lambda:path/2015-03-31/functions/{function_arn}/invocations"
        if (
            integration.get("IntegrationType") != "AWS_PROXY"
            or integration.get("PayloadFormatVersion") != "2.0"
            or integration.get("IntegrationUri") not in {function_arn, invoke_arn}
        ):
            raise DeploymentError("Live API integration does not invoke this deployment's Lambda.")
        credentials = self.aws(
            ["configure", "export-credentials", "--format", "process"], secret=True
        )
        payload = (body or "").encode()
        url = endpoint + path
        headers, error = aws_sigv4_headers(
            url, self.settings["region"], method=method, payload=payload, credentials=credentials
        )
        if error:
            raise DeploymentError(error)
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url, data=payload if method == "POST" else None, headers=headers, method=method
        )
        opener = urllib.request.build_opener(_NoRedirectResponseProcessor)
        try:
            try:
                response = opener.open(request, timeout=30)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                data = response.read(1048577)
                if len(data) > 1048576:
                    raise DeploymentError("API response exceeded 1 MiB.")
                result = {
                    "method": method,
                    "url": url,
                    "status": response.code,
                    "body": data.decode("utf-8", errors="replace"),
                    "request_body_sha256": hashlib.sha256(payload).hexdigest(),
                    "utc": utc(),
                }
        except (OSError, urllib.error.URLError) as error:
            raise DeploymentError(f"Deployment API request failed: {error}") from error
        if self.event_dir:
            write_json(self.event_dir / ("http-" + uuid.uuid4().hex[:8] + ".json"), result)
        return result

    def health(self) -> dict[str, Any]:
        # A new function/API integration can need a short propagation window.
        result: dict[str, Any] = {}
        for attempt in range(6):
            result = self.request("GET", "/health")
            if 200 <= result["status"] < 300:
                return result
            if attempt < 5:
                time.sleep(2)
        raise DeploymentError(
            f"Signed /health failed: HTTP {result.get('status')}. See captured responses."
        )

    def recover(self, previous: dict[str, str]) -> dict[str, Any]:
        context = self.outputs()
        current = self.live_function(context)
        if not current or current["arn"] != previous["arn"]:
            raise DeploymentError(
                "Cannot recover: Lambda ARN differs from the previously recorded function."
            )
        self.check_image(previous["image_uri"])
        configuration = self.aws(
            ["lambda", "get-function-configuration", "--function-name", previous["arn"]]
        )
        if configuration.get("LastUpdateStatus") == "InProgress":
            self.aws(["lambda", "wait", "function-updated-v2", "--function-name", previous["arn"]])
        self.aws(
            [
                "lambda",
                "update-function-code",
                "--function-name",
                previous["arn"],
                "--image-uri",
                previous["image_uri"],
            ]
        )
        self.aws(["lambda", "wait", "function-updated-v2", "--function-name", previous["arn"]])
        if self.live_function(context) != previous:
            raise DeploymentError("Recovery image readback does not match the previous digest.")
        refresh = self.event_dir / "recovery.tfplan"
        self.tf(
            [
                "plan",
                "-refresh-only",
                "-input=false",
                "-no-color",
                f"-out={refresh}",
                f"-var-file={self.event_dir / 'recovery.tfvars.json'}",
            ]
        )
        self.tf(["apply", "-input=false", "-no-color", str(refresh)])
        # Terraform refresh must agree with the restored live Lambda.
        if self.outputs().get("image_uri") != previous["image_uri"]:
            raise DeploymentError("Recovery state did not record the restored image digest.")
        return {
            "function": previous,
            "health": self.health(),
            "capacity": self.verify_capacity(self.outputs()),
            "state_sha256": digest(self.state),
        }

    def apply(self, plan_id: str, sha256: str, yes: bool) -> dict[str, Any]:
        directory, review = self.reviewed(plan_id, sha256)
        if not yes:
            return self.finish(
                "review-required",
                review=review,
                full_plan=str(directory / "plan.txt"),
                message=f"After reading plan.txt: devsecops apply {self.name} --plan-id {plan_id} --sha256 {sha256} --yes",
            )
        self.identity()
        context = self.outputs()
        if self.live_function(context) != review["previous"]:
            raise DeploymentError("Live Lambda changed after planning; review a new plan.")
        if review["stage"] in {"workload", "rollback"}:
            self.capacity()
            self.check_image(review["image_uri"])
            if review["previous"]:
                self.check_image(review["previous"]["image_uri"])
        self.init_tf()
        # Recheck after provider initialization as well; no regeneration at apply.
        self.reviewed(plan_id, sha256)
        write_json(
            directory / "applied.json", {"attempted_at": utc(), "evidence": str(self.event_dir)}
        )
        try:
            result = self.tf(
                ["apply", "-input=false", "-no-color", str(directory / "plan.tfplan")], check=False
            )
            if result.returncode:
                raise DeploymentError(f"Terraform apply failed (exit {result.returncode}).")
            context = self.outputs()
            if review["stage"] == "destroy":
                if read_json(self.state).get("resources"):
                    raise DeploymentError(
                        "Destroy returned success but state still contains resources."
                    )
                return self.finish(
                    "destroyed",
                    message="Deployment resources removed from state. Check KMS deletion schedule and delayed billing; local evidence retained.",
                )
            if review["stage"] == "registry":
                return self.finish(
                    "registry-ready",
                    repository_url=self.repository,
                    message="Publish your Lambda image here, then plan the workload with an immutable digest.",
                )
            live = self.live_function(context)
            if (
                not live
                or live["image_uri"] != review["image_uri"]
                or context.get("image_uri") != review["image_uri"]
            ):
                raise DeploymentError(
                    "Live Lambda, planned digest and Terraform state do not agree."
                )
            health = self.health()
            capacity = self.verify_capacity(context)
            return self.finish(
                "healthy",
                function=live,
                health=health,
                capacity=capacity,
                state_sha256=digest(self.state),
                message="Saved plan applied; live digest, Terraform state and signed health agree.",
            )
        except (DeploymentError, KeyboardInterrupt) as error:
            recovery: dict[str, Any] = {
                "status": "manual-attention",
                "message": "Keep state and evidence; inspect the partial apply before replanning.",
            }
            # Destroy/registry never trigger code recovery. First deployment has
            # no previous healthy function, so resources are deliberately kept.
            if review["previous"] and review["stage"] in {"workload", "rollback"}:
                try:
                    variables = read_json(directory / "inputs.tfvars.json")
                    variables["lambda_image_uri"] = review["previous"]["image_uri"]
                    write_json(self.event_dir / "recovery.tfvars.json", variables)
                    recovery = {"status": "recovered", **self.recover(review["previous"])}
                except (DeploymentError, OSError, KeyboardInterrupt) as recovery_error:
                    recovery = {"status": "recovery-failed", "message": str(recovery_error)}
            return self.finish(
                "failed",
                error=str(error) or "Interrupted during apply.",
                recovery=recovery,
                interrupted=isinstance(error, KeyboardInterrupt),
                message="Deployment failed; recovery status is recorded separately. Inspect evidence before retrying.",
            )

    def status(self) -> dict[str, Any]:
        identity = self.identity()
        context = self.outputs()
        live = self.live_function(context)
        if live:
            if live["image_uri"] != context.get("image_uri"):
                raise DeploymentError(
                    "Live Lambda digest differs from Terraform state; inspect drift before proceeding."
                )
            return self.finish(
                "healthy",
                identity=identity,
                outputs=context,
                function=live,
                health=self.health(),
                capacity=self.verify_capacity(context),
            )
        return self.finish(
            "not-deployed",
            identity=identity,
            repository_url=self.repository,
            outputs=context,
            capacity=self.capacity(),
            message="No deployment workload recorded. Prepare registry, publish images, then review a workload plan.",
        )

    def logs(self) -> dict[str, Any]:
        self.identity()
        context = self.outputs()
        live = self.live_function(context)
        if not live:
            raise DeploymentError(
                "No deployment function recorded; deploy the workload before reading logs."
            )
        end_ms = int(time.time() * 1000)
        value = self.aws(
            [
                "logs",
                "filter-log-events",
                "--log-group-name",
                "/aws/lambda/" + self.settings["project_name"] + "-dev-lambda",
                "--start-time",
                str(end_ms - 900_000),
                "--end-time",
                str(end_ms),
                "--query",
                "{events:events[-50:]}",
            ]
        )
        return self.finish(
            "ok",
            function=live,
            log_events=value.get("events", []),
            message="Latest 50 Lambda log events from the last 15 minutes, after reading all pages; private evidence may include application data.",
        )

    def finish(self, status: str, **values: Any) -> dict[str, Any]:
        payload = {
            "kind": "deployment",
            "schema_version": SCHEMA,
            "status": status,
            "name": self.name,
            "account_id": self.settings.get("account_id"),
            "region": self.settings.get("region"),
            "evidence": str(self.event_dir) if self.event_dir else None,
            **values,
        }
        if self.event_dir:
            write_json(self.event_dir / "result.json", payload)
            files = {
                str(path.relative_to(self.event_dir)): digest(path)
                for path in self.event_dir.rglob("*")
                if path.is_file() and path.name != "SHA256SUMS.json"
            }
            write_json(self.event_dir / "SHA256SUMS.json", files)
        return payload


def execute(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    deployment = Deployment(root, args.name)
    if (
        args.command == "init"
        and (root / ".devsecops" / "labs" / args.name / "settings.json").exists()
    ):
        raise DeploymentError(
            "Legacy state exists for this name. Review devsecops migrate NAME before initialization."
        )
    if args.format == "human":
        deployment.progress = lambda line: print(line, flush=True)
    with deployment.locked():
        if args.command == "init":
            return deployment.initialize(args.expected_account_id, args.region, args.profile)
        deployment.load()
        deployment.begin_event(args.command)
        try:
            if args.command == "plan":
                return deployment.plan(args.stage, args.image_uri)
            if args.command == "concurrency":
                return deployment.concurrency(args.mode, args.reserved_executions)
            if args.command == "apply":
                return deployment.apply(args.plan_id, args.sha256, args.yes)
            if args.command == "request":
                deployment.identity()
                result = deployment.request(args.method, args.path, args.body)
                return deployment.finish(
                    "ok" if 200 <= result["status"] < 300 else "failed", response=result
                )
            if args.command == "logs":
                return deployment.logs()
            if args.command == "config":
                deployment.outputs()
                return deployment.finish("configured", settings=deployment.settings)
            return deployment.status()
        except (DeploymentError, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
            payload = deployment.finish(
                "failed",
                error=str(error) or "Interrupted; inspect evidence before retrying.",
                exit_code=2 if isinstance(error, DeploymentToolError) else 1,
            )
            if isinstance(error, KeyboardInterrupt):
                raise
            return payload
