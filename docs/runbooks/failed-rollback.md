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
* The deploy role cannot read the function, fetch the ECR digest, or update Lambda code.
* The previous digest was deleted or is no longer pullable.
* The selected Terraform workspace points to a different Lambda ARN.
* The state refresh failed or the restored endpoint returned a non-2xx response.

## Fix

1. Find `Previous Lambda digest` in the workflow log. Confirm that digest remains available in ECR.
2. Verify the target account, `prod` workspace, and the Lambda ARN. Check deploy role permissions for Lambda read and update and ECR pull.
3. Preview `devsecops deploy rollback --image-uri '<repository>@sha256:<digest>' --dry-run` with a reviewed digest.
4. Dispatch the same command without `--dry-run` and follow it with `devsecops deploy status --watch`.
5. Confirm the log records `Verified Lambda recovery`. Compare `aws lambda get-function --query 'Code.ResolvedImageUri'` for the deployed function with `terraform -chdir=terraform output -raw lambda_current_image_uri` in the `prod` workspace. Confirm `/health` returns 2xx.

Rollback updates Lambda code and refreshes Terraform state. To retry after a
state refresh failure, dispatch the same digest again. If that digest is
already configured, the workflow verifies the function and refreshes state
without another code update. Changes to other infrastructure from an earlier
failed apply require their own review. Update and synchronize the desired
image before the next full deploy if the recovered version should remain active.
