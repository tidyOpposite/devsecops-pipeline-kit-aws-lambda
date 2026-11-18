# Manual Sandbox Plans

Every pull request runs Terraform formatting, backend-free validation and IaC
scanning without AWS credentials. This policy covers internal branches and
forks. The template repository needs no AWS secrets or backend for these checks.
Require `Security and Terraform Validate` and `Terraform Format and Validate`
on `main`; remove the old `Terraform Plan` required check.

A deployment repository can explicitly enable an AWS-backed sandbox preview.
It runs only reviewed code already merged to `main`, only after manual
dispatch, and only for `dev`. It never applies a plan. Production plans remain
inside the protected production deploy job and use the deployment backend.

## Provision An Independent Backend

During final cloud setup, select a sandbox AWS account/profile and confirm it
with `aws sts get-caller-identity`. Use a separate AWS account where possible.
Provision a dedicated state bucket, log bucket, KMS key and DynamoDB lock
table. The state bucket and lock table must differ from the deployment
configuration in `PIPELINE_CONFIG_JSON`.

The existing bootstrap can provision these resources in its own ignored local
working directory, preserving the deployment bootstrap's state. Replace the
example names with globally unique sandbox names and review the plan before
applying:

```bash
mkdir -p dist/devsecops/sandbox-backend-bootstrap
cp terraform/bootstrap/*.tf dist/devsecops/sandbox-backend-bootstrap/
terraform -chdir=dist/devsecops/sandbox-backend-bootstrap init -input=false
terraform -chdir=dist/devsecops/sandbox-backend-bootstrap plan -out=backend.tfplan \
  -var='aws_region=eu-central-1' \
  -var='state_bucket_name=your-unique-sandbox-state' \
  -var='lock_table_name=your-sandbox-locks'
terraform -chdir=dist/devsecops/sandbox-backend-bootstrap apply backend.tfplan
```

Keep this bootstrap state securely; it manages the sandbox backend resources.
Give the plan role access only to this backend and its KMS key, plus the
sandbox resource reads required by Terraform. It needs backend workspace/lock
writes, but no workload create/update/delete permissions and no access to
deployment state. Use the exact main-branch
[OIDC trust policy](../AWS_policy.md#plan-trust-policy-example); remove PR trust
from existing roles as part of upgrading.

## Enable In The Deployment Repository

The existing repository-scoped `AWS_PLAN_ROLE_TO_ASSUME_ARN` identifies the
sandbox plan role. `github setup` retains the optional planning variables;
it does not enable AWS planning or provision a backend automatically.

Save the following non-secret JSON as
`dist/devsecops/sandbox-backend.json`, using the provisioned resource names:

```json
{
  "bucket": "your-unique-sandbox-state",
  "key": "sandbox/terraform.tfstate",
  "region": "eu-central-1",
  "lock_table": "your-sandbox-locks",
  "workspace_key_prefix": "sandbox-environments"
}
```

Only these five string fields are accepted. Backend credentials belong in
OIDC/IAM, never this JSON. Configure the explicit destination:

```bash
gh variable set PLAN_BACKEND_JSON --repo OWNER/REPO \
  --body "$(cat dist/devsecops/sandbox-backend.json)"
gh variable set ENABLE_AWS_PLAN --repo OWNER/REPO --body true
```

## Run And Review

After reviewing and merging the Terraform change to protected `main`:

```bash
gh workflow run deploy.yml --repo OWNER/REPO --ref main \
  -f mode=plan -f environment=dev
gh run list --repo OWNER/REPO --workflow deploy.yml --event workflow_dispatch
gh run view RUN_ID --repo OWNER/REPO
gh run download RUN_ID --repo OWNER/REPO \
  --name sandbox-terraform-plan-dev --dir dist/devsecops/sandbox-plan
```

Before requesting AWS credentials, validation rejects a disabled feature,
another branch, `staging`/`prod`, malformed JSON, or reuse of the deployment
state bucket/lock table. The AWS job checks out the dispatch commit SHA. It
creates/selects `dev` only in the independent sandbox backend, runs `plan`,
and uploads text output with no PR write permission or PR comment.

An empty sandbox state produces a creation preview, not a diff against deployed
production resources. The text artifact cannot be applied. Do not copy
production state into this backend or grant the plan role production access.
Disable future sandbox plans with:

```bash
gh variable set ENABLE_AWS_PLAN --repo OWNER/REPO --body false
```

Disabling the feature does not delete backend resources or their stored data.
