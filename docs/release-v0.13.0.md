# Release v0.13.0

`v0.13.0` is an internal architecture and maintainability release. It turns
the CLI from a single large implementation module into a layered application
while preserving its existing commands, JSON contracts, generated artifacts,
exit codes, and snapshot safety rules.

## Highlights

* Config, rendering, readiness, reports, snapshots, parser construction,
  completion, contracts, shared models, and presentation logic now have
  focused modules.
* AWS and GitHub integrations are provider adapters instead of facades over
  `main.py`.
* Diagnostic and next-action workflows receive replaceable dependencies for
  external tools, HTTP requests, clocks, and snapshot identifiers.
* `main.py` is now the composition, command-handler, and terminal UI boundary;
  its size was reduced by roughly 60 percent.
* Architecture tests prevent circular module dependencies and reverse imports
  into the command layer.
* The runtime version has one canonical source in `devsecops_cli.__init__`.

## Compatibility

There are no intentional command-line or config-schema breaking changes in
this release. Config schema version remains `1`, and existing
`.devsecops-pipeline.toml` files do not require migration or regeneration solely
because of the upgrade.

The established imports exposed through `devsecops_cli.main` remain available
as a compatibility boundary even though their implementations now live in
their owning modules.

## Validation

The release was checked with the full 105-test suite, Python compilation,
top-level help/version/inventory/completion smoke tests, and an installed-wheel
smoke test. The wheel contains every extracted architecture module.
