# Release candidate staging

This first slice defines an offline, repository-only release candidate record. It
creates no image, registry, deployment, or network side effect.

## Manifest

`deploy/release/manifest.schema.json` is the versioned contract. A candidate must
record the exact protected-main `source_sha`, CI run and candidate identifiers,
lock-file and migration digests, migration version, immutable
`repository@sha256:<digest>` image references, frontend artifact digest, risk,
actor, evidence digests, UTC creation time, and `schema_version`.

## Local use

Build a manifest with `scripts/release/build_candidate.py`, supplying every
artifact digest explicitly. The script defaults `source_sha` to local `HEAD` but
does not inspect or modify deployment state. Verify it with
`scripts/release/verify_candidate.py --protected-sha <40-char-sha> manifest.json`.
Verification fails closed for a dirty source tree, a source SHA that differs from
protected main, mutable image tags, or image/frontend digest substitution.

`classify_gate.py` maps a verified risk to `automatic` (green), `manual` (yellow),
or `blocked` (red). Any dirty source, source mismatch, or digest mismatch is
`reject`, regardless of risk. The scripts are intentionally offline and suitable
for focused unit tests; later slices may connect their outputs to CI or release
orchestration.
