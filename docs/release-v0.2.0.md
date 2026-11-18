# Release v0.2.0

This release moves DevSecOps Pipeline Kit into an installable Python package and
adds the CLI-first operating features built after v0.1.0.

## Highlights

* Root package install support with `pipx install .` and the `devsecops`
  console command.
* Package-based CLI structure under `cli/devsecops_cli/`.
* AWS Doctor diagnostics for backend, ECR, IAM, Lambda, API Gateway,
  CloudWatch logs, and configured ECR images.
* Policy preset commands: `preset list`, `preset show <name>`, and
  `preset apply <name>`, including `enterprise` and `student-demo`.
* Pipeline Composer for choosing controls and regenerating config, helper
  artifacts, and readiness reports.
* Dashboard watch mode with compact/full terminal layouts and category
  readiness scores.
* Optional `devsecops tui` command with Rich output and compact dashboard
  fallback.
* GitHub release workflow now attaches Python wheel and source distribution
  artifacts.

## Install

```bash
pipx install .
devsecops dashboard
```
