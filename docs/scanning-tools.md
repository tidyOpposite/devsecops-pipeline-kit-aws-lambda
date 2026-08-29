# Scanning Tool Rationale

The CLI is the product surface for enabling, explaining, and checking scanner
gates. GitHub Actions runs the scanners, while `devsecops compose`,
`devsecops controls`, `devsecops status`, `devsecops preset`, and
`devsecops generate` help the operator choose and validate the active policy.

The kit intentionally separates infrastructure scanning from workload source
scanning. This repository owns the CLI-managed AWS deployment template;
application source, dependencies, and image build hardening belong to the
workload release process that publishes `LAMBDA_IMAGE_URI`.

## Selected Stack

| Layer | Selected tool | Why |
| --- | --- | --- |
| IaC | Trivy config scan | Fast Terraform misconfiguration checks with straightforward GitHub Actions integration and CLI readiness reporting. |
| Container | Snyk Container | Optional deploy gate for known CVEs in the configured Lambda image. The CLI reports whether the gate can run based on config and secrets. |
| DAST | OWASP ZAP baseline | Optional passive HTTP scanning against explicitly public deployed APIs. The CLI keeps it disabled until the operator opts in and the API auth mode is `NONE`. |

## CLI Controls

Use the CLI to inspect and configure scanning posture:

```bash
devsecops controls
devsecops explain dast
devsecops compose
devsecops preset show strict
devsecops preset apply strict --generate
devsecops config set enable_snyk_scan true --generate
devsecops config set enable_dast true --generate
devsecops gh-doctor
```

`minimal` and `balanced` keep HTTP validation and DAST conservative by default.
`strict` enables validation controls and is intended for workloads that already
implement `/health` and can tolerate passive dynamic scanning.
`enterprise` also enables those gates while using locked-down CORS and longer
log retention. `student-demo` keeps scanning gates off for short demonstrations.

Snyk container scanning is controlled by `enable_snyk_scan`, generated as the
`ENABLE_SNYK_SCAN` GitHub variable, and also requires `SNYK_TOKEN`.

## Source SAST And SCA

No sample Lambda application source code is included in this repository, so the
CLI-managed pipeline does not run language-specific SAST or package SCA here.
Add those checks in the repository that builds the Lambda image.

Recommended workload gates:

| Workload layer | Recommended gate |
| --- | --- |
| Source code | Semgrep, CodeQL, Bandit, or an equivalent scanner for the workload language. |
| Dependencies | Snyk, Dependabot, pip-audit, npm audit, or ecosystem-specific SCA. |
| Unit and integration tests | Workload-specific test suite before image publication. |
| Image build | Reproducible build with pinned base image and no mutable production tags. |

## Trivy vs Checkov

| Criterion | Trivy config | Checkov |
| --- | --- | --- |
| Coverage | Terraform, Kubernetes, secrets, and images in one ecosystem. | Deep IaC policy coverage across Terraform, CloudFormation, Kubernetes, and more. |
| CI ergonomics | Simple GitHub Action, fast config scan, consistent severity filters. | Strong policy framework, but usually more configuration and suppression governance. |
| Fit for this repo | Good default because the repository currently needs a lightweight Terraform gate. | Good alternative if the project needs policy-as-code libraries and compliance mapping. |

Decision: Trivy remains the IaC gate because the CLI benefits from a compact
default scanner with simple operator messaging. Checkov is a good addition if
compliance reporting becomes a product goal.

## OWASP ZAP vs Nuclei

| Criterion | OWASP ZAP baseline | Nuclei |
| --- | --- | --- |
| Primary fit | Passive HTTP security baseline and spidering. | Template-driven detection for known exposures and CVEs. |
| Strength | Mature web app scanner, useful for headers, cookies, and common HTTP issues. | Fast, broad, and easy to extend with community templates. |
| Risk | Can create noisy warnings if used as a hard gate without tuning. | Template quality and target relevance need governance. |

Decision: OWASP ZAP is optional because this kit does not define the workload
routes. Enable it through the CLI only when the deployed workload has an
explicitly public HTTP surface that is safe for a passive baseline scan.

## Gate Policy

| Finding source | Gate behavior |
| --- | --- |
| Snyk high/critical image vulnerability | Fail deployment when `SNYK_TOKEN` is configured. |
| Trivy high/critical IaC finding | Fail CI. |
| OWASP ZAP fail-level result | Fail deployment validation and trigger Lambda rollback when `ENABLE_DAST=true` and `API_AUTHORIZATION_TYPE=NONE`. |
| OWASP ZAP warnings | Report but do not fail by default (`-I`) to avoid noisy rollback loops. |
