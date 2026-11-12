# Operational Runbooks

For the single-operator lab, start with `devsecops lab status NAME`,
`devsecops lab logs NAME` and the failed command's evidence directory.
For experimental production, inspect `devsecops deploy status` and
`devsecops deploy logs`. Choose the matching recovery guide below.

| Failure | Runbook |
| --- | --- |
| Terraform plan failed | [Failed Terraform plan](failed-terraform-plan.md) |
| Terraform apply failed | [Failed Terraform apply](failed-terraform-apply.md) |
| Validation failed | [Failed validation](failed-validation.md) |
| Lambda image missing or unusable | [Missing Lambda image](missing-image.md) |
| Deployment rollback failed | [Failed deployment rollback](failed-rollback.md) |
| Finish demo, retain data or decommission resources | [Finish demo / decommission](finish-demo.md) |

All commands are read-only unless a command explicitly includes `--apply`,
`--yes`, a separately approved `teardown bucket-purge --acknowledge-backup`,
or a GitHub/AWS mutating command shown for manual recovery.

During a production proof walkthrough, attach the relevant runbook link to the
evidence bundle. If a failure does not fit one of these runbooks, add or update
a runbook before marking the release production-proven. See
[Production deployment evidence](../production-deployment-evidence.md).
