# Scanning Tools

The experimental GitHub production workflow uses Trivy for IaC, Snyk Container
for configured images and OWASP ZAP for passive checks on explicitly public APIs.
The single-operator lab uses its own health and deployment checks.

Use `devsecops controls`, `devsecops explain dast` and `devsecops doctor github`
to inspect gates. See [security controls](security-controls.md) for presets and
[scanner isolation](security-gate-acceptance.md#reproducible-scanner-boundary)
for how CI runs the tools.

Snyk requires `enable_snyk_scan=true` and the GitHub secret `SNYK_TOKEN`.
ZAP requires explicit opt-in and `API_AUTHORIZATION_TYPE=NONE`; keep IAM auth
for private APIs and verify authenticated routes with workload-specific tests.
Run source and dependency checks in the workload build process before
publishing the image.

## Gate Policy

| Finding source | Gate behavior |
| --- | --- |
| Snyk high/critical image vulnerability | Fail deployment when `SNYK_TOKEN` is configured. |
| Trivy high/critical IaC finding | Fail CI. |
| OWASP ZAP fail-level result | Fail deployment validation and trigger Lambda rollback when `ENABLE_DAST=true` and `API_AUTHORIZATION_TYPE=NONE`. |
| OWASP ZAP warnings | Report but do not fail by default (`-I`) to avoid noisy rollback loops. |
