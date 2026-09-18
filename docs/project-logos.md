# Project logos and heat

GitHub README logo/wordmark/icon images are discovered during daily ingestion.
Only explicit logo evidence is accepted; screenshots, badges and sponsor logos
are excluded. Relative paths resolve against the README download URL.
This first version supports GitHub-hosted artwork, not arbitrary project websites.
An account avatar is a fallback, never recorded as a project logo.

The daily pipeline attempts up to 500 due repositories with a five-minute batch
budget (an in-flight request may finish after it), prioritizing unseen
high-star projects. Historical/new candidates share the same persistent queue.
The resumable CLI drains all due projects with:

```bash
python scripts/backfill_github_project_logos.py --limit 0
```

Use `--dry-run` to inspect a bounded queue sample or `--limit 100` for one batch.
Run against the intended deployed environment after migration 0075; never run
development migrations against production. A rate limit stops the batch.
Unattempted projects remain due; failed attempts retry after one day, missing
logos after seven days, successful logos after thirty days.

Images are DNS-pinned to public IPs, HTTPS-only, and restricted to GitHub asset
hosts. Redirects are not followed and GitHub API credentials are never attached
to image requests. Download limit is 1 MB; persisted content is at most 256 KiB.
Raster images are decoded and re-encoded to a 256px WebP; SVGs use an element
and attribute allowlist with no scripts, CSS, external references or entities.
The read-only image endpoint serves only stored bytes, with ETag, nosniff and
sandbox CSP. Failed refreshes retain the last good image.

Heat reuses existing daily v5 scores (0–100): scale-corrected growth 55%,
acceleration 20%, absolute growth 10%, maintenance 10%, community 5%.
No available growth snapshot means “— / pending”, not a synthetic zero.
Heat is activity, not project quality. Stars and the existing ranking remain.
