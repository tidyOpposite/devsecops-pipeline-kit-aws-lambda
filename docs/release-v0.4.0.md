# Release v0.4.0

This release focuses on trustworthy generation and CI validation for the
CLI-owned infrastructure artifacts.

## Highlights

* Golden tests protect generated Terraform tfvars, GitHub variable files, and
  GitHub setup scripts.
* Generated `terraform/generated.auto.tfvars` now uses Terraform
  fmt-compatible alignment.
* Rendered artifacts are tested for stable diffs across repeated runs.
* End-to-end CLI coverage now runs `config new`, `config validate`, `render`,
  and `report` in a temporary repository.
* CI installs the root package and verifies the `devsecops` console command.
* CI renders generated Terraform variables before running Terraform
  `fmt`, `init -backend=false`, and `validate`.
* Mocked tests cover missing `gh`, missing AWS credentials, and unavailable
  Terraform.
* Snapshot and rollback tests prove CLI-owned files can be restored without
  overwriting user-owned files.

## Recommended First Run

```bash
pipx install .
devsecops config new --preset balanced
devsecops config validate
devsecops render
devsecops report
```

## Validation

The release was validated with:

```bash
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate -no-color
```
