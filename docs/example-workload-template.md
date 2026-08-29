# Separate Example Workload Template

The pipeline kit intentionally does not bundle Lambda application source. Use
this document as the template contract for a separate workload repository.

## Recommended Separate Repository Shape

Create a different repository, for example:

```text
devsecops-lambda-example
```

Recommended files in that separate repository:

```text
Dockerfile
src/
tests/
.github/workflows/publish-image.yml
README.md
```

The separate repository should:

* build a Lambda-compatible container image;
* run workload tests and dependency scans;
* publish the image to ECR with an immutable tag or digest;
* output the final image URI for use as `LAMBDA_IMAGE_URI`.

## Minimal Publish Contract

The external repository or image pipeline should produce one value:

```text
LAMBDA_IMAGE_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

Then return to this repository and run:

```bash
devsecops image validate --image-uri "$LAMBDA_IMAGE_URI"
devsecops config set lambda_image_uri "$LAMBDA_IMAGE_URI" --generate
```

This keeps the product boundary clean: workload code lives in the workload
repository, while this repository owns pipeline configuration, Terraform,
GitHub Actions, readiness diagnostics, and deployment orchestration.
