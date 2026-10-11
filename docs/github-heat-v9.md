# GitHub heat v9: gentle consecutive top-five penalty

Superseded by [v10](github-heat-v10.md): top ten, one grace day,
3% per extra day, capped at 15%. This document preserves the v9 contract.

The October 8–11, 2026 metric slices had the same three leading projects
(rea, photocraft and AnyPS5), with changes in their order. v9 preserves the v8
rolling 24-hour growth formula and adds a small exposure discount.

| Consecutive top-five day, including today | Heat discount |
| --- | --- |
| 1–2 | 0% |
| 3 | 2% |
| 4 | 4% |
| 5 | 6% |
| 6+ | 8% |

The input is the consecutive run of **previous** calendar-day top-five boards,
ending yesterday in the scheduler timezone. Each day's board uses the public
daily heat ordering and eligibility: enriched, canonical, active repositories
outside quarantine, with positive heat-window growth. Global boards are used
even during a targeted refresh. Leaving the top five or a missing daily slice
breaks the run; neither today's rank nor today's earlier computes count.

`hot_score = v8_heat × (1 − min(0.02 × max(prior_days − 1, 0), 0.08))`

The discount is relative to freshly computed heat, after the existing suspicion
adjustment. Growth counts, subscores and suspicion signals keep their meanings.
Strong growth can still lead the board; there is no forced rotation or exclusion.

Migration 0097 adds `previous_top_streak_days` (0–5, capped at the lookback needed
for the maximum discount). It leaves historical scores and versions unchanged.
This stored input lets community-data repairs preserve the original discount.
The next scheduled metric compute writes `daily_hot_v9`; intraday recomputes
apply the discount once. REST/MCP/SSE response shapes are unchanged.

Read-only replay of the October 11 live slice (before deployment):

| Project | Heat before → after | Rank before → after |
| --- | --- | --- |
| morluto/rea | 98.9244 → 91.0104 | 1 → 1 |
| storytold/wordcraft | 72.6147 → 72.6147 | 5 → 2 |
| boykopovar/AnyPS5 | 75.5838 → 72.5604 | 3 → 3 |
| storytold/photocraft | 78.3769 → 72.1067 | 2 → 4 |
| storytold/artcraft | 73.2385 → 71.7737 | 4 → 5 |

This applies v9 to the saved v8 scores using their preceding boards. Live
growth and subsequent daily board changes will affect the eventual order.
