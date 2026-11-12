# Documentation

Start with the [project Quick Start](../README.md#quick-start), then choose a
local demo or a [single-operator AWS lab](single-operator-lab.md).

## Use The CLI

| Guide | Covers |
| --- | --- |
| [Distribution and compatibility](distribution.md) | Source/release installation, verified downloads, supported tools and completion. |
| [First successful pipeline](first-successful-pipeline.md) | Local setup through a real AWS lab. |
| [Single-operator lab](single-operator-lab.md) | Authentication, saved plans, images, updates, recovery and requests. |
| [Upgrade guide](upgrade-guide.md) | Configuration compatibility, safe upgrades and local recovery. |
| [Troubleshooting](troubleshooting.md) | Diagnosis and corrective commands. |
| [Operational runbooks](runbooks/README.md) | Plan/apply/validation/rollback failures and cleanup. |
| [Text Stats Lambda](../examples/text-stats/README.md) | Optional demonstration application and A/B/C images. |
| [Bring your own image](bring-your-own-image.md) | Lambda container requirements and external build boundary. |
| [Cost estimation](cost-estimation.md) | Cost drivers and estimation limits. |

## Understand The Contracts

| Reference | Covers |
| --- | --- |
| [Command inventory](command-inventory.md) | Commands, aliases and experimental/support surfaces. |
| [Stability contract](stability-contract.md) | JSON, schema migration and compatibility promises. |
| [Generated artifacts](generated-artifacts.md) | Ownership, regeneration and snapshot boundaries. |
| [Security model](security-model.md) | Trust boundaries, threats and residual risks. |
| [Security controls](security-controls.md) | Presets and control behavior. |
| [Scanning tools](scanning-tools.md) | Scanner roles and limitations. |
| [Known limitations](known-limitations.md) | Supported scope and release gates. |

## Maintain And Release

- [Contributing and tests](../CONTRIBUTING.md), [CLI architecture](cli-architecture.md).
- [Release checklist](release-checklist.md), [single-operator evidence contract](single-operator-release-evidence.md).
- [Changelog](../CHANGELOG.md), [current prerelease notes](release-v0.16.0b2.md), [previous beta notes](release-v0.16.0b1.md), [roadmap](../ROADMAP.md).

## Experimental Production Integration

These guides describe a separate protected GitHub/OIDC path. Lab acceptance
makes no production acceptance claim.

- [Production walkthrough](experimental-production-walkthrough.md).
- [AWS IAM/OIDC policies](../AWS_policy.md) and [manual sandbox plans](sandbox-plans.md).
- [Production deployment evidence](production-deployment-evidence.md).
- [Scanner isolation and separate-account runtime acceptance](security-gate-acceptance.md).
