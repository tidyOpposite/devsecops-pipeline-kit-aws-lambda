# Troubleshooting Guide

Start with the command for the workflow you are actually using:

```bash
devsecops status                  # Local demo/configuration
devsecops doctor local --deep     # Local tools and Terraform
devsecops lab status NAME         # Live single-operator dev lab
```

Use `devsecops lab logs NAME` for workload events. Inspect the evidence path
returned by a failed lab command before creating a new plan. Do not discard
local state to recover from an AWS error. For retained data and deletion, use
[Finish demo / decommission](runbooks/finish-demo.md).

For the **experimental production path**, use
`status --pre-deploy --strict` before first deployment, `status --deep --strict`
for live workload verification, and `deploy status` / `deploy logs` for its
GitHub run. Its GitHub/backend diagnostics below do not describe lab readiness.

Human-readable output includes a recommended next command. `[i]` opens details
inside the menu; it is not a key handled by standalone status output. Closed
input exits the menu or pauses setup with code `0`; other interactive prompts
cancel with `130` without accepting defaults. Re-run setup to resume.

For release acceptance, `criteria --strict` verifies a scoped lab bundle and
both platform transcripts; production proof uses `--scope production`.
The optional TUI falls back to compact status if Rich/Textual are unavailable.

## CLI Installation And Navigation

### `devsecops` command is not found

Install the matching CLI and checkout using [Distribution](distribution.md).
Activate the venv or add the installer's bin directory to your PATH, then run
`devsecops --version` and `devsecops menu`.

From an existing checkout with a supported Python, you can also run
`PYTHONPATH=cli python3 -m devsecops_cli menu`.

### I entered a menu section by mistake

Input sections can be cancelled with `b`, `back`, `0`, or `cancel`. In the
configuration wizard, cancellation returns to the main menu without saving.

### Guided setup was interrupted or resumes at an unexpected step

Rerun the same command without deleting config:

```bash
devsecops setup
```

Setup progress is stored in `.devsecops/setup-state.json`. The CLI rechecks
dependencies, config, image, AWS identity, and GitHub on every run, so a stage
can become incomplete again when real state changes. In particular, changing
config invalidates the saved dry-run result. `b`, `back`, `0`, and `Ctrl-C`
leave enough progress to resume.

Inspect the file only for diagnosis; it must not contain credentials or token
values. If the CLI reports `Setup state error`, preserve the invalid file for
inspection and start with a new state file:

```bash
mv .devsecops/setup-state.json .devsecops/setup-state.invalid.json
devsecops setup
```

Moving this file discards only the resume cursor. It does not remove local
config, generated files, GitHub settings, Terraform state, or AWS resources.

### I changed local config and want to undo it

Use `devsecops snapshot list`, then inspect a saved version with
`devsecops snapshot show 1`. Run `devsecops snapshot restore --last --dry-run`
to review changes before applying `devsecops snapshot restore --last`.

Use the [rollback runbook](runbooks/failed-rollback.md) for a failed cloud
rollback. Local snapshots cover CLI-owned files such as config and generated inputs.

## CLI Configuration

### Local config is missing

Create a clean local source config:

```bash
devsecops setup --preset balanced --yes
devsecops config validate
```

For a no-write preview first:

```bash
devsecops dry-run --preset balanced
```

### Project files are missing

Use the matching checkout from [Quick Start](../README.md#quick-start). Check
for `terraform/main.tf`, `terraform/modules/lambda/main.tf` and
`.github/workflows/deploy.yml`. Restore missing source files before generating
inputs or planning.

The CLI finds the checkout from its subdirectories. A nearer config or a
nested Git repository defines its own project boundary. Enter the intended
checkout if you are in an incomplete nested project.

### Config validation fails

Run config validation and fix the reported key:

```bash
devsecops config validate
devsecops config show --format toml
devsecops config set <key> <value>
```

Then rerun:

```bash
devsecops config validate
devsecops generate --dry-run
```

### Status says backend bucket is missing

For experimental production, follow the [backend procedure](experimental-production-walkthrough.md#4-configure-terraform-backend).
Confirm the AWS account, region and names before planning or applying the
bootstrap stack. The [dev lab](single-operator-lab.md) uses local state.

### Lambda image URI is missing or invalid

Set an immutable Lambda container image:

```bash
devsecops image validate --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-a1b2c3
devsecops config set lambda_image_uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-a1b2c3 --generate
devsecops status
```

The production workflow rejects `latest` and `bootstrap` because rollback and
auditability depend on stable image identity.

If image validation reports a region mismatch, publish or select an image in the same
region as `aws_region`, then rerun:

```bash
devsecops image validate --image-uri <immutable-ecr-image-uri>
```

See [Bring your own Lambda image](bring-your-own-image.md) for the image
contract.

### Update one setting without rerunning the wizard

Use `devsecops config set` with a dotted config key:

```bash
devsecops config set backend.bucket my-state-bucket --generate
devsecops config set enable_dast true
devsecops config set environments.prod.lambda_memory_size 2048
devsecops config validate
```

### Rebuild config and generated outputs from controls

Run the composer when policy toggles drift across local config and GitHub
helpers:

```bash
devsecops compose
```

It updates `.devsecops-pipeline.toml`, generates Terraform/GitHub helper
artifacts, and rewrites `dist/devsecops/readiness-report.md`.

### Generated files look stale

Generate them again:

```bash
devsecops generate
devsecops status
```

Generated files are intentionally ignored by Git. They are local bridge files
between the CLI and Terraform/GitHub setup.

## GitHub Diagnostics

### Generate GitHub setup commands

Run `devsecops github setup --write` and review `dist/devsecops/github-setup.sh`.
See [repository settings](experimental-production-walkthrough.md#5-configure-github-repository-settings)
for role inputs, explicit apply and post-apply checks.

### GitHub doctor cannot inspect the repository

Install [GitHub CLI](https://cli.github.com/), then authenticate it:

```bash
gh auth login
devsecops doctor github
```

`devsecops doctor github` checks repository variables and secret names, but it
never prints secret values.

### GitHub repository variables or secrets are missing

Run `devsecops doctor github --strict` to identify missing settings. Follow
the [repository setup procedure](experimental-production-walkthrough.md#5-configure-github-repository-settings)
to review and apply the required inputs.

### Branch protection doctor reports missing checks

Run:

```bash
devsecops doctor branch
```

The expected required checks are:

* `Security and Terraform Validate`
* `Terraform Format and Validate`

Configure them in the GitHub branch protection settings for `main` after the
checks have run at least once.
Remove the previous `Terraform Plan` requirement; AWS-backed sandbox plans are
manual and cannot satisfy a PR merge requirement.

### Actions status cannot show workflow runs

Run:

```bash
gh auth login
gh run list
devsecops doctor actions
```

`doctor actions` uses `gh run list` and, for failed runs, `gh run view` to show
failed job names, failed step names, next actions, and runbook links. For a
failed deployment, start with:

```bash
devsecops deploy status
devsecops deploy logs --failed
```

Common runbooks:

* [Failed Terraform plan](runbooks/failed-terraform-plan.md)
* [Failed Terraform apply](runbooks/failed-terraform-apply.md)
* [Failed validation](runbooks/failed-validation.md)
* [Missing Lambda image](runbooks/missing-image.md)
* [Failed deployment rollback](runbooks/failed-rollback.md)

### Deployment command cannot find a run or rollback target

`devsecops deploy status`, `logs`, and `rollback` first use an explicit
`--run-id`, then the ignored `.devsecops/deployments.json` journal. If a
dispatch has no confirmed run, the CLI searches for the unique request ID in
the workflow title. Retry `devsecops deploy status --watch` to follow that
request before dispatching again.

If the journal came from another workstation or was intentionally removed:

```bash
devsecops deploy status --run-id <github-actions-run-id>
devsecops deploy logs --run-id <github-actions-run-id> --failed
devsecops deploy rollback --run-id <successful-deployment-run-id> --dry-run
devsecops deploy rollback --image-uri <known-good-immutable-ecr-image-uri> --dry-run
```

Do not reconstruct or guess an image URI from logs. Confirm the digest or
immutable tag in ECR and review the current image shown by `devsecops aws
outputs --environment prod`.

### Deployment command reports an active production run

Deploy and rollback share one non-cancelling production concurrency lane.
Wait for the active run and inspect it before starting another state mutation:

```bash
devsecops deploy status --watch
devsecops deploy logs --failed
```

If the run is genuinely stuck, cancel it in GitHub Actions after reviewing its
current Terraform/Lambda step, then rerun deployment preflight. The CLI does
not automatically cancel or replace protected production runs.

## AWS Diagnostics

### Check AWS account and deployed resources

Run:

```bash
devsecops doctor aws --environment prod
devsecops aws outputs --environment prod
```

AWS Doctor checks:

* AWS CLI installation and `sts get-caller-identity`;
* Terraform backend S3 bucket;
* DynamoDB lock table;
* ECR repository for the selected environment;
* Lambda execution IAM role;
* Lambda function;
* API Gateway HTTP API;
* Lambda CloudWatch log group;
* configured `lambda_image_uri` existence when it points to ECR.

Before the first deploy, ECR, Lambda execution role, Lambda, API Gateway, and
log group checks can return `WARN not deployed yet`. That is expected. Fix
identity/backend warnings first, then run the manual deploy flow.

Use `--strict` when AWS Doctor runs in automation and any scored warning should
fail the command:

```bash
devsecops doctor aws --environment prod --strict
```

### AWS Doctor cannot inspect resources

Install and configure AWS CLI:

```bash
aws sts get-caller-identity
devsecops doctor aws --environment prod
```

If identity works but resource checks fail, confirm `aws_region`,
`backend.region`, and the selected `--environment` match the account where the
pipeline was deployed.

### Inspect deployed Lambda and API Gateway outputs

Run:

```bash
devsecops aws outputs --environment prod
devsecops aws outputs --environment prod --format json
```

This is read-only. It reports the expected Lambda function name, current Lambda
state, deployed image URI when AWS exposes it, API Gateway invoke URL,
`/health` URL, and CloudWatch log group details.

## Terraform Diagnostics

### Terraform CLI is not found

Install Terraform and confirm it is on `PATH`:

```bash
terraform version
devsecops doctor local --format compact
```

### Terraform validation fails

Run the same local validation command used by the CLI and CI:

```bash
terraform -chdir=terraform init -backend=false -input=false -no-color
terraform -chdir=terraform validate -no-color
```

Fix the reported Terraform file, then rerun:

```bash
devsecops doctor local --deep --format compact
```

For workflow failures, use the
[failed validation runbook](runbooks/failed-validation.md).

### Terraform plan fails

Start with:

```bash
devsecops github status --format compact
devsecops terraform plan prod --create-workspace
```

Then follow [failed Terraform plan](runbooks/failed-terraform-plan.md).

### Terraform apply fails

Start with:

```bash
devsecops github status --format compact
devsecops aws outputs --environment prod
```

Then follow [failed Terraform apply](runbooks/failed-terraform-apply.md).

## Git Diagnostics

### Git or branch readiness fails

Production deploy workflow dispatch must run from `main`:

```bash
git branch --show-current
git switch main
devsecops status
```

## GitHub OIDC

### `Not authorized to perform sts:AssumeRoleWithWebIdentity`

Check the IAM role trust policy:

* `token.actions.githubusercontent.com:aud` must equal `sts.amazonaws.com`.
* Deploy/rollback uses the protected `prod` environment subject:
  `repo:<owner>/<repo>:environment:prod`.
* The sandbox plan role trusts only `repo:<owner>/<repo>:ref:refs/heads/main`
  (or the repository's corresponding immutable subject), without PR subjects
  or branch wildcards. It never falls back to the deploy role.
* All PRs intentionally run without AWS credentials, including internal branches.
* Confirm the workflow has `permissions: id-token: write`.

Then re-run:

```bash
devsecops doctor github
devsecops doctor branch
```

### Manual sandbox plan cannot access Terraform backend

Set `ENABLE_AWS_PLAN=true` and a valid `PLAN_BACKEND_JSON` in the deployment
repository, with a bucket and lock table different from the deployment backend.
The plan role needs access to those sandbox resources and their KMS key, not
production state. Dispatch `mode=plan`, `environment=dev` from `main` only.
See [Manual sandbox plans](sandbox-plans.md) and [IAM guidance](../AWS_policy.md).
PRs require neither AWS secrets nor a configured backend.

## Terraform Backend

### `S3 bucket does not exist`

Confirm the account, backend region and bucket name. Use the
[backend setup procedure](experimental-production-walkthrough.md#4-configure-terraform-backend)
to review the bootstrap plan before creating backend resources. Use the
generated `dist/devsecops/backend.hcl` through the CLI's Terraform wrapper.

### `Error acquiring the state lock`

Another Terraform run may be active. Check:

```bash
devsecops doctor actions
```

Then inspect GitHub Actions concurrency and the DynamoDB item in the lock table.
Only use `terraform force-unlock` after confirming no apply is running.

### Wrong environment is planned

Use the CLI plan wrapper:

```bash
devsecops plan dev --create-workspace
```

Manual fallback:

```bash
terraform -chdir=terraform workspace show
terraform -chdir=terraform workspace select dev
```

The root module rejects unsupported workspaces. Valid values are `dev`,
`staging`, and `prod`.

## Lambda Image Deployment

### Deploy fails because `LAMBDA_IMAGE_URI` is empty

Set the value through the CLI, render, then apply GitHub setup:

```bash
devsecops config set lambda_image_uri <immutable-image-uri> --generate
devsecops gh-setup --apply \
  --deploy-role-arn <deploy-role-arn> \
  --plan-role-arn <plan-role-arn>
devsecops doctor github
```

### Lambda image does not exist

Publish the workload image before the production deploy workflow runs. If you
use the ECR repository created by this Terraform stack, create the repository
first with a plan/apply or publish the image from an upstream workflow after ECR
exists.

Run:

```bash
devsecops image validate --image-uri <immutable-ecr-image-uri>
devsecops aws outputs --environment prod
```

Then follow [missing Lambda image](runbooks/missing-image.md).

### Snyk cannot scan a private ECR image

Confirm the deploy role can call `ecr:GetAuthorizationToken`,
`ecr:BatchGetImage`, `ecr:BatchCheckLayerAvailability`, and
`ecr:GetDownloadUrlForLayer` for the repository. Also confirm the image URI
points to the same account or to a registry the runner can authenticate to.

### Rollback did not run

Pipeline rollback requires an existing previous Lambda image URI. On the first
ever deployment there is nothing to roll back to. This is separate from CLI
snapshot rollback, which only restores local CLI-owned files.

Use [failed deployment rollback](runbooks/failed-rollback.md) when the workflow
attempted rollback but the deployed Lambda image still looks wrong.

### Health check returns 500

The production deployment workflow requires a successful `GET /health`.
Check that the Lambda handles API Gateway HTTP API events and inspect
CloudWatch for handler, permission or configuration errors. Verify the same
endpoint with `devsecops health --url HEALTH_URL --aws-sigv4` for an IAM API.
Follow the [failed-validation runbook](runbooks/failed-validation.md) if the
endpoint still fails.

## Scanners

### Snyk steps are skipped

Set `SNYK_TOKEN` in repository secrets. Without it, Terraform validate and
Trivy still run.

### Trivy flags an IaC finding

Review whether the finding is a real infrastructure risk. If a suppression is
needed, keep it scoped to the specific resource and document the accepted risk
in code or `SECURITY.md`.

### OWASP ZAP fails deploy validation

Review the generated `zap-baseline-prod` artifact. Warnings are reported but do
not fail the job by default. Fail-level findings should be triaged before
rerunning the deployment.

## Lambda concurrency is insufficient

`doctor aws` and `status --pre-deploy --strict` report **Lambda concurrency**
with account quota, unreserved capacity and the selected function's current
reservation. AWS requires 100 executions to remain unreserved when allocating
reservations. Thus a fresh account with a quota of 10 cannot simply reserve
10, or even 1. Missing `GetAccountSettings`/`GetFunctionConcurrency` permissions,
expired sessions or inconsistent responses fail the check rather than assuming
capacity is available. Recheck with the intended AWS profile and region.

For production, arrange adequate quota and keep the positive reservation;
the protected runner repeats the check under its actual AWS role. Local profile
success does not prove that role's permissions/account. Do not disable approval
or use the lab as production acceptance.

For the separate single-operator dev lab, explicitly choose
`devsecops lab concurrency NAME --mode unreserved`, then run `lab status NAME`
and create a new plan. This uses the finite shared account quota, without a
dedicated function cap or guaranteed capacity. No AWS change occurs until a
new saved plan is reviewed and applied. See [lab guide](single-operator-lab.md).
