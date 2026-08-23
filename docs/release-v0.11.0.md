# Release v0.11.0

Release date: 2026-06-13

`v0.11.0` is the first published release after `v0.8.0`. It combines the
production evidence, stability contract, and final pre-1.0 hardening work into
one release-candidate path. This is not the `v1.0.0` stable tag; it gives users
clearer first-success guidance, quieter diagnostics, and a concrete evidence
map for the eventual stable release.

## Highlights

* Added the [Production deployment evidence](production-deployment-evidence.md)
  workflow so release records can capture setup, workflow, Terraform, AWS,
  health, log, image, and rollback-readiness evidence.
* Added the [Stability contract](stability-contract.md) with stable command,
  flag, JSON output, config migration, generated artifact, and deprecation
  expectations.
* Promoted Terraform helper commands to the stable command contract so the
  documented first-success workflow no longer depends on experimental behavior.
* Added fail-closed config loading for future schema versions. A CLI that does
  not understand a future `.devsecops-pipeline.toml` schema refuses to render
  or overwrite CLI-owned files.
* Added generated artifact compatibility notes that explain when re-rendering
  is required and what diffs users should expect.
* Added the [v1.0.0 release candidate checklist](v1.0.0-release-candidate-checklist.md)
  with Version 1.0 criteria mapped to commands, docs, tests, and release
  artifacts.
* Added [Known limitations](known-limitations.md), separating accepted product
  boundaries from blockers that must close before `v1.0.0`.
* Added `devsecops next`, which detects the current project context and shows
  one next action instead of cascading Terraform, GitHub, or AWS errors.
* Added `devsecops start`, a safe guided onboarding flow that can create local
  config and finish by showing the next action.
* Added `devsecops evidence collect --rc`, which writes a local release
  candidate evidence bundle under `dist/devsecops/evidence/rc/`.
* Improved readiness output with separate gates for local config, project
  files, production readiness, and release evidence.
* Improved `devsecops config validate --strict` output with explicit
  production blockers, warnings promoted by `--strict`, and next commands.
* Reduced diagnostic noise when root tools or project files are missing.
  Missing AWS CLI is reported as one grouped skipped AWS block.
* Added GitHub setup prechecks before `devsecops github setup --apply`.

## Install

The canonical `v0.11.0` package path is the GitHub Release wheel:

```bash
python3.11 -m pipx install --python python3.11 \
  "devsecops-pipeline-cli @ https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/v0.11.0/devsecops_pipeline_cli-0.11.0-py3-none-any.whl"
devsecops --version
```

For the latest-release install command, see
[Distribution and compatibility](distribution.md).

## Verify Artifacts

```bash
VERSION="0.11.0"
TAG="v${VERSION}"
BASE_URL="https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/${TAG}"
WHEEL="devsecops_pipeline_cli-${VERSION}-py3-none-any.whl"

curl -fsSLO "${BASE_URL}/SHA256SUMS"
curl -fsSLO "${BASE_URL}/${WHEEL}"
grep " ${WHEEL}$" SHA256SUMS > "${WHEEL}.SHA256SUMS"
shasum -a 256 -c "${WHEEL}.SHA256SUMS"
```

## Release Candidate Evidence

```bash
devsecops next --format json
devsecops readiness --strict --format json
devsecops evidence collect --rc
```

Attach the generated `dist/devsecops/evidence/rc/manifest.json` and referenced
files to the release record when preparing the final stable-release evidence.

## Upgrade Notes

`v0.11.0` does not change config schema semantics. Current schema version
remains `1`.

Existing schema version `1` files and legacy files without `schema_version`
continue to normalize to schema version `1`. Config files with a future
`schema_version` are refused until the CLI is upgraded.

After upgrading, review local state and generated artifact diffs before
applying any GitHub or AWS mutations:

```bash
devsecops next
devsecops config validate
devsecops config diff
devsecops render --dry-run
devsecops readiness --format compact
```

## Known Limitations

The `v1.0.0` blocker register still requires a real AWS/GitHub production
walkthrough bundle, GitHub CLI and AWS CLI compatibility evidence from the
target repository/account, and a WSL2 transcript before the stable tag.

## Validation

The release was validated with:

```bash
PYTHONPATH=cli python3.13 -m unittest discover -s cli/tests
python3.13 -m build
git diff --check
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform init -backend=false -input=false -no-color
terraform -chdir=terraform validate -no-color
devsecops --version
```
