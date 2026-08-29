# Security Controls And Policy Presets

Milestone 6 makes security controls visible as CLI product features. Terraform,
GitHub Actions, AWS, and scanners remain transparent execution layers, but the
operator should be able to answer: which control is enabled, which CLI option
drives it, and what generated behavior enforces it.

## Control Catalog

Use the CLI for the live catalog:

```bash
devsecops controls
devsecops controls --format json
devsecops explain immutable-image
devsecops explain cors
```

| Control | CLI option or command | Terraform behavior | GitHub behavior | AWS behavior | Scanner behavior |
| --- | --- | --- | --- | --- | --- |
| GitHub OIDC | `devsecops github setup --deploy-role-arn`, `--plan-role-arn` | AWS provider receives short-lived role credentials from GitHub Actions. | AWS jobs use `id-token: write` and `aws-actions/configure-aws-credentials`. | IAM OIDC provider and scoped plan/deploy role trust policies. | None. |
| Production approval gate | `use_prod_approval_environment`, `devsecops compose`, presets | Enforced before Terraform apply starts. | Deploy job uses `environment: ${{ vars.PROD_APPROVAL_ENVIRONMENT \|\| 'prod' }}` and only runs `deploy/prod` from `main`. | AWS credentials are not issued until the environment gate allows the job. | None. |
| Separate AWS plan role | `use_separate_aws_plan_role`, `devsecops github setup --plan-role-arn` | Terraform plan uses backend access and refresh permissions. | Plan job fails if `AWS_PLAN_ROLE_TO_ASSUME_ARN` is missing; no deploy-role fallback. | Plan role should read state and describe resources without mutating workloads. | Trivy runs before AWS-backed planning. |
| Terraform state lock | `backend.*`, `devsecops terraform bootstrap` | Rendered backend uses encrypted S3 state and DynamoDB locking. | Plan/deploy jobs run `terraform init` against the backend. | S3 stores state; DynamoDB serializes state writes. | Trivy scans Terraform configuration. |
| Immutable Lambda image | `lambda_image_uri`, `devsecops image validate` | Root and Lambda module validation reject mutable `latest`/`bootstrap`; Lambda module precondition blocks apply without an image. | Deploy job requires `LAMBDA_IMAGE_URI` and rejects mutable tags. | Lambda is updated to the configured immutable image; rollback restores previous image. | Snyk scans the configured image when enabled. |
| API authorization | `api_authorization_type`, `API_AUTHORIZATION_TYPE` | API Gateway routes default to `AWS_IAM`; `NONE` is accepted only when explicitly configured. | Health validation signs IAM-protected requests with SigV4; ZAP is skipped unless the API is public. | API Gateway requires IAM-signed requests by default. | Trivy scans API Gateway IaC. |
| Production CORS | `environments.<env>.cors_allowed_origins`, strict CORS composer answer | `environment_config` feeds API Gateway CORS; Terraform rejects wildcard prod CORS. | Generated tfvars are consumed by plan/deploy runs. | API Gateway HTTP API `allow_origins` is configured from Terraform. | Trivy scans API Gateway IaC. |
| IaC scan | Always on in tracked workflow | Terraform root/modules are scanned before plan/apply. | `Security and Terraform Validate` runs Trivy for HIGH/CRITICAL findings. | Blocks risky IaC before AWS resources are changed. | Trivy config scan. |
| Snyk container scan | `enable_snyk_scan` | Scan gates deployment before Terraform apply. | Deploy job requires `SNYK_TOKEN` when enabled and scans `LAMBDA_IMAGE_URI`. | ECR login reads the configured image. | Snyk container test. |
| HTTP health validation | `enable_http_validation`, `devsecops health --aws-sigv4` | Terraform outputs `api_gateway_health_url`. | Deploy job curls `/health` when enabled and signs the request when API auth is `AWS_IAM`; failed validation triggers rollback. | API Gateway invokes Lambda through the deployed endpoint. | None. |
| DAST | `enable_dast` | Terraform outputs `api_gateway_invoke_url`. | Deploy job runs OWASP ZAP baseline only when `API_AUTHORIZATION_TYPE=NONE`; failure triggers rollback. | ZAP scans only explicitly public API Gateway invoke URLs. | OWASP ZAP baseline. |
| Deployment rollback | Tracked workflow behavior | Re-applies Terraform with the previous Lambda image after rollback. | Deploy job captures and restores the previous image on failed apply/validation. | `aws lambda update-function-code` restores the previous image. | Triggered by failed enabled scan/validation gates. |
| Audit evidence report | `devsecops report --format json` | Includes Terraform/backend control mappings. | JSON can be attached to PRs, workflow artifacts, or release records. | Summarizes AWS-facing control evidence and role guidance. | Records scanner control states. |

## Policy Preset Comparison

Use the CLI for the current comparison:

```bash
devsecops preset list
devsecops preset show enterprise
```

| Preset | Security posture | Scanner | Validation | Prod CORS | Approval | Plan role | Production use |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `minimal` | Development-only | Off | Off | Wildcard | On | On | No. Use for local cost-sensitive experiments only. |
| `balanced` | Baseline | Off | Off | Explicit | On | On | Review before production; enable health validation and image scanning. |
| `strict` | Strict | Snyk | `/health` + DAST | Explicit | On | On | Suitable for pre-production and production candidates after route review. |
| `enterprise` | Production-oriented | Snyk | `/health` + gated DAST | Explicit | On | On | Strongest bundled posture; keep `API_AUTHORIZATION_TYPE=AWS_IAM` unless the API is intentionally public. |
| `student-demo` | Demo-only | Off | Off | Wildcard | Off | Off | No. Short-lived walkthroughs only. |

Each preset is a starting point. User-specific values such as
`lambda_image_uri`, backend bucket names, and IAM role ARNs are intentionally
not embedded in presets.

## Strict Validation

Run relaxed validation while building a local config:

```bash
devsecops config validate
```

Run strict validation before opening a production pull request, cutting a
release, or starting a production workflow dispatch:

```bash
devsecops config validate --strict
```

Strict validation exits non-zero on production-risk warnings as well as hard
failures. It covers:

* wildcard production CORS;
* disabled production approval gate;
* disabled separate plan-role posture;
* public API route authorization;
* missing HTTP deployment validation;
* mutable Lambda image tags such as `latest` or `bootstrap`;
* missing production image identity before deployment.

Terraform also enforces critical parts of this contract. Root variables reject
wildcard production CORS and invalid environment bounds, and Lambda image
variables reject mutable tags.

## Audit Evidence

Generate Markdown for human review:

```bash
devsecops report
```

Generate JSON for audit evidence:

```bash
devsecops report --format json
```

The JSON report defaults to `dist/devsecops/audit-report.json` and includes:

* CLI version, generated time, project, and region;
* readiness checks and gaps;
* strict config validation result;
* full control catalog with current state;
* preset comparison metadata;
* least-privilege guidance for plan and deploy roles;
* attachable evidence paths for PRs and release records.

## Least Privilege

Use two AWS roles with GitHub OIDC:

| Role secret | Used by | Guidance |
| --- | --- | --- |
| `AWS_PLAN_ROLE_TO_ASSUME_ARN` | Pull request and manual plan workflows | Read Terraform state, lock DynamoDB state, and describe resources for refresh. Avoid create/update/delete workload permissions. |
| `AWS_ROLE_TO_ASSUME_ARN` | Manual production deploy workflow from `main` | Apply Terraform-managed resources, pass only the Lambda execution role, read configured images, and restore the previous Lambda image on rollback. |

The plan role must not fall back to the deploy role. The tracked workflow
enforces this with a required `AWS_PLAN_ROLE_TO_ASSUME_ARN` check. See
[`AWS_policy.md`](../AWS_policy.md) for trust policy and permission examples.
