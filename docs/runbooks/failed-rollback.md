# Runbook: Failed Deployment Rollback

Use this when the production workflow tried to restore the previous Lambda
image but the deployed function still looks wrong.

## Boundary

`devsecops rollback` and `devsecops snapshot restore` only restore local
CLI-owned files. They do not roll back AWS Lambda. Operator cloud rollback is
`devsecops deploy rollback`; it dispatches the protected GitHub Actions
workflow and never updates Lambda directly from the local machine.

## Diagnose

```bash
devsecops deploy status
devsecops deploy logs --failed
devsecops aws outputs --environment prod
```

## Common Causes

* The first deployment had no previous Lambda image to restore.
* The deploy role cannot call `lambda:UpdateFunctionCode`.
* The previous image was deleted or is no longer pullable.
* Terraform re-apply after rollback failed, leaving state drift.

## Fix

1. Confirm whether the failed run captured `previous_image_uri`.
2. Confirm the previous image still exists and can be pulled.
3. Fix deploy role permissions for Lambda update and ECR pull actions.
4. Preview `devsecops deploy rollback --image-uri <known-good-immutable-image-uri> --dry-run`.
5. Dispatch `devsecops deploy rollback --image-uri <known-good-immutable-image-uri>` and follow it with `devsecops deploy status --watch`.
6. Use `devsecops aws outputs --environment prod` to verify the resulting
   Lambda image and API Gateway endpoint.
