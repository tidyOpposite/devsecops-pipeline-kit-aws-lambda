# Production Deployment Evidence

Use this guide when proving a production deployment against a real AWS account
and GitHub repository. The goal is to produce a reviewable evidence bundle that
can be attached to a release record without requiring reviewers to inspect the
source tree.

Do not mark a release or roadmap item as production-proven until this workflow
has been run against the intended AWS account, GitHub repository, immutable
Lambda image, and protected `main` branch.

## Evidence Bundle

Store live evidence outside Git. Collect it for one candidate commit on the
release repository's `main` branch. The successful CI run for that commit
provides the package files used in the walkthrough and stable publication.

```bash
export RELEASE_TAG="v$(PYTHONPATH=cli python3 -c 'from devsecops_cli import VERSION; print(VERSION)')"
export RELEASE_SHA="$(git rev-parse HEAD)"
export RELEASE_REPOSITORY="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
export EVIDENCE_ROOT="${EVIDENCE_ROOT:-dist/devsecops/production-evidence}"
export EVIDENCE_DIR="${EVIDENCE_DIR:-${EVIDENCE_ROOT}/${RELEASE_TAG}}"

mkdir -p "${EVIDENCE_DIR}/workflow-artifacts"
```

The final bundle should contain:

| Evidence | File |
| --- | --- |
| Candidate identity | `release-proof.json` |
| Release install and checksum proof | `release-install.txt`, `release-checksums.txt` |
| Local config and strict validation | `config.json`, `config-validate.json` |
| Rendered/audit evidence | `readiness-report.md`, `audit-report.json`, generated helper artifacts |
| GitHub setup and branch protection | `github-doctor.json`, `branch-doctor.json` |
| Workflow dispatch and run result | `workflow-run.json`, `github-status.json` |
| Terraform deployed outputs | `terraform-output.json` |
| AWS live resource outputs | `aws-outputs.json`, `aws-doctor.json` |
| Health and API verification | `health.json`, `health-response.txt` |
| CloudWatch log proof | `cloudwatch-log-groups.json`, `cloudwatch-tail.txt` |
| Rollback readiness proof | `active-lambda-image.txt`, `automatic-rollback-run.json`, `manual-rollback-run.json` |
| WSL2 compatibility proof | `wsl2-transcript.txt` |

## Prerequisites

Complete these before dispatching production:

* Select the successful `CLI and Terraform CI` run for the candidate commit on
  `main`. Copy its run ID into `CI_RUN_ID` for the next section.
* Use a real GitHub repository with `main` protected by pull requests and the
  required `Security and Terraform Validate` and `Terraform Plan` checks.
* Configure the GitHub Environment `prod` with required reviewers, self-review
  and administrator bypass disabled, and an exact `main` branch allowlist.
* Configure [separate GitHub OIDC roles](../AWS_policy.md#deploy-trust-policy-example)
  for `AWS_PLAN_ROLE_TO_ASSUME_ARN` and `AWS_ROLE_TO_ASSUME_ARN`. Capture the
  role names and run IDs as described in [Verify role setup](../AWS_policy.md#verify-role-setup).
* Configure an S3 backend bucket and DynamoDB lock table in the target AWS
  account.
* Publish a Lambda-compatible immutable ECR image before workflow dispatch.
  Use a digest or immutable tag, never `latest` or `bootstrap`.
* Set `enable_http_validation=true` and make sure the workload implements
  `GET /health`.
* If `ENABLE_DAST=true`, set `API_AUTHORIZATION_TYPE=NONE` only when the public
  API can tolerate a passive OWASP ZAP baseline scan.

## 1. Prove Release Install

Download the CI candidate and use the same wheel for the cloud walkthrough and
WSL2 acceptance. The artifact is retained for 30 days.

```bash
export CANDIDATE_DIR="$(mktemp -d)"
export WHEEL="devsecops_pipeline_cli-${RELEASE_TAG#v}-py3-none-any.whl"
gh run download "${CI_RUN_ID:?set the successful candidate CI run ID}" --repo "${RELEASE_REPOSITORY}" \
  --name release-candidate --dir "${CANDIDATE_DIR}"
(
  set -e
  cd "${CANDIDATE_DIR}"
  shasum -a 256 -c SHA256SUMS
  shasum -a 256 "${WHEEL}"
) | tee "${EVIDENCE_DIR}/release-checksums.txt"
python3 -m venv "${CANDIDATE_DIR}/venv"
. "${CANDIDATE_DIR}/venv/bin/activate"
python -m pip install --no-deps "${CANDIDATE_DIR}/${WHEEL}"
devsecops --version | tee "${EVIDENCE_DIR}/release-install.txt"
```

## 2. Prove Local Configuration

Create or inspect the source config, validate it strictly, generate helper
artifacts, and export both Markdown and JSON evidence:

```bash
devsecops config show --format json > "${EVIDENCE_DIR}/config.json"
devsecops config validate --strict --format json > "${EVIDENCE_DIR}/config-validate.json"
devsecops generate
devsecops report --output "${EVIDENCE_DIR}/readiness-report.md"
devsecops report --format json --output "${EVIDENCE_DIR}/audit-report.json"

cp terraform/generated.auto.tfvars "${EVIDENCE_DIR}/terraform-generated.auto.tfvars"
cp dist/devsecops/github-setup.sh "${EVIDENCE_DIR}/github-setup.sh"
cp dist/devsecops/github-variables.env "${EVIDENCE_DIR}/github-variables.env"
cp dist/devsecops/setup-checklist.md "${EVIDENCE_DIR}/setup-checklist.md"
```

Strict config validation must exit `0`. Capture deep readiness after the first
successful deploy in step 5.

## 3. Prove GitHub Setup

Capture repository variables, secrets readiness, branch protection, and recent
workflow state:

```bash
devsecops github setup --write
devsecops doctor github --strict --format json > "${EVIDENCE_DIR}/github-doctor.json"
devsecops doctor branch --branch main --strict --format json > "${EVIDENCE_DIR}/branch-doctor.json"
devsecops github status --format json > "${EVIDENCE_DIR}/github-status-before.json"
```

If either doctor output reports gaps, fix GitHub repository settings before
continuing.

## 4. Dispatch Production

Use the CLI to verify readiness, bind the exact immutable image, confirm the
production boundary, and dispatch the protected workflow from `main`:

```bash
devsecops deploy prod --dry-run
devsecops deploy prod --yes --watch
devsecops deploy status --format json > "${EVIDENCE_DIR}/deployment-status.json"
devsecops deploy logs > "${EVIDENCE_DIR}/workflow-log.txt"
devsecops github status --format json > "${EVIDENCE_DIR}/github-status.json"
```

The human dispatch output and JSON status include the GitHub run ID and URL.
The CLI also saves the run ID, requested image, and previously active image in
the ignored `.devsecops/deployments.json` journal; it never stores tokens or
credentials there. If workflow artifacts are part of the evidence policy,
download them by the recorded run ID with `gh run download <run-id> -D
"${EVIDENCE_DIR}/workflow-artifacts"`.

The workflow run must show `status=completed` and `conclusion=success`.
Review the run log for these production steps:

* `Verify reviewed production intent before approval`, with the reviewed commit,
  configuration SHA-256, and ECR digest in the run summary
* `Verify production policy and prepare pipeline configuration`
* `Capture currently deployed Lambda image`
* `Verify Terraform recovery state`
* `Plan production workload from reviewed inputs`
* `Terraform apply workload with configured Lambda image`
* `Read deployment outputs`
* `Wait for Lambda update`
* `Smoke test Lambda health endpoint`
* `Run DAST scan with OWASP ZAP`, when DAST is enabled and
  `API_AUTHORIZATION_TYPE=NONE`
* `Roll back Lambda image on failed deployment validation`, present as the
  failure recovery path

Also capture a no-write manual rollback rehearsal. This proves that the CLI
can resolve the previous immutable image without changing AWS:

```bash
devsecops deploy rollback --dry-run \
  > "${EVIDENCE_DIR}/rollback-dry-run.txt"
```

## 5. Prove Terraform And AWS Outputs

Capture Terraform outputs and read-only AWS inspection after the workflow
succeeds:

```bash
terraform -chdir=terraform output -json > "${EVIDENCE_DIR}/terraform-output.json"
devsecops status --deep --strict --format json > "${EVIDENCE_DIR}/readiness.json"
devsecops aws outputs --environment prod --format json > "${EVIDENCE_DIR}/aws-outputs.json"
devsecops doctor aws --environment prod --strict --format json > "${EVIDENCE_DIR}/aws-doctor.json"
```

The evidence should prove:

* active environment is `prod`;
* Lambda function state is `Active`;
* Lambda `LastUpdateStatus` is `Successful`;
* API Gateway invoke and health URLs are present;
* CloudWatch log group exists;
* active Lambda image matches the configured immutable image.

## 6. Prove Health And Logs

Extract the health URL from Terraform output and validate it through the CLI.
Production APIs default to `AWS_IAM`, so use SigV4 signing:

```bash
HEALTH_URL="$(
  python3 - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads((Path(os.environ["EVIDENCE_DIR"]) / "terraform-output.json").read_text())
print(payload["api_gateway_health_url"]["value"])
PY
)"

devsecops health --url "${HEALTH_URL}" --aws-sigv4 --format json > "${EVIDENCE_DIR}/health.json"
curl --fail --silent --show-error \
  --aws-sigv4 "aws:amz:${AWS_REGION}:execute-api" \
  --user "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" \
  -H "x-amz-security-token: ${AWS_SESSION_TOKEN}" \
  "${HEALTH_URL}" | tee "${EVIDENCE_DIR}/health-response.txt"
```

Then capture recent Lambda logs:

```bash
LAMBDA_FUNCTION="$(
  python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["EVIDENCE_DIR"]) / "terraform-output.json"
payload = json.loads(path.read_text())
print(payload["lambda_function_name"]["value"])
PY
)"

aws logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/${LAMBDA_FUNCTION}" \
  --output json > "${EVIDENCE_DIR}/cloudwatch-log-groups.json"

aws logs tail "/aws/lambda/${LAMBDA_FUNCTION}" \
  --since 15m \
  --format short > "${EVIDENCE_DIR}/cloudwatch-tail.txt"
```

The health evidence must show an HTTP success response, and the log evidence
must show the expected Lambda log group for the deployed function.

## 7. Prove Rollback Readiness

The production workflow captures the previous Lambda image before applying the
new image and contains the rollback step
`Roll back Lambda image on failed deployment validation`.

Capture the currently active image after the successful deployment:

```bash
aws lambda get-function \
  --function-name "${LAMBDA_FUNCTION}" \
  --query 'Code.ResolvedImageUri' \
  --output text > "${EVIDENCE_DIR}/active-lambda-image.txt"
```

In a controlled deployment account with a working image already deployed,
deploy a test image that fails `/health`. Capture the failed run and verify
that the recovery step reports `Verified Lambda recovery`, the active digest
matches the previously captured digest, `lambda_current_image_uri` in the
`prod` Terraform state matches it, and the endpoint returns 2xx. Repeat with
an approved manual rollback to a reviewed digest and attach both run IDs.
Use the [rollback runbook](runbooks/failed-rollback.md) if recovery fails.

Set `DEPLOY_RUN_ID`, `AUTOMATIC_ROLLBACK_RUN_ID`, and `MANUAL_ROLLBACK_RUN_ID`
to the three run IDs. Save the GitHub run and job responses for each run:

```bash
capture_run() {
  local run_path="repos/${RELEASE_REPOSITORY}/actions/runs/$1"
  gh api "${run_path}" > "${EVIDENCE_DIR}/run.tmp.json" &&
  gh api "${run_path}/jobs?per_page=100" > "${EVIDENCE_DIR}/jobs.tmp.json" &&
  jq -n --slurpfile run "${EVIDENCE_DIR}/run.tmp.json" --slurpfile jobs "${EVIDENCE_DIR}/jobs.tmp.json" \
    '{run: $run[0], jobs: $jobs[0].jobs}' > "${EVIDENCE_DIR}/$2"
}
capture_run "${DEPLOY_RUN_ID:?set the successful deploy run ID}" workflow-run.json
capture_run "${AUTOMATIC_ROLLBACK_RUN_ID:?set the failed deploy run ID}" automatic-rollback-run.json
capture_run "${MANUAL_ROLLBACK_RUN_ID:?set the manual rollback run ID}" manual-rollback-run.json
```

Set `DEPLOY_DIGEST`, `FAILED_DIGEST`, and `MANUAL_ROLLBACK_DIGEST` to the
three distinct ECR digest URIs from their run summaries. Capture cloud outputs
and `/health` for the successful deployment before starting the rollback drills.

```bash
wheel_sha="$(awk -v wheel="${WHEEL}" '$2 == wheel { print $1 }' "${CANDIDATE_DIR}/SHA256SUMS")"
jq -n --arg tag "${RELEASE_TAG}" --arg commit "${RELEASE_SHA}" --arg repo "${RELEASE_REPOSITORY}" \
  --argjson ci "${CI_RUN_ID}" --arg image "${DEPLOY_DIGEST}" --arg failed "${FAILED_DIGEST}" \
  --arg rollback "${MANUAL_ROLLBACK_DIGEST}" --arg sha "${wheel_sha}" \
  '{schema_version: 1, tag: $tag, commit_sha: $commit, repository: $repo, ci_run_id: $ci,
    image_uri: $image, failed_image_uri: $failed, manual_rollback_image_uri: $rollback, wheel_sha256: $sha}' \
  > "${EVIDENCE_DIR}/release-proof.json"
```

## 8. Prove WSL2 Compatibility

In a clean Ubuntu WSL2 checkout at the same commit, download and verify the
CI candidate as in step 1. Activate a fresh virtual environment and capture
the install and the rest of the walkthrough:

```bash
(
  set -e
  printf 'Release commit: %s\n' "$(git rev-parse HEAD)"
  uname -a
  python -m pip install --no-deps "${CANDIDATE_DIR}/${WHEEL}"
  devsecops --version
  devsecops setup --mode demo --yes --strict
  devsecops completion bash
  PYTHONPATH=cli python -m unittest discover -s cli/tests
) > wsl2-transcript.txt 2>&1
```

Copy `wsl2-transcript.txt` into the evidence directory.

## Post-Deploy Checklist

Before accepting the production proof, confirm:

* Release artifact checksum verification passed.
* `devsecops config validate --strict` passed.
* `devsecops status --deep --strict` passed after the successful deployment.
* `doctor github` and `doctor branch` showed no blocking GitHub setup gaps.
* Production workflow ran from `main` with `mode=deploy` and
  `environment=prod`.
* Workflow conclusion was `success`.
* Terraform output includes API Gateway URLs, Lambda function name, ECR
  repository, and workload data bucket.
* `devsecops aws outputs` shows Lambda state `Active` and update status
  `Successful`.
* `devsecops doctor aws --strict` passed.
* `devsecops health` and `curl` returned success for `/health`.
* CloudWatch log group evidence is present.
* Active Lambda image matches the immutable image used for dispatch.
* Rollback readiness is documented with the workflow capture step and active
  image evidence.

## Lessons To Record

Add a short `notes.md` file to the evidence directory before release approval.
Include:

* AWS account ID and region used for the walkthrough, redacted if needed.
* Backend bucket and lock table names.
* GitHub repository, branch protection settings, and production environment
  approval settings.
* Plan and deploy IAM role names.
* Immutable image URI and where the workload image was produced.
* Whether Snyk, HTTP validation, and DAST were enabled.
* Any failed setup step, its runbook link, and whether an existing runbook had
  to be updated.

If the walkthrough discovers a failure mode not covered by
[Operational runbooks](runbooks/README.md), add or update a runbook before the
release is considered production-proven.

## Final Verification Gate

After all files are present, run the machine-checkable Version 1.0 gate against
the evidence directory:

```bash
devsecops criteria --strict --format json --evidence-dir "${EVIDENCE_DIR}" \
  --verify-github "${RELEASE_REPOSITORY}" --artifacts-dir "${CANDIDATE_DIR}" > "${EVIDENCE_DIR}/criteria.json"
```

The strict command must exit `0` before a stable tag is cut. If it fails, the
output names the missing file or criterion and the next action to take.

For a stable tag at `v1.0.0` or later, stage the evidence as a separate draft
release named `evidence-${RELEASE_TAG}` before pushing the stable tag. The
publisher verifies the draft target, live GitHub runs and logs, and the exact
candidate wheel. The evidence archive stays on the draft.

```bash
export EVIDENCE_ARCHIVE="${CANDIDATE_DIR}/release-evidence.zip"
PYTHONPATH=cli python3 - <<'PY'
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from devsecops_cli.release_evidence import PRODUCTION_EVIDENCE_REQUIRED_FILES, WSL2_EVIDENCE_REQUIRED_FILES

source = Path(os.environ["EVIDENCE_DIR"])
with ZipFile(os.environ["EVIDENCE_ARCHIVE"], "w", ZIP_DEFLATED) as archive:
    for name in PRODUCTION_EVIDENCE_REQUIRED_FILES + WSL2_EVIDENCE_REQUIRED_FILES:
        archive.write(source / name, name)
PY
gh release create "evidence-${RELEASE_TAG}" "${EVIDENCE_ARCHIVE}" --repo "${RELEASE_REPOSITORY}" \
  --draft --target "${RELEASE_SHA}" --title "Evidence for ${RELEASE_TAG}" --notes "Private release evidence staging"
```
