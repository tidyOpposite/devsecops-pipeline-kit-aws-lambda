# Upgrade Guide

This guide documents upgrade behavior for CLI releases and config schema
changes. It must be updated before a release ships any change to
`.devsecops-pipeline.toml` semantics.

The broader stability and deprecation policy is documented in
[Stability contract](stability-contract.md).

## Current Schema

`v0.14.0` uses config schema version `1`.

There is no config schema migration in `v0.14.0`. Existing
`.devsecops-pipeline.toml` files with `schema_version = 1`, or legacy files
without the field, continue to normalize to schema version `1`.
The additive `api_authorization_type` field defaults to `AWS_IAM` when missing.

If the local config has a future `schema_version` greater than this CLI
supports, the CLI refuses to load it before rendering or changing CLI-owned
files. Upgrade the CLI first.

## Upgrading To v0.15.0

Config schema remains version 1. The deployment workflow now requires the
complete `PIPELINE_CONFIG_JSON` repository variable instead of falling back to
Terraform template values. Update the workflow and CLI together in each user's
deployment repository, review the local configuration, then run:

```bash
devsecops config validate
devsecops generate
devsecops github setup --apply
devsecops doctor github --strict
devsecops status --deep --strict
```

The `--apply` command updates that repository's settings; it is not a deploy.
Existing role secrets can be kept by omitting role arguments. Secrets and
personal configuration must not be committed to the public kit. The new ignored
`dist/devsecops/backend.hcl` replaces the need to copy backend names into tracked
source. Review any state migration requested by Terraform after a backend change.

Configure required reviewers in Settings > Environments > `prod`. Production
jobs always select `prod`; disabling a local demo approval flag cannot redirect
the production workflow to an unprotected environment. Inspection failures
remain blockers until the protection can be verified.

Compact status explicitly leaves cloud readiness unverified, so production
scripts must use `status --deep --strict`. Invalid image dry-runs and setup
outside a project now return non-zero. Invalid config writes are rejected;
expected config errors in JSON mode use the `command-error` envelope.
Generated output drift now requires regeneration. Informational checks no longer
reduce category scores. The menu resumes saved setup and supports confirmed
production deployment and rollback directly.

## AWS Constraints And Bucket Names

CloudWatch retention now uses the AWS-supported discrete values shown by
`devsecops config schema`. The `enterprise` preset uses 1096 days for
production. If an older config contains 1095, correct it explicitly and
regenerate the deployment inputs:

```bash
devsecops config set environments.prod.log_retention_days 1096 --render
devsecops config validate
```

Existing source files keep their saved value until edited. Synchronize the
reviewed configuration with GitHub before the next deployment.

Project names still support 3–32 characters. Valid existing access-log and
workload bucket names keep their physical names. A generated name exceeding
63 characters or using a reserved S3 prefix becomes `kit-<first-42-characters>-<16-character-SHA256>`.
The hash includes the full original name, including environment, purpose,
and account ID. Storage and its KMS encryption context use the same naming
module. Run `terraform init` after updating the checkout so Terraform loads
the new local module, then review the plan in the existing workspace.

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

Validate the existing config before generating deployment files:

```bash
devsecops config validate
devsecops config schema --format markdown
devsecops config diff
devsecops generate --dry-run
```

Only generate files after reviewing the dry-run output:

```bash
devsecops generate
devsecops status --format compact
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
* document whether generated files must be regenerated;
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
| `1` | `2` | Describe the exact fields added, renamed, or transformed. | Describe every required operator decision before `devsecops generate`. |

## Rollback After Upgrade

If an upgraded CLI generates unexpected helper artifacts:

```bash
devsecops snapshot list
devsecops snapshot show 1
devsecops snapshot restore --last --dry-run
devsecops snapshot restore --last
```

Snapshot restore only affects local CLI-owned files. It does not roll back
cloud deployments. Use GitHub Actions deployment rollback and the operational
runbooks for cloud failures.
