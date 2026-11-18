# Release v0.6.0

This release implements Milestone 5: Operational Reliability. It strengthens
post-deploy diagnostics while keeping operational commands read-only unless the
operator explicitly chooses a mutating workflow.

## Highlights

* `devsecops github status` and `devsecops doctor actions` now show failed
  jobs, failed steps, next actions, and runbook links.
* `devsecops health` validates the deployed `/health` endpoint outside GitHub
  Actions. It can use Terraform output or an explicit `--url`.
* `devsecops aws outputs` inspects deployed Lambda, API Gateway, and CloudWatch
  values from AWS without changing resources.
* `devsecops readiness --strict` exits non-zero on scored readiness gaps for
  CI-friendly checks.
* Local snapshot restore output now clearly states that it restores only
  CLI-owned local files and does not roll back AWS Lambda or Terraform state.
* Operational runbooks cover failed Terraform plan, failed apply, failed
  validation, missing images, and failed deployment rollback.

## Recommended Operational Checks

```bash
devsecops github status --format compact --strict
devsecops readiness --strict --format compact
devsecops aws outputs --environment prod
devsecops health
```

## Runbooks

* [Failed Terraform plan](runbooks/failed-terraform-plan.md)
* [Failed Terraform apply](runbooks/failed-terraform-apply.md)
* [Failed validation](runbooks/failed-validation.md)
* [Missing Lambda image](runbooks/missing-image.md)
* [Failed deployment rollback](runbooks/failed-rollback.md)

## Validation

The release was validated with:

```bash
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
git diff --check
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate -no-color
python -m pip install --no-deps --no-build-isolation .
devsecops --version
```
