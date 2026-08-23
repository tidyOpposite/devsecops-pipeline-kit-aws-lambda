# Release v0.8.0

Release date: 2026-06-12

Milestone 7 makes distribution and adoption flows explicit. Users can install,
upgrade, enable shell completion, and verify release artifacts without reading
the source tree.

## Highlights

* Added a distribution guide with latest-release install commands, pinned
  install commands, upgrade commands, shell completion setup, artifact
  verification, and compatibility matrix.
* Added a release checklist that covers version bumps, changelog and release
  notes, tests, build, checksums, commit, tag, push, and published release
  verification.
* Added an upgrade guide for `.devsecops-pipeline.toml` schema changes before
  any future schema migration ships.
* Added `devsecops completion <bash|zsh|fish>` for common shell completion
  scripts without adding runtime dependencies.
* GitHub Release artifacts now include `SHA256SUMS` for the wheel and source
  distribution.
* CI now runs CLI/package smoke tests across Python 3.11, 3.12, and 3.13.

## Install

The canonical `v0.8.0` package path is the GitHub Release wheel:

```bash
python3.11 -m pipx install --python python3.11 \
  "devsecops-pipeline-cli @ https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/v0.8.0/devsecops_pipeline_cli-0.8.0-py3-none-any.whl"
devsecops --version
```

For the latest-release install command, see
[Distribution and compatibility](distribution.md).

## Verify Artifacts

```bash
VERSION="0.8.0"
TAG="v${VERSION}"
BASE_URL="https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/${TAG}"
WHEEL="devsecops_pipeline_cli-${VERSION}-py3-none-any.whl"

curl -fsSLO "${BASE_URL}/SHA256SUMS"
curl -fsSLO "${BASE_URL}/${WHEEL}"
grep " ${WHEEL}$" SHA256SUMS > "${WHEEL}.SHA256SUMS"
shasum -a 256 -c "${WHEEL}.SHA256SUMS"
```

## Shell Completion

```bash
devsecops completion bash
devsecops completion zsh
devsecops completion fish
```

Persist the generated scripts using the shell-specific commands in
[Distribution and compatibility](distribution.md).

## Upgrade Notes

`v0.8.0` does not change the config schema. Current schema version remains `1`.

Before upgrading across future schema changes, follow
[Upgrade guide](upgrade-guide.md). Schema-changing releases must document
automatic migration behavior and manual operator actions before they ship.

## Validation

The release was validated with:

```bash
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
rm -rf build
python3 -m build
python3 -m pip install --no-deps --no-build-isolation .
devsecops --version
devsecops completion bash
git diff --check
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform init -backend=false -input=false -no-color
terraform -chdir=terraform validate -no-color
```
