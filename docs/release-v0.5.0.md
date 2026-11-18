# Release v0.5.0

This release implements Milestone 4: First Successful Pipeline Path. The CLI now
gives users a measurable path from install to a dry run, image preflight, and a
production workflow dispatch.

## Highlights

* Added a first successful pipeline guide with exact commands and expected
  outputs.
* Documented the bring-your-own Lambda image path for `LAMBDA_IMAGE_URI`.
* Added a separate example workload template contract instead of bundling
  workload source in this repository.
* Added `devsecops dry-run` for a no-write, no-AWS-credentials first pipeline
  preview.
* Added `devsecops render --dry-run` to preview generated artifacts before files
  change.
* Added `devsecops preflight` checks for Lambda image URI shape, immutability,
  expected repository naming, and AWS region mismatches.
* Linked readiness and doctor failures to troubleshooting entries so each gap
  includes a concrete next action.

## Recommended First Run

```bash
pipx install .
devsecops dry-run --preset balanced --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
devsecops config new --preset balanced
devsecops config validate
devsecops preflight --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
devsecops render --dry-run
devsecops render
devsecops readiness
```

## Documentation

* [First successful pipeline](first-successful-pipeline.md)
* [Bring your own Lambda image](bring-your-own-image.md)
* [Separate example workload template](example-workload-template.md)
* [Troubleshooting guide](troubleshooting.md)

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
