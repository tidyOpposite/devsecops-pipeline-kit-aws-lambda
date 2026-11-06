# Unreleased Hardening: 0.16.0.dev0

This is the current source development version, not a published release or a
production acceptance record. The published baseline is `v0.15.0`.

The hardening work addresses deployment policies and pinned intent, isolated
PR and scanner execution, resumable GitHub/OIDC setup, safe installer upgrades,
project discovery, a complete local demo, reviewed preset changes and terminal
input/output handling. It also adds a decommission runbook and separately
reviewed S3 version/multipart cleanup; live teardown acceptance remains pending.
See [Changelog](../CHANGELOG.md) and the
[product audit](product-audit-v0.15.0.md) for individual fixes and local evidence.

Install this checkout as documented in the [Quick Start](../README.md#quick-start).
Installing the published `v0.15.0` wheel will not install these fixes.

Final AWS/GitHub deployment and automatic/manual recovery evidence, the sandbox
runtime test, supported-platform acceptance and the remaining audit work are still required.
No production-ready or stable release is declared by these notes. After all
fixes, choose a new release version, synchronize package metadata and versioned
notes, and complete the [release checklist](release-checklist.md). Never replace
the `v0.15.0` tag or assets. The publication workflow deliberately refuses a
development-version tag such as `v0.16.0.dev0`.

The optional `examples/text-stats/` Lambda provides a stateless text analysis
workload and healthy/failing image variants for diploma acceptance. It does not
change production approval rules. Windows and WSL2 are unverified and outside
this release target; the platform transcript gate now requires macOS or supported
Ubuntu evidence instead. See [Diploma report](diploma-demonstration-report.md)
for the one-account constraints and the screenshot plan.
