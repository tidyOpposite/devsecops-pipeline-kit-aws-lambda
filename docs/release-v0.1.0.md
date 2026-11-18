# Release v0.1.0

Initial reference implementation release.

Note: current `Unreleased` documentation positions the terminal CLI as the
primary product surface. This historical release note describes the original
pipeline-engine baseline before that CLI-first product direction.

Highlights:

* Terraform workspaces for `dev`, `staging`, and `prod`.
* Modular AWS infrastructure.
* PR Terraform plans and production apply on merge to `main`.
* Immutable Lambda image deployments with automatic rollback.
* IaC scanning plus optional container and DAST gates.
* DynamoDB-backed Terraform state locking.
* Expanded architecture, security, cost, and troubleshooting documentation.
