# GitHub heat v10: consecutive top-ten penalty

Superseded by [v11](github-heat-v11.md): 4% per prior top-ten appearance,
capped at 20%, with a three-day reset. This document preserves the v10 contract.

v10 expands v9's exposure discount to the public daily **top ten**. Only
the first day is exempt; each additional consecutive day adds 3 percentage
points of discount, capped at 15%.

| Consecutive top-ten day, including today | Heat discount |
| --- | --- |
| 1 | 0% |
| 2 | 3% |
| 3 | 6% |
| 4 | 9% |
| 5 | 12% |
| 6+ | 15% |

`hot_score = v8_heat × (1 − min(0.03 × prior_days, 0.15))`

The discount applies once to freshly computed heat, after the existing
suspicion adjustment. As in v9, only consecutive prior calendar-day public
boards count; leaving the top ten or a missing daily slice resets the run.
Intraday refreshes never accumulate extra penalties. All ten positions count
equally, including positions 6–10.

The existing five-day lookback and stored `previous_top_streak_days` suffice
for the new cap, so no schema change is needed. The next scheduled metric
compute reconstructs history from prior top-ten boards and writes
`daily_hot_v10`. Existing scores are not rewritten on deployment.
Community-data repairs retain each row's version: v9 keeps its 2%/8% policy,
v10 uses 3%/15%, and older versions remain unchanged. Growth counts and
REST/MCP/SSE response shapes are unchanged.
