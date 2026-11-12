# v1.0.0

First stable release of the local CLI and single-operator AWS dev lab in one
account. Python package version: **`1.0.0`**. Production GitHub/OIDC integrations
remain experimental and do not inherit lab acceptance.

## Included

- Local demo, interactive menu, resumable setup, validated configuration,
  deterministic generation, diagnostics and restricted local snapshots.
- An account-bound dev lab with separate local state: registry creation,
  deployment, signed requests, logs, automatic image recovery and manual rollback.
- Saved Terraform plans bound to account/region, immutable image, source/provider,
  settings and state, with review SHA-256, expiry and replay protection.
- Explicit shared-pool concurrency for low-quota dev accounts, without a
  per-function capacity guarantee. Production retains its reservation policy.
- Temporary named-profile credential support, including interpreter paths with
  spaces, without saving credential output in lab evidence.
- Reviewed cleanup helpers for versioned buckets, with backup acknowledgement,
  exact inventory checks and verification of remaining resources.
- Installation and upgrade recovery on the macOS/Debian target, a patched Text
  Stats Lambda example, streamlined documentation and behavioral/security tests.

## Install

Keep the checkout and package at the same tag:

```bash
git clone --branch v1.0.0 --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-kit &&
cd devsecops-kit &&
sh install.sh --version v1.0.0 &&
export PATH="$HOME/.local/bin:$PATH" &&
devsecops --version
```

Expected: `devsecops 1.0.0`. The installer verifies the wheel against the release
manifest. Verify a downloaded installer before execution; see
[distribution](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v1.0.0/docs/distribution.md).

## Upgrade

Config schema remains `1`. Upgrade CLI and Terraform sources together, back up
local configuration/lab state, validate config and review generated differences.
Source/provider changes invalidate saved lab plans: create a fresh reviewed plan.
A package upgrade does not apply AWS changes or synchronize GitHub permissions.
See the [upgrade guide](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v1.0.0/docs/upgrade-guide.md).

## Scope And Limits

The stable workflow requires one operator and one AWS account; it does not
require an independent reviewer or a second sandbox. It uses local state and
IAM-protected APIs. Image builds/publication and workload business permissions
remain operator/application responsibilities. The lab does not run the
production scanner jobs. Windows/WSL2 support and PyPI publishing are unverified
or deferred.

Release acceptance binds the exact source commit and installed CI wheel to
macOS/Debian checks, A/B/failed-C/recovery/manual rollback and reviewed cleanup.
KMS deletion schedules and delayed billing follow-up are recorded explicitly;
PendingDeletion is not represented as completed physical deletion. Checksums
establish integrity, not independent AWS attestation. Private runtime records
and screenshots are not part of the public package assets.

Follow the [lab guide](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v1.0.0/docs/single-operator-lab.md)
and [known limitations](https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda/blob/v1.0.0/docs/known-limitations.md).
