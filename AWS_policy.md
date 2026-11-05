# AWS IAM Policy Guidance For The CLI-Managed Pipeline

DevSecOps Pipeline Kit uses the CLI as the setup and diagnostics surface, while
GitHub Actions uses OIDC to exchange a GitHub-issued identity token for
short-lived AWS credentials. Do not store long-lived AWS access keys in GitHub
secrets.

Use the CLI to render and validate repository setup:

```bash
devsecops github-setup --write
devsecops gh-setup --apply \
  --deploy-role-arn arn:aws:iam::<ACCOUNT_ID>:role/<DEPLOY_ROLE> \
  --plan-role-arn arn:aws:iam::<ACCOUNT_ID>:role/<PLAN_ROLE>
devsecops gh-doctor
devsecops branch-doctor
```

Review IAM trust and permission policies manually before applying them. The CLI
helps configure GitHub variables/secrets and diagnose repository state; it does
not create AWS IAM roles for you.

## Recommended Roles

| Role | Used by | Purpose |
| --- | --- | --- |
| `AWS_PLAN_ROLE_TO_ASSUME_ARN` | Pull request and manual plan workflows | Read Terraform state, acquire state lock, refresh resources, and produce plans. |
| `AWS_ROLE_TO_ASSUME_ARN` | Manual production deploy workflow from `main` | Apply Terraform, read configured images for optional scanning, and perform rollback. |

Use separate roles. The workflow requires `AWS_PLAN_ROLE_TO_ASSUME_ARN` for
Terraform plans and does not fall back to the deploy role. The plan role should
not be able to mutate workload resources beyond Terraform backend locking.

## Least-Privilege Boundaries

Treat the two roles as different blast-radius controls:

| Role | Allow | Avoid |
| --- | --- | --- |
| Plan role | Read Terraform state, acquire/release the DynamoDB lock, list/read backend objects, and describe existing resources for Terraform refresh. | Do not grant broad create, update, delete, `iam:PassRole`, Lambda update, or KMS administration permissions. Do not reuse the deploy role for pull request planning. |
| Deploy role | Apply Terraform-managed resources after the protected production environment gate, pass only the Terraform-managed Lambda execution role, read the configured ECR image, invoke the IAM-protected health route, and update Lambda image code for deploy/rollback. | Do not use for PR plans. Do not use unscoped account-wide permissions after project, environment, and resource names are stable. Do not store long-lived AWS keys in GitHub. |

Generate `dist/devsecops/audit-report.json` with
`devsecops report --format json` before a production review. The report records
the current control states and this role-separation guidance as attachable
evidence.

## OIDC Provider

Create an IAM OIDC identity provider:

* Provider URL: `https://token.actions.githubusercontent.com`
* Audience: `sts.amazonaws.com`

In both trust policies below, replace `<ACCOUNT_ID>` with the AWS account that
owns the IAM role and `<GITHUB_REPOSITORY_SUBJECT>` with the repository segment
from the deployment repository's OIDC `sub` claim.

| Repository subject format | Value to substitute |
| --- | --- |
| Name-based | `OWNER/REPOSITORY` |
| Immutable | `OWNER@OWNER_ID/REPOSITORY@REPOSITORY_ID` |

GitHub repositories created after July 15, 2026 use immutable subjects by
default. Older repositories can opt in. If the repository customizes its
subject claims, use the exact `sub` for each allowed job. Match the audience
and subjects with `StringEquals`. See the [GitHub OIDC subject reference](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims).

## Deploy Trust Policy Example

The deploy and rollback job uses the GitHub Environment `prod`. Its subject
ends in `:environment:prod`. The workflow also checks that it runs from `main`.
The environment subject does not encode the branch, so enforce that restriction
in GitHub before attaching this trust policy to the deploy role.

In **Settings → Environments → prod**, set **Deployment branches and tags** to
**Selected branches and tags**. Add an exact `main` branch rule and leave tags
out of the allowlist. Add required reviewers, enable **Prevent self-review**,
and clear **Allow administrators to bypass configured protection rules**.
See the [GitHub environment protection settings](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#deployment-branches-and-tags).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:<GITHUB_REPOSITORY_SUBJECT>:environment:prod"
        }
      }
    }
  ]
}
```

## Plan Trust Policy Example

The Terraform Plan job runs without a GitHub Environment. Same-repository
pull requests use the `:pull_request` subject. For manual plans, dispatch
`deploy.yml` from `main` with `mode=plan` to match the branch subject below.
Add an exact branch subject to this list for each additional ref that you
intend to allow for manual plans. The workflow skips AWS-backed plans for fork
pull requests. The PR subject itself does not distinguish fork authors.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": [
            "repo:<GITHUB_REPOSITORY_SUBJECT>:pull_request",
            "repo:<GITHUB_REPOSITORY_SUBJECT>:ref:refs/heads/main"
          ]
        }
      }
    }
  ]
}
```

## Verify Role Setup

After creating the roles, run:

```bash
devsecops github setup --apply \
  --repo <OWNER>/<REPO> \
  --deploy-role-arn arn:aws:iam::<ACCOUNT_ID>:role/<DEPLOY_ROLE> \
  --plan-role-arn arn:aws:iam::<ACCOUNT_ID>:role/<PLAN_ROLE>
devsecops doctor github --strict
devsecops doctor branch --branch main --strict
```

Create and protect the `prod` GitHub Environment before applying setup. Setup
inspects repository and `prod` secret metadata. When a deployment role or Snyk
token already exists in `prod`, setup updates that effective scope. The plan
role belongs at repository scope because plan jobs run outside `prod`.

During final acceptance, run the dedicated verification workflow:

```bash
gh workflow run verify-oidc.yml --ref main --repo <OWNER>/<REPO>
devsecops doctor github --repo <OWNER>/<REPO> --strict
```

The plan job assumes the repository plan role. After `prod` approval, the
deploy job assumes the effective production role and verifies that it differs
from the verified plan role. Both jobs compare the STS identity with the
intended role and account. The workflow performs identity checks only.
Doctor requires both jobs to succeed on current `main` and checks that role
secret timestamps precede the verification. A secret update or a new commit
requires verification again. Record the run ID in the
[deployment evidence](docs/production-deployment-evidence.md).

`AWS_PLAN_ROLE_TO_ASSUME_ARN` is required even if older local config or presets
have `use_separate_aws_plan_role=false`. That config value is retained for
readiness posture display, but deploy-role fallback is disabled.

## Backend Access

Both plan and deploy roles need access to the Terraform backend:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TerraformStateBucket",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::<TERRAFORM_STATE_BUCKET_NAME>",
        "arn:aws:s3:::<TERRAFORM_STATE_BUCKET_NAME>/*"
      ]
    },
    {
      "Sid": "TerraformDynamoDBLocking",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:DescribeTable"
      ],
      "Resource": "arn:aws:dynamodb:<AWS_REGION>:<ACCOUNT_ID>:table/<TERRAFORM_LOCK_TABLE_NAME>"
    }
  ]
}
```

## Deploy Permissions Baseline

Terraform creates and updates IAM, KMS, S3, ECR, Lambda, API Gateway,
CloudWatch Logs, SQS, and related policies. A practical deploy-role baseline is
shown below. Tighten resources by ARN once your account, project name, and
environment names are stable.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "ECRManageAndRead",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:CreateRepository",
        "ecr:DeleteLifecyclePolicy",
        "ecr:DeleteRepository",
        "ecr:DescribeImages",
        "ecr:DescribeRepositories",
        "ecr:GetDownloadUrlForLayer",
        "ecr:GetLifecyclePolicy",
        "ecr:GetRepositoryPolicy",
        "ecr:PutImageScanningConfiguration",
        "ecr:PutImageTagMutability",
        "ecr:PutLifecyclePolicy",
        "ecr:SetRepositoryPolicy",
        "ecr:TagResource",
        "ecr:UntagResource"
      ],
      "Resource": "arn:aws:ecr:<AWS_REGION>:<ACCOUNT_ID>:repository/<PROJECT_NAME>-*-lambda-repo"
    },
    {
      "Sid": "ManageECRKMSGrants",
      "Effect": "Allow",
      "Action": ["kms:CreateGrant", "kms:RetireGrant"],
      "Resource": "arn:aws:kms:<AWS_REGION>:<ACCOUNT_ID>:key/*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ecr.<AWS_REGION>.amazonaws.com",
          "aws:ResourceTag/Project": "<PROJECT_NAME>"
        }
      }
    },
    {
      "Sid": "ManageWorkloadWithTerraform",
      "Effect": "Allow",
      "Action": [
        "apigateway:*",
        "cloudwatch:*",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:PassRole",
        "iam:PutRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "kms:CancelKeyDeletion",
        "kms:CreateAlias",
        "kms:CreateKey",
        "kms:DeleteAlias",
        "kms:DescribeKey",
        "kms:EnableKeyRotation",
        "kms:GetKeyPolicy",
        "kms:GetKeyRotationStatus",
        "kms:ListAliases",
        "kms:ListResourceTags",
        "kms:PutKeyPolicy",
        "kms:ScheduleKeyDeletion",
        "kms:TagResource",
        "kms:UntagResource",
        "lambda:AddPermission",
        "lambda:CreateFunction",
        "lambda:DeleteFunction",
        "lambda:GetFunction",
        "lambda:GetFunctionCodeSigningConfig",
        "lambda:GetFunctionConfiguration",
        "lambda:ListTags",
        "lambda:ListVersionsByFunction",
        "lambda:RemovePermission",
        "lambda:TagResource",
        "lambda:UntagResource",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "logs:*",
        "s3:*",
        "sqs:*",
        "xray:PutTelemetryRecords",
        "xray:PutTraceSegments"
      ],
      "Resource": "*"
    },
    {
      "Sid": "InvokeHealthRoute",
      "Effect": "Allow",
      "Action": "execute-api:Invoke",
      "Resource": "arn:aws:execute-api:<AWS_REGION>:<ACCOUNT_ID>:*/*/GET/health"
    }
  ]
}
```

An operator creating the built-in repository with Terraform needs its ECR
and KMS permissions in the target account. For an external repository, grant
the deploy role `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` on that
repository ARN. A cross-account repository must also authorize the consumer
account and the Lambda service as described in the
[AWS Lambda image permissions guide](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html#images-create-permissions).
The local deployment reviewer also needs these two ECR read actions and
`ecr:GetAuthorizationToken`. Local AWS doctor uses `ecr:DescribeImages`.

## Plan Role Guidance

The plan role needs backend access and enough read permissions for Terraform
refresh. Start with read-only permissions for the services above, then add
specific `kms:DescribeKey`, `iam:GetRole`, `iam:GetRolePolicy`,
`lambda:GetFunctionConfiguration`, `ecr:DescribeRepositories`, and S3 listing
permissions as Terraform reports missing access.

Keep the role scoped to the [plan subjects](#plan-trust-policy-example) you
intend to allow. Use a separate sandbox account and review process if you need
AWS-backed plans for untrusted code.

## KMS Admin Role Name

The CLI exposes the Terraform variable `terraform_admin_role_name` through local
config:

```bash
devsecops set terraform_admin_role_name <existing-role-name> --render
```

The variable is optional and defaults to an empty string. If you set it, the
workload KMS key policy grants explicit key administration to that IAM role name
in addition to account root delegation. Only set it to a role that already
exists; otherwise AWS KMS can reject the key policy because of an invalid
principal.
