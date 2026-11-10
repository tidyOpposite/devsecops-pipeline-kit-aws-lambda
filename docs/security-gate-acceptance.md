# Security Gate And AWS Runtime Acceptance

## Reproducible Scanner Boundary

The IaC gate keeps Trivy v0.71.0 with its embedded checks: automatic policy
bundle updates and policy-cache restoration are disabled. This avoids mixing
a pinned engine with rules requiring a newer engine. Update the Trivy version
intentionally and review its findings. The optional CI renderer also uses an
exact Rich version, while Dependabot watches the root Python manifests,
the scanner Dockerfile and the actual Terraform configurations.

`tools/snyk/Dockerfile` pins the official Linux/amd64 Snyk image by SHA-256
digest and CLI version (1.1308.4). The production job builds it and verifies
the actual binary version before assuming AWS credentials. The upstream
entrypoint is bypassed so it cannot select/download another CLI at startup.
Dependabot tracks this real Dockerfile; review digest and version changes
together and let `Locked Scanner Isolation` validate them before merging.

The runner uses AWS only to authenticate to ECR and export the already-reviewed
digest to a temporary Docker archive. ECR login uses a temporary Docker config
which is deleted with the archive after the scan. Snyk runs as UID/GID 65534 in
a container with a read-only filesystem, no capabilities, no new privileges,
bounded CPU/memory/process counts and a temporary writable cache. Its only
host file is the read-only archive. It receives `SNYK_TOKEN`, not AWS credentials,
OIDC request variables, GitHub tokens, Docker config, the repository, or the
Docker socket. A service account token scoped to the scanning organization is
recommended. No additional AWS scan role is required.

Archive scanning is supported by the
[Snyk CLI](https://docs.snyk.io/developer-tools/snyk-cli/scan-and-maintain-projects-using-the-cli/snyk-cli-for-snyk-container/advanced-use-of-snyk-container-cli).
Vulnerability findings and scanner/service failures all block deployment.
The pinned tool still consults the live Snyk vulnerability database; findings
can change as that database changes. The runner needs Docker, registry/Snyk
network access and sufficient disk for both the pulled image and its archive.

Run the same container checks locally without AWS or a Snyk token:

```bash
PYTHONPATH=cli python3 -m devsecops_cli.scanner prepare
PYTHONPATH=cli python3 -m devsecops_cli.scanner probe
```

The CI probe uses sentinel host credentials and proves that they do not reach
the container, while the intended scan token and read-only archive do. Unit
tests additionally verify failures, exit codes and removal of temporary data.

## Two Acceptance Levels

Every PR and `main` CI run executes the existing mocked AWS constraint tests
and a mocked apply/teardown of `terraform/acceptance`. These require no cloud
credentials. The normal test directory contains only mock-provider tests.
They exercise the fixture and policy but do not prove AWS service behavior.

`cloud-acceptance.yml` is the separate real-service test. It is manual, disabled
by default, restricted to protected `main` and gated by the GitHub Environment
`acceptance`. Run it only during final cloud acceptance after the product fixes
are finished. It creates and removes sandbox resources; it is not run by PR/CI
or by CLI setup.

## Configure The Sandbox For Final Acceptance

1. Independently confirm a dedicated sandbox AWS account and the production
   account. They must differ. Do not use the production account for this test.
2. Create an acceptance IAM role in the sandbox account. Use the deploy
   permissions baseline in [AWS policy guidance](../AWS_policy.md), scoped to
   `acceptance-*` fixture resources, hashed `kit-acceptance-*` buckets,
   image read access and the KMS/IAM actions
   needed to create/remove the fixture. It needs no deployment-backend access.
   Ensure the sandbox has enough Lambda concurrency quota to reserve one
   execution while preserving AWS's required unreserved capacity.
   Preparation now reads account/function capacity under the assumed role
   before writing the fixture. It fails closed if capacity or read permissions
   are missing and records successful readback in
   `dist/devsecops/acceptance/capacity.json`, included in the run artifact.
   This workflow retains its reservation and separate-account requirements;
   the dev lab's shared-pool option does not alter acceptance policy.
3. Create GitHub Environment `acceptance`: require an independent reviewer,
   prevent self-review, disable admin bypass, and allow only the exact branch
   `main`, without tags. The workflow verifies these protections before AWS.
4. Use the deploy trust-policy template with the exact subject
   `repo:<GITHUB_REPOSITORY_SUBJECT>:environment:acceptance` and audience
   `sts.amazonaws.com`. Use the repository's immutable subject segment when
   applicable. Never allow PR subjects or branch/environment wildcards.
5. Set `AWS_ACCEPTANCE_ROLE_ARN` in the `acceptance` environment secrets. Publish
   a Lambda-compatible Linux/amd64 image in the sandbox account's ECR.
6. Set repository variables, using independently confirmed values:

| Variable | Meaning |
| --- | --- |
| `ACCEPTANCE_AWS_ACCOUNT_ID` | Dedicated sandbox account, 12 digits. |
| `PRODUCTION_AWS_ACCOUNT_ID` | Different production account, 12 digits. |
| `ACCEPTANCE_AWS_REGION` | Sandbox workload/ECR region. |
| `ACCEPTANCE_IMAGE_URI` | Sandbox ECR image pinned to `@sha256:...`. |
| `ENABLE_CLOUD_ACCEPTANCE` | Set to `true` only when ready for the final test. |

The workflow verifies opt-in, refs, account IDs, role account and image scope
before AWS access, then checks the actual STS account and image contents.
Terraform independently restricts its provider to the sandbox account ID.
The unique 32-character `acceptance-*` project prefix includes run/attempt
identity and is used only by this fixture. It cannot select existing deployment
resources. The fixture has no remote backend, imports or deployment state.

## Execute And Preserve Evidence

During the final acceptance stage:

```bash
gh workflow run cloud-acceptance.yml --repo OWNER/REPO --ref main
gh run list --repo OWNER/REPO --workflow cloud-acceptance.yml
gh run view RUN_ID --repo OWNER/REPO --log
gh run download RUN_ID --repo OWNER/REPO \
  --name isolated-aws-acceptance-RUN_ID-ATTEMPT --dir dist/devsecops/aws-acceptance
```

Terraform test applies the shared KMS and Lambda modules plus empty encrypted
fixture buckets for a 32-character project in `staging`. It reads back the live
CloudWatch retention (1096 days) and Lambda environment, and checks the actual
bucket names accepted by S3. It asserts no reserved `AWS_REGION` variable was
configured. The chosen image is checked before apply; the fixture does not
invoke the workload or exercise the production API.

Terraform test automatically tears down its resources. Only these unique
fixture buckets use `force_destroy=true`; the product's data buckets keep their
existing protection. State/log evidence is uploaded even on failure and may
contain sensitive infrastructure details; restrict artifact access. If teardown
fails or the job is interrupted, use the saved state and `acceptance-*` tags to
inspect and finish sandbox cleanup before rerunning. KMS keys enter their
configured deletion waiting period. Do not mark acceptance successful if
cleanup failed, and do not delete production or pre-existing image resources.
Disable `ENABLE_CLOUD_ACCEPTANCE` again after finishing.

Attach this run/attempt ID and artifact alongside the full
[production deployment evidence](production-deployment-evidence.md). This test
supplements the separate deployment, health and rollback walkthrough; it does
not replace those gates.
