# v0.16.0-beta.2

Prerelease for testing the local CLI and single-operator AWS dev lab.
Python package version: **`0.16.0b2`**. Version 1.0 has not been released;
GitHub/OIDC production integration remains experimental.

## Included

- A dev-only `lab` command/menu for one operator in one AWS account. It owns
  separate local state and supports registry creation, deployment, signed HTTP
  requests, logs, automatic recovery, manual rollback and reviewed destruction.
- Saved plans bound to account/region, immutable image, source/provider,
  settings and state, with review SHA-256, expiry and replay protection.
- Explicit shared-pool concurrency for low-quota dev accounts; production
  retains its positive reservation policy and approval safeguards.
- Temporary named-profile credential support, including interpreter paths with
  spaces. Credentials are resolved in memory rather than saved in lab state.
- Fixes for Lambda KMS configuration permissions, CloudWatch pagination and
  installation-path-independent source fingerprints.
- Debian 13 ARM64 compatibility and CI checks, alongside the macOS target.
  Windows/WSL2 support remains unverified.
- A patched, pinned Text Stats Lambda example, final-image scan guidance,
  streamlined documentation and focused behavioral/security regression tests.

## Install

Keep the checkout and package at the same tag:

```bash
git clone --branch v0.16.0-beta.2 --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-beta &&
cd devsecops-beta &&
sh install.sh --version v0.16.0-beta.2 &&
export PATH="$HOME/.local/bin:$PATH" &&
devsecops --version
```

Expected: `devsecops 0.16.0b2`. Select the prerelease explicitly; an unpinned
installer selects the latest non-prerelease. The installer verifies the wheel
against the release manifest. Downloaded installers should be verified before
execution, as described in the [distribution guide](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v0.16.0-beta.2/docs/distribution.md).

## Upgrade And Scope

Config schema remains `1`. Upgrade CLI and Terraform sources together, back up
local configuration/lab state, validate config and review a generation preview.
Source/provider changes invalidate saved lab plans: create a fresh reviewed
plan. Beta.1 wheels do not contain the lab commands.

The lab is the supported release target for one-account demonstrations, not
production acceptance. It does not run the protected production scanner jobs.
Build/publish images separately, review retained data before teardown and
verify actual resource removal, KMS schedules and delayed billing.

Cloud acceptance and screenshots are tied to their recorded commit and wheel;
proof from an earlier snapshot does not accept this new release identity.
Follow the [lab guide](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v0.16.0-beta.2/docs/single-operator-lab.md),
[upgrade guide](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v0.16.0-beta.2/docs/upgrade-guide.md)
and [known limitations](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v0.16.0-beta.2/docs/known-limitations.md).
