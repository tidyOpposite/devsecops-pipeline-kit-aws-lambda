# Release v0.12.0

`v0.12.0` is a security-hardening and release-readiness release. It includes
the one-command installer work, the Version 1.0 criteria gate, and the security
audit remediations completed before this release.

## Highlights

* API Gateway routes now default to `AWS_IAM` authorization through
  `api_authorization_type` and the `API_AUTHORIZATION_TYPE` GitHub variable.
* `devsecops health --aws-sigv4` can validate IAM-protected `/health` routes.
* Production deploy health validation signs IAM-protected requests with SigV4;
  OWASP ZAP baseline DAST runs only when the API is explicitly public.
* KMS service usage is constrained with account, service, and encryption
  context conditions where AWS supports them.
* Terraform bootstrap now uses a customer-managed KMS key, encrypted state
  locking, state access logging, TLS-only bucket policies, and lifecycle
  retention.
* GitHub Actions are pinned to commit SHAs, and CI/release build tooling is
  pinned to exact versions.
* Release artifacts now include `install.sh` and checksum coverage for the
  installer, wheel, and source distribution.
* `devsecops criteria` and `criteria.json` make Version 1.0 blockers
  machine-checkable.

## Upgrade Notes

Existing `.devsecops-pipeline.toml` files without `api_authorization_type`
continue to load through the existing config normalization path and default to
`AWS_IAM`. If a workload must stay public, set:

```bash
devsecops config set api_authorization_type NONE --render
```

Use `NONE` only for demo or intentionally public non-sensitive APIs. Production
health evidence should use:

```bash
devsecops health --aws-sigv4
```

## Limitations

Workload-level identity, tenant isolation, and business authorization remain
outside this repository even though the generated API route now defaults to IAM
authorization.
