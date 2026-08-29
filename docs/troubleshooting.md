# Troubleshooting Guide

Start with the CLI. It is the primary troubleshooting surface for this project;
Terraform, GitHub Actions, AWS, and scanner commands are the execution layer
behind the CLI.

## Start Here

Run:

```bash
devsecops status
devsecops setup --preset balanced
devsecops status
devsecops status --watch --interval 10
devsecops tui
devsecops status
devsecops status --strict --format compact
devsecops doctor
devsecops doctor --deep
devsecops github status --format compact
devsecops aws outputs --environment prod
devsecops health --aws-sigv4
```

Use `[i] details` from the main menu or `devsecops status` to see only the
checks that block 100% readiness and the concrete fix for each one. Use
`devsecops doctor` when you need the full local check list. Project status
groups readiness into Local, Terraform, GitHub, AWS, Security, and Deployment
scores.

Use `devsecops criteria --strict` when preparing a stable release. It checks
every Version 1.0 criterion plus the external production and WSL2 evidence
gates, then prints the next missing artifact or command.

`devsecops tui` uses optional Rich/Textual dependencies. Without them, it falls
back to compact status. For a published install, add the dependencies
with `python3.11 -m pipx inject devsecops-pipeline-cli "rich>=13.7" "textual>=0.79"`.
For development from a local checkout, use
`PYTHON="${PYTHON:-python3.11}"` and `"${PYTHON}" -m pip install -e ".[tui]"`.

Generate a shareable report:

```bash
devsecops report --deep
```

The report is written to `dist/devsecops/readiness-report.md`.

## CLI Installation And Navigation

### `devsecops` command is not found

Install the latest published CLI release with the commands in
[Distribution and compatibility](distribution.md), then confirm the console
command is available:

```bash
devsecops --version
devsecops menu
```

For development from a local checkout, install it in editable mode:

```bash
PYTHON="${PYTHON:-python3.11}"
"${PYTHON}" -m pip install -e .
devsecops menu
```

Without installing, run the package module from the repository:

```bash
PYTHON="${PYTHON:-python3.11}"
PYTHONPATH=cli "${PYTHON}" -m devsecops_cli menu
```

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

Inspect snapshots:

```bash
devsecops snapshots
devsecops snapshots --show 1
```

Preview and apply rollback:

```bash
devsecops rollback --last --dry-run
devsecops rollback --to <number-or-id>
```

Rollback restores only CLI-owned local files such as `.devsecops-pipeline.toml`,
`terraform/generated.auto.tfvars`, and generated files under `dist/devsecops/`.
It does not change AWS Lambda, Terraform state, GitHub Actions, or deployed
traffic. For cloud rollback diagnostics, use
[`failed-rollback`](runbooks/failed-rollback.md).

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

Readiness expects the tracked Terraform module and GitHub workflow files to be
present:

```text
terraform/main.tf
terraform/modules/lambda/main.tf
.github/workflows/deploy.yml
```

Restore those files from the repository before running `devsecops generate`,
Terraform plans, or production workflow dispatch.

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

Set a real backend bucket through the CLI and generate deployment files:

```bash
devsecops config set backend.bucket my-state-bucket --generate
devsecops status
```

Then plan or apply the bootstrap stack:

```bash
devsecops bootstrap
devsecops bootstrap --apply
```

`devsecops bootstrap` runs a Terraform plan by default. Use
`devsecops bootstrap --apply` only when the target AWS account and backend
names are correct.

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

Run:

```bash
devsecops github-setup --write
```

Review `dist/devsecops/github-setup.sh` before running it. It contains
placeholder values for role ARNs and optional secrets.

### GitHub doctor cannot inspect the repository

Install and authenticate GitHub CLI:

```bash
gh auth login
devsecops gh-doctor
```

`devsecops gh-doctor` checks repository variables and secret names, but it
never prints secret values.

### GitHub repository variables or secrets are missing

Generate and review setup commands:

```bash
devsecops github setup --write
```

Apply repository variables and provided secrets:

```bash
devsecops github setup --apply \
  --deploy-role-arn arn:aws:iam::<account-id>:role/<deploy-role> \
  --plan-role-arn arn:aws:iam::<account-id>:role/<plan-role>
```

Then verify:

```bash
devsecops doctor github --strict
```

### Branch protection doctor reports missing checks

Run:

```bash
devsecops branch-doctor
```

The expected required checks are:

* `Security and Terraform Validate`
* `Terraform Plan`

Configure them in the GitHub branch protection settings for `main` after the
checks have run at least once.

### Actions status cannot show workflow runs

Run:

```bash
gh auth login
gh run list
devsecops actions-status
```

`actions-status` uses `gh run list` and, for failed runs, `gh run view` to show
failed job names, failed step names, next actions, and runbook links. For a
failed deployment, start with:

```bash
devsecops github status --format compact --strict
gh run view <run-id> --log-failed
```

Common runbooks:

* [Failed Terraform plan](runbooks/failed-terraform-plan.md)
* [Failed Terraform apply](runbooks/failed-terraform-apply.md)
* [Failed validation](runbooks/failed-validation.md)
* [Missing Lambda image](runbooks/missing-image.md)
* [Failed deployment rollback](runbooks/failed-rollback.md)

## AWS Diagnostics

### Check AWS account and deployed resources

Run:

```bash
devsecops aws-doctor --environment prod
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
devsecops aws-doctor --environment prod --strict
```

### AWS Doctor cannot inspect resources

Install and configure AWS CLI:

```bash
aws sts get-caller-identity
devsecops aws-doctor --environment prod
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
* For deploys, `sub` should include `repo:<owner>/<repo>:ref:refs/heads/main`.
* For PR plans, use `AWS_PLAN_ROLE_TO_ASSUME_ARN`; plan workflows do not fall
  back to the deploy role.
* Pull requests from forks intentionally do not run AWS-backed plans.
* Confirm the workflow has `permissions: id-token: write`.

Then re-run:

```bash
devsecops gh-doctor
devsecops branch-doctor
```

### PR plan cannot access Terraform backend

The plan role needs S3 access to the state bucket and DynamoDB access to the
lock table. It also needs read permissions for resources Terraform refreshes.
Use `AWS_policy.md` as the IAM review guide, then re-run the failing workflow.

If the pull request comes from a fork, the AWS-backed Terraform plan job is
skipped by design. Run the plan from a trusted branch or use a reviewed manual
`workflow_dispatch` plan.

## Terraform Backend

### `S3 bucket does not exist`

Prefer the CLI bootstrap flow:

```bash
devsecops config set backend.bucket <globally-unique-state-bucket> --generate
devsecops bootstrap --apply
```

Manual fallback:

```bash
cd terraform/bootstrap
terraform init
terraform apply -var="state_bucket_name=<globally-unique-state-bucket>"
```

Then copy or adapt `dist/devsecops/backend.tf` into `terraform/backend.tf`.

### `Error acquiring the state lock`

Another Terraform run may be active. Check:

```bash
devsecops actions-status
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
devsecops gh-doctor
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

Health validation is optional and runs only when
`ENABLE_HTTP_VALIDATION=true`. If enabled, verify:

* The workload image handles API Gateway HTTP API events.
* `GET /health` returns a successful HTTP response.
* CloudWatch Logs for the Lambda function do not show handler, permission, or
  environment errors.
* The Lambda execution role has the AWS permissions required by the workload.

Run the same check outside GitHub Actions:

```bash
devsecops health --url <health-url> --aws-sigv4
devsecops health --aws-sigv4
```

Then follow [failed validation](runbooks/failed-validation.md) if the endpoint
still returns a non-success response.

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
