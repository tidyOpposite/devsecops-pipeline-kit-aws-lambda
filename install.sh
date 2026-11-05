#!/bin/sh
set -eu

# Release installer settings can be overridden for mirrors, pinned versions,
# custom Python interpreters, or non-default user-local installation paths.
REPO="${DEVSECOPS_INSTALL_REPO:-tidyOpposite/devsecops-pipeline-kit-aws-lambda}"
COMMAND_NAME="devsecops"
VERSION="${DEVSECOPS_VERSION:-latest}"
PYTHON_OVERRIDE="${PYTHON:-}"
INSTALL_DIR="${DEVSECOPS_INSTALL_DIR:-$HOME/.local/share/devsecops-pipeline-cli}"
BIN_DIR="${DEVSECOPS_BIN_DIR:-$HOME/.local/bin}"
VERIFY_CHECKSUMS=1
WITH_TUI="${DEVSECOPS_WITH_TUI:-0}"
RUN_AFTER=0
HTTP_TIMEOUT="${DEVSECOPS_HTTP_TIMEOUT:-30}"

usage() {
  cat <<'EOF'
Install DevSecOps Pipeline Kit CLI from GitHub Releases.

Usage:
  sh install.sh [options]

Options:
  --version VERSION    Install a release tag or version, for example v0.11.0.
  --python PATH       Use this Python interpreter instead of auto-detecting one.
  --bin-dir DIR       Write the devsecops launcher to DIR.
  --install-dir DIR   Store verified private environments under DIR.
  --with-tui          Install optional Rich/Textual dependencies.
  --no-verify         Skip SHA256SUMS verification.
  --run               Run the CLI after installation when stdin is interactive.
  -h, --help          Show this help text.

Environment:
  DEVSECOPS_VERSION       Same as --version.
  PYTHON                  Same as --python.
  DEVSECOPS_BIN_DIR       Same as --bin-dir.
  DEVSECOPS_INSTALL_DIR   Same as --install-dir.
  DEVSECOPS_WITH_TUI=1    Same as --with-tui.
  DEVSECOPS_HTTP_TIMEOUT  GitHub download timeout in seconds. Default: 30.
  GITHUB_TOKEN            Optional token for higher GitHub API rate limits.
EOF
}

log() {
  printf '%s\n' "devsecops-install: $*"
}

warn() {
  printf '%s\n' "devsecops-install: warning: $*" >&2
}

fail() {
  printf '%s\n' "devsecops-install: error: $*" >&2
  exit 1
}

# Parse options before performing network or filesystem changes.
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      [ "$#" -ge 2 ] || fail "--version requires a value"
      VERSION="$2"
      shift 2
      ;;
    --python)
      [ "$#" -ge 2 ] || fail "--python requires a value"
      PYTHON_OVERRIDE="$2"
      shift 2
      ;;
    --bin-dir)
      [ "$#" -ge 2 ] || fail "--bin-dir requires a value"
      BIN_DIR="$2"
      shift 2
      ;;
    --install-dir)
      [ "$#" -ge 2 ] || fail "--install-dir requires a value"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --with-tui)
      WITH_TUI=1
      shift
      ;;
    --no-verify)
      VERIFY_CHECKSUMS=0
      shift
      ;;
    --run)
      RUN_AFTER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

command_path() {
  # Accept either a command name on PATH or an explicit executable path.
  if command -v "$1" >/dev/null 2>&1; then
    command -v "$1"
    return 0
  fi
  if [ -x "$1" ]; then
    printf '%s\n' "$1"
    return 0
  fi
  return 1
}

valid_python() {
  # Package metadata supports Python 3.11 through 3.14; validate the actual
  # interpreter instead of inferring compatibility from its executable name.
  "$1" - <<'PY' >/dev/null 2>&1
import sys
major_minor = sys.version_info[:2]
raise SystemExit(0 if (3, 11) <= major_minor < (3, 15) else 1)
PY
}

select_python() {
  if [ -n "$PYTHON_OVERRIDE" ]; then
    candidate_path="$(command_path "$PYTHON_OVERRIDE" || true)"
    [ -n "$candidate_path" ] || fail "Python interpreter not found: $PYTHON_OVERRIDE"
    valid_python "$candidate_path" || fail "Python must be 3.11, 3.12, 3.13, or 3.14: $candidate_path"
    printf '%s\n' "$candidate_path"
    return 0
  fi

  # Prefer the newest explicitly supported interpreter, then accept a generic
  # python3 only when its runtime version passes the same check.
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    candidate_path="$(command_path "$candidate" || true)"
    if [ -n "$candidate_path" ] && valid_python "$candidate_path"; then
      printf '%s\n' "$candidate_path"
      return 0
    fi
  done

  fail "Python 3.11, 3.12, 3.13, or 3.14 is required. Install one, then rerun this installer."
}

# Unsupported platforms receive a warning rather than an early failure because
# POSIX-compatible environments may still complete the installation safely.
platform="$(uname -s 2>/dev/null || printf unknown)"
case "$platform" in
  Darwin|Linux) ;;
  *) warn "untested platform: $platform. Supported targets are macOS, Linux, and WSL2." ;;
esac

PYTHON_BIN="$(select_python)"
PYTHON_VERSION="$("$PYTHON_BIN" - <<'PY'
import sys
print(".".join(map(str, sys.version_info[:3])))
PY
)"
log "Using Python $PYTHON_VERSION at $PYTHON_BIN"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/devsecops-install.XXXXXX")"
cleanup() {
  # TMP_DIR is a concrete mktemp result, never a broad or caller-supplied path.
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

# Use the validated interpreter for HTTPS release resolution and downloads so
# the shell script does not depend on curl, jq, or platform checksum utilities.
release_info="$("$PYTHON_BIN" - "$REPO" "$VERSION" "$TMP_DIR" "$VERIFY_CHECKSUMS" "$HTTP_TIMEOUT" <<'PY'
import json
import os
import pathlib
import signal
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager

repo, version, destination, verify, timeout_text = sys.argv[1:6]
destination_path = pathlib.Path(destination)
token = os.environ.get("GITHUB_TOKEN")
try:
    timeout = float(timeout_text)
except ValueError as exc:
    raise SystemExit(f"Invalid DEVSECOPS_HTTP_TIMEOUT value: {timeout_text!r}.") from exc
if timeout <= 0:
    raise SystemExit("DEVSECOPS_HTTP_TIMEOUT must be greater than zero.")

headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "devsecops-pipeline-installer",
}
if token:
    headers["Authorization"] = f"Bearer {token}"

if version in {"", "latest"}:
    release_url = f"https://api.github.com/repos/{repo}/releases/latest"
else:
    tag = version if version.startswith("v") else f"v{version}"
    release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"


def request(url: str) -> urllib.request.Request:
    """Build a GitHub request with optional authenticated rate limits."""

    return urllib.request.Request(url, headers=headers)


class DeadlineExpired(Exception):
    pass


@contextmanager
def deadline(label: str):
    """Apply an overall operation deadline where SIGALRM is available."""

    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def handle_timeout(signum: int, frame: object) -> None:
        raise DeadlineExpired(label)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout)
    signal.signal(signal.SIGALRM, handle_timeout)
    try:
        yield
    except DeadlineExpired as exc:
        raise SystemExit(f"Timed out {exc} after {timeout:g}s.") from exc
    finally:
        signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
        signal.signal(signal.SIGALRM, previous_handler)


try:
    with deadline(f"resolving release {version!r} from {repo}"):
        with urllib.request.urlopen(request(release_url), timeout=timeout) as response:
            release = json.load(response)
except urllib.error.HTTPError as exc:
    raise SystemExit(f"Could not resolve release {version!r} from {repo}: HTTP {exc.code}") from exc
except urllib.error.URLError as exc:
    raise SystemExit(f"Could not resolve release {version!r} from {repo}: {exc.reason}") from exc
except TimeoutError as exc:
    raise SystemExit(f"Timed out resolving release {version!r} from {repo}.") from exc

assets = release.get("assets") or []
wheel_asset = next((asset for asset in assets if asset.get("name", "").endswith("-py3-none-any.whl")), None)
sums_asset = next((asset for asset in assets if asset.get("name") == "SHA256SUMS"), None)

if wheel_asset is None:
    raise SystemExit(f"No universal wheel asset found on release {release.get('tag_name', version)}.")
if verify == "1" and sums_asset is None:
    raise SystemExit(f"No SHA256SUMS asset found on release {release.get('tag_name', version)}.")


def download(asset: dict[str, object]) -> pathlib.Path:
    """Download one release asset into the installer-owned temporary directory."""

    name = str(asset["name"])
    url = str(asset["browser_download_url"])
    output_path = destination_path / name
    try:
        with deadline(f"downloading {name}"):
            with urllib.request.urlopen(request(url), timeout=timeout) as response:
                output_path.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Could not download {name}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not download {name}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise SystemExit(f"Timed out downloading {name}.") from exc
    return output_path


wheel_path = download(wheel_asset)
sums_path = download(sums_asset) if sums_asset is not None else pathlib.Path("")

print(release.get("tag_name", version))
print(wheel_path)
print(sums_path)
PY
)"

# The embedded resolver emits this fixed three-line protocol for simple,
# dependency-free transfer back into the shell.
RELEASE_TAG="$(printf '%s\n' "$release_info" | sed -n '1p')"
WHEEL_PATH="$(printf '%s\n' "$release_info" | sed -n '2p')"
SUMS_PATH="$(printf '%s\n' "$release_info" | sed -n '3p')"
WHEEL_NAME="$(basename "$WHEEL_PATH")"

log "Downloaded $WHEEL_NAME from $RELEASE_TAG"

if [ "$VERIFY_CHECKSUMS" = "1" ]; then
  # Match by exact wheel filename and compare digest before installation.
  "$PYTHON_BIN" - "$WHEEL_PATH" "$SUMS_PATH" <<'PY'
import hashlib
import pathlib
import sys

wheel_path = pathlib.Path(sys.argv[1])
sums_path = pathlib.Path(sys.argv[2])
expected = None

for line in sums_path.read_text(encoding="utf-8").splitlines():
    parts = line.strip().split()
    if len(parts) >= 2 and parts[-1].lstrip("*") == wheel_path.name:
        expected = parts[0].lower()
        break

if expected is None:
    raise SystemExit(f"No checksum entry found for {wheel_path.name}.")

actual = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit(f"Checksum mismatch for {wheel_path.name}: expected {expected}, got {actual}.")
PY
  log "Verified SHA256 checksum"
fi

# Build the replacement at its permanent path: virtual environments contain
# absolute paths and must not be renamed after pip has created entry points.
installed_version="$("$PYTHON_BIN" - "$INSTALL_DIR" "$BIN_DIR/$COMMAND_NAME" "$WHEEL_PATH" "$RELEASE_TAG" "$WITH_TUI" <<'PYINSTALL'
import fcntl
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile

install_dir = pathlib.Path(sys.argv[1]).expanduser().resolve()
launcher_path = pathlib.Path(sys.argv[2]).expanduser().absolute()
wheel_path = sys.argv[3]
release_tag = sys.argv[4]
with_tui = sys.argv[5] == "1"
marker = install_dir / ".devsecops-installer-managed"
staged_env = None
staged_launcher = None
created_marker = False
activated = False
locks = []
phase = "preparing installation paths"


def interrupted(signum, frame):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, interrupted)


def owned_launcher() -> bool:
    """Recognize both the legacy launcher and the versioned launcher format."""
    if launcher_path.is_symlink() or not launcher_path.is_file() or not marker.is_file():
        return False
    lines = launcher_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "#!/bin/sh":
        return False
    commands = [line for line in lines[1:] if line and not line.startswith("#")]
    if len(commands) != 1:
        return False
    parts = shlex.split(commands[0])
    if not parts or parts[0] != "exec" or parts[2:] not in (
        ["-m", "devsecops_cli.main", "$@"], ["-I", "-m", "devsecops_cli.main", "$@"]
    ):
        return False
    # Normalize directory aliases such as macOS /var -> /private/var, while
    # leaving the interpreter symlink unresolved for ownership checks.
    interpreter = pathlib.Path(os.path.abspath(parts[1]))
    interpreter = interpreter.parent.resolve() / interpreter.name
    legacy = install_dir / "venv/bin/python"
    return interpreter == legacy or (
        interpreter.name == "python" and interpreter.parent.name == "bin"
        and interpreter.parent.parent.parent == install_dir / "environments"
        and interpreter.parent.parent.name.startswith("venv-")
    )


try:
    install_dir.mkdir(parents=True, exist_ok=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep lock files in place so concurrent processes lock the same inodes.
    # Lock both paths: distinct install roots may share the same bin directory.
    for lock_path in (install_dir / ".install.lock", launcher_path.parent / ".devsecops.install.lock"):
        lock = lock_path.open("a")
        locks.append(lock)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another installation is running for this install or bin directory; retry after it finishes.") from None
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise ValueError("The installer ownership marker is not a regular file.")
    if (install_dir / "venv").exists() and not marker.is_file():
        raise ValueError("The existing venv was not created by this installer.")
    if os.path.lexists(launcher_path) and not owned_launcher():
        raise ValueError(f"Refusing to replace an unrelated launcher: {launcher_path}")

    environments = install_dir / "environments"
    environments.mkdir(exist_ok=True)
    staged_env = pathlib.Path(tempfile.mkdtemp(prefix="venv-", dir=environments))
    phase = "creating the replacement virtual environment"
    print(f"devsecops-install: Creating private virtual environment at {staged_env}", file=sys.stderr)
    subprocess.run([sys.executable, "-I", "-m", "venv", str(staged_env)], check=True, stdout=sys.stderr)
    venv_python = staged_env / "bin/python"
    phase = "installing the release wheel"
    subprocess.run([str(venv_python), "-I", "-m", "pip", "install", wheel_path], check=True, stdout=sys.stderr)
    if with_tui:
        phase = "installing optional TUI dependencies"
        print("devsecops-install: Installing optional TUI dependencies", file=sys.stderr)
        subprocess.run([str(venv_python), "-I", "-m", "pip", "install", "rich>=13.7", "textual>=0.79"],
                       check=True, stdout=sys.stderr)

    phase = "verifying the replacement CLI"
    expected_version = f"devsecops {release_tag.removeprefix('v')}"
    version = subprocess.run([str(venv_python), "-I", "-m", "devsecops_cli.main", "--version"],
                             check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if version != expected_version:
        raise ValueError("The installed CLI version does not match the selected release.")
    # The temporary launcher lives alongside its destination, guaranteeing
    # the final replace stays on one filesystem and is atomic.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".devsecops-install-",
                                     dir=launcher_path.parent, delete=False) as handle:
        staged_launcher = pathlib.Path(handle.name)
        handle.write("#!/bin/sh\n# Managed by DevSecOps Pipeline Kit installer.\n"
                     f'exec {shlex.quote(str(venv_python))} -I -m devsecops_cli.main "$@"\n')
    staged_launcher.chmod(0o755)
    phase = "verifying the replacement launcher"
    launcher_version = subprocess.run([str(staged_launcher), "--version"], check=True,
                                      capture_output=True, text=True, timeout=30).stdout.strip()
    if launcher_version != expected_version:
        raise ValueError("The replacement launcher did not start the selected CLI version.")

    phase = "activating the verified CLI"
    if not marker.exists():
        marker.touch(mode=0o600, exist_ok=False)
        created_marker = True
    # Recheck immediately before publication in case a different install
    # directory targets this same bin path while we prepare the candidate.
    if os.path.lexists(launcher_path) and not owned_launcher():
        raise ValueError(f"The destination launcher changed during installation: {launcher_path}")
    # A signal after publication must never remove the now-active environment.
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        os.replace(staged_launcher, launcher_path)
        activated = True
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    print(version)
except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
    detail = str(exc) if isinstance(exc, (OSError, ValueError)) else type(exc).__name__
    outcome = "The verified replacement CLI is active." if activated else "The previous CLI was preserved."
    raise SystemExit(f"Installation failed while {phase}: {detail}. {outcome}") from None
finally:
    if staged_launcher is not None:
        staged_launcher.unlink(missing_ok=True)
    if not activated:
        if staged_env is not None:
            shutil.rmtree(staged_env, ignore_errors=True)
        if created_marker:
            marker.unlink(missing_ok=True)
    for lock in reversed(locks):
        lock.close()
PYINSTALL
)"
log "Installed $installed_version"

# Colon-delimited matching avoids false positives from partial directory names.
case ":$PATH:" in
  *":$BIN_DIR:"*)
    log "Run the CLI with: $COMMAND_NAME"
    ;;
  *)
    warn "$BIN_DIR is not on PATH for this shell."
    log "Run now with: $BIN_DIR/$COMMAND_NAME"
    log "Or add it with: export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

if [ "$RUN_AFTER" = "1" ]; then
  # Never start an interactive CLI when the installer is running in a pipe or
  # unattended bootstrap environment.
  if [ -t 0 ]; then
    cleanup
    exec "$BIN_DIR/$COMMAND_NAME"
  fi
  warn "--run was requested, but installer stdin is not interactive. Run: $BIN_DIR/$COMMAND_NAME"
fi
