# Release v0.14.0

`v0.14.0` consolidates the CLI around one resumable setup journey, one shared
status and next-action surface, and a protected production deployment flow.

## Highlights

* `devsecops setup` now guides and resumes a nine-stage flow across `demo`,
  `standard`, and `production` modes without persisting credentials or tokens.
* `devsecops status` reports the shared next action, while primary help focuses
  on eight first-route commands and keeps existing aliases callable.
* Production deploy, status, logs, and rollback commands share a bounded local
  deployment journal and the same protected GitHub Actions workflow.
* Setup and deployment state are schema-versioned, fail closed on unsupported
  data, and invalidate stale progress when project inputs change.
* Help, completion, documentation, and machine-readable contracts now use the
  same setup, image validation, generation, and deployment terminology.

## Deployment Safety

Production deploy and rollback reject concurrent runs, require confirmation,
and use the configured GitHub Environment, OIDC roles, Terraform state,
scanner gates, and immutable Lambda image references. Automatic rollback now
captures the active Lambda `Code.ImageUri` before deployment so the real prior
image is available to the workflow and local journal.

## Compatibility

There are no config-schema migrations in this release. Config schema version
remains `1`, and existing `.devsecops-pipeline.toml` files continue to work.
The `start`, `next`, `readiness`, `dashboard`, `preflight`, `render`, and
`--render` compatibility aliases remain callable with their existing JSON
contracts.

Python 3.11, 3.12, 3.13, and 3.14 remain supported.

## Upgrade

After installing `v0.14.0`, run `devsecops status` in an existing project. Use
`devsecops setup` to start or resume the consolidated flow. Review
`devsecops generate --dry-run` before regenerating CLI-owned files.
