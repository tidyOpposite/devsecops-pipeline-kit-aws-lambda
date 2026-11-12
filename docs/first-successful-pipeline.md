# First Successful Pipeline

The stable target is local CLI plus single-operator AWS dev lab. Production
GitHub/OIDC workflows are a separate [experimental walkthrough](experimental-production-walkthrough.md).
Use `v1.0.0` (`1.0.0`) or its matching source checkout; beta.1
assets do not include lab commands.

## Install and run locally

Follow the [Quick Start](../README.md#quick-start), keeping CLI and Terraform
sources at the same commit. From that checkout:

```bash
devsecops setup --mode demo --yes --strict
devsecops status
devsecops dry-run
devsecops config validate
devsecops config diff
devsecops generate --dry-run
devsecops report --format json
```

Expected: `Demo complete`, no AWS changes. `setup --yes` does not grant GitHub
write permission. Inspect immutable image shape with `devsecops image validate`;
edit config through `devsecops config set` and collect local preparation with
`devsecops evidence collect --rc`. These local records do not prove cloud success.

## Operate one AWS lab

Use the full [single-operator lab guide](single-operator-lab.md) for AWS CLI login,
explicit account/region, ECR publication, concurrency and saved-plan review.

```bash
devsecops lab init diploma --expected-account-id 123456789012 --region eu-north-1 --profile diploma
devsecops lab plan diploma --stage registry
# Review plan.txt. Substitute the actual ID and review SHA-256:
devsecops lab apply diploma --plan-id PLAN_ID --sha256 REVIEW_SHA256 --yes
```

Publish the example images, then use `devsecops lab plan` and `devsecops lab apply`
for A, B, intentionally failed C with automatic B, and manual rollback A.
Use `devsecops lab status`, `devsecops lab request`, and `devsecops lab logs`
to verify actual results. Failed C must remain exit 1 after successful recovery.
The IAM API requires signed requests. Local state and evidence stay private.

## Finish

Archive and verify required data and evidence, empty the exclusively owned ECR
and versioned buckets after reviewing their inventories, then review/apply
`devsecops lab plan diploma --stage destroy`. Verify exact resource absence,
KMS schedule and later billing. Follow [finish-demo](runbooks/finish-demo.md).
For stable acceptance use the [release contract](single-operator-release-evidence.md)
and `devsecops criteria --strict`; production commands are not required.
