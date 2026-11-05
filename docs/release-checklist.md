# Release Checklist

Use this checklist for every new release. The published baseline is `v0.15.0`;
current source is `0.16.0.dev0`, unpublished beta hardening. Do not reuse the
existing tag or publish the development version. Choose a new final version
after all fixes, then complete acceptance against that commit and CI wheel.

## 1. Prepare The Version

```bash
git status --short --branch
```

Update all version references together:

* `cli/devsecops_cli/__init__.py`
* `pyproject.toml`
* `cli/pyproject.toml`

Update release documentation before validating:

* `CHANGELOG.md`
* version-specific notes at `docs/release-v<VERSION>.md`
* `README.md` release links when a new release note is added
* `ROADMAP.md` milestone status when a milestone ships

Confirm the CLI and both package versions agree. Before building/tagging,
derive the release identity from source instead of copying an old example:

```bash
export VERSION="$(PYTHONPATH=cli python3 -c 'from devsecops_cli import VERSION; print(VERSION)')"
export TAG="${TAG:-v${VERSION}}"
export NOTES="docs/release-v${VERSION}.md"
PYTHONPATH=cli python3 -m devsecops_cli.release_version "${TAG}" . || exit 1
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "Choose a new version; this tag already exists." >&2
  exit 1
fi
```

For a prerelease, set `TAG` explicitly (for example `v0.16.0-rc.1`) and use its
canonical Python version (`0.16.0rc1`) in CLI/package metadata and notes. The
publisher validates this mapping and the installer checks the canonical version.

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

export PACKAGE_OUT="$(mktemp -d)"
"${PYTHON}" -m build --outdir "${PACKAGE_OUT}"
cp install.sh "${PACKAGE_OUT}/install.sh"
chmod 0755 "${PACKAGE_OUT}/install.sh"
(
  cd "${PACKAGE_OUT}"
  shasum -a 256 install.sh *.whl *.tar.gz > SHA256SUMS
  shasum -a 256 -c SHA256SUMS
)
```

Keep `dist/devsecops/production-evidence` intact. Package staging uses a fresh
directory and must not delete the walkthrough evidence needed for publication.

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
  "${NOTES}" \
  docs/command-inventory.md
git commit -m "Release ${TAG}"
```

## 5. Tag And Push

Create an annotated tag from the release commit:

```bash
git tag -a "${TAG}" -m "Release ${TAG}"
git push origin main
git push origin "${TAG}"
```

The `Publish GitHub Release` workflow runs on `v*.*.*` tags.
For a final tag at `v1.0.0` or later, complete the [production evidence workflow](production-deployment-evidence.md#final-verification-gate)
and stage its separate draft before pushing the stable tag. The publisher
cross-checks GitHub runs and logs for the release commit and publishes the
reviewed CI candidate artifacts. A missing or invalid bundle fails publication.

## 6. Verify The Published Release

After the workflow finishes:

```bash
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
the version-specific notes at `${NOTES}`.

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
* verified Terraform backend/workspace and AWS identity in `terraform-context.json`,
  Terraform outputs and `devsecops aws outputs` JSON;
* `devsecops doctor aws --strict` JSON;
* `/health` validation output, response body and explicit 2xx in `health-status.txt`;
* CloudWatch log group/tail evidence;
* active Lambda image and rollback-readiness notes.

Include the isolated AWS runtime acceptance run/attempt ID and cleanup result
from [Security gate acceptance](security-gate-acceptance.md). This real-service
test belongs to final acceptance in a dedicated sandbox account; CI runs only
its mock rehearsal and scanner-isolation probe.

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

For the current hardening candidate and the final pre-`v1.0.0` release
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
