# Runbook: Failed Terraform Apply

Use this when the production deploy workflow fails during Terraform apply or
while deploying the Lambda image.

## Diagnose

```bash
devsecops deploy status
devsecops deploy logs --failed
devsecops aws outputs --environment prod
devsecops doctor aws --environment prod
```

## Common Causes

* The deploy role lacks permission for a resource Terraform is changing.
* `LAMBDA_IMAGE_URI` points to an image the deploy role cannot pull.
* Terraform state is locked by another run.
* The target workspace is not `prod` or the workflow was not dispatched from
  `main`.

## Fix

1. Confirm `devsecops doctor github --strict` and `devsecops doctor branch` are
   clean.
2. Confirm `devsecops image validate --image-uri <immutable-ecr-image-uri>` passes.
3. Confirm deployed state with `devsecops aws outputs --environment prod`.
4. Fix IAM, image, or Terraform errors from the failed step log.
5. Preview `devsecops deploy prod --dry-run` and dispatch it only after the
   failed run has completed.
