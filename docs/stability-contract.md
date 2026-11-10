# Stability Contract

Current source: `0.16.0b2.dev0` (unpublished). Published prerelease:
`0.16.0b1` (`v0.16.0-beta.1`).

`lab` is a separate dev-only single-operator path. Its JSON kind is
`single-operator-lab`, with `production_acceptance=false`. Saved plans expire
after one hour and require an exact review hash and explicit `--yes` for apply.
Private state/evidence are documented in [the lab guide](single-operator-lab.md).
Previous published baseline: `v0.15.0`. Final acceptance is pending.

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
| First success | `devsecops`, `devsecops setup --mode --preset --apply-mode-preset --image-uri --backend-bucket --backend-region --backend-lock-table --apply-github --deploy-role-arn --plan-role-arn --snyk-token --generate --yes --strict`, `devsecops status --deep --pre-deploy --strict --format --watch --interval`, `devsecops dry-run --preset --image-uri --environment`, `devsecops image validate --image-uri --environment --format` |
| Deployment | `devsecops deploy prod --dry-run --yes --watch --interval`, `devsecops deploy status --run-id --watch --interval --format`, `devsecops deploy logs --run-id --failed`, `devsecops deploy rollback --run-id --image-uri --dry-run --yes --watch --interval` |
| Troubleshooting | `devsecops doctor local --deep --strict --format`, `devsecops doctor github --strict --format`, `devsecops doctor aws --environment --strict --format`, `devsecops doctor branch --branch --strict --format`, `devsecops doctor actions --limit --strict --format`, `devsecops doctor all --deep --branch --environment --strict --format` |
| Configuration and generation | `devsecops config validate --strict --format`, `devsecops config diff --preset --exit-code`, `devsecops generate --dry-run`, `devsecops report --deep --format --output --print` |
| Advanced release maintenance | `devsecops inventory --format --status`, `devsecops evidence collect --rc --output`, `devsecops criteria --format --evidence-dir --strict` |
| GitHub setup | `devsecops github setup --write --apply --repo --deploy-role-arn --plan-role-arn --snyk-token`, `devsecops github status --limit --strict --format`, `devsecops github branch --branch --strict --format`, `devsecops github doctor --repo --strict --format` |
| Terraform helpers | `devsecops terraform plan <environment> --no-init --create-workspace`, `devsecops terraform bootstrap --apply` |
| Decommission | `devsecops terraform teardown --format`, `devsecops terraform teardown bucket-plan --bucket --expected-account-id --region --purpose --output --format`, `devsecops terraform teardown bucket-purge --bucket --expected-account-id --region --manifest --sha256 --acknowledge-backup --allow-backend-cleanup --format` |
| Snapshots | `devsecops snapshot list --format`, `devsecops snapshot show <selection> --format`, `devsecops snapshot restore --to --last --dry-run --yes` |
| Completion and inventory | `devsecops completion <shell> --program`, `devsecops inventory --format --status` |

The documented first-success workflow does not depend on experimental
commands. `devsecops compose` and `devsecops tui` are intentionally outside the
first-success scripting path.

`devsecops setup` stores resumable workflow state in
`.devsecops/setup-state.json`. This local schema is fail-closed: unreadable,
unknown-mode, or future-version state is rejected rather than silently reset.
Observable stages are always recalculated, and a config change invalidates a
saved dry-run fingerprint. The state file may contain mode, timestamps, step
status, and non-secret check details; credentials, role secret values, GitHub
tokens, and Snyk tokens are forbidden. `--yes` authorizes safe local defaults
only. Repository mutation requires an interactive confirmation or the explicit
`--apply-github` flag.

Supplied setup arguments are validated before any setup progress, config or
snapshot writes and before provider inspection. Existing-config preset
replacements display the actual diff with project identity and backend kept.
Interactive acceptance defaults to keeping the config; canceling this review
does not update saved progress. Noninteractive replacement requires
`--apply-mode-preset`; `--yes` alone returns a validation error without writes
when replacement needs review. Accepted replacements create a recovery snapshot.
Selecting a mode by itself changes required checks and reuses compliant settings.

New setup defaults to local demo; a saved standard/production mode is resumed
unchanged. Normal status uses the saved demo scope and reconciles local config
and the current preview fingerprint. It adds `context.scope=demo` and
`demo_complete` to JSON, while production gates remain unverified. Explicit
`status --strict`, `--pre-deploy` and `--deep` retain production requirements.
The separate `setup --mode production` action begins cloud configuration.

`devsecops deploy prod` and `devsecops deploy rollback` store only non-secret
run metadata in `.devsecops/deployments.json`. Its schema is fail-closed and
history is bounded. Status and logs can reconcile the local journal once
GitHub confirms the request ID. Deploy and cloud rollback show the underlying
GitHub CLI command and require confirmation unless `--yes` is explicit.
The protected workflow serializes production runs. Inferred rollback reads the
recovery artifact from a completed, successful deployment attempt and verifies
that its deployed image is still active.

## Terminal Output And Closed Input

Menu shortcuts appear only in the interactive menu. Human guidance, boxes,
tables and prompts adapt to terminal width. Each next action prints its shell
command once; long commands remain literal on a separate line for copying.
Machine formats, generated scripts and config diffs are never prose-wrapped.

EOF exits `menu` with code `0` and pauses `setup` with code `0` at its saved
step. EOF before review approval does not update progress or config. Other
unhandled interactive EOFs return `130`; EOF never accepts a prompt's default
or authorizes changes. Malformed explicit health URLs fail as endpoint
validation with code `1` before signing or network access; the JSON health
envelope stays unchanged.

## Project Root And Relative Paths

The CLI discovers the project from the current directory and its ancestors.
The nearest local config or complete kit checkout is selected. A Git directory
or worktree marker stops searching for an outer project; a closer config also
defines a boundary even if required source files are missing. Without a match,
the current directory remains the boundary. Setup then reports missing project
files before writing config or progress.

Config, setup/deployment state, snapshots, generated artifacts and relative
report/evidence paths use this root. Absolute output paths retain their explicit
destination. The installed package directory is never used as a fallback root.

## JSON Output Contract

Teardown manifests use their own `schema_version=1`: exact bucket/account/region,
purpose, creation time, versioning status and version/upload metadata. They are
owner-only, bounded, never overwritten and expire for execution after one hour.
Purge verifies SHA-256, repeated scope, backup acknowledgment, live identity and
fresh inventory before mutations; partial errors or remaining data return `1`.
Backend purposes require the extra `--allow-backend-cleanup` decision. No helper
deletes buckets, ECR, keys or Terraform state infrastructure automatically.

JSON output is stable by `kind`. Fields may be added within the same
`schema_version`, but existing documented keys will not be renamed or removed
without a deprecation window.

| Kind | Commands | Stable keys |
| --- | --- | --- |
| `config` | `devsecops config validate --format json` | `kind`, `schema_version`, `score`, `overall_breakdown_score`, `breakdown`, `gaps`, `checks` |
| `status` | `devsecops status --format json` | `kind`, `schema_version`, `score`, `breakdown`, `gaps`, `checks`, `context`, `next_action` |
| `image-validation` | `devsecops image validate --format json` | `kind`, `schema_version`, `score`, `breakdown`, `gaps`, `checks`, `context` |
| `deployment-status` | `devsecops deploy status --format json` | `kind`, `schema_version`, `environment`, `operation`, `deployment_result`, `deployment_detail`, `request_id`, `run_confirmation`, `requested_image_uri`, `previous_image_uri`, `active_image_uri`, `run`, `jobs` |
| `readiness` | `devsecops readiness --format json` (compatibility alias) | Existing legacy keys remain stable. |
| `preflight` | `devsecops preflight --format json` (compatibility alias) | Existing legacy keys remain stable. |
| `health` | `devsecops health --format json` | `kind`, `schema_version`, `score`, `overall_breakdown_score`, `breakdown`, `gaps`, `checks`, `context` |
| `github-actions-status` | `devsecops github status --format json`, `devsecops doctor actions --format json` | `kind`, `schema_version`, `error`, `runs`, `failed_jobs`, `failed_steps`, `next_actions` |
| `aws-outputs` | `devsecops aws outputs --format json` | `kind`, `schema_version`, `environment`, `outputs`, `checks`, `next_actions` |
| `snapshots` | `devsecops snapshot list --format json` | `kind`, `schema_version`, `snapshots` |
| `snapshot` | `devsecops snapshot show --format json` | `kind`, `schema_version`, `snapshot` |
| `audit-evidence` | `devsecops report --format json` | `kind`, `schema_version`, `cli_version`, `project`, `readiness`, `config_validation`, `controls` |
| `next-action` | `devsecops next --format json` (compatibility alias) | `kind`, `schema_version`, `context`, `action`, `command`, `detail`, `why`, `changes`, `blocked`, `docs` |
| `release-candidate-evidence` | `devsecops evidence collect --rc` | `kind`, `schema_version`, `generated_at`, `output_dir`, `files`, `terraform_validate` |
| `v1-criteria` | `devsecops criteria --format json` | `kind`, `schema_version`, `cli_version`, `stable_ready`, `criteria`, `stable_release_gates`, `next_actions` |
| `teardown-guide` | `devsecops terraform teardown --format json` | `kind`, `schema_version`, `docs`, `phases`, `message` |
| `teardown-bucket-plan` | `devsecops terraform teardown bucket-plan --format json` | `kind`, `schema_version`, `manifest`, `sha256`, `bucket`, `purpose`, `object_versions`, `multipart_uploads`, `message` |
| `teardown-bucket-purge` | `devsecops terraform teardown bucket-purge --format json` | `kind`, `schema_version`, `bucket`, `status`, `deleted_versions`, `aborted_uploads`, `message` |
| `control-catalog` | `devsecops controls --format json` | `kind`, `schema_version`, `controls` |
| `command-inventory` | `devsecops inventory --format json` | `kind`, `schema_version`, `commands`, `deprecation_policy`, `json_outputs`, `generated_artifacts` |

Config syntax and structure errors in JSON commands return a `command-error`
envelope with `kind`, `schema_version`, `command`, `error`, and `exit_code`.
They use exit code 1 rather than an unexpected-runtime code.
`status --pre-deploy --strict` verifies deployment prerequisites.
`status --deep --strict` also requires a healthy deployed workload. The flags
`--pre-deploy` and `--deep` are mutually exclusive. Compact status leaves
provider checks unverified. Informational checks are excluded from both scores
and gaps. Use `criteria --strict` to verify release evidence.

`deploy status` reports `deployment_result` as `unconfirmed`, `pending`,
`success`, or `failed`. A completed operation succeeds only when the
workflow, production job, and required apply/health or restore steps succeeded.
`skipped`, `neutral`, and missing production results return exit code 1.
An observation of a pending run returns 0. With `--watch`, an unconfirmed or
incomplete run returns a non-zero code. The raw GitHub conclusion remains in
`run.conclusion`.

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
* document whether `devsecops generate`, `devsecops report`, or
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
| `.devsecops/deployments.json` | Schema-versioned local runtime state | A protected deploy or rollback dispatch succeeds | One non-secret run/image record is prepended; bounded history only |
| `terraform/generated.auto.tfvars` | Stable Terraform variables | Config values, schema migration output, or Terraform variable contract changes | HCL assignment values and `environment_config` values |
| `dist/devsecops/backend.tf` | Stable review template | `backend.*` values or backend template policy changes | S3 backend attribute values |
| `dist/devsecops/backend.hcl` | Stable backend inputs | `backend.*` values change | Partial backend assignments for `terraform init -backend-config` |
| `dist/devsecops/github-variables.env` | Stable helper | Repository variable source config changes | `PROJECT_NAME`, `LAMBDA_IMAGE_URI`, `ENABLE_*`, or `PROD_APPROVAL_ENVIRONMENT` values |
| `dist/devsecops/github-setup.sh` | Stable helper script | GitHub setup contract changes | Validated CLI invocation, explicit destination, setup options, header changes |
| `dist/devsecops/setup-checklist.md` | Stable checklist | GitHub, backend, or branch-protection checklist contract changes | Checklist item values or required item additions |
| `dist/devsecops/readiness-report.md` | Stable report | Readiness checks, config values, or environment state changes | Generated timestamp, score/check/action rows |
| `dist/devsecops/audit-report.json` | Stable JSON evidence | Audit evidence, readiness, config, or control state changes | `generated_at` timestamp and changed readiness/config/control payloads |
| `dist/devsecops/evidence/rc/manifest.json` | Stable JSON evidence manifest | Release-candidate evidence is collected | `generated_at`, evidence file list, and Terraform validation status |
