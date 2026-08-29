# First Successful Pipeline

This guide gives a measurable path from a clean install to one production
workflow dispatch. The CLI remains the product surface; Terraform, GitHub
Actions, AWS, and scanners stay visible execution layers.

Every `devsecops` command used in this guide is part of the stable command
contract in [Stability contract](stability-contract.md).

## 1. Install And Run A No-Credentials Dry Run

Install the latest published CLI release with the commands in
[Distribution and compatibility](distribution.md), then run a dry run. The dry
run does not write files and does not require AWS credentials.

```bash
devsecops --version
devsecops status
devsecops dry-run \
  --preset balanced \
  --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

Expected output includes:

```text
First Successful Pipeline Dry Run
No files changed.
AWS credentials are not required for this dry run.
Files that would be generated
Lambda image shape          OK
Lambda image immutability   OK
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

## 2. Create Local Source Config

Use the guided setup flow when you want the CLI to explain the current
context and create missing local config after confirmation:

```bash
devsecops setup --preset balanced
```

For a non-interactive path:

```bash
devsecops setup --preset balanced --yes
devsecops config validate
devsecops config diff
devsecops status
```

Expected output:

```text
Created clean config .devsecops-pipeline.toml
Config
Config schema version   OK
No config diff detected.
```

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
