# Release v0.15.0

GitHub Actions now uses the deployment repository's settings to generate
Terraform inputs and backend configuration. The local configuration and
generated inputs remain ignored by Git.

* Production readiness checks verify required GitHub reviewers and Lambda health.
* The CLI detects stale generated files, rejects invalid config edits, and
  returns machine-readable errors for malformed configuration in JSON mode.
* The terminal menu resumes setup and offers deployment and rollback previews
  and confirmed actions. Tables wrap to fit narrower terminals.

Update the CLI and workflow together, regenerate deployment inputs, and run
`devsecops github setup --apply` in the deployment repository to synchronize
the new `PIPELINE_CONFIG_JSON` variable. See the [upgrade guide](upgrade-guide.md)
for the full sequence and production verification commands.
