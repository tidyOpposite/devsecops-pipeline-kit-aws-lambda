# DevSecOps CLI Kit for AWS Lambda

A terminal CLI for configuring, deploying and operating a Lambda container in
an explicitly selected AWS account. Review saved Terraform plans before apply,
check signed HTTP responses, and recover a previous image after failed health
validation.

Current source: **`0.16.0b2.dev0`** (unpublished). Published prerelease:
**`v0.16.0-beta.1`** (`0.16.0b1`); previous baseline: `v0.15.0`.
The published beta predates the single-operator lab. **Version 1.0 is not released.**
See the [source notes](docs/release-v0.16.0b2.dev0.md) and [changelog](CHANGELOG.md).

## Choose Your Workflow

| Workflow | Purpose | Requirements |
| --- | --- | --- |
| Local demo | Learn the menu, configuration and plan preview without cloud requests. | Git, Python 3.11–3.14 and venv/pip on Debian 13 or macOS. |
| Single-operator AWS lab | Deploy, update, verify, roll back and remove a dev workload in one account. This is the stable 1.0 target. | The checkout and matching CLI, Terraform, AWS CLI with a named profile, and Lambda-compatible images in ECR. |
| Experimental production integration | Operate through protected GitHub Actions/OIDC workflows. | Additional repository protections, separate plan/deploy roles and a remote Terraform backend. |

The lab requires neither an independent reviewer nor a second AWS account.
Production integration retains its separate safeguards and acceptance process.

## Quick Start

Install the current checkout and run its local demo:

```bash
git clone https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-pipeline-kit &&
cd devsecops-pipeline-kit &&
python3 -m venv .venv &&
.venv/bin/python -m pip install --no-deps . &&
export PATH="$PWD/.venv/bin:$PATH" &&
devsecops --version &&
devsecops setup --yes --strict &&
devsecops status &&
devsecops dry-run
```

Expected result: `Demo complete`, a local `.devsecops-pipeline.toml`, and a
sample-image preview. A new setup defaults to demo; an existing setup resumes
its saved mode. No AWS or GitHub credentials are needed for this path.

Keep the checkout: the wheel contains the CLI, while Terraform and workflow
sources live in the repository. Record `git rev-parse HEAD` and
`devsecops --version` when verifying a source build. Commands from checkout
subdirectories use the detected project root.

For release assets, verified installation and supported tool versions, see
[Distribution and compatibility](docs/distribution.md).

## Daily Commands

```bash
devsecops menu                       # Interactive navigation
devsecops                           # Compact status and next action
devsecops config validate            # Check local settings
devsecops config diff                # Review configuration drift
devsecops generate --dry-run         # Preview generated files
devsecops snapshot list              # Inspect local recovery points
devsecops inventory --format json    # Command and stability contract
```

Run `devsecops COMMAND --help` for flags and examples. Human-readable output
includes a recommended next command; machine-readable output stays parseable.
Configuration changes belong in the local config. Regenerate CLI-owned files
instead of editing them directly. Local snapshot restore affects local files;
cloud rollback is a separate operation.

## Deploy One AWS Lab

Start with the [single-operator lab guide](docs/single-operator-lab.md). It covers
AWS authentication, account/region checks, registry creation, image publication,
concurrency, signed requests and cleanup. The optional
[Text Stats Lambda](examples/text-stats/README.md) supplies small A/B/C images
for a complete update and recovery demonstration.

```bash
devsecops lab init diploma --expected-account-id 123456789012 --region eu-north-1 --profile diploma
devsecops lab plan diploma --stage registry
# Read the saved plan; use its actual plan ID and review SHA-256:
devsecops lab apply diploma --plan-id PLAN_ID --sha256 REVIEW_SHA256 --yes
```

Apply accepts the reviewed saved plan, bound to account, region, source,
settings, state and immutable image. Use `lab status`, `lab request` and
`lab logs` to inspect actual results. Failed updates attempt recovery to the
previous verified image; a recovered deployment still returns a failure exit.

Lab state, settings and evidence live under `.devsecops/labs/`. Back them up
before teardown. Follow [Finish demo / decommission](docs/runbooks/finish-demo.md)
to review retained data, empty owned versioned buckets and ECR, apply a destroy
plan, then verify resource absence, KMS schedules and delayed billing.

## Current Limitations

- The CLI consumes published images. Application builds, dependency scans and
  image publication belong to the workload's build process.
- The lab uses local state and one operator. It does not run the production
  workflow or its security scanners. Low-quota shared-pool mode has no dedicated
  per-function capacity guarantee.
- API Gateway defaults to IAM authorization. Application users, tenant checks
  and business permissions remain workload responsibilities.
- Production/OIDC workflows are experimental. Optional ZAP testing is a passive
  baseline scan; Snyk requires a separate account/token.
- Windows/WSL2 compatibility is unverified. PyPI publishing is deferred.

See [Known limitations](docs/known-limitations.md) for the full scope and
[release evidence](docs/single-operator-release-evidence.md) for acceptance
requirements tied to a specific commit and wheel.

## Documentation

Use the [documentation index](docs/README.md) to find installation, upgrades,
troubleshooting, security, command contracts and maintainer guides.

- [First successful pipeline](docs/first-successful-pipeline.md)
- [Experimental production walkthrough](docs/experimental-production-walkthrough.md)
- [Stability contract](docs/stability-contract.md) and [generated artifacts](docs/generated-artifacts.md)
- [Contributing and tests](CONTRIBUTING.md)
- [Release checklist](docs/release-checklist.md) and [roadmap](ROADMAP.md)
