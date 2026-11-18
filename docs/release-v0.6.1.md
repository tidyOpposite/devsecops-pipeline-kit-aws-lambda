# Release v0.6.1

This patch release hardens the security posture of the pipeline without adding
new product milestones.

## Security Fixes

* GitHub Actions permissions are scoped per job. OIDC tokens are available only
  to jobs that need AWS credentials, and pull request write permission is
  limited to the plan job that comments on PRs.
* `actions/checkout` no longer persists repository credentials in workflow job
  git config.
* Terraform plan workflows require `AWS_PLAN_ROLE_TO_ASSUME_ARN`; they no
  longer fall back to the production deploy role.
* AWS-backed Terraform plans do not run for pull requests from forked
  repositories.
* Terraform validates `lambda_image_uri` as an immutable ECR image URI when it
  is set and prevents Lambda workload plan/apply when it is empty.
* Workload data and access-log S3 buckets deny non-TLS requests.

## Validation

The release was validated with:

```bash
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
git diff --check
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate -no-color
python -m build
devsecops --version
```
