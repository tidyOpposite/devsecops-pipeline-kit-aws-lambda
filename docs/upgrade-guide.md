# Upgrade Guide

This guide documents upgrade behavior for CLI releases and config schema
changes. It must be updated before a release ships any change to
`.devsecops-pipeline.toml` semantics.

The broader stability and deprecation policy is documented in
[Stability contract](stability-contract.md).

## Current Schema

`v0.13.0` uses config schema version `1`.

There is no config schema migration in `v0.13.0`. Existing
`.devsecops-pipeline.toml` files with `schema_version = 1`, or legacy files
without the field, continue to normalize to schema version `1`.
The additive `api_authorization_type` field defaults to `AWS_IAM` when missing.

If the local config has a future `schema_version` greater than this CLI
supports, the CLI refuses to load it before rendering or changing CLI-owned
files. Upgrade the CLI first.

## Standard Upgrade Flow

Before upgrading:

```bash
devsecops --version
devsecops config validate
devsecops config diff
```

Upgrade the package:

```bash
PYTHON="${PYTHON:-python3.11}"
"${PYTHON}" -m pipx install --force --python "${PYTHON}" "devsecops-pipeline-cli @ ${WHEEL_URL}"
devsecops --version
```

Validate the existing config before rendering:

```bash
devsecops config validate
devsecops config schema --format markdown
devsecops config diff
devsecops render --dry-run
```

Only render after reviewing the dry-run output:

```bash
devsecops render
devsecops readiness --format compact
```

## Schema Change Policy

Any future release that changes config schema behavior must document the change
before it ships:

* increment `CONFIG_SCHEMA_VERSION`;
* update `migrate_config` with deterministic migration behavior;
* update `config_schema` and `config_schema_markdown`;
* add tests for legacy config loading and the migrated output;
* add tests that future schema versions fail closed before generated files are
  written;
* add tests that generated artifact paths still match the compatibility
  contract;
* add changelog and release-note upgrade sections;
* document whether generated files must be re-rendered;
* document rollback expectations for CLI-owned files.

## Migration Behavior

The CLI migration boundary is local source config only:

* `.devsecops-pipeline.toml` is user-owned local source config.
* `terraform/generated.auto.tfvars` and `dist/devsecops/*` are generated
  outputs and should be regenerated after config changes.
* Local snapshot restore can recover CLI-owned files from previous local states.
* Config migration does not mutate AWS resources, Terraform state, GitHub
  variables, GitHub secrets, or deployed Lambda images.
* A CLI that does not understand a future schema version must stop before
  writing generated artifacts.

Expected release-note format for schema changes:

| From | To | Automatic behavior | Manual action |
| --- | --- | --- | --- |
| `1` | `2` | Describe the exact fields added, renamed, or transformed. | Describe every required operator decision before `devsecops render`. |

## Rollback After Upgrade

If an upgraded CLI renders unexpected helper artifacts:

```bash
devsecops snapshot list
devsecops snapshot show 1
devsecops snapshot restore --last --dry-run
devsecops snapshot restore --last
```

Snapshot restore only affects local CLI-owned files. It does not roll back
cloud deployments. Use GitHub Actions deployment rollback and the operational
runbooks for cloud failures.
