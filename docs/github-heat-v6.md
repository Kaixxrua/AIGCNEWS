# GitHub heat v6

`daily_hot_v6` scores elapsed-time growth velocity instead of treating a partial
day's observed growth as a full day. The first twelve observation hours blend
the current velocity with the preceding interval's velocity. There is no EMA
or daily reset of heat. Actual daily star/fork/watcher deltas, their source and
availability, and suspicion signals retain their existing contracts.

## Formula

For consecutive labelled days, let `h` be the actual hours between snapshots,
`v = max(current_stars - previous_stars, 0) * 24 / h`, and `p` the preceding
interval's daily velocity. Use `w = min(h / 12, 1)` and `G = w*v + (1-w)*p`.
For a preceding velocity of 240/day, observations of 20 stars in 2 hours keep
G at 240; observations at 60/day produce G=210, 150 and 60 at 2, 6 and 12 hours.

The raw score weights are scale-corrected growth 50%, absolute growth 30%,
trend 10%, community 5% and maintenance 5%. Scale uses
`log1p(G / sqrt(max(previous_stars, 500))) / log(5)`; absolute uses
`log1p(G) / log(1001)`. Both are clamped to [0, 1] and multiplied by 100.

Trend compares `(G+20)/(B+20)` against log-interpolated anchors
0.25/0.5/1/2/4 -> 0/20/60/85/100. B is the time-weighted daily velocity in
valid intervals overlapping the seven days preceding the current interval.
Confidence is `min(valid_baseline_hours / 72, 1)`; zero G has zero trend.
Community uses similarly blended fork/subscriber velocities and the existing
0.6/0.4 logarithmic references (100 forks and 10 subscribers). Incomplete
community observations contribute zero. Maintenance retains the 14-day curve.

The final piecewise-linear display mapping is:

| Raw | 0 | 20 | 40 | 60 | 70 | 80 | 85 | 90 | 95 | 100 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Display | 0 | 25 | 45 | 65 | 77 | 85 | 90 | 93 | 96 | 100 |

## Missing Data and Rollout

The repository provides up to twelve labelled days of snapshots in one query.
The scorer excludes future slices, non-timezone timestamps, apparent backfills
whose UTC date differs from the label by more than one day, and intervals
outside (0, 48] hours. It requires yesterday's snapshot; intervals under twelve
hours also require a reliable preceding velocity. Closing-window snapshots
remain supported, using their actual capture time.

When reliable rate inputs are missing, the existing v5 score (including the
Trending cold-start fallback) is retained and labelled `daily_hot_v5`; it is
not relabelled as a v6 estimate. Compute results report `speed_scored` and
`legacy_fallback`. Daily metric schema and REST/MCP/SSE shapes do not change.

Existing historical scores are not rewritten on deployment. The next normal
snapshot/scoring job writes v6 for eligible rows; the existing targeted or dated
recompute operation can explicitly rebuild history. A failed fetch is not an
observation of zero growth. Identical snapshot inputs always produce the same
score, independent of recompute time and previously saved heat. Watcher repair
respects each row's score version when removing community contributions.

Daily snapshots merge some fields with maxima and may be sparse: reconstructed
velocities remain estimates, not complete hourly telemetry. The approved preview
showed 41/38 projects at 90+ for the prior/current slices; these are observed
outcomes, not ranking quotas or guaranteed future counts.
