# Bring Your Own Lambda Image

This project does not build or bundle workload source. The production workflow
deploys the immutable image URI you provide through `LAMBDA_IMAGE_URI`.

## Image Contract

The image must:

* be an AWS Lambda-compatible container image;
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

## Validate The Image Locally

Validate the image before writing the value into config:

```bash
devsecops image validate \
  --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

Image validation checks:

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

## HTTP Validation Contract

If `ENABLE_HTTP_VALIDATION=true`, the image must handle API Gateway HTTP API
events and return a successful response for:

```text
GET /health
```

If `ENABLE_DAST=true`, set `API_AUTHORIZATION_TYPE=NONE` only when the
deployed API is intentionally public and safe for passive OWASP ZAP baseline
scanning.

## External Repository Boundary

Keep application source, Dockerfile, dependency scanning, and image publishing
in a workload repository or image release pipeline outside this repository. The
pipeline kit consumes the published image; it does not own the workload build.
