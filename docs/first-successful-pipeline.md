# First Successful Pipeline

This guide gives a measurable path from a clean install to one production
workflow dispatch. The CLI remains the product surface; Terraform, GitHub
Actions, AWS, and scanners stay visible execution layers.

Every `devsecops` command used in this guide is part of the stable command
contract in [Stability contract](stability-contract.md).

## 1. Install And Run The No-Credentials Guided Demo

Install the latest published CLI release with the commands in
[Distribution and compatibility](distribution.md), then run demo setup. Demo
mode creates local config and runs a no-write dry-run with a clearly marked
sample image URI. It neither queries nor changes AWS or GitHub.

```bash
devsecops --version
devsecops setup --mode demo --yes --strict
```

Expected output includes:

```text
First Successful Pipeline Dry Run
No files changed.
AWS credentials are not required for this dry run.
Files that would be generated
Lambda image shape          OK
Lambda image immutability   OK
Guided Setup Summary
Guided setup complete. No deployment was started.
```

The equivalent standalone preview remains available when you do not want to
create setup progress:

```bash
devsecops dry-run \
  --preset balanced \
  --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

If you only want to preview generated files from an existing config:

```bash
devsecops generate --dry-run
```

Expected output includes:

```text
Dry run only. No files changed.
Deployment File Plan
terraform/generated.auto.tfvars
dist/devsecops/github-setup.sh
```

## 2. Start Or Resume Standard Setup

Switch the saved workflow to standard mode when you have an AWS account,
GitHub repository, and an existing immutable Lambda image. The interactive
flow walks through dependency checks, local config, image, backend, AWS
identity, GitHub/OIDC, dry-run, and summary:

```bash
devsecops setup --mode standard
```

The selected mode and current step are saved in
`.devsecops/setup-state.json`. Press `Ctrl-C`, `b`, `back`, or `0` at a prompt;
the next `devsecops setup` run rechecks observable state and resumes. The state
file is ignored by Git and never stores credentials or token/secret values.

For a non-interactive local-input path:

```bash
devsecops setup --mode standard --yes \
  --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123 \
  --backend-bucket my-devsecops-pipeline-tfstate
devsecops config validate
devsecops config diff
devsecops status
```

Expected output:

```text
Created clean config .devsecops-pipeline.toml
Guided Setup Summary
Next command: devsecops setup
```

`--yes` uses safe local defaults and never authorizes GitHub changes. Add
`--strict` when a partial setup should return a non-zero exit code. A configured
backend name is not treated as ready by itself: setup verifies that the S3
bucket and DynamoDB lock table exist in the active AWS account.

## 3. Bring Your Own Lambda Image

Build a single-platform Linux `amd64` Lambda image outside this repository.
Publish it with an immutable tag or digest to an existing ECR repository,
or publish it after provisioning the built-in repository in step 4.

```bash
devsecops image validate \
  --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

Expected output:

```text
Validate Image
Lambda image URI            OK
Lambda image shape          OK
Lambda image immutability   OK
Lambda image region         OK
```

Then write the image URI into local config and generate the deployment files:

```bash
devsecops config set lambda_image_uri \
  123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
devsecops generate
```

## 4. Configure Terraform Backend

Choose globally unique backend names for your AWS account:

```bash
devsecops config set backend.bucket my-devsecops-pipeline-tfstate
devsecops config set backend.lock_table devsecops-pipeline-terraform-locks
devsecops generate
devsecops terraform bootstrap
```

Review the plan. Apply only after confirming the account and names:

```bash
devsecops terraform bootstrap --apply
```

The CLI generates ignored `dist/devsecops/backend.hcl`. Local plan commands
pass this file to Terraform explicitly. GitHub Actions generates its own copy
from your repository configuration. Leave the tracked `terraform/backend.tf`
template unchanged; your backend names do not need to be committed.

If you use the kit's ECR repository, [provision it and publish the image](bring-your-own-image.md#provision-the-built-in-repository-before-the-first-deploy)
before running the production preflight.

## 5. Configure GitHub Repository Settings

Create separate AWS IAM roles using the [deploy and plan trust policies](../AWS_policy.md#deploy-trust-policy-example)
for your deployment repository. The deploy role trusts the `prod` environment
subject. The plan role trusts the PR subject and the exact branches you allow
for manual plans. The workflow limits AWS-backed PR plans to branches within
the same repository.

In repository Settings > Environments > `prod`, configure at least one
required reviewer, enable **Prevent self-review**, disable administrator
bypass, and allow the exact branch `main` with no tags. Both the CLI and the
production runner verify these settings. Diagnostics fail when the account
plan or token permissions prevent inspecting the rules.

The guided equivalent is explicit about the repository mutation boundary:

```bash
devsecops setup --apply-github \
  --deploy-role-arn arn:aws:iam::123456789012:role/devsecops-pipeline-deploy \
  --plan-role-arn arn:aws:iam::123456789012:role/devsecops-pipeline-plan
```

This writes GitHub repository variables and encrypted secrets only. It does
not run a workflow or change AWS. Role arguments and `--snyk-token`, when used,
are passed directly to `gh` and are never written to setup progress.

The lower-level equivalent remains available for automation and review:

Generate the setup script:

```bash
devsecops github setup --write
```

Apply safe repository variables and provided secrets:

```bash
devsecops github setup --apply --repo <OWNER>/<REPO> \
  --deploy-role-arn arn:aws:iam::123456789012:role/devsecops-pipeline-deploy \
  --plan-role-arn arn:aws:iam::123456789012:role/devsecops-pipeline-plan
```

Expected output includes:

```text
GitHub destination: OWNER/REPO
GitHub setup result for OWNER/REPO
Applied GitHub repository variables/secrets available from config and arguments.
```

This setup also synchronizes `PIPELINE_CONFIG_JSON`: your complete non-secret
configuration, including region, environment runtime settings, CORS, log
retention, and backend names. The cloud workflow requires this variable and
does not silently fall back to template defaults. Run the setup command again
after changing local settings. Never put credentials or tokens in this variable.

If a write fails, the summary lists applied, failed, and unattempted settings.
`PIPELINE_CONFIG_JSON` stays blocked until synchronization completes. Retry
with the same destination and arguments. Configuration-only updates may omit
roles and tokens that are already present in their effective scopes. To change
a role, supply both distinct role ARNs.

The generated helper uses the same CLI behavior. Pass the destination and
setup options when running it from the checkout, for example
`bash dist/devsecops/github-setup.sh OWNER/REPO --deploy-role-arn <arn> --plan-role-arn <arn>`.
Run [OIDC role verification](../AWS_policy.md#verify-role-setup) during final
acceptance. Secret names alone leave OIDC readiness unverified.


```bash
devsecops doctor github --strict
devsecops doctor branch --branch main
```

## 6. Generate, Report, And Review

In a fresh checkout, initialize the workload module for local validation.
The bootstrap command in step 4 already initializes the bootstrap module.

```bash
devsecops generate
terraform -chdir=terraform init -backend=false -input=false
devsecops status --pre-deploy --strict
devsecops report
```

Expected output should either show no scored gaps or point to a concrete next
action and a troubleshooting section:

```text
Fix
Set `LAMBDA_IMAGE_URI` ... See `docs/troubleshooting.md#lambda-image-uri-is-missing-or-invalid`.
```

## 7. Run The Production Workflow Dispatch

Implement `GET /health` and enable it with `devsecops config set enable_http_validation true`.
Regenerate and synchronize the configuration after this change. The production
workflow rejects disabled health validation before requesting AWS credentials.

After CI has passed on `main`, preview the exact production operation. This
runs local, GitHub, branch-protection, image, and concurrent-run checks but
does not dispatch a workflow:

```bash
devsecops deploy prod --dry-run
```

The preview shows the repository, current remote `main` commit, effective
configuration SHA-256, backend, and exact ECR image digest. For both tags and
digests, the CLI uses local AWS credentials to verify the manifest,
Linux `amd64` platform, and ECR pull access. The runner repeats these checks
under the deploy role before initializing Terraform.

Then confirm the pinned inputs and dispatch the protected workflow:

```bash
devsecops deploy prod
devsecops deploy status --watch
```

For a direct GitHub UI launch, select `mode=deploy`, `environment=prod`, and
branch `main`. Copy the reviewed `image_uri`,
`commit_sha`, and `config_sha256` from the preview's `gh workflow run` command.
Review the same values in the run summary before approving `prod`. If GitHub
reports that the commit or settings changed, run the preview again. The
approved deploy creates and applies one saved Terraform plan. Standalone plan
runs remain previews.

After completion, the CLI verifies that the production job and its apply and
health steps succeeded. A skipped job or operation returns an error even if
GitHub reports the overall workflow as successful.

The CLI refuses to overlap an active production run and records non-secret
intent and run metadata in `.devsecops/deployments.json`. Use `--yes` only for
already reviewed non-interactive execution.
Use a CLI and a deployed workflow revision that both support these dispatch
inputs when upgrading an existing deployment repository.

The Deploy menu offers the same preflight and confirmation flow, plus separate
preview options; you can complete deployment and rollback without exiting it.

Expected successful outcome:

```text
Production Deployment Status
Operation: deploy
Status: completed
Conclusion: success
```

Inspect a failure without finding the Actions run ID manually:

```bash
devsecops deploy logs --failed
```

If a successful deployment must be reversed, preview and dispatch the previous
image through the same protected GitHub Environment, OIDC role, validation,
and Terraform state. The CLI reads the recovery artifact from the successful
deployment attempt and verifies the active digest. The runner verifies the
digest and Lambda ARN again after entering the production queue.

```bash
devsecops deploy rollback --dry-run
devsecops deploy rollback
devsecops deploy status --watch
```

Use `--run-id` to select a successful deployment when the local journal is
unavailable. If the run predates recovery artifacts, the artifact expired, or
the deployment failed, pass a reviewed immutable target explicitly with
`devsecops deploy rollback --image-uri <immutable-ecr-image-uri>`.

After success, inspect AWS resources:

```bash
devsecops doctor aws --environment prod
```

Expected deployed resources include the Lambda function, API Gateway, log
group, and configured ECR image.

For a release-ready evidence bundle after this succeeds, follow
[Production deployment evidence](production-deployment-evidence.md), then collect
local release-candidate evidence:

```bash
devsecops evidence collect --rc
```
