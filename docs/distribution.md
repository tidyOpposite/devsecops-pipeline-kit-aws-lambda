# Distribution And Compatibility

Stable 1.0 acceptance targets the local CLI and **single-operator dev lab in one
AWS account**. GitHub/OIDC production deployment, independent reviewers and
separate-account sandbox acceptance are **experimental integrations**, outside
this stable scope. Their runtime security guards remain unchanged. See
[Single-operator release evidence](single-operator-release-evidence.md).

This document is the install, verification, shell completion, and compatibility
contract for released DevSecOps Pipeline Kit CLI versions.

## Published Package Path

The canonical package path is GitHub Releases:

* Repository: `tidyOpposite/devsecops-pipeline-kit-aws-lambda`
* Release tag format: `vX.Y.Z`; prereleases use tags such as `v0.16.0-beta.1`
* Python package name: `devsecops-pipeline-cli`
* Release assets produced by the current workflow:
  * `install.sh`
  * `devsecops_pipeline_cli-<version>-py3-none-any.whl`
  * `devsecops_pipeline_cli-<version>.tar.gz`
  * `SHA256SUMS`

PyPI publication is deferred. Published installs use GitHub Release assets.
Current source is `0.16.0b2.dev0` (unpublished). The published prerelease is
`0.16.0b1`, tag `v0.16.0-beta.1`; it does not contain the new `lab` commands.
For the lab, install a matching source checkout with `python3 -m pip install --no-deps .`
inside a virtual environment. Keep its Terraform sources and installed CLI together.
Final production acceptance is pending. The previous published baseline is
[v0.15.0](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/tag/v0.15.0),
published 4 November 2026.

## Install The Prerelease

Choose the prerelease explicitly; an unpinned installer selects the latest
non-prerelease. Keep the Terraform/workflow checkout at the same tag:

```bash
git clone --branch v0.16.0-beta.1 --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-beta &&
cd devsecops-beta &&
sh install.sh --version v0.16.0-beta.1 &&
export PATH="$HOME/.local/bin:$PATH" &&
devsecops --version
```

Expected CLI version: `devsecops 0.16.0b1`. Prerelease package filenames use
the canonical Python version, for example
`devsecops_pipeline_cli-0.16.0b1-py3-none-any.whl`.

## Install Current Source

Install CLI, Terraform and workflows from the same checkout. Use Python 3.11,
3.12, 3.13 or 3.14 with venv/pip support (Ubuntu may need `python3-venv`).

```bash
git clone https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-pipeline-kit &&
cd devsecops-pipeline-kit &&
python3 -m venv .venv &&
.venv/bin/python -m pip install --no-deps . &&
export PATH="$PWD/.venv/bin:$PATH" &&
devsecops --version &&
devsecops setup --yes --strict
```

Record `git rev-parse HEAD`, `devsecops --version` and the built wheel checksum
for evaluation. Source installation uses that checkout; running an
installer pinned to `v0.15.0` installs the historical wheel instead.

When using a manual wheel or pipx installation, keep a checkout too; installing
the package does not download the Terraform/workflow source. Follow the
[Quick Start](../README.md#quick-start) for the complete local demonstration.
Commands run from project subdirectories find the root automatically. The
nearest config or complete kit checkout wins, and a nested Git repository is
a boundary; unrelated working directories never use the installed package as
their project root.

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

Use `PYTHON=/path/to/python3.12` when auto-detection should use a specific
interpreter. Use `--with-tui` to install optional Rich/Textual dependencies.

For editable development in the source checkout's private environment:

```bash
.venv/bin/python -m pip install --no-deps -e .
devsecops --version
```

## Upgrade

Run the installer again, then validate local config before generating or applying
anything:

```bash
sh install.sh --version v0.16.0-beta.1
devsecops --version
devsecops config validate
devsecops config diff
devsecops generate --dry-run
```

Read [Upgrade guide](upgrade-guide.md) before upgrading across a release that
changes `.devsecops-pipeline.toml` schema behavior.

Choose the intended tag explicitly. `v0.16.0-beta.1` opts into the prerelease;
the pinned baseline section above still installs historical `v0.15.0`.
Use a release's verified installer when outside a reviewed checkout.
An unpinned `sh install.sh` resolves latest and does not select this beta.

Each installer run prepares a fresh environment under
`~/.local/share/devsecops-pipeline-cli/environments/venv-*` (or the configured
`--install-dir`). It checks the selected release's exact CLI version and tests
the replacement launcher before atomically replacing `devsecops`. The launcher
uses that environment's Python in isolated mode, so `PYTHONPATH` and the current
directory cannot substitute a different installed module.

Failures while creating the environment, installing the wheel/TUI dependencies,
checking startup, or publishing the launcher leave the existing launcher and
environment intact. Incomplete candidates are removed. The legacy managed
`<install-dir>/venv` layout upgrades automatically and remains available.
Unrelated launchers and unmarked legacy environments are refused; use a
different `--bin-dir`/`--install-dir` rather than overwriting another tool.
Concurrent installers targeting the same install or bin directory are refused
with a retry message; OS locks are released when the process exits.

Old environments are retained so already-running commands can finish. They
consume disk space until explicitly removed. Inspect the active launcher to
identify its environment, and only remove other environments after their CLI
processes have exited. To return to an earlier release, rerun this installer
with `--version vX.Y.Z`; it verifies and activates that release through the same
process. Older release-specific installer assets retain their historical
behavior, so use the updated installer for this upgrade protection.

## Manual Wheel Install With pipx

The installer is the recommended user path. For controlled environments that
already standardize on `pipx`, install a pinned wheel URL directly:

```bash
python3.11 -m pip install --user pipx
python3.11 -m pipx ensurepath
python3.11 -m pipx install --python python3.11 \
  "devsecops-pipeline-cli @ https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/v0.15.0/devsecops_pipeline_cli-0.15.0-py3-none-any.whl#sha256=58d3dfb2986f1a398a8cb359fdcbd6d017425c8995d08017c6fd954092c82428"
devsecops --version
```

## Verify Release Artifacts

Every GitHub Release produced by the current workflow includes `SHA256SUMS` for
the installer, wheel, and source distribution.

```bash
VERSION="0.15.0"
TAG="v${VERSION}"
BASE_URL="https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/${TAG}"
WHEEL="devsecops_pipeline_cli-${VERSION}-py3-none-any.whl"

curl -fsSLO "${BASE_URL}/SHA256SUMS"
curl -fsSLO "${BASE_URL}/install.sh"
curl -fsSLO "${BASE_URL}/${WHEEL}"
grep " install.sh$" SHA256SUMS > install.sh.SHA256SUMS
grep " ${WHEEL}$" SHA256SUMS > "${WHEEL}.SHA256SUMS"
shasum -a 256 -c install.sh.SHA256SUMS
shasum -a 256 -c "${WHEEL}.SHA256SUMS"

sh install.sh --version "${TAG}"
devsecops --version
```

On Linux, `sha256sum -c "${WHEEL}.SHA256SUMS"` is equivalent.

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
| Ubuntu Linux | Ubuntu 22.04 LTS and 24.04 LTS on x86_64 or arm64 | GitHub Actions runs package, unit, golden, install, Terraform fmt, init, and validate checks on Ubuntu. |
| macOS | macOS 13 or newer on Intel or Apple Silicon | Supported for local CLI usage with Python, Terraform, AWS CLI, GitHub CLI, and shell completion installed by the operator. |
| Windows and WSL2 | Not supported or verified for the current source/release target. | No Windows/WSL2 acceptance claim is made. Use a supported Ubuntu or macOS host. |
| Python | 3.11, 3.12, 3.13, and 3.14 | CLI tests, packaging, and install smoke run in CI for all supported Python versions. Package metadata uses `requires-python = ">=3.11,<3.15"` so unsupported Python releases are not advertised as supported. |
| Terraform CLI | 1.5.0 or newer | Terraform `required_version` is `>= 1.5.0`; CI validates with the pinned workflow version. |
| GitHub CLI | 2.45.0 or newer | Required for `gh variable`, `gh secret`, `gh api`, and `gh run` workflows. Missing-tool behavior is tested; run `devsecops doctor github` in real repositories. |
| AWS CLI | 2.15.0 or newer | Required for AWS diagnostics, backend checks, ECR inspection, Lambda outputs, and health-adjacent workflows. AWS CLI v1 is not supported. |

Newer Terraform, GitHub CLI, and AWS CLI versions may work, but they are not
considered supported until this matrix or the CI release gate is updated.
Python 3.15 and newer are intentionally outside the support matrix until CI and
release smoke tests cover them.
