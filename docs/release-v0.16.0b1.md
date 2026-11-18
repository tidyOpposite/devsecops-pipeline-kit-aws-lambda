# v0.16.0-beta.1

This prerelease packages the deployment, security and terminal improvements
since `v0.15.0`. The Python package and `devsecops --version` use the canonical
version **`0.16.0b1`**. It is available for testing; final production acceptance
is pending.

## Changes

* Start with a complete local demo without AWS credentials. Guided setup resumes
  safely, previews preset replacements and preserves deployment identity.
* Validate production policy in both CLI and GitHub Actions, pin the reviewed
  commit/configuration/image digest, and verify deployment/rollback run identity.
* Validate Lambda image manifests and Linux `amd64` compatibility; retain image
  digests required for recovery and verify health after deployment or rollback.
* Keep PR checks free of AWS credentials, separate plan/deploy OIDC roles and
  isolate the pinned scanner from host credentials.
* Preserve a working installation when an upgrade fails and check package,
  installer and release versions before publication.
* Improve narrow terminal layouts, menu shortcuts, closed-input handling and
  malformed endpoint errors.
* Add reviewed decommission guidance and scoped S3 cleanup helpers.
* Include an optional, tested text-statistics Lambda with healthy/failing image
  variants. A separate workload repository is optional.

## Install

Keep the CLI, Terraform and workflows at the same tag:

```bash
git clone --branch v0.16.0-beta.1 --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-beta &&
cd devsecops-beta &&
python3 -m venv .venv &&
.venv/bin/python -m pip install --no-deps . &&
export PATH="$PWD/.venv/bin:$PATH" &&
devsecops --version &&
devsecops setup --mode demo --yes --strict
```

The release also provides an installer, wheel, source archive and `SHA256SUMS`.
Select `--version v0.16.0-beta.1` explicitly when using the installer; an
unpinned installer does not select this prerelease.

Config schema remains `1`. After an upgrade, review configuration and generated
diffs before applying GitHub or AWS changes. See the
[upgrade guide](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v0.16.0-beta.1/docs/upgrade-guide.md).

## Acceptance And Limitations

Real AWS deployment, automatic/manual recovery and decommission acceptance
remain pending. The protected production workflow requires an independent
reviewer. A one-operator cloud demonstration in one AWS account is not yet
implemented; the separate runtime acceptance workflow requires a distinct
sandbox account. Publishing this prerelease does not run those workflows.

Windows and WSL2 are unverified and outside this release target. Platform
evidence must come from macOS or supported Ubuntu. Internal audit journals,
personal demonstration reports and raw test evidence remain local and are
excluded from tracking; user guides and reusable release instructions remain
in the repository. See
[known limitations](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v0.16.0-beta.1/docs/known-limitations.md).
