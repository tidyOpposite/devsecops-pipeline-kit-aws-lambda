# Runbook: Missing Lambda Image

Use this when deploy fails because `LAMBDA_IMAGE_URI` is empty, mutable, in the
wrong region, or not found in ECR.

## Diagnose

```bash
devsecops image validate --image-uri <immutable-ecr-image-uri>
devsecops doctor github --strict
devsecops doctor aws --environment prod
devsecops aws outputs --environment prod
```

## Common Causes

* Repository variable `LAMBDA_IMAGE_URI` is missing.
* The image tag is `latest` or `bootstrap`.
* The image region does not match `aws_region`.
* The ECR repository was not created yet.
* The deploy role cannot pull from the image repository.

## Fix

1. Publish the workload image in the same region as `aws_region`.
2. Use an immutable tag or digest.
3. Set the value with `devsecops config set lambda_image_uri <image-uri> --generate`.
4. Apply GitHub setup with `devsecops github setup --apply ...`.
5. Rerun `devsecops image validate` and `devsecops doctor github --strict`.
