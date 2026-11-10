# Production Deployment Evidence

Use this guide when proving a production deployment against a real AWS account
and GitHub repository. The goal is to produce a reviewable evidence bundle that
can be attached to a release record without requiring reviewers to inspect the
source tree.

Current source is `0.16.0b2.dev0` (unpublished). The single-operator `lab`
records separate dev evidence and does not satisfy this production contract.
Published prerelease is `0.16.0b1` (`v0.16.0-beta.1`); the previous published
baseline is `v0.15.0`. Production acceptance is still pending. After the
remaining fixes, choose a stable candidate and collect this bundle from one
reviewed commit and its CI wheel. Do not use the old published wheel to prove current fixes.

Complete the [finish-demo/decommission acceptance](runbooks/finish-demo.md#final-acceptance-record)
after deployment/recovery proof. Preserve its retention decisions, restore test,
per-workspace destroy results, retained/retired backend inventory and later
KMS/billing checks outside retiring resources. These are pending final AWS
acceptance; local mocked teardown is preparation, not live-service proof.

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
| Terraform backend, workspace, AWS identity and deployed outputs | `terraform-context.json`, `terraform-output.json` |
| AWS live resource outputs | `aws-outputs.json`, `aws-doctor.json` |
| Health and API verification | `health.json`, `health-response.txt`, `health-status.txt` |
| CloudWatch log proof | `cloudwatch-log-groups.json`, `cloudwatch-tail.txt` |
| Rollback readiness proof | `active-lambda-image.txt`, `automatic-rollback-run.json`, `manual-rollback-run.json` |
| Supported-platform compatibility proof | `platform-transcript.txt` |

## Prerequisites

During final acceptance, also complete the separate
[AWS runtime constraint test](security-gate-acceptance.md) in a dedicated sandbox
account. Record its run/attempt ID, artifact and cleanup result in `notes.md`.
It supplements this production health/rollback walkthrough; it must not run
against the production account.

Complete these before dispatching production:

* Select the successful `CLI and Terraform CI` run for the candidate commit on
  `main`. Copy its run ID into `CI_RUN_ID` for the next section.
* Use a real GitHub repository with `main` protected by pull requests and the
  required `Security and Terraform Validate` and `Terraform Format and Validate` checks.
* Configure the GitHub Environment `prod` with required reviewers, self-review
  and administrator bypass disabled, and an exact `main` branch allowlist.
* Configure [separate GitHub OIDC roles](../AWS_policy.md#deploy-trust-policy-example)
  for `AWS_PLAN_ROLE_TO_ASSUME_ARN` and `AWS_ROLE_TO_ASSUME_ARN`. Capture the
  role names and run IDs as described in [Verify role setup](../AWS_policy.md#verify-role-setup).
* Configure an S3 backend bucket and DynamoDB lock table in the target AWS
  account.
* Publish a Lambda-compatible immutable ECR image before workflow dispatch.
  Use a digest or immutable tag, never `latest` or `bootstrap`.
  For the kit's repository, follow the separate
  [ECR bootstrap procedure](bring-your-own-image.md#provision-the-built-in-repository-before-the-first-deploy).
* Set `enable_http_validation=true` and make sure the workload implements
  `GET /health`.
* If `ENABLE_DAST=true`, set `API_AUTHORIZATION_TYPE=NONE` only when the public
  API can tolerate a passive OWASP ZAP baseline scan.

## 1. Prove Release Install

Download the CI candidate and use the same wheel for the cloud walkthrough and
supported-platform acceptance. The artifact is retained for 30 days.

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
workflow state. After synchronization, run `verify-oidc.yml` from `main` and
complete the `prod` approval. Confirm both identity jobs succeeded before
capturing strict doctor output. Record the verification run ID in `notes.md`.

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
devsecops status --pre-deploy --strict --format json > "${EVIDENCE_DIR}/pre-deploy-status.json"
devsecops deploy prod --dry-run
devsecops deploy prod --yes --watch
devsecops deploy status --format json > "${EVIDENCE_DIR}/deployment-status.json"
devsecops deploy logs > "${EVIDENCE_DIR}/workflow-log.txt"
devsecops github status --format json > "${EVIDENCE_DIR}/github-status.json"
```

The pre-deployment gate verifies Terraform, GitHub protections, AWS identity,
the state backend, and the configured ECR image. Lambda, API Gateway, and
workload logs can be absent at this stage. Initialize both Terraform modules
for validation in a fresh checkout. Review the exact inputs and workflow
availability in the dry run before dispatch.

The human dispatch output and JSON status include the GitHub run ID and URL
once confirmed. Until then the local journal tracks the dispatch request ID.
Use `devsecops deploy status --watch` if the run is unconfirmed. The runner
uploads the previous digest in `deployment-recovery-<attempt>` for the exact
deployment run. If workflow artifacts are part of the evidence policy,
download them by the recorded run ID with `gh run download <run-id> -D
"${EVIDENCE_DIR}/workflow-artifacts"`.

The workflow run must show `status=completed` and `conclusion=success`.
Review the run log for these production steps:

* `Verify reviewed production intent before approval`, with the reviewed commit,
  configuration SHA-256, and ECR digest in the run summary
* `Verify production policy and prepare pipeline configuration`
* `Verify reviewed Lambda image in ECR` before Terraform initialization
* `Capture currently deployed Lambda image`
* `Verify Terraform recovery state`
* `Upload deployment recovery point`
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
succeeds. Use Bash with `set -euo pipefail` for the following blocks, so failed
commands stop evidence collection. Independently confirm the workload account
ID in the AWS console; do not derive the expected account from the current CLI
session. Initialize the reviewed backend and select the existing `prod`
workspace explicitly. Do not create a workspace during evidence collection.
Deep status requires HTTP 2xx from the deployed API's `/health`
route. For `AWS_IAM`, export `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
and `AWS_SESSION_TOKEN` when using temporary credentials. The caller needs
`execute-api:Invoke` on the route.

```bash
set -euo pipefail
export EXPECTED_AWS_ACCOUNT_ID="123456789012" # replace with the confirmed workload account
unset TF_WORKSPACE TF_DATA_DIR TF_CLI_ARGS TF_CLI_ARGS_init TF_CLI_ARGS_output TF_CLI_ARGS_workspace
devsecops config validate --strict
devsecops generate
terraform -chdir=terraform init -reconfigure -input=false -no-color \
  -backend-config=../dist/devsecops/backend.hcl
terraform -chdir=terraform workspace select prod
python -m devsecops_cli.cloud_evidence \
  --expected-account-id "${EXPECTED_AWS_ACCOUNT_ID}" --directory "${EVIDENCE_DIR}"
devsecops status --deep --strict --format json > "${EVIDENCE_DIR}/readiness.json"
devsecops aws outputs --environment prod --format json > "${EVIDENCE_DIR}/aws-outputs.json"
devsecops doctor aws --environment prod --strict --format json > "${EVIDENCE_DIR}/aws-doctor.json"
```

The collector reads only the initialized backend metadata, selected workspace,
STS identity, Terraform outputs and `lambda get-function`. It refuses a backend
that differs from local config, a workspace other than `prod`, a different AWS
account, or a live Lambda ARN/digest that disagrees with the outputs. It records
only backend identifiers, never backend credentials or the full state file.
`terraform-context.json` and `active-lambda-image.txt` must stay with these
outputs. The release evidence gate validates their agreement too.

The evidence should prove:

* active environment is `prod`;
* Lambda function state is `Active`;
* Lambda `LastUpdateStatus` is `Successful`;
* API Gateway invoke and health URLs are present;
* CloudWatch log group exists;
* active Lambda image matches the configured immutable image.

## 6. Prove Health And Logs

Extract the health URL from Terraform output and validate it through the CLI.
Read the deployed authorization mode from Terraform outputs: `AWS_IAM` checks
use SigV4 and explicitly public `NONE` APIs use an unsigned request. Both checks
require 2xx and reject redirects. The curl request has a 5-second connect
timeout and a 20-second total timeout:

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

AWS_REGION="$(python -c 'import json,os; from pathlib import Path; print(json.loads((Path(os.environ["EVIDENCE_DIR"])/"terraform-context.json").read_text())["aws_region"])')"
export AWS_REGION
AUTH_TYPE="$(python -c 'import json,os; from pathlib import Path; print(json.loads((Path(os.environ["EVIDENCE_DIR"])/"terraform-output.json").read_text())["api_gateway_authorization_type"]["value"])')"
health_args=(--timeout 20 --format json)
curl_args=(--silent --show-error --proto '=https' --connect-timeout 5 --max-time 20)
case "${AUTH_TYPE}" in
  AWS_IAM)
    health_args+=(--aws-sigv4 --aws-region "${AWS_REGION}")
    curl_args+=(--aws-sigv4 "aws:amz:${AWS_REGION}:execute-api" \
      --user "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}")
    if [ -n "${AWS_SESSION_TOKEN:-}" ]; then
      curl_args+=(-H "x-amz-security-token: ${AWS_SESSION_TOKEN}")
    fi ;;
  NONE) ;;
  *) printf 'Unexpected API authorization mode: %s\n' "${AUTH_TYPE}" >&2; exit 1 ;;
esac
rm -f "${EVIDENCE_DIR}/health-status.txt"
devsecops health --url "${HEALTH_URL}" "${health_args[@]}" > "${EVIDENCE_DIR}/health.json"
http_status="$(curl "${curl_args[@]}" \
  --output "${EVIDENCE_DIR}/health-response.txt" --write-out '%{http_code}' "${HEALTH_URL}")"
printf '%s\n' "${http_status}" > "${EVIDENCE_DIR}/health-status.txt"
case "${http_status}" in
  2[0-9][0-9]) cat "${EVIDENCE_DIR}/health-response.txt" ;;
  *) printf 'Health failed: HTTP %s\n' "${http_status}" >&2; exit 1 ;;
esac
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

The collector in section 5 already saved the currently active image from
`lambda get-function` → `Code.ResolvedImageUri` in `active-lambda-image.txt`
and checked it against Terraform. `get-function-configuration` does not return
this `Code` field. Preserve this snapshot from the successful deployment before
starting rollback drills; do not overwrite it with a later rollback's image.

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

## 8. Prove Supported Platform Compatibility

On a clean supported macOS or Ubuntu host at the same commit, download and verify the
CI candidate as in step 1. Activate a fresh virtual environment and capture
the install and the rest of the walkthrough:

```bash
(
  set -e
  printf 'Release commit: %s\n' "$(git rev-parse HEAD)"
  uname -a
  if [ "$(uname -s)" = Darwin ]; then sw_vers; else cat /etc/os-release; fi
  python -m pip install --no-deps "${CANDIDATE_DIR}/${WHEEL}"
  devsecops --version
  devsecops setup --mode demo --yes --strict
  devsecops completion bash
  PYTHONPATH=cli python -m unittest discover -s cli/tests
) > platform-transcript.txt 2>&1
```

Copy `platform-transcript.txt` into the evidence directory. Windows/WSL2 are
unverified and outside this release target. This transcript proves the recorded
host; attach the exact CI run for the rest of the supported matrix.

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
from devsecops_cli.release_evidence import PRODUCTION_EVIDENCE_REQUIRED_FILES, PLATFORM_EVIDENCE_REQUIRED_FILES

source = Path(os.environ["EVIDENCE_DIR"])
with ZipFile(os.environ["EVIDENCE_ARCHIVE"], "w", ZIP_DEFLATED) as archive:
    for name in PRODUCTION_EVIDENCE_REQUIRED_FILES + PLATFORM_EVIDENCE_REQUIRED_FILES:
        archive.write(source / name, name)
PY
gh release create "evidence-${RELEASE_TAG}" "${EVIDENCE_ARCHIVE}" --repo "${RELEASE_REPOSITORY}" \
  --draft --target "${RELEASE_SHA}" --title "Evidence for ${RELEASE_TAG}" --notes "Private release evidence staging"
```
