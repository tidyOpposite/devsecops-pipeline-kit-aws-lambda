# Upgrade Guide

Upgrade the CLI and its Terraform/workflow checkout together. Read the target
release notes before changing local configuration. Package upgrade, local
snapshot restore and AWS image rollback are separate operations.

## Current Schema

Current source and the published `v0.15.0` baseline use config schema `1`.
Legacy configs without `schema_version` normalize to `1`; missing
`api_authorization_type` defaults to `AWS_IAM`. A future `schema_version`
greater than this CLI supports is rejected before rendering or writing files.
Upgrade the CLI rather than manually lowering that version number.

## Before Upgrading

```bash
devsecops --version
devsecops config validate
devsecops config diff
devsecops snapshot list
```

Back up `.devsecops-pipeline.toml` and `.devsecops/`, including any lab state,
settings and evidence. Finish active CLI operations before switching versions.
Local configuration, Terraform state and credentials must stay outside Git.

## Install And Verify

Use the reviewed installer or source procedure in
[Distribution and compatibility](distribution.md#upgrade). The current installer
verifies a candidate before replacing the launcher; a failed upgrade preserves
the previous working CLI. Older published installers retain their old behavior.

```bash
devsecops --version
devsecops config validate
devsecops config diff
devsecops generate --dry-run
```

After reviewing the differences, run `devsecops generate` and `devsecops status`.
Generated files belong to the CLI; edit local configuration for durable changes.
An upgrade does not apply AWS changes or synchronize GitHub settings. Existing
lab plans become invalid when their bound source/provider/settings change:
review a new plan instead of attempting to reuse the old one.

## Existing Configurations And Scripts

| Change | Required action |
| --- | --- |
| Setup defaults | New `setup --yes` starts a local demo; saved modes resume. `--yes` does not authorize GitHub writes or replacing existing settings with a different preset. |
| Mode changes | Review the proposed diff. Use `--apply-mode-preset` only when explicitly accepting replacement; omitted authorization leaves existing settings intact. |
| Image validation | Real deployment images must be Lambda-compatible, in the correct account/region and immutable. Lab uses exact ECR digests. |
| CloudWatch retention | Values must be AWS-supported choices from `config schema`. Correct legacy production `1095` to `1096` with `config set environments.prod.log_retention_days 1096 --render`. |
| Health checks | Only HTTP 2xx succeeds; redirects are rejected. Use the final HTTPS endpoint and a positive timeout. |
| Project discovery | Commands from checkout subdirectories use the nearest project root and stop at nested Git boundaries. Keep a matching checkout alongside the installed CLI. |
| Demo status | `Demo complete` describes local checks. Production `status --strict`, `--pre-deploy` and `--deep` remain separate experimental checks. |
| Terminal input | EOF exits or pauses safely. Re-run `setup` to resume saved progress; noninteractive scripts should use explicit commands/flags. |

For the experimental GitHub/OIDC path, review its
[production walkthrough](experimental-production-walkthrough.md). Existing
pre-hardening deployments must configure `PIPELINE_CONFIG_JSON`, separate
plan/deploy roles, protected manual workflow dispatch and isolated sandbox
planning. Update those settings explicitly; a CLI package upgrade does not
migrate repository or IAM permissions.

## Recover From An Upgrade

If installation fails, keep using the existing launcher and inspect the
reported failed stage. If a verified new package behaves incorrectly, select a
previous release with the current installer and restore compatible local files:

```bash
devsecops snapshot list
devsecops snapshot show 1
devsecops snapshot restore --last --dry-run
devsecops snapshot restore --last
```

Snapshot restore is restricted to CLI-owned local paths. It does not restore
AWS resources, Terraform state, GitHub secrets or a deployed Lambda image.
Use the [rollback runbook](runbooks/failed-rollback.md) for cloud recovery and
[finish-demo](runbooks/finish-demo.md) for decommissioning.

## Schema Change Policy

Before releasing a schema change, increment `CONFIG_SCHEMA_VERSION`, implement
a deterministic migration, update schema help/release notes and test both
legacy loading and future-version refusal. Document required regeneration and
manual decisions. Migration affects local source config only; see the
[stability contract](stability-contract.md#config-migration-rules) and
[generated artifact contract](generated-artifacts.md).
