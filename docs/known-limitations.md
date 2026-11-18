# Known Limitations

This register separates accepted product limitations from blockers that must
be closed before `v1.0.0` can be called stable.

## Accepted Limitations

These are intentional boundaries for the first stable CLI release. They should
stay explicit in docs and release notes, but they do not block `v1.0.0`.

| Limitation | Why accepted | User action |
| --- | --- | --- |
| Workload builds are separate from the CLI deploy workflow. | The product consumes an already published image. An optional diploma example now lives in `examples/text-stats/`. | Build/test that example or your own application, then publish an immutable Lambda-compatible image. |
| Terraform, GitHub Actions, AWS, and scanners remain visible execution layers. | Operators need reviewable infrastructure and workflow behavior. | Inspect Terraform plans, workflow logs, and generated artifacts before mutating AWS or GitHub. |
| Windows and WSL2 are outside the current release target. | No Windows/WSL2 machine is available for acceptance; compatibility is unverified. | Use a supported Debian or macOS host. Reintroducing Windows/WSL2 support requires its own validation. |
| PyPI publishing is deferred. | GitHub Release wheels plus `SHA256SUMS` are the documented package path. | Install pinned or latest wheels from GitHub Releases. |
| Workload-level application authorization is outside this repository. | The generated API route defaults to IAM authorization, but user identity, tenant isolation, and business rules are workload-specific. | Keep `API_AUTHORIZATION_TYPE=AWS_IAM` for production and add workload-specific authZ/authN where required. |
| DAST is an OWASP ZAP passive baseline scan. | Authenticated flows and business-logic testing are workload-specific. | Add application-specific DAST, API tests, and auth-aware security tests in the workload repository. |
| Snyk container scanning is optional. | Some users do not have Snyk accounts or tokens during early pipeline setup. | Enable `ENABLE_SNYK_SCAN=true` and configure `SNYK_TOKEN` for stricter production candidates. |
| Scanner plugin support is not implemented. | Extensible scanner plugins are a post-1.0 backlog item. | Use the documented Trivy, Snyk, and OWASP ZAP hooks, or add custom workflow steps intentionally. |
| Deployment run and previous-image history is local to one checkout. | The ignored journal intentionally avoids a shared mutable control plane and stores no credentials. Named runs remain discoverable, but another workstation does not inherit the previous-image value. | Use `--run-id` for status/logs and pass a reviewed immutable `--image-uri` when rolling back without the originating journal. |
| Single-operator `lab` uses local state and private dev evidence. | It enables an explicitly separate account-bound demonstration, without independent production review. It does not run the protected production pipeline or its security scanners. | Back up `.devsecops/labs/`, explicitly select a quota-compatible concurrency policy and complete [real lab acceptance](single-operator-lab.md); do not treat lab proof as production acceptance. |

## Blockers Before v1.0.0 Stable

Stable scope is local CLI plus the single-operator dev lab in one AWS account.
Production/OIDC, independent review and a separate sandbox account are outside
this scope and remain experimental. Do not claim production acceptance from lab proof.

| Blocker | Closure evidence |
| --- | --- |
| Candidate lab acceptance | Same commit/wheel: fresh A, update B, failed C with automatic B, manual A, signed HTTP, state/digest/logs. |
| Platform acceptance | Candidate install/demo/completion/tests and upgrade/failure recovery transcripts for declared platforms. |
| Cleanup/retention | Verified independent archives/restore, reviewed destroy, exact resource absence, KMS schedule and explicit delayed-billing follow-up. |
| Package/source identity | Successful candidate CI, wheel SHA-256, checked source fingerprint and checksum manifest; `devsecops criteria --strict`. |

The [release evidence contract](single-operator-release-evidence.md) is normative.
`criteria --scope production` retains the separate experimental production verifier.

## Review Rule

Every release note from `v0.11.0` onward should state whether these limitations
changed. A limitation that causes install, upgrade, verification, deployment,
or rollback failure in a supported environment must move from accepted
limitation to blocker until fixed or explicitly removed from support.
