# GitHub heat v7

`daily_hot_v7` replaces v6 (`docs/github-heat-v6.md`) and retires the v5
fallback. Every row with observed star growth is scored on one scale, so rows
are comparable no matter whether their rate came from snapshots, an observed
day delta, or the GitHub Trending cold start. Observed daily deltas, their
source/availability fields, and the ranking filter `daily_star_growth > 0` keep
their existing contracts; REST/MCP/SSE shapes do not change.

## Problems fixed

| v6 behaviour | v7 |
| --- | --- |
| Scale saturated at `G/√S = 4`, absolute at 1000/day, so the whole top of the board tied at 100 and trend/maintenance decided the order (the day's #1 grower ranked 14th–47th) | References moved to the historical daily peaks; magnitude decides, secondary signals only modulate |
| Without baseline history, trend confidence was 0 and the trend term 0: newcomers were penalised | Missing baseline → neutral trend (60); missing community/maintenance drop out of the quality average |
| Rows without a usable snapshot interval fell back to the v5 formula on a different scale | Same v7 formula with the observed delta as the rate |
| Display stretch compressed the top into 90–100 | No stretch; the score is the formula value |
| Zero-growth rows kept heat from maintenance/community | Observed growth 0 → heat 0 |
| Suspicion only tagged | Multi-signal suspicion demotes heat |

## Formula

Rates: the v6 snapshot velocity is kept (actual elapsed hours, 12-hour blend
with the preceding interval, no EMA), with intervals of up to seven days
(`MAX_GAP_DAYS`). A first interval without a predecessor uses its own rate.
Elapsed hours come from each snapshot's `captured_at`, stamped when its GraphQL
chunk (or REST call) returned rather than when the round started: a full
refresh takes one to several hours, so a round-level stamp skewed the intervals
of repositories fetched late. Availability checks keep the round start.
Without a usable interval the observed delta is the rate (gap deltas are already
normalised per day; Trending rows use `stars today`). `S` is the star count
before the interval, floored at 500.

```
scale      = 100 · min(log1p(G / √S) / log1p(100), 1)
absolute   = 100 · min(log1p(G) / log1p(10000), 1)
magnitude  = 0.625 · scale + 0.375 · absolute
trend      = c · curve((G+20)/(B+20)) + (1−c) · 60      (0 when G = 0)
quality    = weighted mean of known {trend 0.5, community 0.25, maintenance 0.25}
hot        = magnitude · (0.8 + 0.2 · quality/100) · demotion(suspicion)
demotion   = 1 when suspicion < 0.5, else 1 − 0.6 · min(suspicion, 1)
```

`curve` keeps the log-interpolated anchors 0.25/0.5/1/2/4 → 0/20/60/85/100;
`c = min(baseline_hours/72, 1)` for snapshot rates and `min(samples/3, 1)` for
observed rates. Community uses the existing fork/subscriber references and is
unknown unless both snapshots are complete. Maintenance keeps `100/(1+d/14)`.
The quality term can move heat by at most 20%, so it breaks near-ties but cannot
lift a small grower past one growing several times faster.

Historical daily peaks (production, September 2026): p99.9 of `G/√S` is about
10.6 and of `G` about 913; daily tops reach `G/√S` 15–110 and `G` 2k–6.5k.

## Suspicion and demotion

Signals are summed and capped at 1.0; a same-day cross-channel mention
(HN/news/dailyhot/X) clears the score but keeps the signals for review.

| Signal | Weight | Condition (growth ≥ 100/day) |
| --- | --- | --- |
| `low_fork_follow` | 0.4 | complete community pair, fork growth < 1% of star growth |
| `spike_from_zero_baseline` | 0.3 | ≥ 3 baseline samples averaging < 1/day (no history is unknown, not zero) |
| `new_repo_surge` | 0.2 | repo younger than 30 days, growth ≥ 200 |
| `coordinated_creation` | 0.6 | ≥ 3 distinct owners created their repos within 5 minutes and all surge the same day; sticky for 7 days once seen |

Single-repo signals only demote in combination; `coordinated_creation` is
cross-account evidence and demotes alone. It needs minute-precision creation
times (`github_repo_candidates.created_at`), so only rows with an API timestamp
can cluster, and a targeted recompute only sees clusters among its own rows.
In 30 days of production data every 3-owner cluster was a batch of malware-lure
repositories (e.g. `Microsoft-365-setup`, `Discord-Server-Raider`, `AutoCad`),
while a 2-owner threshold also caught three unrelated legitimate pairs.

## Quarantine (bait repositories)

Demotion only lowers heat; repositories in `github_repo_quarantine`
(migration 0082) are removed from every public surface instead: hot board,
catalog list/search/counts/categories, name lookup, hover peek, keyword
tracking and the MCP project tools. The list is derived state, recomputed as a
whole after each metrics write (a failure logs a warning and keeps the previous
list), so a repository that stops matching is released automatically.

| Reason | Rule |
| --- | --- |
| `coordinated_surge` | any metrics row with suspicion ≥ 0.8 that carries `coordinated_creation` |
| `name_reuse` | same repository name (case-insensitive, canonical rows only): the copies created on or after the day of the earliest copy GitHub has removed span ≥ 3 owners, with ≥ 2 removed and removed ≥ half of them; the whole wave is quarantined |

Copies created before the first removed one are kept as presumed originals:
quarantining every name shared by ≥ 3 owners with one removed copy would have
hidden `anthropic/skills`, `awesome-mcp-servers` and `claude-code` in a
read-only production replay (2026-10-04), while the wave rule caught 68 lure
repositories (24 surge, 44 name reuse across about 15 names) and no legitimate
group.

## Replay (read-only, production snapshots)

| Day | Growth #1 rank v6 → v7 | Top-10 overlap with growth top-10, v6 → v7 | Demoted |
| --- | --- | --- | --- |
| 2026-09-20 | 47 → 1 | 1 → 4 | 1 |
| 2026-09-21 | 27 → 1 | 5 → 6 | 8 (lure batch) |
| 2026-09-22 | 27 → 1 | 1 → 7 | 2 (same batch) |
| 2026-09-23 | 14 → 1 | 4 → 5 | 0 |
| 2026-09-24 (partial) | 17 → 1 | 6 → 7 | 1 |

In the v6 data 13,390 zero-growth rows carried heat > 0; the v7 replay has none.

## Rollout

Existing rows are not rewritten on deployment; the next scheduled compute
writes v7 for the live slice. `POST /ops/github-projects/metrics/backfill-suspicion`
recomputes the last N days with corroboration and rewrites heat with v7. Watcher
repair rebuilds heat per row version (v7 formula, v6 display stretch, v5 legacy).
