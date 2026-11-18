# Runbook: Failed Terraform Plan

Use this when `devsecops github status` reports a failed manual sandbox plan.
All PRs use credential-free validation; investigate their formatting, validation
or IaC scan logs without adding AWS credentials.

## Diagnose

```bash
devsecops github status --format compact
devsecops doctor github --strict
gh variable list --repo OWNER/REPO
```

Inspect the failed workflow logs:

```bash
gh run view <run-id> --log-failed
```

## Common Causes

* `AWS_PLAN_ROLE_TO_ASSUME_ARN` is missing or cannot read Terraform state.
* `ENABLE_AWS_PLAN` is disabled or `PLAN_BACKEND_JSON` is malformed.
* The requested ref is not `main`, or the environment is not `dev`.
* The sandbox bucket, KMS key or lock table is missing or inaccessible.
* The sandbox backend reuses a deployment bucket or lock table.
* Generated Terraform variables are stale.

## Fix

1. Run `devsecops generate --dry-run`, then `devsecops generate` if generated
   variables are stale.
2. Run `devsecops github setup --write` and compare required variables/secrets.
3. Follow [Manual sandbox plans](../sandbox-plans.md) to verify the independent
   backend and scope the plan role to it. Do not grant production-state access.
4. Review and merge the change, then rerun the manual plan from `main` with
   `environment=dev`. Review `sandbox-terraform-plan-dev`; it is a sandbox
   preview rather than a production diff.
