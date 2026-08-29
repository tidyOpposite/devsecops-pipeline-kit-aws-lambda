# Runbook: Failed Validation

Use this when Terraform validation, Trivy, Snyk, `/health`, or OWASP ZAP fails.

## Diagnose

```bash
devsecops github status --format compact
devsecops status --strict --format compact
devsecops health --aws-sigv4
gh run view <run-id> --log-failed
```

## Common Causes

* Terraform formatting or validation errors.
* Trivy detected a high or critical IaC issue.
* Snyk cannot scan the private image or found high-severity container issues.
* `/health` returns an error, timeout, or non-HTTP response.
* OWASP ZAP found a fail-level issue when DAST is enabled for an explicitly
  public API.

## Fix

1. For Terraform, run `terraform -chdir=terraform fmt -recursive` and
   `terraform -chdir=terraform validate -no-color`.
2. For image scanning, confirm `SNYK_TOKEN` and ECR pull permissions.
3. For health failures, run
   `devsecops health --url <health-url> --aws-sigv4` for IAM-protected APIs
   and inspect CloudWatch logs for the Lambda function from
   `devsecops aws outputs`.
4. For DAST failures, review the `zap-baseline-prod` artifact before rerunning.
