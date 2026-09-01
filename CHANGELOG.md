# Changelog

All notable changes to this project are documented here. The project uses
semantic versioning.

## Unreleased

## v0.14.0 - 2026-09-01

### Added

* Preferred `setup`, `status`, `image validate`, and `generate` commands with
  matching help, shell completion, documentation, and machine-readable
  contracts.
* A resumable nine-stage guided setup with `demo`, `standard`, and `production`
  modes, dependency and identity checks, image/backend configuration,
  GitHub/OIDC connection, current-input dry-run tracking, and a final next
  command.
* Atomic, ignored `.devsecops/setup-state.json` progress with fail-closed schema
  validation and tests for resume, drift invalidation, mode boundaries, and
  secret non-persistence.
* A complete protected deployment journey through `devsecops deploy prod`,
  `deploy status`, `deploy logs`, and `deploy rollback`, including exact-image
  dispatch, concurrent-run protection, watch/JSON status, and failed-log
  routing.
* A bounded, schema-versioned `.devsecops/deployments.json` journal containing
  only non-secret run and image metadata so status, logs, and rollback share
  one deployment context.

### Changed

* Unified the first-run vocabulary around one setup flow and one status surface
  that includes the shared next action.
* Moved release-maintainer commands out of primary help and removed the second
  legacy readiness percentage from human status output.
* Limited primary help to eight first-route commands while keeping stable
  operational commands callable, documented, and available in completion.
* Added examples and explicit side-effect boundaries to the primary setup,
  status, deploy, dry-run, generation, diagnostics, and configuration help.
* Kept `start`, `next`, `readiness`, `dashboard`, `preflight`, `render`, and
  `--render` callable as compatibility aliases with their existing JSON kinds.
* Made `--yes` a local-defaults-only setup authorization; GitHub repository
  changes now require interactive confirmation or explicit `--apply-github`.
* Serialized deploy and rollback in one production workflow concurrency lane,
  added deployment-specific run names, and routed explicit rollback through
  the same protected GitHub Environment, OIDC role, Terraform state, scanners,
  and validation as normal deployment.

### Fixed

* Capture the active Lambda image with `aws lambda get-function` so automatic
  workflow rollback and the CLI rollback journal receive the real
  `Code.ImageUri` value.
* Route the shared next action through GitHub CLI installation and
  authentication before suggesting repository mutation commands.
* Label dry-run image scoring separately from overall readiness gaps and add a
  contextual follow-up command after deployment logs.
* Replace stale Roadmap claims about config schema, migration, tests, and
  generated-artifact ownership with the remaining evidence limitations.

## v0.13.1 - 2026-08-24

### Added

* Python 3.14 support across package metadata, the installer, CI, local release
  validation, and the documented compatibility matrix.

### Changed

* The bootstrap installer now accepts and auto-detects Python 3.14 while
  retaining support for Python 3.11, 3.12, and 3.13.
* Package metadata now advertises Python 3.11 through 3.14 and excludes Python
  3.15 and newer until they are covered by compatibility gates.

## v0.13.0 - 2026-08-23

### Added

* Documented CLI module boundaries, dependency direction, extension rules, and
  side-effect boundaries in the new CLI architecture guide.
* Architecture regression tests that reject internal dependency cycles and
  reverse imports from domain or provider modules into `main.py`.

### Changed

* Split the monolithic CLI implementation into focused config, rendering,
  snapshot, readiness, reporting, parser, workflow, and provider-adapter
  modules while retaining the existing command and Python compatibility
  surface.
* Reduced `main.py` to the command orchestration and terminal UI layer.
* Made AWS, GitHub, diagnostics, project-context, and snapshot workflows
  replace external side effects through explicit adapter boundaries.
* Centralized the runtime version in `devsecops_cli.__init__` so package and
  feature modules cannot drift between releases.

### Fixed

* Removed the circular facade pattern where reusable modules imported symbols
  back from `main.py` during package initialization.

## v0.12.0 - 2026-06-19

### Added

* One-command `install.sh` bootstrapper for GitHub Release installs without a
  separate `pipx` setup step.
* `devsecops criteria` stable-readiness gate for Version 1.0 criteria,
  production evidence, and WSL2 evidence checks.
* `API_AUTHORIZATION_TYPE`/`api_authorization_type` support with `AWS_IAM` as
  the secure default for generated API Gateway routes.
* SigV4 signing support for `devsecops health --aws-sigv4` so IAM-protected
  health endpoints can be validated outside GitHub Actions.
* Terraform output for the API Gateway authorization mode.

### Changed

* Quick Start and distribution docs now install through the bootstrapper and
  launch the CLI with `devsecops`.
* Release-candidate evidence bundles now include `criteria.json` so stable
  blockers are machine-checkable rather than only documented.
* Release publishing now includes `install.sh` in release assets and
  `SHA256SUMS`.
* GitHub Actions are pinned to commit SHAs and CI/release build tooling is
  pinned to exact `pip`, `build`, `setuptools`, and `wheel` versions.
* Production health validation signs requests when API Gateway uses IAM
  authorization; OWASP ZAP baseline DAST now runs only for explicitly public
  APIs.
* Terraform backend bootstrap now provisions a customer-managed KMS key,
  encrypted DynamoDB locking, state bucket access logging, TLS-only bucket
  policies, and lifecycle retention.
* Workload S3 buckets now include lifecycle retention for old versions and
  access logs.
* Lambda functions now use the workload KMS key for environment variables and
  configure reserved concurrency.

### Security

* API Gateway routes are no longer public by default; `NONE` authorization must
  be explicitly configured for demo or intentionally public APIs.
* KMS key policy service access is constrained with account, service, and
  encryption-context conditions where AWS services support them.
* `devsecops health` now rejects non-HTTP URL schemes before opening a URL.
* Security docs and limitations were updated to remove the old
  unauthenticated-by-default API exception and describe residual
  workload-level authorization responsibilities.

## v0.11.0 - 2026-06-13

### Added

* Production deployment evidence guide for Milestone 8, including evidence
  bundle layout, production workflow dispatch capture, Terraform/AWS/health
  proof, rollback-readiness checks, and real-account lessons to record.
* Stability contract for Milestone 9, including machine-readable command
  inventory, deprecation policy, JSON output contract, config migration
  expectations, and generated artifact compatibility notes.
* `v1.0.0` release-candidate checklist and evidence map for Milestone 10
  hardening.
* Known-limitations register that separates accepted limitations from blockers
  before the stable release.
* UX hardening commands: `devsecops next`, `devsecops start`, and
  `devsecops evidence collect --rc`.

### Changed

* Release checklist now includes production evidence, stability contract, and
  release-candidate hardening gates.
* Terraform helper commands are part of the stable command contract for the
  documented first-success workflow.
* Python package metadata and install docs now align with the supported
  Python 3.11, 3.12, and 3.13 compatibility matrix.
* Readiness and strict config validation now make production blockers and
  release-evidence readiness clearer.
* Deep diagnostics now suppress cascaded Terraform/AWS warnings when root tools
  or project files are missing.

## v0.8.0 - 2026-06-12

### Added

* Distribution guide with latest-release install commands, pinned release
  install commands, upgrade commands, artifact verification, shell completion
  setup, and compatibility matrix.
* Release checklist covering version bump, changelog, tests, build, checksum,
  commit, tag, push, and published-release verification steps.
* Upgrade guide for config schema changes before future schema migrations ship.
* `devsecops completion <bash|zsh|fish>` for dependency-free shell completion
  generation.

### Changed

* GitHub Release publishing now attaches `SHA256SUMS` for wheel and source
  distribution artifacts.
* CLI/package CI now runs the unit, golden, E2E, build, and install smoke suite
  across Python 3.11, 3.12, and 3.13.

## v0.7.0 - 2026-06-08

### Added

* Security control catalog with `devsecops controls --format json` and
  catalog-backed `devsecops explain <control>` mappings across CLI options,
  Terraform, GitHub Actions, AWS, and scanners.
* Policy preset comparison table with documented security posture for every
  preset.
* JSON audit evidence report through `devsecops report --format json`, written
  to `dist/devsecops/audit-report.json` by default.
* Security controls documentation covering strict validation, attachable audit
  evidence, preset posture, and least-privilege role guidance.

### Security

* `devsecops config validate --strict` now fails on production-risk warnings
  such as wildcard production CORS, disabled production approval gates,
  disabled separate plan-role posture, missing HTTP validation, missing image
  identity, and mutable image tags.
* Terraform now validates environment bounds, non-empty CORS origins, and
  rejects wildcard production CORS in `environment_config`.
* Regression tests now assert generated workflow gates and Terraform variable
  security contracts.

## v0.6.1 - 2026-06-07

### Added

* README development-status callout and repository badges that make the early
  alpha stage, active development cadence, and evolving security controls clear
  to new visitors.

### Security

* GitHub Actions now use narrower job-level permissions and checkout steps no
  longer persist repository credentials.
* Terraform plan workflows require `AWS_PLAN_ROLE_TO_ASSUME_ARN` and no longer
  fall back to the deployment role.
* Pull requests from forked repositories no longer run the AWS-backed Terraform
  plan job.
* Terraform now rejects mutable Lambda image tags and prevents planning or
  applying the Lambda workload without an explicit immutable image URI.
* Workload and access-log S3 buckets now deny non-TLS requests with bucket
  policies.

## v0.6.0 - 2026-06-07

### Added

* Stronger GitHub Actions status output with failed step summaries, strict
  failure mode, next actions, and linked runbooks.
* `devsecops health` for validating the deployed `/health` endpoint outside
  GitHub Actions.
* `devsecops aws outputs` for read-only inspection of deployed Lambda, API
  Gateway, and CloudWatch output values.
* Milestone 5 runbooks for failed Terraform plan, failed apply, failed
  validation, missing images, and failed deployment rollback.

### Changed

* `devsecops readiness --strict` now supports CI-friendly non-zero exits when
  readiness is below 100%.
* Local snapshot restore output now explicitly distinguishes local CLI-owned
  file recovery from cloud Lambda deployment rollback.

## v0.5.0 - 2026-06-06

### Added

* First successful pipeline guide with exact commands and expected output.
* Bring-your-own Lambda image documentation and a separate workload template
  contract that keeps workload source outside this repository.
* `devsecops preflight` for local Lambda image URI shape, immutability, and
  region checks.
* `devsecops dry-run` for a no-write, no-AWS-credentials first-success
  preview.
* `devsecops render --dry-run` for previewing generated artifact changes
  without writing files.
* Troubleshooting links in readiness next actions.

## v0.4.1 - 2026-06-06

### Fixed

* Avoided the `RuntimeWarning` emitted by `python -m devsecops_cli.main` by
  making package-level `main` loading lazy.
* Added tests that keep CLI, package, and root/CLI package versions aligned.

### Changed

* CI jobs now have explicit timeouts to avoid stalled package or Terraform
  checks holding runners indefinitely.
* CI now builds root package artifacts before the install smoke test, so
  packaging failures are caught before release publication.
* Release packaging now installs `setuptools` and `wheel` explicitly before
  building artifacts.
* Roadmap implementation statuses now point to released versions instead of
  stale `Unreleased` wording.

## v0.4.0 - 2026-06-06

### Added

* Golden tests for generated Terraform tfvars, GitHub variable files, and
  GitHub setup scripts.
* End-to-end CLI test that runs `config new`, `config validate`, `render`, and
  `report` in a temporary repository.
* Root package install smoke test that verifies the `devsecops` console
  command.
* Mocked failure tests for missing `gh`, missing AWS credentials, unavailable
  Terraform, and snapshot rollback safety for CLI-owned versus user-owned
  files.
* CI workflow for CLI tests plus generated Terraform `fmt`, `init`, and
  `validate` checks.

### Changed

* Generated `terraform/generated.auto.tfvars` now uses Terraform fmt-compatible
  attribute alignment.

## v0.3.0 - 2026-06-06

### Removed

* Bundled sample workload source, local image build files, and browser client.
* Sample-workload documentation for generated media, public web hosting, and
  bundled runtime binaries.

### Changed

* Production deploy now consumes a prebuilt immutable image from
  `LAMBDA_IMAGE_URI`.
* HTTP smoke testing and OWASP ZAP DAST are opt-in repository-variable gates.
* Default project naming now uses `devsecops-pipeline`.
* GitHub Actions no longer run on direct pushes to `main`; pull requests still
  validate automatically, and production deploys are manual workflow dispatch
  runs.
* Documentation now positions the terminal CLI as the primary product surface
  and Terraform/GitHub Actions as the execution layer behind it.
* CLI package descriptions and top-level help now describe the same
  CLI-product first-run path as the README.
* Recommended first-run workflow now uses `devsecops config new`,
  `config validate`, and `config diff` before rendering.
* Top-level CLI help now focuses on grouped primary commands while preserving
  legacy flat aliases.
* Main menu navigation now clears the terminal when entering sections and when
  returning to the menu, and menu items are grouped into sections with up to
  three actions per row.

### Added

* Product roadmap, command inventory, and generated-artifact ownership
  documentation for the Milestone 0 product contract.
* Schema-versioned clean configuration workflow with `devsecops config new`,
  `show`, `validate`, `diff`, `reset`, and `schema`.
* Config schema export, canonical config diffing, and a migration scaffold for
  future config schema versions.
* Grouped CLI UX for `doctor`, `github`, `terraform`, and `snapshot`
  workflows, plus `config set` as the primary config edit command.
* JSON and compact output modes for readiness and doctor workflows used by
  automation.
* Stable CLI exit-code constants for validation, missing tools, auth failures,
  unexpected runtime errors, and interrupts.
* Dependency-free terminal CLI with main menu, setup wizard, readiness report,
  render command, Terraform plan wrapper, backend bootstrap helper, and control
  explanations.
* CLI dashboard, environment table, controls matrix, config validation,
  architecture view, non-interactive `set` command, and unit tests.
* Dashboard watch mode, compact/full terminal layouts, category readiness
  scoring, and visible main-menu readiness gap fixes.
* Optional `devsecops tui` command with Rich rendering when optional UI
  dependencies are installed, and compact dashboard fallback otherwise.
* CLI readiness report export, GitHub setup script generation, environment
  presets, and optional Terraform workspace creation for plans.
* Policy preset profiles now support `preset list`, `preset show <name>`, and
  `preset apply <name>`, with new `enterprise` and `student-demo` profiles.
* Pipeline composer command for choosing Snyk, DAST, health checks, strict
  CORS, production approval environment, and separate AWS plan role controls,
  then regenerating config, helper artifacts, and readiness report.
* Root Python packaging for `pipx install .`, package-based CLI modules, and
  GitHub release wheel/sdist artifacts.
* GitHub CLI integration with `gh-doctor`, `gh-status`, and safe
  `github-setup --apply` support for repository variables and provided
  secrets.
* AWS Doctor CLI command for identity, backend, ECR, Lambda execution role,
  Lambda, API Gateway, CloudWatch log group, and configured ECR image
  diagnostics, with strict mode for automation.
* Branch protection and GitHub Actions diagnostics with `branch-doctor` and
  `actions-status`, including required check validation and failed job
  summaries.
* CLI snapshot and rollback workflow with newest-first restore points, change
  inspection, dry-run preview, confirmation prompt, and safety snapshot before
  restore.
* Menu input sections now support `b`, `back`, `0`, or `cancel` to return
  without saving pending configuration changes.
* Readiness indicator now exposes an `[i] details` shortcut and
  `devsecops readiness` command with concrete fix actions for checks blocking
  100% readiness.

## v0.1.0 - 2026-06-04

### Added

* Multi-environment Terraform support for `dev`, `staging`, and `prod`
  through workspaces.
* Modular Terraform structure for KMS, storage, ECR, Lambda, and API Gateway.
* S3 remote state backend with DynamoDB locking plus a bootstrap stack.
* GitHub Actions PR Terraform plan with PR comments and downloadable plan
  artifacts.
* Production apply/deploy path on merge to `main`.
* Immutable Lambda image deployment.
* Automatic Lambda rollback to the previous image on failed deployment
  validation.
* Optional OWASP ZAP DAST baseline scan after production deployment.
* Reference documentation for architecture, security model, scanner rationale,
  cost estimation, and troubleshooting.

### Changed

* Removed mutable `latest` image publishing from the deployment flow.
* Environment-specific names now include the active workspace.
