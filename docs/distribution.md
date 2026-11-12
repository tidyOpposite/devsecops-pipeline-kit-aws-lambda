# Distribution And Compatibility

Current source: `0.16.0b2.dev0` (unpublished). The published prerelease is
`v0.16.0-beta.1` (`0.16.0b1`); the previous baseline is `v0.15.0`.
**Beta.1 assets do not contain the single-operator lab.** Install the matching
source checkout for that workflow.

Packages are distributed through GitHub Releases, not PyPI:
`install.sh`, the `devsecops-pipeline-cli` wheel, source archive and `SHA256SUMS`.
Keep Terraform/workflow sources at the same commit or release tag as the CLI.

## Install Current Source

Follow the complete [Quick Start](../README.md#quick-start). For an existing
reviewed checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --no-deps .
export PATH="$PWD/.venv/bin:$PATH"
devsecops --version
```

Debian needs `python3-venv`. For editable development, use
`.venv/bin/python -m pip install --no-deps -e .`. Record `git rev-parse HEAD`
and the installed version when evaluating a source build.

## Install The Prerelease

Choose the prerelease explicitly; an unpinned installer selects the latest
non-prerelease. These commands install beta.1, not the current lab source:

```bash
git clone --branch v0.16.0-beta.1 --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-beta &&
cd devsecops-beta &&
sh install.sh --version v0.16.0-beta.1 &&
export PATH="$HOME/.local/bin:$PATH" &&
devsecops --version
```

Expected version: `devsecops 0.16.0b1`. The installer verifies its wheel against
the release manifest. Use a reviewed checkout or verify a downloaded installer
before executing it; the pinned example below demonstrates that boundary.

## Pinned Published Baseline

This reproduces the existing `v0.15.0` release, including its historical setup
and installer behavior. It does not contain the current audit fixes. A separate
install directory and bin directory keep this baseline away from the active CLI.
The checkout commit and checksum manifest are pinned as verified on 5 November
2026. The manifest covers both installer and wheel; it is checked before any
downloaded code executes. The installer then verifies its wheel against it.

```bash
(
set -eu
TAG="v0.15.0"
BASE_URL="https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/${TAG}"
git clone --branch "${TAG}" --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-release-demo
cd devsecops-release-demo
test "$(git rev-parse HEAD)" = "438902e02565e535f0b6ebc85576692c6bf51e95"
INSTALLER_DIR="$(mktemp -d)"
trap 'rm -rf "${INSTALLER_DIR}"' EXIT
curl -fsSL "${BASE_URL}/SHA256SUMS" -o "${INSTALLER_DIR}/SHA256SUMS"
curl -fsSL "${BASE_URL}/install.sh" -o "${INSTALLER_DIR}/install.sh"
python3 - "${INSTALLER_DIR}" <<'PY'
import hashlib
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
manifest = (root / "SHA256SUMS").read_bytes()
if hashlib.sha256(manifest).hexdigest() != "21acf395c149ac9b5ce08cfbc770106cc4d1b4c515c2de70d6bef66d0c2ea4cc":
    raise SystemExit("Published checksum manifest differs from the reviewed baseline.")
entries = dict((name.lstrip("*"), checksum) for checksum, name in (line.split() for line in manifest.decode().splitlines()))
if hashlib.sha256((root / "install.sh").read_bytes()).hexdigest() != entries.get("install.sh"):
    raise SystemExit("Installer checksum verification failed.")
PY
sh "${INSTALLER_DIR}/install.sh" --version "${TAG}" \
  --install-dir "${HOME}/.local/share/devsecops-release-demos/${TAG}" \
  --bin-dir "${HOME}/.local/share/devsecops-release-demos/${TAG}/bin"
export PATH="${HOME}/.local/share/devsecops-release-demos/${TAG}/bin:${PATH}"
devsecops --version
devsecops setup --mode demo --yes --strict
devsecops generate --dry-run
)
```

Expected version is `devsecops 0.15.0`. That release reports
`Guided setup complete`; its ordinary status can still show production gaps.
The current source reports `Demo complete` with separate demo status.

After all fixes and acceptance, publish a stable version and pin its tag,
source commit and checksum manifest. Never repoint the
old tag or imply that the old wheel includes new source changes.

## Upgrade

Use a reviewed current installer and select the intended release explicitly:

```bash
sh install.sh --version v0.16.0-beta.1
devsecops --version
devsecops config validate
devsecops config diff
devsecops generate --dry-run
```

The current installer prepares and verifies a new environment before atomically
replacing its launcher. Failed environment creation, dependency installation,
startup checks or activation preserve the working CLI. Concurrent installs are
blocked; unrelated launchers and unmanaged environments are refused.

Previous managed environments remain available for running processes. Remove
unused environments only after checking the active launcher and closing older
CLI processes. Re-run the current installer with an older `--version` to revert
package versions safely. Historical installer assets retain their old behavior.
See [Upgrade guide](upgrade-guide.md) for config and snapshot recovery.

## Verify Release Artifacts

Download the installer, wheel, source archive and `SHA256SUMS` from the same
release. Compare
the manifest with a separately reviewed checksum, then check each file before
execution. On macOS use `shasum -a 256 -c SHA256SUMS`; on Debian use
`sha256sum -c SHA256SUMS`. A matching manifest downloaded alongside files proves
consistency, not independent authenticity.

## Shell Completion

The CLI can print completion scripts for common shells.

Bash:

```bash
mkdir -p ~/.local/share/bash-completion/completions
devsecops completion bash > ~/.local/share/bash-completion/completions/devsecops
```

Zsh:

```bash
mkdir -p ~/.zfunc
devsecops completion zsh > ~/.zfunc/_devsecops
printf '\nfpath=(~/.zfunc $fpath)\nautoload -Uz compinit\ncompinit\n' >> ~/.zshrc
```

Fish:

```bash
mkdir -p ~/.config/fish/completions
devsecops completion fish > ~/.config/fish/completions/devsecops.fish
```

For a different binary name, pass `--program`:

```bash
devsecops completion bash --program devsecops-dev
```

## Compatibility Matrix

| Component | Supported versions | Release gate |
| --- | --- | --- |
| Debian Linux | Debian 13 (trixie), ARM64/aarch64 | Native Debian 13 VM acceptance plus pinned Debian CI container for package/unit/install checks. Ubuntu remains a CI host, not a declared acceptance target. |
| macOS | macOS 13 or newer on Intel or Apple Silicon | Supported for local CLI usage with Python, Terraform, AWS CLI, GitHub CLI, and shell completion installed by the operator. |
| Windows and WSL2 | Not supported or verified for the current source/release target. | No Windows/WSL2 acceptance claim is made. Use a supported Debian or macOS host. |
| Python | 3.11, 3.12, 3.13, and 3.14 | CLI tests, packaging, and install smoke run in CI for all supported Python versions. Package metadata uses `requires-python = ">=3.11,<3.15"` so unsupported Python releases are not advertised as supported. |
| Terraform CLI | 1.10.5 or newer for stable lab | The experimental primary stack retains its older minimum; lab requires >= 1.10.5. |
| GitHub CLI | 2.45.0 or newer | Required for `gh variable`, `gh secret`, `gh api`, and `gh run` workflows. Missing-tool behavior is tested; run `devsecops doctor github` in real repositories. |
| AWS CLI | 2.15.0 or newer | Required for AWS diagnostics, backend checks, ECR inspection, Lambda outputs, and health-adjacent workflows. AWS CLI v1 is not supported. |

Tool minimums describe accepted inputs, not proof of every newer version.
Record actual versions in candidate acceptance; CI pins Terraform 1.10.5.
Python 3.15+ and Windows/WSL2 need their own compatibility validation before
being added to the declared target.
