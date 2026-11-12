# Contributing

The supported product scope is local CLI and single-operator AWS dev lab.
Production GitHub/OIDC integrations remain experimental, with their security
guards intact. Prefer small changes that improve operator behavior, correctness
or reproducibility. Follow the [module boundaries](docs/cli-architecture.md).

## Local Checks

From a reviewed checkout with Python 3.11–3.14:

```bash
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
python3 -m unittest discover -s examples/text-stats/tests
sh -n install.sh
git diff --check
```

Install optional Rich to exercise its renderer locally; CI runs that check
separately. The real-provider credential regression needs
`DEVSECOPS_TEST_TERRAFORM` and `DEVSECOPS_TEST_AWS_PROVIDER_DIR`; CI configures
those after installing the locked provider. It uses fake credentials and a
local STS endpoint, not an AWS account.

For packaging changes, build/install the wheel in a fresh environment and check
`devsecops --version`, `completion` and the local demo. For infrastructure
changes, also run:

```bash
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform validate
terraform -chdir=terraform test
```

Lab and isolated-acceptance mock tests live in `terraform/lab/tests` and
`terraform/acceptance/tests`. Their CI steps show initialization and provider
lock handling. Real AWS acceptance is a separate explicitly scoped operation;
ordinary tests must not create cloud resources or use real credentials.

## Keep Tests Focused

- Test observable results, failure exits and side effects at process/provider
  boundaries. Use temporary projects and fake credentials.
- Retain regressions for data loss, authentication, plan drift, recovery,
  pagination, installation and teardown. Security failures must remain visible.
- Prefer one behavioral scenario or golden fixture over several tests checking
  the same output. Avoid assertions about document wording, heading order or
  internal helper calls when an existing journey already covers the behavior.
- Keep regression cases that reproduce a real bug even when the fix is small.
  Do not add tests for reversible prose changes.

## Documentation And Local Files

Start user guidance with the CLI action and its expected result. Put advanced
production details in their own guides; link to the authoritative procedure
instead of copying it. Update the relevant guide and changelog for user-visible
changes. The [documentation index](docs/README.md) is the entry point.

Keep audit notes, test logs and demonstration evidence in ignored `docs/local/`,
`.devsecops/` or an external directory. Never commit credentials, local config,
Terraform state, saved plans, snapshots or generated `.tfvars` files. Public
documentation contains reusable guidance, not workstation-specific run logs.

See [SECURITY.md](SECURITY.md) for private vulnerability reporting and the
[release checklist](docs/release-checklist.md) for publishing requirements.
