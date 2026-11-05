# Upgrade Guide

This guide documents upgrade behavior for CLI releases and config schema
changes. It must be updated before a release ships any change to
`.devsecops-pipeline.toml` semantics.

The broader stability and deprecation policy is documented in
[Stability contract](stability-contract.md).

## Current Schema

The current `0.16.0.dev0` source and published `v0.15.0` use config schema version `1`.

There is no schema migration between `v0.15.0` and this hardening source. Existing
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
devsecops github setup --apply --repo OWNER/REPO
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

Create `prod` before applying setup. Setup inspects both repository and `prod`
secrets and preserves the effective scope of existing deploy-role and Snyk
secrets. The plan-role secret must be repository-scoped. To replace role secrets,
supply both `--deploy-role-arn` and `--plan-role-arn`; valid, distinct IAM roles
are required. If a write fails, setup reports each operation and leaves
`PIPELINE_CONFIG_JSON` blocked until synchronization completes. Retry with the
same arguments and pinned `--repo OWNER/REPO`.

Regenerate `dist/devsecops/github-setup.sh`: it now delegates to the installed
CLI and requires `OWNER/REPO` as its first argument. After updating `main`, run
`verify-oidc.yml` manually from `main` during final cloud acceptance. It checks
the plan and production roles in separate jobs, including their STS identities.
`doctor github --strict` requires a successful verification on current `main`
that is newer than both effective role secrets. Repeat verification after a
role-secret or `main` change, then run:

```bash
devsecops doctor github --repo OWNER/REPO --strict
devsecops status --pre-deploy --strict
# After deployment, verify the workload as well:
devsecops status --deep --strict
```

Compact status explicitly leaves cloud readiness unverified, so production
scripts must use `status --deep --strict`. Invalid image dry-runs and setup
outside a project now return non-zero. Invalid config writes are rejected;
expected config errors in JSON mode use the `command-error` envelope.
Generated output drift now requires regeneration. Informational checks no longer
reduce category scores. The menu resumes saved setup and supports confirmed
production deployment and rollback directly.

## Pull Requests And Sandbox Planning

All PRs now run without AWS credentials. Remove `:pull_request` and branch
wildcards from the plan role's IAM trust policy; only the exact main-branch
subject is supported. Updating workflow files alone does not update IAM.
Replace the `Terraform Plan` required branch check with `Terraform Format and
Validate`, retaining `Security and Terraform Validate`.

The template repository requires no AWS settings for PR checks. Optional
AWS-backed sandbox plans in deployment repositories require
`ENABLE_AWS_PLAN=true`, a separate state bucket/lock table in `PLAN_BACKEND_JSON`,
and manual dispatch from `main` with `mode=plan`, `environment=dev`.
Other plan environments and refs are rejected before AWS access. The protected
production job still plans against the deployment backend before applying.
Follow [Manual sandbox plans](sandbox-plans.md) to configure the independent
backend. Existing `github setup` commands retain these optional variables.

## Health And Production Evidence

Public and IAM-protected `health` checks now require HTTP 2xx and reject
redirects. Use the final endpoint URL and a positive `--timeout` (default 20
seconds). The deployment smoke step uses the same check, with a one-minute
workflow step limit in addition to the HTTP timeout.

Existing production evidence bundles need `terraform-context.json` and
`health-status.txt`. Follow the updated production evidence runbook to
initialize the configured backend, select the existing `prod` workspace and
capture the independently confirmed AWS account, backend identifiers and live
Lambda digest. The evidence gate rejects inconsistent context; HTTP 204 may
have an empty `health-response.txt` body.

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

## Security Scanner And Runtime Acceptance

Update the workflow and CLI together: the production job now builds the
digest/version-pinned scanner in `tools/snyk/Dockerfile` before AWS access and
scans an exported image archive in an unprivileged container. Remove older
`npm install -g snyk` and ECR-login steps when updating a customized workflow.
The trusted runner needs Docker and disk for the image plus archive; Snyk
receives only the scan token and read-only archive. No new scan role is needed.

Trivy uses the pinned engine's embedded checks instead of a moving downloaded
policy bundle; CI pins its optional Rich version. Dependabot targets the root
Python project, the scanner Dockerfile and actual Terraform directories.

The new AWS runtime acceptance workflow is disabled by default and requires
a dedicated account, separate role, protected `acceptance` environment and
explicit final-stage opt-in. CI rehearses its fixture using a mock provider;
it never runs real AWS tests. Follow [Security gate acceptance](security-gate-acceptance.md)
for permissions, variables, evidence and cleanup. The fixture requires
Terraform 1.10.5 or newer; the manual workflow pins 1.10.5.

## Decommissioning

The new `terraform teardown` guide changes nothing and makes no provider calls.
Its bucket-plan/purge helpers use separately reviewed, expiring version/upload
manifests; permanent S3 deletion is never implied by opening the guide or menu.
Follow [Finish demo](runbooks/finish-demo.md) for backup decisions, ECR, workload
workspaces and the separately approved backend phase. Both Terraform roots add
an optional `expected_account_id` provider guard for manual operations; existing
deployment defaults stay compatible. Live teardown acceptance remains pending.

## Terminal Layout And Closed Input


Ordinary status, dry-run and TUI reports no longer advertise menu keys. The
menu lists its working `[i] Readiness details` action explicitly and keeps
completed-demo details in local scope. Prose, boxes, tables and prompts adapt
to terminal width and account for ANSI colors and wide characters. Long shell
commands stay literal on a separate line, once per next action; machine
formats and config diffs are unchanged.

`menu </dev/null` now exits normally (`0`). Setup pauses on EOF (`0`) and can
resume, while EOF at preset review preserves existing config and progress.
Other interactive EOFs return `130`, without accepting defaults or confirmations.
Malformed health URLs are endpoint validation failures (`1`), including invalid
ports, empty arguments and unencoded whitespace. They do not reach the network
or SigV4 signing and no longer appear as internal errors.

## Reviewed Setup Mode Changes

`setup --mode production --yes` no longer silently replaces existing policy
or per-environment settings. When the config needs the selected mode preset,
setup prints the exact diff and returns a validation error without changing
config, progress, snapshots or generated files. Review it, then rerun with
`--apply-mode-preset` and the same options to accept replacement explicitly.
The flag also allows a deliberate preset replacement when mode requirements
already pass. Without a replacement request, compliant settings are reused.

Interactive setup displays the same diff before saving; Enter keeps existing
settings and leaves unmet requirements pending. Canceling at review preserves
saved progress too. Accepted changes retain project, region, image, admin role
and backend, and create a recovery snapshot. Invalid supplied image/backend/role
arguments or incompatible options fail before any setup writes or provider calls.
Update scripts that relied on `--yes` to replace existing settings.

## Demo Completion And Status Scope

For a new setup, `setup --yes` and Enter at the mode prompt select local demo
with the `student-demo` preset. Existing saved modes and explicit presets/modes
keep their meaning. Demo completion now says `Demo complete`, previews `dev`,
and ordinary status/menu/TUI surfaces show local checks without production
backend or credential gaps. The sample image is never saved as a real workload.
The legacy `dashboard` command also uses the local demo view by default;
explicit `dashboard --mode full` keeps the cloud diagnostics view.

`status --format json` in demo scope adds `context.scope=demo` and
`demo_complete`; the score describes local demo checks. Production readiness
gates remain unverified. Existing `status --strict`, `--pre-deploy` and `--deep`
continue to require production evidence, even in a demo project. Use the
separate interactive `setup --mode production` action (also menu option `7`
after demo completion) to connect cloud deployment. Config drift invalidates
the demo preview and requires a local setup refresh.

## Project Root Discovery

Commands can now run from subdirectories of a kit checkout. The CLI searches
upward from the caller for a local config or complete project sources and
stops at the nearest Git repository boundary. Config, progress, snapshots,
generated files and relative report/evidence paths use the discovered root.
A closer config takes precedence even if that nested checkout is incomplete.
Outside a project, the current directory remains the boundary; setup reports
missing source files and does not create progress or configuration there.

The installed wheel still contains only the CLI. Use the updated Quick Start's
`git clone` and `cd` steps to obtain Terraform and workflows before setup.

## Installer Upgrade Safety

The updated installer keeps the active environment while preparing a replacement
under `<install-dir>/environments/venv-*`. It validates both CLI startup and the
temporary launcher's `--version` against the selected release, then atomically
replaces the launcher within its existing bin directory. A failed venv, pip,
optional TUI install, startup check or activation preserves the working CLI.
Legacy installer-managed `<install-dir>/venv` installations migrate without
deleting that environment. Unmanaged environments and unrelated launchers are
not overwritten, and concurrent updates to the same destination are blocked.

Successful upgrades retain previous environments for running commands. Their
disk space can be reclaimed manually after verifying the active launcher path
and closing processes using an older environment. Use the updated installer
when choosing `--version vX.Y.Z` to reinstall an older release safely; historical
installer assets do not gain these guarantees retroactively. See
[Distribution and compatibility](distribution.md#upgrade).

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
