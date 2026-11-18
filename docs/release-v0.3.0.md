# Release v0.3.0

This release turns the project into a clearer CLI product with a stable local
configuration workflow, grouped command surface, and more predictable terminal
navigation.

## Highlights

* Product contract documentation for the CLI boundary, command inventory, and
  generated artifact ownership.
* Clean configuration workflow:
  `devsecops config new`, `show`, `validate`, `diff`, `reset`, `set`, and
  `schema`.
* `.devsecops-pipeline.toml` now includes `schema_version = 1` and has a
  migration scaffold for future schema versions.
* Generated files now include CLI-owned headers and point users back to local
  source configuration.
* Grouped CLI commands for:
  `doctor`, `github`, `terraform`, and `snapshot`.
* JSON and compact output modes for readiness and doctor workflows used by
  automation.
* Stable exit code constants for validation failures, missing external tools,
  authentication failures, unexpected errors, and interrupts.
* Main menu navigation now clears the terminal when entering and leaving menu
  sections.
* Main menu items are grouped into readable sections with up to three actions
  per row.

## Recommended First Run

```bash
pipx install .
devsecops config new --preset balanced
devsecops config validate
devsecops config diff
devsecops render
devsecops readiness
devsecops report
```

## Compatibility

Existing top-level aliases still work, including `init`, `set`,
`validate-config`, `github-setup`, `gh-doctor`, `aws-doctor`,
`actions-status`, `branch-doctor`, `plan`, `bootstrap`, `snapshots`, and
`rollback`.

New scripts should prefer grouped commands such as:

```bash
devsecops config set backend.bucket my-state-bucket --render
devsecops doctor local --format compact
devsecops doctor aws --environment prod --strict
devsecops github status --format json
devsecops terraform plan dev --create-workspace
devsecops snapshot restore --last --dry-run
```

## Validation

The release was validated with:

```bash
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
```
