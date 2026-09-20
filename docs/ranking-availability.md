# Ranking Availability

Existing snapshots remain readable while collection continues. REST dashboard
top, radar and summary responses, and MCP ranking tools/resources retain their
response fields; `is_embargoed` is now always false. Explicit dates remain exact.
Default REST views can fall back to yesterday, including an unfinished snapshot.

`is_finalized` follows the selected source's existing scheduled close: 01:00 CST
on the following day for GitHub/news/HN/X, 17:00 for HF/Product Hunt. Aggregate
views wait for the latest source close. This flag is a scheduled status, not a
receipt proving collection succeeded or an immutable archive. Persisted closing
receipts, historical backfill and archive versioning remain separate work.

Ranking response caches expire after 60 seconds. Cache keys include the CST day
and source-closing phase even for explicitly selected historical dates. The
default-board warmer refreshes before expiry; client requests use a new stable
version parameter to avoid old browser-cached embargo responses. Background
refreshes bypass the browser cache but share the bounded server cache.

The homepage refreshes while visible, at source close and at CST midnight, and
on returning to the page. Refresh failures retain existing rows. Selecting a
historical date keeps that selection across midnight. The displayed board date
comes from the selected source response rather than the aggregate summary.

Regression coverage includes midnight/closing transitions through real response
caching, visible unfinished REST and MCP snapshots, frozen MCP wire fixtures,
date fallback, hidden-page cleanup, failed refresh recovery and CST rollover.
