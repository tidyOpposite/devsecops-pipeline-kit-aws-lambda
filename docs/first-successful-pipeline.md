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

Build and publish the Lambda workload image outside this repository. The image
must be an AWS Lambda-compatible container image in ECR and must use an
immutable tag or digest.

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

Copy or adapt the reviewed backend block from `dist/devsecops/backend.tf` into
`terraform/backend.tf`, then open a pull request so CI can validate it.

## 5. Configure GitHub Repository Settings

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
devsecops github setup --apply \
  --deploy-role-arn arn:aws:iam::123456789012:role/devsecops-pipeline-deploy \
  --plan-role-arn arn:aws:iam::123456789012:role/devsecops-pipeline-plan
```

Expected output includes:

```text
Applied GitHub repository variables/secrets available from config and arguments.
```

Then check GitHub readiness:

```bash
devsecops doctor github --strict
devsecops doctor branch --branch main
```

## 6. Generate, Report, And Review

```bash
devsecops generate
devsecops status
devsecops report
```

Expected output should either show no scored gaps or point to a concrete next
action and a troubleshooting section:

```text
Fix
Set `LAMBDA_IMAGE_URI` ... See `docs/troubleshooting.md#lambda-image-uri-is-missing-or-invalid`.
```

## 7. Run The Production Workflow Dispatch

After CI has passed on `main`, start the production workflow from GitHub:

```bash
gh workflow run "Secure Serverless DevSecOps Pipeline" \
  --ref main \
  -f mode=deploy \
  -f environment=prod
```

Watch it:

```bash
devsecops github status --format compact
```

Expected successful outcome:

```text
Deploy
completed
success
```

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
