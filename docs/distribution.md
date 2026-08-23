# Distribution And Compatibility

This document is the install, verification, shell completion, and compatibility
contract for released DevSecOps Pipeline Kit CLI versions.

## Published Package Path

The canonical package path is GitHub Releases:

* Repository: `tidyOpposite/devsecops-pipeline-kit-aws-lambda`
* Release tag format: `vX.Y.Z`
* Python package name: `devsecops-pipeline-cli`
* Release assets produced by the current workflow:
  * `install.sh`
  * `devsecops_pipeline_cli-<version>-py3-none-any.whl`
  * `devsecops_pipeline_cli-<version>.tar.gz`
  * `SHA256SUMS`

PyPI publication is intentionally deferred. Until a PyPI publishing workflow is
added and documented, install from GitHub Release assets rather than from the
source tree.

## Install The Latest Release

Use the installer for the shortest supported path. It finds Python 3.11, 3.12,
or 3.13, downloads the latest release wheel, verifies it against `SHA256SUMS`,
installs into a private virtual environment, and writes a launcher to
`~/.local/bin/devsecops`.

```bash
curl -fsSL https://raw.githubusercontent.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/main/install.sh | sh
devsecops --version
devsecops
```

If the current shell does not have `~/.local/bin` on `PATH`, the installer
prints the absolute command path to run immediately.

Pinned install with the release asset for tags that include `install.sh`:

```bash
VERSION="0.12.0"
TAG="v${VERSION}"
BASE_URL="https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/${TAG}"

curl -fsSL "${BASE_URL}/install.sh" | sh -s -- --version "${TAG}"
devsecops --version
```

For tags published before `install.sh` was added as a release asset, use the
main-branch bootstrapper with the same pinned version:

```bash
curl -fsSL https://raw.githubusercontent.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/main/install.sh | sh -s -- --version "${TAG}"
devsecops --version
```

Use `PYTHON=/path/to/python3.12` when auto-detection should use a specific
interpreter. Use `--with-tui` to install optional Rich/Textual dependencies.

Development installs still use the local checkout:

```bash
PYTHON="${PYTHON:-python3.11}"
"${PYTHON}" -m pip install -e .
devsecops --version
```

## Upgrade

Run the installer again, then validate local config before rendering or applying
anything:

```bash
curl -fsSL https://raw.githubusercontent.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/main/install.sh | sh
devsecops --version
devsecops config validate
devsecops config diff
devsecops render --dry-run
```

Read [Upgrade guide](upgrade-guide.md) before upgrading across a release that
changes `.devsecops-pipeline.toml` schema behavior.

## Manual Wheel Install With pipx

The installer is the recommended user path. For controlled environments that
already standardize on `pipx`, install a pinned wheel URL directly:

```bash
python3.11 -m pip install --user pipx
python3.11 -m pipx ensurepath
python3.11 -m pipx install --python python3.11 \
  "devsecops-pipeline-cli @ https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/v0.12.0/devsecops_pipeline_cli-0.12.0-py3-none-any.whl"
devsecops --version
```

## Verify Release Artifacts

Every GitHub Release produced by the current workflow includes `SHA256SUMS` for
the installer, wheel, and source distribution.

```bash
VERSION="0.12.0"
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
| Windows | WSL2 Ubuntu is supported. Native Windows is not a `v0.12.0` release target. | Native PowerShell/CMD completion and path behavior are not release-gated. |
| Python | 3.11, 3.12, and 3.13 | CLI tests, packaging, and install smoke run in CI for all supported Python versions. Package metadata uses `requires-python = ">=3.11,<3.14"` so unsupported Python releases are not advertised as supported. |
| Terraform CLI | 1.5.0 or newer | Terraform `required_version` is `>= 1.5.0`; CI validates with the pinned workflow version. |
| GitHub CLI | 2.45.0 or newer | Required for `gh variable`, `gh secret`, `gh api`, and `gh run` workflows. Missing-tool behavior is tested; run `devsecops doctor github` in real repositories. |
| AWS CLI | 2.15.0 or newer | Required for AWS diagnostics, backend checks, ECR inspection, Lambda outputs, and health-adjacent workflows. AWS CLI v1 is not supported. |

Newer Terraform, GitHub CLI, and AWS CLI versions may work, but they are not
considered supported until this matrix or the CI release gate is updated.
Python 3.14 and newer are intentionally outside the support matrix until CI and
release smoke tests cover them.
