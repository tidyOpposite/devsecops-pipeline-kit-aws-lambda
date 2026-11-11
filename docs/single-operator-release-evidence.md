# Single-operator release evidence

Stable 1.0 targets the local CLI and the single-operator `dev` lab in one AWS
account. Production GitHub/OIDC, independent review and separate-account runtime
acceptance remain experimental. Their original safeguards are unchanged.
Neither the proof nor the CLI may label a lab run `production_acceptance=true`.

Keep per-candidate evidence outside Git, for example in a private Desktop folder.
The owner can inspect it without receiving credentials. Use one clean reviewed
commit, one installed wheel and its matching Terraform checkout. Version 1.0 is
published only through a separate explicit release decision.

## Candidate bundle

- `release-proof.json`: schema_version 2, scope `single-operator-dev`,
  production_acceptance false, version, commit_sha, source_sha256, repository,
  ci_run_id, wheel_sha256, account_id, region, project_name, api_id and distinct
  immutable image URIs under images.a/b/c.
- `artifacts/`: the accepted CI wheel, source archive, installer and SHA256SUMS.
  `release-install.txt` records the installed version; `release-checksums.txt`
  includes the wheel hash and successful verification.
- `lab-scenario.json`: operations in order a/b/c/rollback/destroy, each with
  event (relative directory), review (relative review.json) and CLI exit_code.
  Preserve the original operation.json, result.json, command and HTTP records,
  saved plan.tfplan/plan.json/plan.txt/inputs/review. A is a fresh workload;
  B restores A on failure; C must fail (exit 1, observed 503) and recover B;
  manual rollback restores A. Every healthy result must bind live ARN/digest,
  state SHA-256 and signed health 2xx. Logs and requests supplement these checks.
- `cleanup.json`: account_id/region/project_name, managed_resources_after 0,
  backup_restore_verified true, backend `local-retained`, final_state and
  inventory relative file paths, billing_followup `pending` or `verified`.
  The inventory contains the 12 physical resource records including stage,
  alias and global role. checks must cover those exact ARNs, each with status,
  raw command evidence and query_id. An explicit not-found response or empty
  targeted list proves absence; KMS PendingDeletion needs its actual deadline.
  Archive data/images/logs/state independently and exercise restore before
  permanent cleanup. Preserve the actual backup/restore command transcripts.
- `platform-transcript.txt` and platform-specific records: actual OS identity,
  candidate commit/install/version, local demo, completion, passing tests,
  upgrade and installation failure recovery. Record tested architecture.
- `notes.md`: captions, limitations, UTC timestamps, inventory, retained data,
  KMS deadline and delayed billing follow-up. A pending billing follow-up must
  never be represented as confirmed zero cost.
- `manifest.json`: schema_version 1, files mapping every evidence-relative file
  to its SHA-256 (excluding manifest.json itself). Reject traversal, symlinks,
  changed/missing files, excessive sizes and mismatched identities. Checksums
  prove integrity; they do not constitute an independent AWS attestation.

## Verify before any stable tag

```bash
devsecops criteria --strict --format json --evidence-dir /absolute/private/bundle
# Before publication additionally verify the actual candidate CI and wheel:
devsecops criteria --strict --evidence-dir /absolute/private/bundle \
  --verify-github OWNER/REPO --artifacts-dir /absolute/private/bundle/artifacts
```

The existing production verifier is available separately with `--scope production`.
Do not substitute lab results for those experimental production checks.
The publisher verifies the default stable lab scope and exact CI wheel; no
production reviewer or separate AWS account is required for this scope.
To stage evidence for a future authorized release, use a separate draft
`evidence-vVERSION` on the exact commit and attach `release-evidence.zip`.
Do not create a stable tag until the owner authorizes publication.
