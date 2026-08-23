# Contributing

This repository is now developed as a CLI-first DevSecOps product for AWS
Lambda pipelines. Contributions are welcome when they improve the terminal
experience, correctness, security, reproducibility, documentation, or the
Terraform/GitHub execution layer behind the CLI.

## Product Priorities

The CLI is the primary user interface. Changes should keep these priorities in
mind:

* Clear terminal workflows for setup, validation, rendering, diagnostics, and
  rollback.
* Actionable readiness feedback instead of raw tool output wherever possible.
* Safe defaults, explicit confirmation for risky actions, and local snapshots
  before overwriting CLI-owned files.
* Terraform and GitHub Actions behavior that can be configured, explained, and
  verified from the CLI.
* Documentation that starts with `devsecops ...` commands before manual
  Terraform, AWS, or GitHub fallback steps.

## Useful Contribution Areas

* CLI navigation, prompts, command ergonomics, packaging, and tests.
* Readiness checks for local tooling, Terraform, GitHub, AWS, security gates,
  and deployment state.
* GitHub CLI integration for repository variables, secrets, Actions status, and
  branch protection.
* AWS diagnostics for backend, ECR, Lambda, API Gateway, CloudWatch, and IAM.
* Terraform security improvements and least-privilege IAM refinements.
* Scanner integration, policy presets, reports, and release workflow
  automation.
* Documentation for using the CLI in real AWS accounts.

## Development Notes

1. Treat CLI behavior as product behavior. If a change affects commands,
   prompts, menu navigation, generated artifacts, or readiness scoring, update
   tests and documentation in the same change.
2. Do not commit cloud credentials, API tokens, Terraform state, local CLI
   config, snapshots, or `.tfvars` files.
3. Keep security scanner failures visible. Avoid suppressions unless the risk
   is documented and intentionally accepted.
4. Prefer small pull requests with clear rationale and validation notes.
5. Preserve dependency-free core CLI flows unless a dependency is clearly worth
   the packaging and installation cost.
6. Preserve the module boundaries in [CLI architecture](docs/cli-architecture.md):
   domain and provider modules must not import `devsecops_cli.main`, and new
   side effects should remain replaceable in tests.

## Local Checks

Run the focused CLI checks before opening a pull request:

```bash
python3 -m py_compile cli/devsecops_cli/*.py cli/tests/test_devsecops_cli.py
PYTHONPATH=cli python3 -m unittest discover -s cli/tests -v
PYTHONPATH=cli python3 -m devsecops_cli readiness
```

For infrastructure changes, also run the relevant Terraform and workflow
validation:

```bash
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/deploy.yml")'
```

## Documentation

Documentation should be CLI-first:

* Start with the CLI command that performs or diagnoses the workflow.
* Explain generated files and Terraform/GitHub behavior as implementation
  details behind that command.
* Include manual commands only as fallback or advanced operator guidance.
* Update `README.md`, `CHANGELOG.md`, and the relevant document under `docs/`
  for user-visible behavior changes.

## Security

Please do not disclose vulnerabilities publicly before they are reviewed. Use
the process described in `SECURITY.md`.
