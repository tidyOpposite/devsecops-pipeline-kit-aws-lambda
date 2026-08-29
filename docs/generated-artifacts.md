# Generated Artifacts

DevSecOps Pipeline Kit separates source configuration from generated helper
artifacts. This keeps the CLI product predictable: users edit or create local
configuration, then the CLI generates deterministic files for Terraform, GitHub,
and operator checklists.

The generated artifact compatibility contract is also listed in
[Stability contract](stability-contract.md) and in machine-readable form:

```bash
devsecops inventory --format json
```

## Ownership Rules

| File | Owner | Commit? | How to change it |
| --- | --- | --- | --- |
| `.devsecops-pipeline.toml` | CLI-managed local source config | No | Use `devsecops setup` initially; use Configuration commands or the Advanced control editor for later changes, then run `devsecops config validate`. |
| `.devsecops/setup-state.json` | CLI-owned local workflow state | No | Rerun `devsecops setup`; the CLI atomically reconciles saved progress with config, tools, AWS identity, and GitHub. Move the file aside only when intentionally discarding setup history. |
| `.devsecops/deployments.json` | CLI-owned local deployment journal | No | Created after successful `devsecops deploy prod` or `devsecops deploy rollback` dispatches. Keep it to let status, logs, and rollback select the same run; it contains no credentials or tokens. |
| `terraform/generated.auto.tfvars` | CLI-owned generated artifact | No | Update `.devsecops-pipeline.toml`, then run `devsecops generate`. |
| `dist/devsecops/backend.tf` | CLI-owned generated template | No | Update backend settings, then run `devsecops generate`. Copy or adapt into `terraform/backend.tf` only after review. |
| `dist/devsecops/github-variables.env` | CLI-owned generated helper | No | Update `.devsecops-pipeline.toml`, then run `devsecops generate`. |
| `dist/devsecops/github-setup.sh` | CLI-owned generated helper | No | Update `.devsecops-pipeline.toml`, then run `devsecops generate` or `devsecops github-setup --write`. |
| `dist/devsecops/setup-checklist.md` | CLI-owned generated checklist | No | Update `.devsecops-pipeline.toml`, then run `devsecops generate`. |
| `dist/devsecops/readiness-report.md` | CLI-owned generated report | No | Run `devsecops report` after changing config or environment state. |
| `dist/devsecops/audit-report.json` | CLI-owned generated audit evidence | No | Run `devsecops report --format json` after changing config, controls, readiness, or release evidence. |
| `dist/devsecops/evidence/rc/*` | CLI-owned generated release-candidate evidence | No | Run `devsecops evidence collect --rc` after local validation or before attaching an RC evidence bundle. Includes `criteria.json` from `devsecops criteria --format json`. |
| `dist/devsecops/production-evidence/<tag-or-version>/` | Operator-owned production evidence bundle | No | Populate by following [Production deployment evidence](production-deployment-evidence.md), then verify with `devsecops criteria --strict --evidence-dir <dir>`. |
| `.devsecops/snapshots/` | CLI-owned local recovery data | No | Created automatically before CLI-owned files are overwritten. Inspect with `devsecops snapshots`. |

## CLI-Owned Header

Generated text files include a header that identifies them as CLI-owned. JSON
reports use `kind`, `schema_version`, and generated-path documentation for the
same ownership signal. The ownership marker means:

* Do not edit the generated file directly for durable changes.
* Change `.devsecops-pipeline.toml` or the relevant external system instead.
* Regenerate the artifact with the command named in the header.
* Review generated files before copying, running, or applying anything that can
  mutate GitHub or AWS.

## Source Config Versus Generated Output

`.devsecops-pipeline.toml` is local source configuration. It includes
`schema_version = 1` so future versions can migrate deliberately. It should
contain project settings, environment settings, feature flags, and backend
names. It must not contain AWS credentials, GitHub tokens, Snyk tokens, private
keys, or other secrets.

`.devsecops/setup-state.json` is neither source config nor generated deployment
output. It is an ignored, permission-restricted resume cursor containing mode,
timestamps, stage statuses, non-secret check details, and a one-way dry-run
fingerprint. It never stores credentials, GitHub or Snyk tokens, or values sent
to encrypted GitHub secrets. Every setup run rechecks observable state rather
than trusting a stale completion marker.

`.devsecops/deployments.json` is a bounded, schema-versioned journal of
non-secret deployment metadata: operation, production environment/ref,
requested and previously observed immutable image URIs, source/run IDs, URL,
and dispatch timestamp. It is written with private permissions. Future schema
versions fail closed instead of silently discarding rollback history.

Generated artifacts are outputs of that source config. They may contain
non-secret values such as project names, regions, repository variable values,
and placeholder commands for secrets. They are ignored by Git because they are
environment-specific and can be regenerated.

`dist/devsecops/audit-report.json` is intended to be attached to pull requests,
workflow artifacts, or release records. It summarizes readiness checks,
strict config validation, control catalog state, policy preset posture, and
least-privilege role guidance. It is still generated output, not durable source
configuration.

## Compatibility And Regeneration

Generated artifacts are deterministic outputs of local source config plus the
CLI generator version. Generate the files again when config values change,
when a documented schema migration changes normalized config values, or when
release notes say the artifact contract changed.

| File | Compatibility | Generate again when | Expected diffs |
| --- | --- | --- | --- |
| `.devsecops/deployments.json` | Schema-versioned local runtime state | A successful protected deploy or rollback is dispatched | One non-secret deployment record is prepended; history remains bounded. |
| `terraform/generated.auto.tfvars` | Stable Terraform variables | Config values, schema migration output, or Terraform variable contract changes | HCL assignment values and `environment_config` entries. |
| `dist/devsecops/backend.tf` | Stable review template | `backend.*` config values or backend template policy changes | S3 backend attributes such as bucket, key, region, lock table, or workspace prefix. |
| `dist/devsecops/github-variables.env` | Stable helper | Repository variable source config changes | `PROJECT_NAME`, `LAMBDA_IMAGE_URI`, `API_AUTHORIZATION_TYPE`, `ENABLE_*`, or `PROD_APPROVAL_ENVIRONMENT` values. |
| `dist/devsecops/github-setup.sh` | Stable helper script | GitHub variable or required secret contract changes | `gh variable` commands, API auth value, Snyk token requirement, or CLI-owned header changes. |
| `dist/devsecops/setup-checklist.md` | Stable checklist | GitHub, backend, or branch-protection checklist contract changes | Checklist item values or required item additions. |
| `dist/devsecops/readiness-report.md` | Stable report | Readiness checks, config values, or environment state changes | Generated timestamp, score/check/action rows, controls, and environment rows. |
| `dist/devsecops/audit-report.json` | Stable JSON evidence | Audit evidence, readiness, config, or control state changes | `generated_at` timestamp and changed readiness/config/control payloads. |
| `dist/devsecops/evidence/rc/manifest.json` | Stable RC evidence manifest | Release-candidate evidence is collected | `generated_at`, evidence file list, and Terraform validation status. |
| `dist/devsecops/evidence/rc/criteria.json` | Stable Version 1.0 criteria evidence | Release-candidate evidence is collected or stable blockers change | `generated_at`, criteria status, stable-release gate status, and next actions. |

If a regeneration diff only contains expected value changes, review and continue.
Unexpected new files, missing CLI-owned headers, or changed GitHub/AWS mutation
commands should be treated as release-review findings before applying them.

## Backend Template Exception

The repository contains `terraform/backend.tf` as the Terraform backend file
used by the root module. The CLI also generates `dist/devsecops/backend.tf` as a
reviewable template. Treat the generated file as a helper, not as an automatic
replacement for the tracked Terraform backend file.

When you are ready to switch backend values, review the generated template and
copy or adapt the backend block intentionally.

## Rollback Boundary

`devsecops rollback` and `devsecops snapshot restore` restore only local
CLI-owned files from snapshots. They do not roll back a deployed Lambda
function in AWS, Terraform state, GitHub Actions, or live traffic.

Cloud deployment rollback is handled automatically by the GitHub Actions
production workflow when a deployment or enabled validation step fails, or
explicitly through `devsecops deploy rollback`. Keep these paths separate:

* Local rollback: restore CLI-managed config and generated files.
* Automatic cloud rollback: restore the previous Lambda image during a failed
  production workflow.
* Operator cloud rollback: validate and restore the recorded previous image, or
  an explicit immutable image, through the same protected GitHub Environment,
  OIDC role, validation, and Terraform state.

Use `devsecops deploy status`, `devsecops deploy logs --failed`,
`devsecops aws outputs`, and `devsecops health` to inspect deployment state
before previewing `devsecops deploy rollback --dry-run`.
