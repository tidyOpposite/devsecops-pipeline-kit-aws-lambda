# Roadmap

DevSecOps Pipeline Kit is currently an alpha-stage CLI-first product. The
core direction is promising, but the project should be treated as a developing
product rather than a finished platform. This roadmap turns the current
Terraform/GitHub/AWS reference kit into a polished `devsecops` CLI experience.

## Product Direction

The CLI is the product. Terraform modules, GitHub Actions workflows, AWS
resources, scanners, and generated files are the execution layer behind it.

The product promise:

* Create a clean, reviewable local pipeline configuration.
* Validate whether the pipeline is ready for a real deployment.
* Render deterministic Terraform and GitHub helper artifacts.
* Diagnose local, GitHub, AWS, security, and deployment gaps.
* Help operators recover safely from CLI-managed configuration changes.

## Current Assessment

Strengths:

* Installable dependency-free CLI with `pipx install .`.
* Local setup wizard, presets, composer, dashboard, readiness checks, reports,
  snapshots, and rollback for CLI-managed files.
* GitHub and AWS diagnostics through `gh-doctor`, `branch-doctor`,
  `actions-status`, and `aws-doctor`.
* Security-aware deployment model with immutable Lambda image input, GitHub
  OIDC, Terraform validation, IaC scanning, optional Snyk, optional HTTP
  validation, optional OWASP ZAP baseline, and production rollback.
* Clear repository decision to avoid bundling sample application code and to
  consume a prebuilt `LAMBDA_IMAGE_URI`.

Gaps that make the project feel raw:

* The primary CLI route is consolidated, but the broad compatibility surface
  remains until the documented deprecation windows can be completed.
* Standard and production setup still depend on users installing and
  authenticating Terraform, AWS CLI, and GitHub CLI themselves.
* Deployment run and previous-image history is intentionally local to one
  checkout; cross-workstation rollback requires an explicit reviewed image.
* The product has not yet proven a full happy path in a documented real AWS
  account walkthrough.
* WSL2 install and first-success evidence is still required before a stable
  release can be declared production-proven.

## Roadmap Themes

1. Productize the configuration lifecycle.
2. Consolidate and simplify the CLI user experience.
3. Make validation and generated artifacts trustworthy.
4. Prove the first successful deployment path.
5. Harden operational workflows for real users.
6. Improve release engineering and install confidence.
7. Keep security controls visible, testable, and explainable.

## Milestone 0: Stabilize The Product Contract

Target: immediate cleanup before the next feature release.
Status: implemented in `v0.3.0`.

Goals:

* Define the product as a CLI that creates, validates, renders, and diagnoses a
  secure AWS Lambda delivery pipeline.
* Keep Terraform, GitHub Actions, AWS, and scanners as transparent execution
  layers rather than hidden magic.
* Make the supported user journey obvious from the README and `--help`.

Deliverables:

- [x] Roadmap document.
- [x] README link to the roadmap.
- [x] Short product-positioning section in README if the existing introduction
  becomes too broad.
- [x] Command inventory that marks each command as stable, experimental, alias, or
  support.
- [x] Documentation for generated artifact ownership.

Acceptance criteria:

- [x] A new user can understand the product boundary in under five minutes.
- [x] The README quick start and `devsecops --help` describe the same path.
- [x] Generated files are clearly labeled as CLI-owned.

## Milestone 1: Clean Configuration Workflow

Target release: `v0.3.0`.
Status: implemented in `v0.3.0`.

Problem: `init`, `set`, `preset`, `compose`, `validate-config`, and `render`
are useful, but the clean configuration lifecycle is implicit.

Planned command shape:

```bash
devsecops config new --preset balanced
devsecops config show --format toml
devsecops config validate
devsecops config diff
devsecops config reset --preset minimal
devsecops config schema
devsecops render
```

Deliverables:

* Add a `schema_version` field to `.devsecops-pipeline.toml`.
* Add deterministic clean-config generation with no secrets and no generated
  output mixed into source configuration.
* Add `config new`, `config reset`, `config diff`, and `config schema`.
* Keep existing commands working while steering users toward the grouped
  `config` workflow.
* Add idempotency tests for clean config generation and rendering.
* Add a migration scaffold for future config schema versions.

Acceptance criteria:

* A clean config can be generated non-interactively.
* Running config generation and render twice produces no unexpected diff.
* Validation catches bad values before Terraform or GitHub commands run.
* No AWS secrets, GitHub secrets, tokens, or credentials are written to the
  local config.

## Milestone 2: CLI UX Consolidation

Target release: `v0.3.0`.
Status: implemented in `v0.3.0`.

Problem: the command surface is powerful but too wide for a first-time user.

Planned improvements:

* Organize commands into clear groups:
  * `config`: create, show, set, validate, diff, reset, schema.
  * `render`: generate Terraform and GitHub helper artifacts.
  * `doctor`: local, GitHub, AWS, branch, actions, and deep diagnostics.
  * `terraform`: plan and bootstrap helpers.
  * `github`: setup and status helpers.
  * `snapshot`: list, inspect, and restore CLI-managed files.
* Keep top-level compatibility aliases where useful, but mark legacy aliases in
  help output.
* Standardize output modes: human, compact, and JSON where automation needs it.
* Define stable exit codes for validation failure, missing external tools,
  authentication failure, and unexpected runtime errors.
* Improve `devsecops menu` so it follows the same command groups.

Acceptance criteria:

* `devsecops --help` is short enough to scan.
* Every command has an example in help or documentation.
* JSON output exists for readiness and doctor workflows used by automation.
* Golden tests protect important help text and command output.

## Milestone 3: Trustworthy Generation And Tests

Target release: `v0.4.0`.
Status: implemented in `v0.4.0`.

Problem: a CLI that generates infrastructure files must prove that generation
is deterministic, reviewable, and valid.

Deliverables:

- [x] Golden tests for generated `terraform/generated.auto.tfvars`.
- [x] Golden tests for generated GitHub setup scripts and variable files.
- [x] Terraform formatting and validation checks in CI.
- [x] CLI install smoke test from the root package.
- [x] End-to-end test that runs `config new`, `validate`, `render`, and `report`
  in a temporary repository.
- [x] Mocked tests for missing `gh`, missing AWS credentials, and unavailable
  Terraform.
- [x] Snapshot and rollback tests for overwritten CLI-owned files.

Acceptance criteria:

- [x] Generated artifacts have stable diffs across repeated runs.
- [x] CI fails if generated Terraform is syntactically invalid.
- [x] A package install smoke test proves the `devsecops` console command works.
- [x] Rollback tests prove user-owned files are not restored or overwritten by
  mistake.

## Milestone 4: First Successful Pipeline Path

Target release: `v0.5.0`.
Status: implemented in `v0.5.0`.

Problem: users need a direct, measurable route from install to one successful
pipeline run.

Deliverables:

- [x] A "first successful pipeline" guide with exact commands and expected
  outputs.
- [x] A documented bring-your-own-image path for `LAMBDA_IMAGE_URI`.
- [x] A separate example workload repository or template, not bundled into this
  repository.
- [x] Preflight checks for Lambda container image shape, immutability, and region
  mismatch.
- [x] A dry-run mode that explains what would be rendered or checked before files
  change.
- [x] Troubleshooting entries linked from readiness and doctor failures.

Acceptance criteria:

- [x] A user can complete a documented dry run without AWS credentials.
- [x] A user with AWS, GitHub, and a valid Lambda image can follow one guide to a
  successful production workflow dispatch.
- [x] The CLI explains the next action whenever readiness is below 100%.

## Milestone 5: Operational Reliability

Target release: `v0.6.0`.
Status: implemented in `v0.6.0`.

Problem: the project should help users operate the pipeline after initial
setup, not only generate it.

Deliverables:

- [x] Stronger `actions-status` output with failed step summaries and next actions.
- [x] Health validation command that can run outside the GitHub workflow.
- [x] AWS output inspection command for deployed Lambda/API Gateway resources.
- [x] Clear separation between local config rollback and deployed Lambda rollback.
- [x] Runbooks for failed Terraform plan, failed apply, failed validation, missing
  image, and failed rollback.
- [x] Optional strict mode for CI-friendly `doctor` and `readiness` checks.

Acceptance criteria:

- [x] A failed deployment can be diagnosed from CLI output and linked runbooks.
- [x] The user can distinguish local generated-file recovery from cloud deployment
  rollback.
- [x] Operational commands are safe by default and require explicit confirmation
  for mutating actions.

## Milestone 6: Security And Policy Maturity

Target release: `v0.7.0`.
Status: implemented in `v0.7.0`.

Problem: security controls should be visible as product features, not just
Terraform or workflow details.

Deliverables:

* [x] Control catalog that maps CLI options to Terraform, GitHub, AWS, and scanner
  behavior.
* [x] Policy preset comparison table.
* [x] Strict validation for production-risky values such as wildcard CORS,
  disabled approval gates, mutable image tags, and missing validation.
* [x] Optional machine-readable report for audit evidence.
* [x] Clear least-privilege guidance for deploy and plan roles.
* [x] Security regression tests for generated workflows and Terraform variables.

Acceptance criteria:

* [x] Each preset has a documented security posture.
* [x] `devsecops explain <control>` maps a control to concrete generated behavior.
* [x] Audit output can be attached to a pull request or release record.

## Milestone 7: Distribution And Adoption Readiness

Target release: `v0.8.0`.
Status: implemented in `v0.8.0`.

Problem: users should be able to install, upgrade, and trust releases without
reading the source tree.

Deliverables:

* Release checklist with version bump, changelog, tests, build, and tag steps.
* Published package path decision.
* Upgrade guide for config schema changes.
* Shell completion for common shells.
* Signed or checksummed release artifacts.
* Compatibility matrix for supported operating systems, Python versions,
  Terraform versions, GitHub CLI versions, and AWS CLI versions.

Acceptance criteria:

* A user can install the latest release from documented commands.
* Upgrade behavior is documented before config schema changes ship.
* Release artifacts can be verified.

## Milestone 8: Production Proof And Deployment Evidence

Target release: `v0.9.0`.
Status: in progress.

Problem: the project has strong local validation and dry-run workflows, but it
still needs one documented real AWS/GitHub happy path with evidence that a new
operator can trust and reproduce.

Deliverables:

* [x] Production deployment evidence workflow that operators can run against a
  real AWS account and GitHub repository.
* [x] Captured release, setup, workflow, Terraform, AWS output, and
  health-check evidence bundle contract that can be attached to a release
  record.
* [x] Post-deploy verification checklist for Lambda, API Gateway, CloudWatch
  logs, Terraform outputs, GitHub Actions status, and rollback readiness.
* [x] Documented real-account lessons to record, including required IAM,
  backend, branch protection, and image-publishing prerequisites.
* [x] Release checklist and runbook gate for failure modes discovered during
  the production walkthrough.
* [ ] Full production deployment walkthrough executed against a real AWS
  account and GitHub repository.

Acceptance criteria:

* [ ] A new operator can reproduce one documented production deployment from a
  fresh install.
* [ ] The walkthrough proves the deployed API outputs and readiness evidence
  match the documented expectations.
* [ ] Release evidence is concrete enough to review without inspecting the
  source tree.

## Milestone 9: Stability Contract And Migration Readiness

Target release: `v0.11.0`.
Status: implemented in `v0.11.0`.

Problem: before `v1.0.0`, the public CLI, config schema, generated artifacts,
and compatibility promises need an explicit stability contract so users know
what can change and how migrations will be handled.

Deliverables:

* [x] Stable command and flag contract for first-success, diagnostics, rendering,
  GitHub setup, Terraform helpers, snapshots, reports, and completions.
* [x] Deprecation policy for aliases, experimental commands, output formats, and
  config fields.
* [x] Tested config schema migration rules for future schema versions, including
  rollback expectations for CLI-owned files.
* [x] Generated artifact compatibility notes that explain when re-rendering is
  required and what diffs users should expect.
* [x] Stronger help, command inventory, JSON output, completion, and generated
  artifact regression coverage.

Acceptance criteria:

* [x] No documented first-success workflow depends on behavior still marked
  experimental.
* [x] Future config schema changes have documented and tested migration
  expectations before they ship.
* [x] Users can tell which commands, flags, files, and output shapes are stable
  enough to script against.

## Milestone 10: 1.0 Release Candidate Hardening

Target release: `v0.11.0`.
Status: release candidate shipped in `v0.11.0`.

Current stage: `v0.11.0` ships the release-candidate evidence checklist,
blocker register, guided onboarding UX, and local evidence helper. Do not mark
`v1.0.0` stable until the blocker register in
[`docs/v1.0.0-release-candidate-checklist.md`](docs/v1.0.0-release-candidate-checklist.md)
is empty and the final production evidence bundle is attached.

Problem: the final pre-1.0 release should close remaining stability gaps and
turn the `Version 1.0 Criteria` into an evidence-based release checklist.

Deliverables:

* `v1.0.0` release-candidate checklist that maps each stability criterion to
  commands, docs, tests, or release artifacts.
* Compatibility verification pass across supported operating systems, Python
  versions, Terraform versions, GitHub CLI versions, and AWS CLI versions.
* Documentation audit for quick start, first-success path, upgrade guide,
  troubleshooting, runbooks, command inventory, and generated artifacts.
* Security review of GitHub Actions permissions, OIDC role guidance, Terraform
  validation, scanner gates, rollback behavior, and audit evidence.
* Known-limitations review that separates accepted limitations from blockers
  for `v1.0.0`.
* Final criteria evidence map for the stable release record.

Acceptance criteria:

* Every `Version 1.0 Criteria` bullet has a linked or named evidence source.
* No unresolved blocker remains for `v1.0.0`.
* The project can publish a release candidate whose install, upgrade,
  verification, deployment, and rollback paths are all documented and tested.

## Version 1.0 Criteria

The project should not be called stable until all of these are true:

* CLI command groups and core flags are stable.
* Config schema versioning and migration behavior are implemented.
* Clean config generation, validation, rendering, and readiness are covered by
  end-to-end tests.
* Generated Terraform and GitHub artifacts are deterministic and documented.
* At least one full AWS/GitHub production deployment walkthrough is documented.
* Local rollback cannot overwrite files outside the CLI-owned file set.
* Security controls have documented behavior and regression tests.
* Release and upgrade flows are documented.
* Known limitations are explicit rather than hidden in implementation details.

## Post-1.0 Backlog

These ideas may be useful later, but they should not distract from making the
CLI product stable first:

* Plugin system for additional scanners.
* Additional cloud providers.
* Kubernetes deployment target.
* Web UI.
* Authenticated DAST workflows.
* Organization-wide GitHub policy management.
* Remote state inspection beyond the supported AWS backend.

## Near-Term Priority Order

If the project feels too raw, improve it in this order:

1. Make clean config generation a first-class workflow.
2. Simplify the command surface around grouped commands.
3. Add golden and end-to-end tests for generated files.
4. Write the first-success guide.
5. Prove the guide against a real AWS/GitHub setup.
6. Harden operational diagnostics and rollback documentation.
