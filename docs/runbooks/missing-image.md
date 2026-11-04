# Runbook: Missing Lambda Image

Use this when deployment preflight rejects the image reference, ECR access,
manifest format, or platform.

## Diagnose

```bash
devsecops image validate --image-uri <immutable-ecr-image-uri>
devsecops doctor github --strict
devsecops doctor aws --environment prod
devsecops deploy prod --dry-run
```

## Common Causes

* Repository variable `LAMBDA_IMAGE_URI` is missing.
* The image tag is `latest` or `bootstrap`.
* The image region does not match `aws_region`.
* The ECR repository was not created yet.
* The local reviewer or deploy role cannot pull from the image repository.
* The image is an OCI index, a Docker manifest list, or uses a platform other than Linux `amd64`.

## Fix

1. Publish a single-platform Linux `amd64` workload image in `aws_region`.
   For the built-in ECR repository, complete the [separate bootstrap](../bring-your-own-image.md#provision-the-built-in-repository-before-the-first-deploy) first.
2. Use an immutable tag or digest.
3. Set the value with `devsecops config set lambda_image_uri <image-uri> --generate`.
4. Apply GitHub setup with `devsecops github setup --apply ...`.
5. Rerun `devsecops deploy prod --dry-run` with credentials that can pull the image.
