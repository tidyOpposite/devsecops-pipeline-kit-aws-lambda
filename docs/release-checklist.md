# Release Checklist

Release scope is local CLI plus the single-operator AWS dev lab in one account.
Production/OIDC integrations retain a separate experimental acceptance process.
This guide defines release requirements; per-run results and screenshots stay
outside Git. Never replace an existing tag or its assets.

## Prepare The Version

Update `cli/devsecops_cli/__init__.py`, both `pyproject.toml` files,
`CHANGELOG.md`, `docs/release-v<VERSION>.md` and the current documentation links.
Use canonical Python versions (`0.16.0rc1`) for semantic prerelease tags
(`v0.16.0-rc.1`). Development versions cannot be published.

```bash
export VERSION="$(PYTHONPATH=cli python3 -c 'from devsecops_cli import VERSION; print(VERSION)')"
export TAG="${TAG:-v${VERSION}}"
PYTHONPATH=cli python3 -m devsecops_cli.release_version "$TAG" .
```

Choose the intended prerelease `TAG` explicitly. Check that the tag does not
already exist locally or on the remote before continuing.

## Validate The Candidate

Follow [Contributing](../CONTRIBUTING.md#local-checks): CLI/example tests,
installer syntax, package build/install, completion and applicable Terraform
checks. Inspect `git diff --check` and the full staged changes before committing.
Use a fresh package-output directory so existing evidence is not deleted.

Push the candidate commit and require a successful CI run. Record its exact
commit, CI run, wheel and SHA-256 manifest. Use the CI wheel for acceptance;
the stable publisher publishes the checked candidate assets rather than a
separately rebuilt wheel.

## Stable Evidence Gate

Complete the [single-operator release evidence contract](single-operator-release-evidence.md)
against the same clean commit, installed wheel and matching Terraform checkout:

- macOS and Debian platform records, including installer/upgrade recovery.
- Fresh A, update B, failed C/automatic B, manual rollback A and signed HTTP.
- Independent backups/restore, reviewed destroy and exact resource readback.
- Retained local state, KMS deletion schedules and explicit billing follow-up.
- Complete checksummed raw evidence and package/source identity.

```bash
devsecops criteria --strict --format json \
  --evidence-dir /absolute/private/candidate \
  --verify-github OWNER/REPO \
  --artifacts-dir /absolute/private/candidate/artifacts
```

Changing the candidate commit or version requires matching evidence. Preparatory
`evidence collect --rc` output alone is not cloud acceptance. Prereleases may be
published for testing before stable acceptance, with their limitations explicit.

For a stable tag, stage the checked `release-evidence.zip` on a separate draft
`evidence-v<VERSION>` at that exact commit, as specified by the release workflow.
Do not push a stable tag until the owner authorizes publication.

## Tag And Publish

After authorization, from the accepted release commit:

```bash
git tag -a "$TAG" -m "Release $TAG"
git push origin main
git push origin "$TAG"
```

The tag workflow validates version/notes identity before publishing. For stable
1.0+, it also verifies scoped evidence, GitHub CI and the accepted artifact
bytes. Check that the workflow succeeded and that the resulting release has
the correct prerelease flag, notes, installer, wheel, source archive and
`SHA256SUMS`. Re-download and verify the assets, then install/test the release
on the declared platforms. A failed workflow is not a completed release.

## Production Evidence Gate

A release claiming production acceptance additionally needs the original
[production evidence](production-deployment-evidence.md) and
[separate-account runtime acceptance](security-gate-acceptance.md), including
reviewer/OIDC protections. This gate does not apply to a lab-only claim. Keep
production safeguards intact and label the evidence scope accurately.

See [Known limitations](known-limitations.md), [Stability contract](stability-contract.md)
and [Upgrade guide](upgrade-guide.md) when reviewing compatibility and release claims.
