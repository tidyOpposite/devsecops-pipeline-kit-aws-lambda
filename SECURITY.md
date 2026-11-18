# Security Policy

DevSecOps Pipeline Kit is a CLI-first product for configuring and operating a
secure AWS Lambda deployment pipeline. The detailed threat model and control
mapping live in [docs/security-model.md](docs/security-model.md).

## Supported Versions

| Version | Supported |
| --- | --- |
| `v0.3.x` | Yes |
| `v0.2.x` | No |
| `v0.1.x` | No |

## Reporting A Vulnerability

Please do not open public issues for exploitable vulnerabilities. Report them
privately to the repository maintainer with:

* affected component and version or commit SHA;
* whether the issue affects the CLI, generated artifacts, Terraform modules,
  GitHub Actions workflow, or documentation;
* reproduction steps;
* expected impact;
* suggested fix, if known.

The maintainer should acknowledge receipt within 5 business days and publish a
fix or mitigation plan after triage.

## CLI Security Baseline

The CLI is the primary product surface and follows these safety rules:

* Local pipeline configuration is stored in `.devsecops-pipeline.toml`, which
  is ignored by Git.
* Local snapshots are stored under `.devsecops/snapshots/`, ignored by Git, and
  limited to CLI-owned config/generated files.
* Rollback creates a safety snapshot before restoring an older snapshot.
* Generated Terraform/GitHub helper artifacts are written under
  `dist/devsecops/` or other ignored paths.
* GitHub setup commands avoid printing secret values already stored in GitHub.
* Risky operations such as rollback require confirmation unless explicitly
  bypassed with a CLI flag.

## Pipeline Security Baseline

The execution layer managed by the CLI includes:

* GitHub Actions OIDC instead of long-lived AWS keys.
* Terraform S3 backend with DynamoDB state locking.
* Environment isolation through Terraform workspaces.
* Modular Terraform with KMS-encrypted private storage, ECR, Lambda, API
  Gateway, CloudWatch Logs, and SQS DLQ.
* API Gateway routes default to `AWS_IAM` authorization; public routes require
  explicitly setting `API_AUTHORIZATION_TYPE=NONE`.
* Trivy IaC scanning, optional Snyk container scanning, and optional OWASP ZAP
  DAST.
* Immutable image deployment through `LAMBDA_IMAGE_URI`.
* Automatic Lambda rollback on failed deployment validation.

## Known Security Exceptions

* Workload-level user identity, tenant isolation, and business authorization are
  outside this repository even though the generated API route defaults to IAM
  authorization.
* Application source, dependency scanning, and image build hardening are outside
  this repository and must be handled by the workload release process.
* CLI snapshots may contain local configuration values. They are ignored by Git
  but should still be treated as local operational data.
* The CLI can generate commands for GitHub secrets, but secret governance and
  rotation remain the operator's responsibility.
