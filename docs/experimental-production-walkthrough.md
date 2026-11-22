# Experimental Production Walkthrough

This guide gives a measurable path from a clean install to one production
workflow dispatch. The CLI remains the product surface; Terraform, GitHub
Actions, AWS, and scanners stay visible execution layers.

Production commands in this guide are experimental; runtime protections still
apply. Consult the command contract in [Stability contract](stability-contract.md).

## 1. Install And Run The No-Credentials Guided Demo

Use [Quick Start](../README.md#quick-start) with the matching CLI and checkout.
After `Demo complete`, open the menu or run `devsecops status` to review local
progress. Use `devsecops dry-run --preset student-demo` to preview without a
saved setup.

For a separate production setup, run `devsecops setup --mode production` or
select option `7` in the completed-demo menu. Review any preset replacement
diff. Enter keeps the current config and cancel exits the review. For scripts,
`setup --mode production --yes` stops for review when replacement is needed;
use `--apply-mode-preset` only after reviewing the diff. Production checks
require an explicit `status --pre-deploy --strict` or `status --deep --strict`.

## 2. Start Or Resume Standard Setup

For a guided preflight with an AWS account, GitHub repo and an immutable image,
run `devsecops setup --mode standard`. If interrupted, rerun `devsecops setup`
to resume. For noninteractive input, use `--yes --image-uri URI --backend-bucket BUCKET`.
Repository writes require `--apply-github` or interactive authorization. Setup
checks the actual backend bucket and lock table in the active account.

## 3. Bring Your Own Lambda Image

Read the [image contract and publishing procedure](bring-your-own-image.md).
Use the optional [Text Stats example](../examples/text-stats/README.md) or your
own single-platform Linux `amd64` image. If using the built-in ECR repository,
provision it through the separate registry step in the image guide.

```bash
devsecops image validate --image-uri IMAGE_URI
devsecops config set lambda_image_uri IMAGE_URI
devsecops generate
```

Replace `IMAGE_URI` with your published immutable ECR URI.

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
subject. The plan role trusts only the exact `main` branch subject. All PRs
run without AWS credentials. Optional manual sandbox plans require an isolated
backend and explicit opt-in; see [Manual sandbox plans](sandbox-plans.md).

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
