# Release v0.13.1

`v0.13.1` extends the supported Python range to Python 3.14 without changing
the CLI command surface, config schema, generated artifacts, or deployment
workflow contracts.

## Highlights

* Root and CLI package metadata now support Python 3.11 through 3.14.
* The bootstrap installer accepts and auto-detects Python 3.14.
* GitHub Actions runs the full CLI, package build, and install-smoke matrix on
  Python 3.14 in addition to Python 3.11, 3.12, and 3.13.
* Compatibility documentation and release-candidate validation now include
  Python 3.14.

## Compatibility

There are no intentional command-line or config-schema breaking changes in
this release. Config schema version remains `1`, and existing
`.devsecops-pipeline.toml` files do not require migration or regeneration.

Python 3.11, 3.12, 3.13, and 3.14 are supported. Python 3.15 and newer remain
outside the supported range until they are covered by CI and release smoke
tests.

## Validation

The release was checked locally on Python 3.14.7 with the full 105-test suite,
package build, editable install, and `devsecops --version` smoke test. The
GitHub Actions release gates repeat the test, build, and install checks across
the complete supported Python matrix.
