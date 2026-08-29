# Runbook: Failed Terraform Plan

Use this when `devsecops github status` or a pull request workflow reports a
failed Terraform plan.

## Diagnose

```bash
devsecops github status --format compact
devsecops doctor github --strict
devsecops doctor aws --environment prod --strict
devsecops terraform plan prod --create-workspace
```

Inspect the failed workflow logs:

```bash
gh run view <run-id> --log-failed
```

## Common Causes

* `AWS_PLAN_ROLE_TO_ASSUME_ARN` is missing or cannot read Terraform state.
* The pull request is from a fork, so the AWS-backed plan job is skipped by
  design.
* The S3 backend bucket or DynamoDB lock table is missing.
* The selected workspace does not exist and was not created.
* Generated Terraform variables are stale.

## Fix

1. Run `devsecops generate --dry-run`, then `devsecops generate` if generated
   variables are stale.
2. Run `devsecops github setup --write` and compare required variables/secrets.
3. Confirm backend resources with `devsecops doctor aws --environment prod`.
4. Rerun the PR or manual `workflow_dispatch` plan after the checks are clean.
