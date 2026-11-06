# Bring Your Own Lambda Image

The production workflow deploys the immutable image URI you provide through
`LAMBDA_IMAGE_URI`; it does not build the image. An optional small
[text statistics Lambda](../examples/text-stats/README.md) is included for the
diploma demonstration. You can keep it in this repository; a separate workload
repository is optional.

## Image Contract

The image must:

* be a single-platform Linux `amd64` image for the kit's `x86_64` Lambda;
* use a Docker V2 Schema 2 or OCI image manifest;
* be published to Amazon ECR before production workflow dispatch;
* be in the same AWS region as `aws_region`;
* use an immutable tag such as `sha-abc123` or an image digest;
* avoid mutable tags such as `latest` and `bootstrap`.

Recommended shape:

```text
123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

Digest shape:

```text
123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo@sha256:<64-hex-digest>
```

Keep the active image and the digests you rely on for rollback in ECR. The kit
repository leaves image cleanup to the operator. Review any lifecycle policy
on a bring-your-own repository so those digests remain pullable. An upgrade
deploy removes the kit's former 30-image expiration policy, and the deploy
role needs `ecr:DeleteLifecyclePolicy` for that migration.
For example, build the workload with `docker buildx build --platform linux/amd64
--provenance=false --load -t lambda-workload:sha-abc123 .` from its source
checkout. See the [AWS image build guide](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html#python-image-instructions).

The CLI and protected runner use ECR to verify the exact manifest digest,
read the image configuration, and request layer download access before
deployment. Grant the reviewer and deploy role
[`BatchGetImage`, `GetDownloadUrlForLayer`, and `GetAuthorizationToken`](../AWS_policy.md#deploy-permissions-baseline).
Grant the deploy role pull access to retained recovery digests too. For
cross-account ECR, configure the repository policy for both the consuming
account and Lambda's service principal. The preflight exercises the caller's
permissions. Lambda's image optimization and `/health` are verified during
the deployment.

## Provision The Built-in Repository Before The First Deploy

Skip this step when publishing to an existing external ECR repository.
For the built-in repository, first [bootstrap the remote state backend](first-successful-pipeline.md#4-configure-terraform-backend).
Use AWS credentials for the target deployment account with permission to
create the project KMS key and ECR repository. Generate the backend and
Terraform inputs from the same project configuration the workflow will use.

```bash
aws sts get-caller-identity
devsecops generate
terraform -chdir=terraform init -input=false -backend-config=../dist/devsecops/backend.hcl
terraform -chdir=terraform workspace select -or-create prod
terraform -chdir=terraform plan -input=false -lock-timeout=60s \
  -target=module.ecr -out=ecr-bootstrap.tfplan
```

Review the plan. It should contain the repository and its KMS dependency.
Apply the saved plan in the same checkout and workspace:

```bash
terraform -chdir=terraform apply -input=false -lock-timeout=60s ecr-bootstrap.tfplan
```

Publish the image to `<account-id>.dkr.ecr.<region>.amazonaws.com/<project-name>-prod-lambda-repo`
and set its immutable tag or digest in `lambda_image_uri`. Keep the same
backend and `prod` workspace for the first workload deployment so Terraform
uses the already managed repository and key.

## Validate The Image Locally

Validate the image before writing the value into config:

```bash
devsecops image validate \
  --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

This offline image validation checks:

* URI is present;
* URI matches ECR image shape;
* tag or digest is immutable;
* image region matches `aws_region`;
* repository name is visible for review.

Write the value after image validation passes:

```bash
devsecops config set lambda_image_uri \
  123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123 \
  --generate
```

After synchronizing GitHub configuration, run `devsecops deploy prod --dry-run`
with local AWS credentials to verify the image in ECR, including when the URI
already contains a digest.

## HTTP Validation Contract

For production, set `enable_http_validation=true`. The image must handle API
Gateway HTTP API events and return a successful response for:

```text
GET /health
```

If `ENABLE_DAST=true`, set `API_AUTHORIZATION_TYPE=NONE` only when the
deployed API is intentionally public and safe for passive OWASP ZAP baseline
scanning.

## External Repository Boundary

Build, test, scan, and publish the workload separately from the kit deploy
workflow. Use `examples/text-stats/` for the diploma or a separate workload
repository for an independent application. The kit still consumes a published
image and does not build or push it during deployment.
