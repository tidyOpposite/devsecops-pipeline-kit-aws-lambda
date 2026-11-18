# Release v0.4.1

This patch release tightens packaging and CI behavior after `v0.4.0`. It does
not add new CLI commands or start the next roadmap milestone.

## Fixes And Improvements

* `python -m devsecops_cli.main --version` no longer emits a package import
  `RuntimeWarning`.
* Version consistency is now tested across the CLI runtime, package
  `__version__`, root `pyproject.toml`, and `cli/pyproject.toml`.
* CI jobs now have explicit timeouts.
* CI now runs `python -m build` before the package install smoke test.
* Release builds explicitly install `build`, `setuptools`, and `wheel`.
* Roadmap implementation statuses now reference released versions instead of
  stale `Unreleased` wording.

## Validation

The release was validated with:

```bash
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
python -m build
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate -no-color
```
