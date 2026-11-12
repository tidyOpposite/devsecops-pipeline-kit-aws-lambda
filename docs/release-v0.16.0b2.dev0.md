# 0.16.0b2.dev0 · source development

Unpublished source after `v0.16.0-beta.1` (`0.16.0b1`). Do not use this
development version as a GitHub Release tag or assume beta.1 assets include it.

* Add `devsecops lab init/plan/apply/status/request/logs` and a Deploy-menu hub
  for one operator in one AWS account, with independent local state and names.
* Bind saved plans to explicit account/region, source/provider fingerprints,
  state, immutable images and a one-hour review hash. No implicit apply.
* Keep APIs IAM protected; record signed requests, readback and private hashes.
  Failed updates restore a previously verified image and refresh state; the
  failed deployment remains a failure even after successful recovery.
* Keep production approval and separate-account acceptance unchanged. Lab proof
  is explicitly separate and never substitutes for production evidence.

* Add Lambda capacity diagnostics using account limits and existing function
  reservations; recheck in the protected runner before planning and apply.
* Add explicit `lab concurrency --mode unreserved` for low-quota dev accounts,
  with live/state readback. Production retains its positive reservation policy.
* Fix lab provider credential-process startup when the installed CLI's Python
  path contains spaces. Verify the locked provider against local fake STS in
  CI, including literal shell characters in workspace paths.

Record deploy/update/recovery/cleanup acceptance for the exact candidate
commit and wheel before publication.
See [the reusable lab guide](single-operator-lab.md).

* Scope stable 1.0 to local CLI and single-operator dev lab. Production helpers
  are experimental. Add checksum/source/package-bound lab release proof with
  real lifecycle and cleanup; preserve the separate production verifier.

* Replace Ubuntu Linux acceptance with Debian 13 ARM64. Require separate macOS
  and Debian transcripts; add a pinned Debian CI container check. Track the
  signed AWS provider Linux ARM64 content checksum so read-only lab init can
  validate an already installed provider on Debian.

* Simplify user documentation around the demo and single-operator lab; keep
  production guidance separate and repair its navigation links. Remove
  duplicate and prose-dependent tests while retaining behavioral regressions.
