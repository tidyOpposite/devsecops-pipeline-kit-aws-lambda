# Release v0.7.0

Release date: 2026-06-08

Milestone 6 makes security and policy controls visible as product features,
not only as Terraform or GitHub Actions implementation details.

## Highlights

* `devsecops controls` now renders a control catalog that maps CLI options to
  Terraform, GitHub, AWS, scanner, and audit behavior.
* `devsecops explain <control>` is catalog-backed and supports controls such
  as `immutable-image`, `cors`, `approval-gate`, `plan-role`, `snyk`, `dast`,
  `rollback`, and legacy aliases like `image` or `backend`.
* `devsecops preset list` is now a policy preset comparison table with a
  documented posture for every preset.
* `devsecops config validate --strict` fails on production-risk warnings.
* `devsecops report --format json` writes attachable audit evidence to
  `dist/devsecops/audit-report.json`.
* Terraform variable validation now rejects wildcard production CORS and
  invalid environment bounds.

## Audit Evidence

Generate evidence for a pull request, workflow artifact, or release record:

```bash
devsecops config validate --strict
devsecops controls --format json
devsecops report --format json
```

The audit JSON includes readiness checks, strict config validation, current
control states, preset posture metadata, and least-privilege guidance for plan
and deploy roles.

## Upgrade Notes

`balanced` now uses an explicit production CORS placeholder
`https://app.example.com` instead of wildcard production CORS. Replace it with
your real production origin before deploying.

Demo-oriented presets can still surface strict validation warnings. This is
intentional: they remain useful for walkthroughs, but strict validation is the
release gate for production review.
