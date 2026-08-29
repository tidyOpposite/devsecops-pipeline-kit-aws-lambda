# DevSecOps Pipeline Kit CLI for AWS Lambda

![Stage: early alpha](https://img.shields.io/badge/stage-early_alpha-orange)
![Development: active](https://img.shields.io/badge/development-active-brightgreen)
![Releases: frequent](https://img.shields.io/badge/releases-frequent-blue)
![Security controls: evolving](https://img.shields.io/badge/security_controls-evolving-blue)
![API stability: 0.x](https://img.shields.io/badge/API_stability-0.x_changes_expected-yellow)

DevSecOps Pipeline Kit helps you prepare, validate, and operate a secure AWS
Lambda container deployment pipeline from one terminal CLI. It turns a local
configuration into reviewable Terraform and GitHub setup artifacts, then shows
what still blocks a deployment.

## What This Product Does

- Creates a local, schema-versioned pipeline configuration.
- Generates Terraform inputs and GitHub repository setup helpers.
- Checks local, Terraform, GitHub, AWS, and security readiness.
- Supports GitHub Actions deployment validation, evidence collection, and
  automatic Lambda image rollback after a failed production validation.

Terraform, GitHub Actions, AWS OIDC, and security scanners remain visible
execution layers; the CLI configures and checks them instead of hiding them.

## Who It Is For

Use this project if you are a developer, platform engineer, security engineer,
or student who already has an AWS Lambda workload and wants a guided,
reviewable DevSecOps delivery path. It is especially suited to demonstrations,
technical evaluations, and teams that want explicit infrastructure and
security controls rather than an opaque deployment service.

## Before You Start

For the no-credentials quick start below, you need:

- Linux, macOS, or WSL2 with `curl` and Python 3.11, 3.12, 3.13, or 3.14.
- A local checkout of this repository; run the commands from its root.
- An immutable ECR-style image URI for validation. The example URI is safe to
  use for the dry run because the CLI does not contact AWS in that step.

A real deployment additionally requires an AWS account, a GitHub repository,
Terraform, AWS CLI, GitHub CLI, configured OIDC roles, a remote Terraform
backend, and a real immutable Lambda image in ECR.

## What This Product Does Not Do

- It does not contain, generate, compile, or package your Lambda application.
- It does not build or push the Lambda container image. Bring a prebuilt image
  identified by an immutable tag or digest; `latest` and `bootstrap` are
  rejected for production.
- It does not deploy anything during the quick start. Production changes run
  through the repository's manually triggered GitHub Actions workflow.
- It is not yet a stable `v1.0` platform; review generated artifacts and pin a
  release for repeatable evaluations.

See [Bring your own image](docs/bring-your-own-image.md) for the workload
boundary and image requirements.

## Quick Start

Install the latest published release:

```bash
curl -fsSL https://raw.githubusercontent.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/main/install.sh | sh
```

Then run the complete three-command first experience from the repository root:

```bash
devsecops setup --preset balanced --yes
devsecops status
devsecops dry-run --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

Expected result:

- `setup` starts or resumes the standard nine-stage setup, checks dependencies,
  creates `.devsecops-pipeline.toml`, and saves non-secret progress under
  `.devsecops/`. With `--yes` it never changes GitHub or AWS.
- `status` shows one overall score, the remaining blockers, and one next action.
- `dry-run` validates the immutable image URI and previews the files that would
  be generated. It does not write files and does not require AWS credentials.

Run `devsecops` without arguments at any time to see compact project status
and the single recommended next command. Human-readable commands finish with
the same recommendation, so the setup path can be resumed without memorizing
the workflow. Machine-readable JSON, TOML, Markdown, generated shell, and
completion output remains unchanged for scripts.

Continue with the step-by-step
[First successful pipeline](docs/first-successful-pipeline.md) guide when you
are ready to connect GitHub and AWS.

## Guided Setup

Run `devsecops setup` without flags for the interactive path. It is a resumable
state machine rather than a one-shot config generator:

```text
1. Choose mode: demo, standard, or production
2. Check dependencies
3. Create local config
4. Select an existing immutable Lambda image or open the image guide
5. Configure Terraform backend names
6. Verify the active AWS identity
7. Connect the GitHub repository and OIDC role secrets
8. Run a no-write dry-run
9. Show saved progress and one next command
```

| Mode | Initial preset | Required outcome |
| --- | --- | --- |
| `demo` | `student-demo` | Creates local config and completes a dry-run with a clearly marked sample image URI. It does not query or change AWS or GitHub. |
| `standard` | `balanced` | Requires Git, Terraform, AWS CLI, GitHub CLI, a real image/backend, AWS identity, and repository variables/OIDC role secrets. |
| `production` | `enterprise` | Uses the production-oriented preset and keeps every standard cloud connection and strict control in scope. |

Progress is atomically saved to `.devsecops/setup-state.json`, which is ignored
by Git and never stores AWS credentials, GitHub tokens, Snyk tokens, or secret
values. Press `Ctrl-C`, `b`, `back`, or `0` at a prompt and rerun
`devsecops setup`; completed stages are rechecked against the real project and
the first incomplete stage is shown. A config change invalidates the saved
dry-run result so stale progress cannot be reported as complete.

`--yes` accepts only safe local defaults and never implies permission to change
GitHub. To apply repository variables and encrypted secrets non-interactively,
authorization must be explicit:

```bash
devsecops setup --mode standard --yes \
  --image-uri <immutable-ecr-image-uri> \
  --backend-bucket <state-bucket> \
  --apply-github \
  --deploy-role-arn <deploy-role-arn> \
  --plan-role-arn <plan-role-arn>
```

The command above checks AWS identity but does not create the backend, apply
Terraform, start a workflow, or deploy AWS resources. Use `--strict` in CI or
scripts when incomplete required stages should produce a non-zero exit code.
In standard and production modes the backend stage becomes complete only after
the configured S3 bucket and DynamoDB lock table are observable in the active
AWS account. Until then the summary recommends `devsecops terraform bootstrap`
for a safe plan before any explicit apply.

## Development Status

This project is in early alpha and is changing quickly. The CLI is usable for
experimentation, review, demos, and guided pipeline setup, but it should not be
treated as a stable platform yet.

Expect frequent releases while the project moves toward `v1.0`. Command names,
configuration fields, generated artifacts, operational diagnostics, and
security controls may change across `0.x` versions as the product boundary gets
sharper. Pin a release tag for repeatable demos or evaluations, read the
[Changelog](CHANGELOG.md) before upgrading, and review generated Terraform and
GitHub artifacts before applying them in real AWS accounts.

Security is an active development area. GitHub OIDC, immutable image inputs,
Terraform validation, IaC scanning, optional Snyk, optional `/health`
validation, optional DAST, and rollback behavior are already present, but the
controls, defaults, and audit outputs are still evolving. Follow the
[Roadmap](ROADMAP.md) to see what is implemented, what is next, and what is not
yet considered stable.

## Product Contract

The product boundary is intentionally narrow: `devsecops` is the user-facing
CLI for setting up, validating, generating, and diagnosing a secure AWS Lambda
delivery pipeline. Terraform modules, GitHub Actions workflows, AWS resources,
and scanners remain transparent execution layers that the CLI configures and
checks.

`.devsecops-pipeline.toml` is local source configuration. Files written by
`devsecops generate`, `devsecops report`, and `devsecops github-setup --write`
are CLI-owned generated artifacts. Do not edit generated files directly for
durable changes; update the local config and regenerate them.

Stable command flags, compatibility aliases, experimental commands, JSON output
kinds, config migration rules, and generated artifact compatibility are
documented in [Stability contract](docs/stability-contract.md). The
machine-readable inventory is available with:

```bash
devsecops inventory --format json
```

## Architecture

The internal CLI module boundaries and dependency rules are documented in
[CLI architecture](docs/cli-architecture.md).

```mermaid
flowchart LR
  operator["Operator"] --> cli["DevSecOps CLI"]
  cli --> config["Local pipeline config"]
  cli --> readiness["Readiness + diagnostics"]
  cli --> generated["Rendered Terraform/GitHub artifacts"]
  cli --> snapshots["Local snapshots + rollback"]
  generated --> terraform["Terraform modules"]
  generated --> githubSetup["GitHub variables/secrets"]
  githubSetup --> checks
  githubSetup --> deploy
  terraform --> checks
  terraform --> deploy
  developer["Developer"] --> pr["Pull Request"]
  pr --> checks["GitHub Actions: Terraform validate + IaC scan"]
  checks --> plan["Terraform plan in PR comment"]
  main["Merge to main"] --> deploy["Production deploy workflow"]
  deploy --> oidc["GitHub OIDC -> AWS IAM role"]
  oidc --> tfstate["S3 Terraform state + DynamoDB lock"]
  deploy --> image["Immutable Lambda image URI"]
  deploy --> ecr["ECR repository for workload images"]
  image --> lambda["AWS Lambda container"]
  api["API Gateway HTTP API"] --> lambda
  lambda --> data["Private workload data bucket"]
  lambda --> dlq["SQS DLQ"]
  lambda --> logs["CloudWatch Logs + X-Ray"]
  deploy --> validation["Optional /health + OWASP ZAP validation"]
  validation --> rollback["Rollback to previous Lambda image on failure"]
  rollback --> lambda
```

## What Is Implemented

| Area | Implementation |
| --- | --- |
| CLI product | Dependency-free terminal menu, guided setup, unified status, config presets, reports, snapshots, rollback, and diagnostics. |
| CLI-managed config | `.devsecops-pipeline.toml` stores local settings and `devsecops generate` generates ignored Terraform/GitHub helper artifacts. |
| Readiness diagnostics | `devsecops status`, `[i] details`, `doctor`, `gh-doctor`, `actions-status`, and `branch-doctor` explain what blocks a deploy-ready pipeline. |
| AWS diagnostics | `devsecops aws-doctor` checks AWS identity, backend bucket, lock table, ECR, Lambda execution role, Lambda, API Gateway, CloudWatch logs, and configured ECR image existence. |
| Environments | `dev`, `staging`, and `prod` are mapped to Terraform workspaces. Resource names include the environment, for example `devsecops-pipeline-prod-lambda`. |
| Terraform state | Remote S3 backend with DynamoDB locking. `terraform/bootstrap` creates KMS-encrypted state, encrypted locks, access logging, lifecycle retention, and public access blocks. |
| IaC structure | Root Terraform composes modules in `terraform/modules`: `kms`, `storage`, `ecr`, `lambda`, and `api-gateway`. |
| PR workflow | Pull requests run Terraform formatting, validation, and Trivy IaC scanning. Same-repository PRs also run an AWS-backed Terraform plan with the plan role and publish a PR comment plus artifact. |
| Production deploy | `devsecops deploy prod` performs readiness and overlap checks, confirms the exact immutable image, and delegates `terraform apply` to a manual protected workflow run from `main`. Direct pushes do not deploy. |
| Image deployment | The deploy workflow and Terraform require an explicit immutable `LAMBDA_IMAGE_URI` and reject mutable `latest` or `bootstrap` tags. |
| API authorization | API Gateway routes default to `AWS_IAM`; health checks use SigV4 signing for protected production endpoints. |
| Container scanning | Snyk can scan the configured image when `SNYK_TOKEN` is present. |
| Rollback | The workflow restores the previous image automatically after failed validation; `devsecops deploy rollback` provides an explicit, confirmed rollback through the same protected environment and Terraform state. |
| Optional validation | `/health` smoke test can validate IAM-protected APIs; OWASP ZAP baseline DAST runs only when the API is explicitly public. |

## Repository Layout

```text
pyproject.toml                      Root Python package metadata for `pipx install .`
cli/devsecops_cli/                  Modular CLI application, domains, and provider adapters
cli/tests/                          Focused CLI unit tests
dist/devsecops/                     Ignored CLI-generated helper artifacts
.github/workflows/deploy.yml        CI, PR plan, production deploy, rollback, optional DAST
.github/workflows/release.yml       Tag release workflow with wheel/sdist artifacts
terraform/bootstrap/                One-time S3 backend and DynamoDB lock table
terraform/modules/kms/              Customer-managed KMS key and alias
terraform/modules/storage/          Private workload data bucket and access log bucket
terraform/modules/ecr/              Immutable ECR repository and lifecycle policy
terraform/modules/lambda/           Lambda, IAM role, logs, and SQS DLQ
terraform/modules/api-gateway/      HTTP API, integration, stage, access logs
docs/                               CLI-first security, scanner, cost, and troubleshooting docs
```

## Detailed CLI Usage

The installer verifies the release wheel against `SHA256SUMS`, installs it into
a private virtual environment, and writes a `devsecops` launcher. See
[Distribution and compatibility](docs/distribution.md) for pinned installs,
manual wheel installation, upgrades, shell completion, checksum verification,
and supported tool versions.

`devsecops status` is the single public status surface behind the default
screen, interactive menu, and command postludes. Every blocker is
shown with what is missing, why it matters, what the recommended command will
change, the exact next command, and a documentation link.

The main menu uses section-style navigation: selecting an item clears the
terminal, opens that section, and returns to the main menu when you press
Enter. Input sections can be cancelled by typing `b`, `back`, `0`, or
`cancel`; the configuration wizard returns without saving when cancelled. The
readiness indicator includes an `[i] details` shortcut that shows the checks
blocking 100% readiness and the concrete fix for each one.

```text
[1] Continue setup
[2] Status
[3] Deploy
[4] Diagnose problems
[5] Configuration
[6] Advanced
[0] Exit
```

The main path stays focused on setup, validation, and deployment. Generated
deployment files, Terraform, GitHub setup, reports and release evidence,
security reference, and local snapshots remain available under `Advanced`.
`Continue setup` uses the shared status decision and opens the relevant
Configuration, Deployment files, GitHub, Diagnostics, Deploy, or Reports
section instead of forcing the user to find it manually.
The `Deploy` section keeps deployment status, the protected CLI command, logs,
AWS outputs, health validation, and cloud rollback together. Merely opening it
never starts a deployment.

For development, install the local package in editable mode:

```bash
PYTHON="${PYTHON:-python3.11}"
"${PYTHON}" -m pip install -e .
devsecops status
```

Without installing, run the package module with `PYTHONPATH`:

```bash
PYTHON="${PYTHON:-python3.11}"
PYTHONPATH=cli "${PYTHON}" -m devsecops_cli status
```

The CLI is intentionally dependency-free for core flows, so it can run before a
Python environment, Terraform backend, GitHub repository, or AWS credentials are
fully configured.

The same first-run path is also shown in `devsecops --help`.

Useful commands:

```bash
devsecops status     # compact project status and one next action
devsecops status --deep
devsecops status --watch --interval 10
devsecops tui           # optional Rich/Textual UI bridge

devsecops setup --mode demo --yes --strict
devsecops setup --mode standard
devsecops setup --mode production --strict
devsecops config show --format toml
devsecops config show --format json
devsecops config validate
devsecops config diff
devsecops config diff --preset strict
devsecops config set backend.bucket my-state-bucket --generate
devsecops config reset --preset minimal
devsecops config schema

devsecops preset list   # show available policy profiles
devsecops preset show strict
devsecops preset apply strict --generate

devsecops doctor local --format compact
devsecops doctor local --deep --format json
devsecops doctor github
devsecops doctor aws --environment prod --strict
devsecops doctor branch --branch main
devsecops doctor actions --format json
devsecops doctor all --format compact
devsecops status     # shows what blocks 100% readiness
devsecops status --format json
devsecops status --strict --format compact
devsecops dry-run --image-uri <immutable-ecr-image-uri>
devsecops image validate --image-uri <immutable-ecr-image-uri>
devsecops health --url https://abc123.execute-api.us-east-1.amazonaws.com/health --aws-sigv4
devsecops aws outputs --environment prod --format json

devsecops deploy prod --dry-run
devsecops deploy prod
devsecops deploy status --watch
devsecops deploy logs --failed
devsecops deploy rollback --dry-run
devsecops deploy rollback

devsecops github setup  # prints gh commands for repo variables/secrets
devsecops github setup --apply --deploy-role-arn arn:aws:iam::123456789012:role/deploy
devsecops github status --format compact
devsecops github branch --branch main

devsecops terraform bootstrap
devsecops terraform bootstrap --apply
devsecops terraform plan dev --create-workspace

devsecops snapshot list
devsecops snapshot show 1
devsecops snapshot restore --last --dry-run

devsecops envs          # environment settings table
devsecops controls      # security controls matrix
devsecops inventory --format json # stable command/JSON/artifact contract
devsecops evidence collect --rc # collect local release-candidate evidence
devsecops criteria --strict # check Version 1.0 criteria and stable blockers
devsecops completion bash # print shell completion for bash, zsh, or fish
devsecops generate        # writes ignored Terraform/GitHub helper artifacts
devsecops generate --dry-run
devsecops report        # exports Markdown readiness report
devsecops report --format json # exports attachable audit evidence
devsecops explain oidc  # explains a security control
```

Top-level compatibility aliases such as `start`, `next`, `readiness`,
`dashboard`, `preflight`, `render`, `init`, `set`, `validate-config`,
`github-setup`, `gh-doctor`, `aws-doctor`, `actions-status`, `branch-doctor`,
`plan`, `bootstrap`, `snapshots`, and `rollback` still work. New scripts should
prefer the grouped commands shown above.

`status` splits the project into Local, Terraform, GitHub, AWS, Security, and
Deployment areas while showing one overall score. `--deep` adds external
checks; `--watch` auto-refreshes every `--interval` seconds.

The core CLI remains dependency-free. To try the optional Rich/Textual UI:

```bash
curl -fsSL https://raw.githubusercontent.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/main/install.sh | sh -s -- --with-tui
devsecops tui
```

From a local checkout, `pipx install ".[tui]"` still works.

The clean configuration workflow writes `.devsecops-pipeline.toml`, which is
intentionally ignored by Git and includes `schema_version = 1`.
`devsecops generate` writes:

```text
terraform/generated.auto.tfvars
dist/devsecops/backend.tf
dist/devsecops/github-variables.env
dist/devsecops/github-setup.sh
dist/devsecops/setup-checklist.md
```

`devsecops report` writes `dist/devsecops/readiness-report.md`.
`devsecops report --format json` writes `dist/devsecops/audit-report.json`
for pull request, workflow artifact, or release evidence.

Successful deployment and rollback dispatches prepend non-secret metadata to
`.devsecops/deployments.json`: operation, environment, ref, requested and
previous image URIs, run ID/URL, and timestamp. The ignored file is written
with a schema version and private permissions; credentials and tokens are not
stored. It lets status, logs, and rollback resolve the same run by default.

Generated artifacts include CLI-owned headers and are ignored by Git. See
[Generated artifacts](docs/generated-artifacts.md) for the source-versus-output
contract.

The CLI creates local snapshots before commands that overwrite CLI-owned
configuration or generated artifacts: `setup`, Configuration changes,
`generate`, `report`, and `github setup --write`. Snapshots are stored under
`.devsecops/snapshots/`, are ignored by Git, and can be inspected or restored:

```bash
devsecops snapshots
devsecops snapshots --show 1
devsecops rollback --last --dry-run
devsecops rollback --to <number-or-id>
```

Rollback restores only the local files managed by the CLI, such as
`.devsecops-pipeline.toml`, `terraform/generated.auto.tfvars`, and generated
files under `dist/devsecops/`. Before a rollback is applied, the CLI creates a
new safety snapshot of the current state. It does not change AWS Lambda,
Terraform state, GitHub Actions, or deployed traffic. Cloud deployment rollback
uses the separate `devsecops deploy rollback` command and the protected
production workflow. It does not reuse the local snapshot mechanism.

## Operational Diagnostics

After a deploy, inspect the live AWS surface without mutating resources:

```bash
devsecops deploy status
devsecops deploy logs --failed
devsecops aws outputs --environment prod
devsecops health --aws-sigv4
devsecops health --url https://abc123.execute-api.us-east-1.amazonaws.com/health --aws-sigv4
devsecops github status --format compact --strict
```

`github status` and `doctor actions` show failed jobs, failed steps, concrete
next actions, and runbook links. Use `readiness --strict` in CI when any scored
gap should fail the command.

For release review or production proof, collect an attachable evidence bundle
with the commands in
[Production deployment evidence](docs/production-deployment-evidence.md). The
bundle captures release verification, strict config/readiness output, GitHub
setup, workflow status, Terraform outputs, AWS outputs, health checks,
CloudWatch logs, and rollback readiness.

Before a stable tag, run:

```bash
devsecops criteria --strict --evidence-dir dist/devsecops/production-evidence/v1.0.0
```

The `config set` command supports non-interactive configuration for scripts and quick
edits:

```bash
devsecops config set lambda_image_uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/app:sha-a1b2c3
devsecops config set enable_dast true
devsecops config set environments.prod.lambda_timeout 300 --generate
devsecops config validate
devsecops config validate --strict
```

Presets provide a quick starting point:

```bash
devsecops preset list
devsecops preset show enterprise
devsecops preset apply minimal --generate       # low-cost local/dev experimentation
devsecops preset apply balanced --generate      # default reference settings
devsecops preset apply strict --generate        # enables health validation and DAST
devsecops preset apply enterprise --generate    # locked-down CORS and longer retention
devsecops preset apply student-demo --generate  # simple demonstration profile
```

For compatibility, `devsecops preset strict --render` still applies the named
preset, but new scripts should use `devsecops preset apply <name>`.

Each preset has a documented security posture and can be compared with
`devsecops preset list`. Use
[Security controls and policy presets](docs/security-controls.md) for the full
control catalog, preset comparison, strict validation rules, and audit evidence
format.

Under `Advanced`, use the compatibility composer when you want the CLI to ask
for individual controls and then update all generated outputs in one pass:

```bash
devsecops compose
```

Composer asks whether to enable Snyk container scanning, DAST, health checks,
strict CORS, the protected `prod` approval environment, and a separate AWS plan
role. It updates `.devsecops-pipeline.toml`, generates Terraform/GitHub helper
artifacts, and writes `dist/devsecops/readiness-report.md`.

## CLI-Managed Backend Bootstrap

Terraform cannot create the S3 backend it is already using. Configure the
backend values through the CLI, generate helper artifacts, and let the CLI run
the bootstrap stack:

```bash
devsecops config set backend.bucket <globally-unique-state-bucket> --generate
devsecops config set backend.lock_table devsecops-pipeline-terraform-locks --generate
devsecops bootstrap
devsecops bootstrap --apply
```

`devsecops bootstrap` plans by default. Use `--apply` only after reviewing the
target AWS account, bucket name, and lock table name.

The generated backend template is written to `dist/devsecops/backend.tf`. Copy
or adapt it into `terraform/backend.tf` when you are ready to initialize the
root Terraform module:

```hcl
terraform {
  backend "s3" {
    bucket               = "<globally-unique-state-bucket>"
    key                  = "serverless-lambda/terraform.tfstate"
    region               = "us-east-1"
    encrypt              = true
    dynamodb_table       = "devsecops-pipeline-terraform-locks"
    workspace_key_prefix = "environments"
  }
}
```

## Environment Workflow

Use the CLI for the normal environment workflow:

```bash
devsecops envs
devsecops preset apply balanced --generate
devsecops plan dev --create-workspace
devsecops plan staging --create-workspace
devsecops plan prod --create-workspace
```

The CLI delegates to Terraform workspaces under the hood. The active workspace
selects `environment_config` from `terraform/variables.tf`. Running in the
default workspace falls back to `var.environment`, which defaults to `dev`.

## GitHub Actions Setup

Generate repository setup commands from the same local config used by
Terraform:

```bash
devsecops github-setup --write
devsecops gh-setup --apply \
  --deploy-role-arn arn:aws:iam::<account-id>:role/<deploy-role> \
  --plan-role-arn arn:aws:iam::<account-id>:role/<plan-role>
devsecops gh-doctor
devsecops branch-doctor
devsecops aws-doctor --environment prod
```

Required repository secrets:

| Secret | Purpose |
| --- | --- |
| `AWS_ROLE_TO_ASSUME_ARN` | Deployment role used by manual production deploy runs from `main`. |
| `AWS_PLAN_ROLE_TO_ASSUME_ARN` | Required least-privilege role for Terraform plan workflows. Plans do not fall back to the deploy role. |
| `AWS_REGION` | AWS region, for example `us-east-1`. |
| `SNYK_TOKEN` | Required when `ENABLE_SNYK_SCAN=true`; otherwise optional. |

Repository variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PROJECT_NAME` | `devsecops-pipeline` | Prefix for AWS resources and ECR repository names. |
| `LAMBDA_IMAGE_URI` | none | Required for manual production deploy. Immutable image URI deployed to Lambda. |
| `API_AUTHORIZATION_TYPE` | `AWS_IAM` | API Gateway route authorization. Use `NONE` only for demo or intentionally public non-sensitive APIs. |
| `ENABLE_SNYK_SCAN` | `false` | When `true` and `SNYK_TOKEN` is present, CI scans the configured image with Snyk. |
| `ENABLE_HTTP_VALIDATION` | `false` | When `true`, CI calls the API Gateway `/health` URL after deployment. |
| `ENABLE_DAST` | `false` | When `true`, CI runs OWASP ZAP baseline scan only when `API_AUTHORIZATION_TYPE=NONE`. |
| `PROD_APPROVAL_ENVIRONMENT` | `prod` | GitHub environment used by the production deploy job. Composer sets `devsecops-no-approval` when approval is disabled. |

Recommended branch protection for `main`:

* Require pull requests before merging.
* Require `Security and Terraform Validate` and `Terraform Plan` to pass.
* Use pull requests from branches in this repository for automatic AWS-backed
  Terraform plans. Pull requests from forks still run validation, but the
  AWS-backed plan job is skipped.
* Direct pushes to `main` do not run this workflow.

Use separate AWS roles for plan and deploy. The plan role should read backend
state, acquire locks, and describe resources for Terraform refresh; it should
not mutate workload resources. The deploy role is reserved for approved manual
production deploys from `main`. See [AWS IAM policy guidance](AWS_policy.md)
and [Security controls and policy presets](docs/security-controls.md).

## Pipeline Behavior

| Event | Environment | Terraform action | Deployment |
| --- | --- | --- | --- |
| Pull request to `main` from same repository | `dev` | `plan` only with `AWS_PLAN_ROLE_TO_ASSUME_ARN` | No apply. |
| Pull request to `main` from fork | n/a | validation only | No AWS credentials. |
| Push to `main` | n/a | none | No workflow run. Maintainer pushes do not consume Actions minutes. |
| Manual `workflow_dispatch`, `mode=plan` | selected `dev/staging/prod` | `plan` only | No apply. |
| Manual `workflow_dispatch`, `mode=deploy`, `environment=prod`, branch `main` | `prod` | `apply` | Scan configured image when enabled, deploy Lambda, optionally validate HTTP and DAST, rollback on failure. |
| Manual `workflow_dispatch`, `mode=rollback`, `environment=prod`, branch `main` | `prod` | `apply` | Restore the explicit immutable image through the protected environment, then run the same enabled validation. |
| Push tag `v*.*.*` | n/a | n/a | Publish GitHub Release from `docs/release-<tag>.md` or `CHANGELOG.md` with installer, wheel, source distribution, and `SHA256SUMS`. |

## Deployment Flow

For a command-by-command walkthrough with expected output, see
[First successful pipeline](docs/first-successful-pipeline.md). For a
production-proof release record, use
[Production deployment evidence](docs/production-deployment-evidence.md).

1. Configure local pipeline state with `devsecops setup`; use the Configuration
   section for later edits.
2. Generate deployment files with `devsecops generate`.
3. Check readiness with `devsecops status`, `doctor`, and GitHub diagnostics.
4. Validate Terraform formatting and configuration in GitHub Actions on pull
   requests or manual runs.
5. Run Trivy IaC scanning.
6. Require an immutable `LAMBDA_IMAGE_URI` on production deploys; Terraform also
   prevents planning or applying the Lambda workload without an explicit
   immutable image URI.
7. Optionally scan the configured Lambda image with Snyk.
8. Apply KMS and ECR bootstrap targets so supporting resources exist.
9. Capture the previously deployed Lambda image URI.
10. Run `devsecops deploy prod`; the CLI checks readiness, prevents overlapping
    production runs, confirms the image, and starts `mode=deploy` with
    `environment=prod` from `main`.
11. Apply the full Terraform workload with the configured image URI.
12. Wait for the Lambda update to complete.
13. Optionally call `/health`; run OWASP ZAP baseline DAST only when
    `API_AUTHORIZATION_TYPE=NONE`.
14. If deployment validation fails, update Lambda back to the previous image
    and re-apply Terraform with the previous URI to remove state drift.
15. Use `devsecops deploy status`, `devsecops deploy logs`, and, when an
    explicit operator rollback is required, `devsecops deploy rollback` for the
    rest of the deployment lifecycle without constructing `gh` commands.

## Workload Image Contract

The supplied image must be compatible with Lambda container package type and
must be published before the production deploy workflow runs. Use immutable tags
or image digests; do not use `latest` or `bootstrap`.

Validate the image URI locally before writing it into config:

```bash
devsecops image validate --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo:sha-abc123
```

The bring-your-own-image path is documented in
[Bring your own Lambda image](docs/bring-your-own-image.md). Keep example or
real workload source in a separate repository; use
[Separate example workload template](docs/example-workload-template.md) as the
repository contract.

If `ENABLE_HTTP_VALIDATION=true`, the image must handle API Gateway HTTP API
events and return a successful response for `GET /health`. If
`ENABLE_DAST=true`, set `API_AUTHORIZATION_TYPE=NONE` only when the API is
safe for a passive unauthenticated OWASP ZAP baseline scan.

## Useful Terraform Outputs

Example shape after a successful `prod` deploy:

```text
environment = "prod"
terraform_workspace = "prod"
api_gateway_health_url = "https://abc123.execute-api.us-east-1.amazonaws.com/health"
api_gateway_invoke_url = "https://abc123.execute-api.us-east-1.amazonaws.com/"
ecr_repository_name = "devsecops-pipeline-prod-lambda-repo"
ecr_repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/devsecops-pipeline-prod-lambda-repo"
lambda_function_name = "devsecops-pipeline-prod-lambda"
output_s3_bucket_name = "devsecops-pipeline-prod-workload-data-123456789012"
```

Health check, when the workload implements `/health`:

```bash
devsecops health --aws-sigv4
```

## Reference Documents

* [Security model](docs/security-model.md)
* [Security controls and policy presets](docs/security-controls.md)
* [Scanning tool rationale](docs/scanning-tools.md)
* [AWS cost estimation](docs/cost-estimation.md)
* [Troubleshooting guide](docs/troubleshooting.md)
* [Product roadmap](ROADMAP.md)
* [Command inventory](docs/command-inventory.md)
* [CLI architecture](docs/cli-architecture.md)
* [Stability contract](docs/stability-contract.md)
* [Generated artifacts](docs/generated-artifacts.md)
* [First successful pipeline](docs/first-successful-pipeline.md)
* [Production deployment evidence](docs/production-deployment-evidence.md)
* [v1.0.0 release candidate checklist](docs/v1.0.0-release-candidate-checklist.md)
* [Bring your own Lambda image](docs/bring-your-own-image.md)
* [Separate example workload template](docs/example-workload-template.md)
* [Operational runbooks](docs/runbooks/README.md)
* [AWS OIDC and IAM policy guidance](AWS_policy.md)
* [Distribution and compatibility](docs/distribution.md)
* [Release checklist](docs/release-checklist.md)
* [Upgrade guide](docs/upgrade-guide.md)
* [Known limitations](docs/known-limitations.md)
* [Changelog](CHANGELOG.md)
* [v0.13.1 release notes](docs/release-v0.13.1.md)
* [v0.13.0 release notes](docs/release-v0.13.0.md)
* [v0.12.0 release notes](docs/release-v0.12.0.md)
* [v0.11.0 release notes](docs/release-v0.11.0.md)
* [v0.8.0 release notes](docs/release-v0.8.0.md)
* [v0.7.0 release notes](docs/release-v0.7.0.md)
* [v0.6.1 release notes](docs/release-v0.6.1.md)
* [v0.6.0 release notes](docs/release-v0.6.0.md)
* [v0.5.0 release notes](docs/release-v0.5.0.md)
* [v0.4.1 release notes](docs/release-v0.4.1.md)
* [v0.4.0 release notes](docs/release-v0.4.0.md)
* [v0.3.0 release notes](docs/release-v0.3.0.md)
* [v0.2.0 release notes](docs/release-v0.2.0.md)
* [v0.1.0 release notes](docs/release-v0.1.0.md)

## Current Limitations

The full accepted-limitations and stable-release blocker register is tracked in
[Known limitations](docs/known-limitations.md).

* Application source, dependency scanning, and image build logic are expected to
  live in the workload repository or an upstream release workflow.
* The CLI is the product surface, but Terraform and GitHub Actions remain the
  execution layer. Advanced operators may still need to inspect Terraform plans
  and workflow logs directly.
* API Gateway defaults to IAM authorization, but workload-level user identity,
  tenant checks, and business authorization are still outside this repository.
* Optional DAST is a passive baseline scan only. Authenticated flows and
  business-logic checks need workload-specific tests.
* Before `v1.0.0`, the release record still needs a real AWS/GitHub production
  walkthrough evidence bundle plus final GitHub CLI, AWS CLI, and WSL2
  compatibility transcripts.
