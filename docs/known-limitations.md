# Known Limitations

This register separates accepted product limitations from blockers that must
be closed before `v1.0.0` can be called stable.

## Accepted Limitations

These are intentional boundaries for the first stable CLI release. They should
stay explicit in docs and release notes, but they do not block `v1.0.0`.

| Limitation | Why accepted | User action |
| --- | --- | --- |
| Workload source and image build logic are outside this repository. | The product is the pipeline CLI, not a sample application framework. | Build and publish an immutable Lambda-compatible image in the workload repository. |
| Terraform, GitHub Actions, AWS, and scanners remain visible execution layers. | Operators need reviewable infrastructure and workflow behavior. | Inspect Terraform plans, workflow logs, and generated artifacts before mutating AWS or GitHub. |
| Native Windows is not a release target. | The supported Windows path is WSL2 Ubuntu, which keeps shell, path, Terraform, and CLI behavior consistent. | Use WSL2 Ubuntu for Windows workstations. |
| PyPI publishing is deferred. | GitHub Release wheels plus `SHA256SUMS` are the documented package path. | Install pinned or latest wheels from GitHub Releases. |
| Workload-level application authorization is outside this repository. | The generated API route defaults to IAM authorization, but user identity, tenant isolation, and business rules are workload-specific. | Keep `API_AUTHORIZATION_TYPE=AWS_IAM` for production and add workload-specific authZ/authN where required. |
| DAST is an OWASP ZAP passive baseline scan. | Authenticated flows and business-logic testing are workload-specific. | Add application-specific DAST, API tests, and auth-aware security tests in the workload repository. |
| Snyk container scanning is optional. | Some users do not have Snyk accounts or tokens during early pipeline setup. | Enable `ENABLE_SNYK_SCAN=true` and configure `SNYK_TOKEN` for stricter production candidates. |
| Scanner plugin support is not implemented. | Extensible scanner plugins are a post-1.0 backlog item. | Use the documented Trivy, Snyk, and OWASP ZAP hooks, or add custom workflow steps intentionally. |
| Deployment run and previous-image history is local to one checkout. | The ignored journal intentionally avoids a shared mutable control plane and stores no credentials. Named runs remain discoverable, but another workstation does not inherit the previous-image value. | Use `--run-id` for status/logs and pass a reviewed immutable `--image-uri` when rolling back without the originating journal. |

## Blockers Before v1.0.0 Stable

These must be closed before tagging `v1.0.0`.

Run `devsecops criteria --strict` before any stable tag decision. It fails
until the production evidence bundle and WSL2 transcript are present in the
evidence directory.

| Blocker | Closure evidence |
| --- | --- |
| Full AWS/GitHub production walkthrough execution evidence is missing. | Completed [Production deployment evidence](production-deployment-evidence.md) bundle attached to the release record. |
| GitHub CLI and AWS CLI compatibility have not been verified in the target repository and AWS account for the release candidate. | `gh --version`, `aws --version`, `devsecops doctor github --strict --format json`, `devsecops doctor aws --environment prod --strict --format json`, and Actions status evidence. |
| WSL2 Ubuntu compatibility does not yet have an attached release-candidate transcript. | WSL2 install, `devsecops --version`, first-success dry-run, completion generation, and unit-test transcript. |

## Review Rule

Every release note from `v0.11.0` onward should state whether these limitations
changed. A limitation that causes install, upgrade, verification, deployment,
or rollback failure in a supported environment must move from accepted
limitation to blocker until fixed or explicitly removed from support.
