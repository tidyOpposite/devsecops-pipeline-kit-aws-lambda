# Production Deployment Evidence

Use this guide when proving a production deployment against a real AWS account
and GitHub repository. The goal is to produce a reviewable evidence bundle that
can be attached to a release record without requiring reviewers to inspect the
source tree.

Do not mark a release or roadmap item as production-proven until this workflow
has been run against the intended AWS account, GitHub repository, immutable
Lambda image, and protected `main` branch.

## Evidence Bundle

Store live evidence outside Git because `dist/` is ignored:

```bash
export RELEASE_TAG="${RELEASE_TAG:-v0.14.0}"
export EVIDENCE_ROOT="${EVIDENCE_ROOT:-dist/devsecops/production-evidence}"
export EVIDENCE_DIR="${EVIDENCE_DIR:-${EVIDENCE_ROOT}/${RELEASE_TAG}}"

mkdir -p "${EVIDENCE_DIR}/workflow-artifacts"
```

The final bundle should contain:

| Evidence | File |
| --- | --- |
| Release install and checksum proof | `release-install.txt`, `release-checksums.txt` |
| Local config and strict validation | `config.json`, `config-validate.json` |
| Rendered/audit evidence | `readiness-report.md`, `audit-report.json`, generated helper artifacts |
| GitHub setup and branch protection | `github-doctor.json`, `branch-doctor.json` |
| Workflow dispatch and run result | `workflow-run.json`, `github-status.json`, `workflow-artifacts/` |
| Terraform deployed outputs | `terraform-output.json` |
| AWS live resource outputs | `aws-outputs.json`, `aws-doctor.json` |
| Health and API verification | `health.json`, `health-response.txt` |
| CloudWatch log proof | `cloudwatch-log-groups.json`, `cloudwatch-tail.txt` |
| Rollback readiness proof | `active-lambda-image.txt`, workflow log references |

## Prerequisites

Complete these before dispatching production:

* Install a verified release package. For `v0.14.0`, use the release wheel and
  `SHA256SUMS` once published.
* Use a real GitHub repository with `main` protected by pull requests and the
  required `Security and Terraform Validate` and `Terraform Plan` checks.
* Configure the protected production GitHub Environment named by
  `PROD_APPROVAL_ENVIRONMENT`, normally `prod`.
* Configure separate GitHub OIDC roles:
  `AWS_PLAN_ROLE_TO_ASSUME_ARN` for plans and `AWS_ROLE_TO_ASSUME_ARN` for
  approved production deploys.
* Configure an S3 backend bucket and DynamoDB lock table in the target AWS
  account.
* Publish a Lambda-compatible immutable ECR image before workflow dispatch.
  Use a digest or immutable tag, never `latest` or `bootstrap`.
* If `ENABLE_HTTP_VALIDATION=true`, make sure the workload implements
  `GET /health`.
* If `ENABLE_DAST=true`, set `API_AUTHORIZATION_TYPE=NONE` only when the public
  API can tolerate a passive OWASP ZAP baseline scan.

## 1. Prove Release Install

Capture the installed CLI version and release artifact verification:

```bash
devsecops --version | tee "${EVIDENCE_DIR}/release-install.txt"

VERSION="${RELEASE_TAG#v}"
BASE_URL="https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/releases/download/${RELEASE_TAG}"
WHEEL="devsecops_pipeline_cli-${VERSION}-py3-none-any.whl"

curl -fsSLo "${EVIDENCE_DIR}/SHA256SUMS" "${BASE_URL}/SHA256SUMS"
curl -fsSLo "${EVIDENCE_DIR}/${WHEEL}" "${BASE_URL}/${WHEEL}"
grep " ${WHEEL}$" "${EVIDENCE_DIR}/SHA256SUMS" > "${EVIDENCE_DIR}/${WHEEL}.SHA256SUMS"
(
  cd "${EVIDENCE_DIR}"
  shasum -a 256 -c "${WHEEL}.SHA256SUMS"
) | tee "${EVIDENCE_DIR}/release-checksums.txt"
```

For local pre-release validation, replace the download commands with the local
build and checksum commands from [Release checklist](release-checklist.md).

## 2. Prove Local Configuration

Create or inspect the source config, validate it strictly, generate helper
artifacts, and export both Markdown and JSON evidence:

```bash
devsecops config show --format json > "${EVIDENCE_DIR}/config.json"
devsecops config validate --strict --format json > "${EVIDENCE_DIR}/config-validate.json"
devsecops generate
devsecops status --strict --format json > "${EVIDENCE_DIR}/readiness.json"
devsecops report --output "${EVIDENCE_DIR}/readiness-report.md"
devsecops report --format json --output "${EVIDENCE_DIR}/audit-report.json"

cp terraform/generated.auto.tfvars "${EVIDENCE_DIR}/terraform-generated.auto.tfvars"
cp dist/devsecops/github-setup.sh "${EVIDENCE_DIR}/github-setup.sh"
cp dist/devsecops/github-variables.env "${EVIDENCE_DIR}/github-variables.env"
cp dist/devsecops/setup-checklist.md "${EVIDENCE_DIR}/setup-checklist.md"
```

The strict config and readiness commands must exit `0` before production
dispatch.

## 3. Prove GitHub Setup

Capture repository variables, secrets readiness, branch protection, and recent
workflow state:

```bash
devsecops github setup --write
devsecops doctor github --format json > "${EVIDENCE_DIR}/github-doctor.json"
devsecops doctor branch --branch main --format json > "${EVIDENCE_DIR}/branch-doctor.json"
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
devsecops deploy status --format json > "${EVIDENCE_DIR}/workflow-run.json"
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

* `Require Lambda image URI`
* `Capture currently deployed Lambda image`
* `Terraform apply workload with configured Lambda image`
* `Read deployment outputs`
* `Wait for Lambda update`
* `Smoke test Lambda health endpoint`, when HTTP validation is enabled
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
aws lambda get-function-configuration \
  --function-name "${LAMBDA_FUNCTION}" \
  --query 'Code.ImageUri' \
  --output text > "${EVIDENCE_DIR}/active-lambda-image.txt"
```

Review the workflow log to confirm that `Capture currently deployed Lambda
image` ran before `Terraform apply workload with configured Lambda image`. If a
validation step fails during a later deployment, use
[Failed deployment rollback](runbooks/failed-rollback.md) and attach the failed
run logs to the same evidence bundle.

## Post-Deploy Checklist

Before accepting the production proof, confirm:

* Release artifact checksum verification passed.
* `devsecops config validate --strict` passed.
* `devsecops status --strict` passed before dispatch.
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
devsecops criteria --strict --evidence-dir "${EVIDENCE_DIR}"
devsecops criteria --format json --evidence-dir "${EVIDENCE_DIR}" > "${EVIDENCE_DIR}/criteria.json"
```

The strict command must exit `0` before a stable tag is cut. If it fails, the
output names the missing file or criterion and the next action to take.
