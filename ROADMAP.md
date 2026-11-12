# Roadmap

Current source: `0.16.0b2.dev0` (unpublished), following `v0.16.0-beta.1`.
The previous published baseline is `v0.15.0`. Version 1.0 has not been released.
Completed changes belong in the [changelog](CHANGELOG.md).

## Version 1.0 Scope

The target is the local CLI and single-operator AWS dev lab in one account:

- Guided local setup, configuration validation and deterministic generation.
- Explicit account/region, immutable images and reviewed saved Terraform plans.
- Signed health checks, update recovery, manual rollback and local evidence.
- Installation and upgrade recovery on macOS and Debian 13.
- Reviewed retention, backups/restore and resource cleanup.

GitHub/OIDC production workflows and separate-account runtime acceptance remain
experimental. Windows/WSL2 and PyPI distribution are outside this release target.

## Before A Stable Release

1. Select the release version and freeze its commit and successful CI wheel.
2. Complete both platform records and the AWS lab lifecycle/cleanup against
   that same candidate, following the [release evidence contract](docs/single-operator-release-evidence.md).
3. Run `devsecops criteria --strict` with the candidate evidence and GitHub/asset
   verification. Attach the checked bundle before the owner authorizes a tag.

Candidate-specific results and screenshots stay outside Git. Documentation
requirements do not imply that a particular release candidate has passed.
See the [release checklist](docs/release-checklist.md) for publication steps.

## Later Work

- Independently accept the protected production/OIDC path in a separate sandbox.
- Add platform support only when install, operation and recovery are verified.
- Consider shared deployment history, additional scanner integrations and PyPI
  after the current operator workflow is stable.
