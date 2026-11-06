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
| Windows and WSL2 are outside the current release target. | No Windows/WSL2 machine is available for acceptance; compatibility is unverified. | Use a supported Ubuntu or macOS host. Reintroducing Windows/WSL2 support requires its own validation. |
| PyPI publishing is deferred. | GitHub Release wheels plus `SHA256SUMS` are the documented package path. | Install pinned or latest wheels from GitHub Releases. |
| Workload-level application authorization is outside this repository. | The generated API route defaults to IAM authorization, but user identity, tenant isolation, and business rules are workload-specific. | Keep `API_AUTHORIZATION_TYPE=AWS_IAM` for production and add workload-specific authZ/authN where required. |
| DAST is an OWASP ZAP passive baseline scan. | Authenticated flows and business-logic testing are workload-specific. | Add application-specific DAST, API tests, and auth-aware security tests in the workload repository. |
| Snyk container scanning is optional. | Some users do not have Snyk accounts or tokens during early pipeline setup. | Enable `ENABLE_SNYK_SCAN=true` and configure `SNYK_TOKEN` for stricter production candidates. |
| Scanner plugin support is not implemented. | Extensible scanner plugins are a post-1.0 backlog item. | Use the documented Trivy, Snyk, and OWASP ZAP hooks, or add custom workflow steps intentionally. |
| Deployment run and previous-image history is local to one checkout. | The ignored journal intentionally avoids a shared mutable control plane and stores no credentials. Named runs remain discoverable, but another workstation does not inherit the previous-image value. | Use `--run-id` for status/logs and pass a reviewed immutable `--image-uri` when rolling back without the originating journal. |

## Blockers Before v1.0.0 Stable

These must be closed before tagging `v1.0.0`.

Run `devsecops criteria --strict` before any stable tag decision. It checks
the contents of the production evidence bundle and supported-platform transcript against
the release commit. Stable publication also verifies GitHub runs and logs and
compares the publication wheel with the reviewed CI candidate.

| Blocker | Closure evidence |
| --- | --- |
| Full AWS/GitHub production walkthrough execution evidence is missing. | Completed [Production deployment evidence](production-deployment-evidence.md) bundle attached to the release record. |
| GitHub CLI and AWS CLI compatibility have not been verified in the target repository and AWS account for the release candidate. | `gh --version`, `aws --version`, `devsecops doctor github --strict --format json`, `devsecops doctor aws --environment prod --strict --format json`, and Actions status evidence. |
| Supported-platform acceptance needs a transcript for the release candidate. | macOS or supported Ubuntu install, `devsecops --version`, local demo, completion, and unit-test transcript in `platform-transcript.txt`; exact CI runs record the remaining declared matrix. |
| Final teardown/retention acceptance has not been executed in the approved AWS test account. | [Finish-demo acceptance](runbooks/finish-demo.md#final-acceptance-record), data restore proof, per-workspace cleanup, backend retention/retirement, KMS schedule and later billing verification. |

## Review Rule

Every release note from `v0.11.0` onward should state whether these limitations
changed. A limitation that causes install, upgrade, verification, deployment,
or rollback failure in a supported environment must move from accepted
limitation to blocker until fixed or explicitly removed from support.
