# Release Checklist

Use this checklist for every `vX.Y.Z` release. Replace `0.13.1` and `v0.13.1`
with the target version.

## 1. Prepare The Version

```bash
git status --short --branch
```

Update all version references together:

* `cli/devsecops_cli/__init__.py`
* `pyproject.toml`
* `cli/pyproject.toml`
* `cli/tests/test_devsecops_cli.py`

Update release documentation:

* `CHANGELOG.md`
* `docs/release-v0.13.1.md`
* `README.md` release links when a new release note is added
* `ROADMAP.md` milestone status when a milestone ships

## 2. Validate Locally

```bash
PYTHON="${PYTHON:-python3.11}"

PYTHONPATH=cli "${PYTHON}" -m unittest discover -s cli/tests
sh -n install.sh
./install.sh --help >/tmp/devsecops-install-help.txt
"${PYTHON}" -m pip install --upgrade pip==26.1.2 build==1.5.0 setuptools==82.0.1 wheel==0.47.0
rm -rf build
"${PYTHON}" -m build
"${PYTHON}" -m pip install --no-deps --no-build-isolation .
devsecops --version
devsecops completion bash >/tmp/devsecops.bash
devsecops completion zsh >/tmp/_devsecops
devsecops completion fish >/tmp/devsecops.fish
git diff --check
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform init -backend=false -input=false -no-color
terraform -chdir=terraform validate -no-color
```

If `gh` and AWS credentials are available, also run:

```bash
devsecops doctor github --format compact
devsecops doctor aws --environment prod --format compact
```

## 3. Build And Check Artifacts

```bash
PYTHON="${PYTHON:-python3.11}"

rm -rf build dist
"${PYTHON}" -m build
cp install.sh dist/install.sh
chmod 0755 dist/install.sh
cd dist
shasum -a 256 install.sh *.whl *.tar.gz > SHA256SUMS
shasum -a 256 -c SHA256SUMS
cd ..
```

The tag workflow repeats this build on GitHub Actions and publishes:

* installer
* wheel
* source distribution
* `SHA256SUMS`

## 4. Commit

```bash
git status --short
git add -- \
  install.sh \
  cli/devsecops_cli/main.py \
  cli/devsecops_cli/__init__.py \
  cli/devsecops_cli/aws.py \
  cli/devsecops_cli/completion.py \
  cli/devsecops_cli/config.py \
  cli/devsecops_cli/context.py \
  cli/devsecops_cli/contracts.py \
  cli/devsecops_cli/doctor.py \
  cli/devsecops_cli/formatting.py \
  cli/devsecops_cli/github.py \
  cli/devsecops_cli/images.py \
  cli/devsecops_cli/models.py \
  cli/devsecops_cli/parser.py \
  cli/devsecops_cli/paths.py \
  cli/devsecops_cli/readiness.py \
  cli/devsecops_cli/render.py \
  cli/devsecops_cli/reports.py \
  cli/devsecops_cli/snapshots.py \
  cli/devsecops_cli/views.py \
  cli/tests/test_architecture.py \
  pyproject.toml \
  cli/pyproject.toml \
  cli/tests/test_devsecops_cli.py \
  .github/workflows/ci.yml \
  .github/workflows/release.yml \
  CHANGELOG.md \
  README.md \
  ROADMAP.md \
  docs/distribution.md \
  docs/cli-architecture.md \
  docs/first-successful-pipeline.md \
  docs/generated-artifacts.md \
  docs/known-limitations.md \
  docs/production-deployment-evidence.md \
  docs/release-checklist.md \
  docs/stability-contract.md \
  docs/v1.0.0-release-candidate-checklist.md \
  docs/upgrade-guide.md \
  docs/release-v0.13.1.md \
  docs/command-inventory.md
git commit -m "Release v0.13.1 Python 3.14 support"
```

## 5. Tag And Push

Create an annotated tag from the release commit:

```bash
git tag -a v0.13.1 -m "Release v0.13.1"
git push origin main
git push origin v0.13.1
```

The `Publish GitHub Release` workflow runs on `v*.*.*` tags.

## 6. Verify The Published Release

After the workflow finishes:

```bash
VERSION="0.13.1"
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

Confirm the release page includes the expected notes from
`docs/release-v0.13.1.md`.

## 7. Production Evidence Gate

For `v0.9.0` and later releases that claim production proof, run
[Production deployment evidence](production-deployment-evidence.md) against the
target AWS account and GitHub repository before closing the release.

Attach or link the evidence bundle in the release record. At minimum, the
bundle must include:

* release install and checksum proof;
* strict config validation and readiness JSON;
* Markdown readiness report and JSON audit report;
* GitHub doctor, branch doctor, and workflow run evidence;
* Terraform outputs and `devsecops aws outputs` JSON;
* `devsecops doctor aws --strict` JSON;
* `/health` validation output and response body;
* CloudWatch log group/tail evidence;
* active Lambda image and rollback-readiness notes.

If the walkthrough exposes a failure mode not covered by
[Operational runbooks](runbooks/README.md), update the runbook set before
publishing the release.

## 8. Stability Contract Gate

For `v0.12.0` and later releases, verify the public contract before publishing:

```bash
devsecops inventory --format json
devsecops inventory --status stable --format markdown
devsecops config schema --format json
devsecops config schema --format markdown
devsecops status --format json
devsecops generate --dry-run
```

Confirm:

* first-success docs use only stable commands;
* aliases have documented stable replacements and deprecation expectations;
* experimental commands are not required by README, first-success, production
  evidence, or release workflows;
* every JSON `kind` used by scripts appears in the inventory contract;
* schema-changing releases include migration tests and upgrade notes before
  generated files are re-rendered;
* generated artifact diffs match the expected compatibility notes in
  [Generated artifacts](generated-artifacts.md).

## 9. v1.0 Release Candidate Hardening Gate

For `v0.13.1` release-candidate hardening and the final pre-`v1.0.0` release
record, complete [v1.0.0 release candidate checklist](v1.0.0-release-candidate-checklist.md).

At minimum, attach evidence for:

* every Version 1.0 criterion in the evidence map;
* `devsecops criteria --strict --format json` output;
* `devsecops evidence collect --rc` output;
* supported operating systems and tool versions in
  [Distribution and compatibility](distribution.md);
* quick start, first-success, upgrade, troubleshooting, runbook, command
  inventory, and generated-artifact documentation audit;
* GitHub Actions permissions, OIDC role guidance, Terraform validation,
  scanner gates, rollback behavior, and audit evidence security review;
* accepted limitations and stable-release blockers from
  [Known limitations](known-limitations.md).

Do not tag `v1.0.0` until `devsecops criteria --strict` exits `0` against the
final evidence directory and the blocker register in the RC checklist is empty.
