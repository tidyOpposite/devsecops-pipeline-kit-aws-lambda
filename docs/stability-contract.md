# Stability Contract

Target release: `v0.13.1`.

This contract explains which `devsecops` surfaces are stable enough to script
against before `v1.0.0`, which surfaces are compatibility aliases or
experimental, and what migration behavior users can expect.

## Stability Levels

| Level | Contract |
| --- | --- |
| Stable | Command names, documented flags, exit codes, generated file paths, and documented JSON `kind` shapes remain compatible within normal semver expectations. |
| Alias | Compatibility command that remains callable through at least `v1.0.0`. New scripts should use the grouped stable command named in the inventory. |
| Experimental | Useful but not part of the first-success or scripting contract. Command shape, grouping, prompts, or output can change in a `0.x` minor release. |
| Support | Human inspection or explanation output. Stable enough for operators, but prose and table layout may change. |

Run the machine-readable inventory with:

```bash
devsecops inventory --format json
devsecops inventory --status stable --format markdown
```

## Stable Command Groups

| Workflow | Stable commands and flags |
| --- | --- |
| First success | `devsecops`, `devsecops next --format`, `devsecops start --preset --render --yes`, `devsecops config new --preset --force --render`, `devsecops config validate --strict --format`, `devsecops config diff --preset --exit-code`, `devsecops dry-run --preset --image-uri --environment`, `devsecops preflight --image-uri --environment --format` |
| Diagnostics | `devsecops readiness --deep --strict --format`, `devsecops doctor local --deep --strict --format`, `devsecops doctor github --strict --format`, `devsecops doctor aws --environment --strict --format`, `devsecops doctor branch --branch --strict --format`, `devsecops doctor actions --limit --strict --format`, `devsecops doctor all --deep --branch --environment --strict --format` |
| Rendering and reports | `devsecops render --dry-run`, `devsecops report --deep --format --output --print`, `devsecops evidence collect --rc --output`, `devsecops criteria --format --evidence-dir --strict` |
| GitHub setup | `devsecops github setup --write --apply --deploy-role-arn --plan-role-arn --snyk-token`, `devsecops github status --limit --strict --format`, `devsecops github branch --branch --strict --format`, `devsecops github doctor --strict --format` |
| Terraform helpers | `devsecops terraform plan <environment> --no-init --create-workspace`, `devsecops terraform bootstrap --apply` |
| Snapshots | `devsecops snapshot list --format`, `devsecops snapshot show <selection> --format`, `devsecops snapshot restore --to --last --dry-run --yes` |
| Completion and inventory | `devsecops completion <shell> --program`, `devsecops inventory --format --status` |

The documented first-success workflow does not depend on experimental
commands. `devsecops compose` and `devsecops tui` are intentionally outside the
first-success scripting path.

## JSON Output Contract

JSON output is stable by `kind`. Fields may be added within the same
`schema_version`, but existing documented keys will not be renamed or removed
without a deprecation window.

| Kind | Commands | Stable keys |
| --- | --- | --- |
| `config` | `devsecops config validate --format json` | `kind`, `schema_version`, `score`, `overall_breakdown_score`, `breakdown`, `gaps`, `checks` |
| `readiness` | `devsecops readiness --format json` | `kind`, `schema_version`, `score`, `overall_breakdown_score`, `breakdown`, `gaps`, `checks`, `context` |
| `preflight` | `devsecops preflight --format json` | `kind`, `schema_version`, `score`, `overall_breakdown_score`, `breakdown`, `gaps`, `checks`, `context` |
| `health` | `devsecops health --format json` | `kind`, `schema_version`, `score`, `overall_breakdown_score`, `breakdown`, `gaps`, `checks`, `context` |
| `github-actions-status` | `devsecops github status --format json`, `devsecops doctor actions --format json` | `kind`, `schema_version`, `error`, `runs`, `failed_jobs`, `failed_steps`, `next_actions` |
| `aws-outputs` | `devsecops aws outputs --format json` | `kind`, `schema_version`, `environment`, `outputs`, `checks`, `next_actions` |
| `snapshots` | `devsecops snapshot list --format json` | `kind`, `schema_version`, `snapshots` |
| `snapshot` | `devsecops snapshot show --format json` | `kind`, `schema_version`, `snapshot` |
| `audit-evidence` | `devsecops report --format json` | `kind`, `schema_version`, `cli_version`, `project`, `readiness`, `config_validation`, `controls` |
| `next-action` | `devsecops next --format json` | `kind`, `schema_version`, `context`, `action`, `command`, `detail`, `why`, `changes`, `blocked`, `docs` |
| `release-candidate-evidence` | `devsecops evidence collect --rc` | `kind`, `schema_version`, `generated_at`, `output_dir`, `files`, `terraform_validate` |
| `v1-criteria` | `devsecops criteria --format json` | `kind`, `schema_version`, `cli_version`, `stable_ready`, `criteria`, `stable_release_gates`, `next_actions` |
| `control-catalog` | `devsecops controls --format json` | `kind`, `schema_version`, `controls` |
| `command-inventory` | `devsecops inventory --format json` | `kind`, `schema_version`, `commands`, `deprecation_policy`, `json_outputs`, `generated_artifacts` |

## Deprecation Policy

Aliases remain callable through at least `v1.0.0`. They can be hidden from
top-level help, but must keep dispatching to the documented target command
until a release note announces removal.

Experimental commands can change in any `0.x` minor release. They must not be
required by the README quick start, first-success guide, release checklist, or
production evidence workflow.

JSON output formats are additive within a `schema_version`. Removing or
renaming a documented key requires a new schema version and release-note
migration guidance.

Config fields can be added, renamed, or removed only through a schema-versioned
migration. The migration must be deterministic, tested, documented in
[Upgrade guide](upgrade-guide.md), and reflected in generated-artifact
compatibility notes before release.

## Config Migration Rules

Current config schema version: `1`.

Legacy `.devsecops-pipeline.toml` files without `schema_version` are treated
as schema version `1` and normalized with current defaults.

Configs with `schema_version` greater than the current CLI supports are
refused before rendering or changing CLI-owned files. Users must upgrade the
CLI first.

Every future schema-changing release must:

* increment `CONFIG_SCHEMA_VERSION`;
* add a deterministic `migrate_config` step for each version hop;
* update `devsecops config schema --format json` and `--format markdown`;
* add tests for legacy load, migrated output, future-version refusal, and
  rollback expectations;
* document whether `devsecops render`, `devsecops report`, or
  `devsecops github setup --write` must be rerun.

Rollback after migration is local only. Snapshot restore can recover
`.devsecops-pipeline.toml`, `terraform/generated.auto.tfvars`, and generated
files under `dist/devsecops/`. It never mutates AWS resources, Terraform
state, GitHub variables/secrets, GitHub Actions runs, or deployed Lambda
images.

## Generated Artifact Compatibility

Generated artifacts are deterministic outputs of local source config and CLI
generator code. Re-render after a config migration, a config value change, or a
release note that explicitly changes the artifact contract.

| File | Compatibility | Re-render required when | Expected diffs |
| --- | --- | --- | --- |
| `terraform/generated.auto.tfvars` | Stable Terraform variables | Config values, schema migration output, or Terraform variable contract changes | HCL assignment values and `environment_config` values |
| `dist/devsecops/backend.tf` | Stable review template | `backend.*` values or backend template policy changes | S3 backend attribute values |
| `dist/devsecops/github-variables.env` | Stable helper | Repository variable source config changes | `PROJECT_NAME`, `LAMBDA_IMAGE_URI`, `ENABLE_*`, or `PROD_APPROVAL_ENVIRONMENT` values |
| `dist/devsecops/github-setup.sh` | Stable helper script | GitHub variable or required secret contract changes | `gh variable` commands, Snyk token requirement, header changes |
| `dist/devsecops/setup-checklist.md` | Stable checklist | GitHub, backend, or branch-protection checklist contract changes | Checklist item values or required item additions |
| `dist/devsecops/readiness-report.md` | Stable report | Readiness checks, config values, or environment state changes | Generated timestamp, score/check/action rows |
| `dist/devsecops/audit-report.json` | Stable JSON evidence | Audit evidence, readiness, config, or control state changes | `generated_at` timestamp and changed readiness/config/control payloads |
| `dist/devsecops/evidence/rc/manifest.json` | Stable JSON evidence manifest | Release-candidate evidence is collected | `generated_at`, evidence file list, and Terraform validation status |
