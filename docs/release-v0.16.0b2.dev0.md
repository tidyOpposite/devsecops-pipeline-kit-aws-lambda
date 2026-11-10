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

Real deploy/update/recovery/cleanup acceptance is pending.
See [the reusable lab guide](single-operator-lab.md).
