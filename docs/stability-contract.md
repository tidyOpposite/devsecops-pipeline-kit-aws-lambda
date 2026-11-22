# Stability Contract

Stable `v1.0.0` covers the local CLI and a dev lab operated in one AWS account.
GitHub/OIDC production workflows have a separate experimental acceptance process.
See the [lab release evidence contract](single-operator-release-evidence.md).

`lab` returns JSON with kind `single-operator-lab` and `production_acceptance=false`.
Saved plans expire after one hour. Apply requires the plan ID, review SHA-256 and
explicit `--yes`. Local changes to concurrency invalidate saved plans. The lab
supports shared-pool mode (`-1`); the protected workflow requires a positive
reservation. See the [lab guide](single-operator-lab.md).

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

See [Command inventory](command-inventory.md) and run
`devsecops inventory --status stable --format markdown` for the stable command
groups and flags for your installed version.

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

Regenerate after a config change, schema migration or documented change to the
generator contract. The [generated artifacts reference](generated-artifacts.md)
lists file ownership, compatibility and expected diffs.
