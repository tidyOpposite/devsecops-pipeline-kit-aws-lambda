"""Run the locked Snyk CLI with an archive and no runner/cloud credentials."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .images import parse_ecr_image_uri

SCANNER_IMAGE = "devsecops-snyk:locked"
DOCKERFILE = Path("tools/snyk/Dockerfile")


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, timeout=900, **kwargs)


def container_command(*, archive: Path | None = None, token: bool = False, entrypoint: str = "/usr/local/bin/snyk") -> list[str]:
    command = ["docker", "run", "--rm", "--platform", "linux/amd64", "--read-only", "--cap-drop=ALL",
               "--security-opt=no-new-privileges", "--user=65534:65534", "--pids-limit=256", "--memory=4g", "--cpus=2",
               "--tmpfs", "/tmp:rw,nosuid,nodev,size=4g", "--env", "HOME=/tmp"]
    if archive is not None:
        command.extend(["--mount", f"type=bind,src={archive},dst=/scan/image.tar,readonly"])
    if token:
        command.extend(["--env", "SNYK_TOKEN"])
    command.extend(["--entrypoint", entrypoint, SCANNER_IMAGE])
    return command


def prepare(root: Path) -> None:
    source = (root / DOCKERFILE).read_text()
    version = re.search(r'^LABEL org\.devsecops\.snyk-version="([0-9]+\.[0-9]+\.[0-9]+)"$', source, re.MULTILINE)
    if not version or not re.search(r"^FROM snyk/snyk:linux@sha256:[a-f0-9]{64}$", source, re.MULTILINE):
        raise ValueError("Pin the Snyk image digest and expected CLI version in tools/snyk/Dockerfile.")
    run(["docker", "build", "--platform", "linux/amd64", "--tag", SCANNER_IMAGE,
         "--file", str(root / DOCKERFILE), str(root / DOCKERFILE.parent)])
    result = run([*container_command(), "--version"], capture_output=True, text=True)
    if result.stdout.strip() != version[1]:
        raise ValueError("The scanner binary does not match the reviewed CLI version.")
    print(f"Verified locked Snyk CLI {version[1]} before AWS access.")


def scan(image: str, region: str) -> None:
    reference = parse_ecr_image_uri(image)
    if not reference or not reference.digest or reference.region != region:
        raise ValueError("Scanning requires the reviewed ECR digest in the deployment region.")
    if not os.environ.get("SNYK_TOKEN", "").strip():
        raise ValueError("SNYK_TOKEN is required when image scanning is enabled.")
    registry = image.split("/", 1)[0]
    local_tag = f"devsecops-scan-target:{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="devsecops-image-scan-") as directory:
        folder = Path(directory)
        docker_environment = dict(os.environ, DOCKER_CONFIG=str(folder / "docker-config"))
        archive = folder / "image.tar"
        try:
            password = run(["aws", "ecr", "get-login-password", "--region", region], capture_output=True, text=True).stdout.strip()
            run(["docker", "login", "--username", "AWS", "--password-stdin", registry],
                input=password, text=True, capture_output=True, env=docker_environment)
            run(["docker", "pull", "--platform", "linux/amd64", image], env=docker_environment)
            run(["docker", "tag", image, local_tag])
            run(["docker", "image", "save", "--output", str(archive), local_tag])
            archive.chmod(0o644)
            # Docker only forwards the explicitly listed container variables.
            # No socket, workspace, Docker config, AWS files or OIDC env is mounted.
            run([*container_command(archive=archive, token=True), "container", "test",
                 "docker-archive:/scan/image.tar", "--severity-threshold=high"])
        finally:
            subprocess.run(["docker", "image", "rm", local_tag], capture_output=True, timeout=30, check=False)


def probe() -> None:
    """Exercise the real Docker boundary in credential-free CI with sentinel env."""
    with tempfile.TemporaryDirectory(prefix="devsecops-scanner-probe-") as directory:
        archive = Path(directory) / "image.tar"
        archive.write_text("scanner fixture")
        archive.chmod(0o644)
        environment = dict(os.environ, AWS_ACCESS_KEY_ID="must-not-reach-scanner", AWS_SECRET_ACCESS_KEY="must-not-reach-scanner",
                           AWS_SESSION_TOKEN="must-not-reach-scanner", ACTIONS_ID_TOKEN_REQUEST_TOKEN="must-not-reach-scanner",
                           GH_TOKEN="must-not-reach-scanner", SNYK_TOKEN="fixture-token")
        script = ('test "$SNYK_TOKEN" = fixture-token; '
                  'test -z "${AWS_ACCESS_KEY_ID:-}${AWS_SECRET_ACCESS_KEY:-}${AWS_SESSION_TOKEN:-}${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}${GH_TOKEN:-}"; '
                  'test ! -S /var/run/docker.sock; test ! -e /root/.aws; test ! -e /github/workspace; '
                  'test "$(cat /scan/image.tar)" = "scanner fixture"; '
                  'awk \'$2 == "/scan/image.tar" && $4 ~ /(^|,)ro(,|$)/ { found=1 } END { exit !found }\' /proc/mounts')
        run([*container_command(archive=archive, token=True, entrypoint="/bin/sh"), "-ec", script], env=environment)
    print("Verified scanner receives only the scan token and read-only archive, without runner AWS/OIDC credentials.")


def main() -> int:
    try:
        operation = sys.argv[1]
        if operation == "prepare":
            prepare(Path.cwd())
        elif operation == "scan":
            scan(os.environ["LAMBDA_IMAGE_URI"], os.environ["AWS_REGION"])
        elif operation == "probe":
            probe()
        else:
            raise ValueError("Use scanner prepare, scan, or probe.")
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"Image scan failed: {detail}. Deployment must stop.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
