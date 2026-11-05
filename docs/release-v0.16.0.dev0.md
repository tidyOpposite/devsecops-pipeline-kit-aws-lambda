# Unreleased Hardening: 0.16.0.dev0

This is the current source development version, not a published release or a
production acceptance record. The published baseline is `v0.15.0`.

The hardening work addresses deployment policies and pinned intent, isolated
PR and scanner execution, resumable GitHub/OIDC setup, safe installer upgrades,
project discovery, a complete local demo, reviewed preset changes and terminal
input/output handling. See [Changelog](../CHANGELOG.md) and the
[product audit](product-audit-v0.15.0.md) for individual fixes and local evidence.

Install this checkout as documented in the [Quick Start](../README.md#quick-start).
Installing the published `v0.15.0` wheel will not install these fixes.

Final AWS/GitHub deployment and automatic/manual recovery evidence, the sandbox
runtime test, WSL2 acceptance and the remaining audit work are still required.
No production-ready or stable release is declared by these notes. After all
fixes, choose a new release version, synchronize package metadata and versioned
notes, and complete the [release checklist](release-checklist.md). Never replace
the `v0.15.0` tag or assets. The publication workflow deliberately refuses a
development-version tag such as `v0.16.0.dev0`.
