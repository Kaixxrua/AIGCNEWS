# GitHub heat v12: more room for small-project breakouts

v12 raises the scale exponent from **0.50 to 0.65**, anchored at 500 stars.
Strong growth in a small repository should compete with a larger repository's
routine growth. Exceptional absolute growth can still put a large repository
at the top. There are no reserved places or size-based exclusions.

## Formula and calibration

`G` is the existing rolling 24-hour growth, with the existing snapshot/observed
fallback. `S` is the star stock before that interval, with the existing floor
and newborn launch expectation:

```text
S           = max(base_stars, 500, launch_stars(age_days))
denominator = sqrt(500) * (S / 500)^0.65
scale       = 100 * min(log1p(G / denominator) / log1p(100), 1)
absolute    = 100 * min(log1p(G), log1p(100000)) / log1p(10000)
magnitude   = min(0.625 * scale + 0.375 * absolute, 100)
```

The quality adjustment, suspicion multiplier and v11 top-ten exposure discount
are unchanged. Absolute growth retains its 37.5% weight and continues rising
above 10,000 stars/day. Growth of zero still scores zero.

Anchoring matters: simply replacing `sqrt(S)` with `S^0.65` would lower even
the 500-star reference score. This normalized denominator keeps that reference
unchanged and increases continuously above it. Ten times the stock requires
about 4.47 times the growth to retain the same **scale subscore**, compared
with 3.16 times before. The absolute term reduces that requirement for equal
total heat, so large repositories can still win through substantial growth.

Examples with neutral trend, unknown community/maintenance, no suspicion and
no exposure discount (the quality multiplier is 0.92):

| Stock before growth | Growth | v12 heat |
| --- | --- | --- |
| 500 | 500 | 62.55 |
| 1,000 | 500 | 57.23 |
| 10,000 | 500 | 41.14 |
| 100,000 | 500 | 30.00 |
| 100,000 | 3,000 | 50.73 |
| 100,000 | 10,000 | 68.47 |

A 100,000-star repository gaining 20,000 stars still scores 63.43 after the
maximum 20% exposure discount, above the undiscounted 1,000-star / +500 case.
A 500-star repository gaining only 20 scores 19.36: small size alone does not
create high heat. Stocks below 500 receive no extra scale advantage, and the
fading newborn launch expectation continues to apply.

## Read-only sensitivity replay

Production metric slices read on 2026-10-15; the seven completed metric dates
are October 8–14. Each date uses current public eligibility and its saved
quality, suspicion and exposure adjustments. Only the scale exponent changes;
this is a fixed-input sensitivity comparison, not a simulation of future
top-ten exposure or a guarantee of the deployed order.

The replay retains the top 100 per date. Higher exponents cannot increase
scores; on every date the new tenth-place score exceeds the old hundredth-place
score, excluding an omitted entrant. Uncapped stored subscores reconstruct
growth and effective stock; saturated scale scores use rolling-window stock
and the launch expectation. Stored subscore rounding makes results approximate.

| Exponent | Mean top-ten projects below 10k stars | Mean top-ten overlap with original |
| --- | --- | --- |
| 0.50 | 6.29 | 10.00 |
| 0.60 | 7.14 | 8.86 |
| **0.65** | **7.43** | **8.43** |
| 0.70 | 7.57 | 8.29 |

0.65 provides a useful increase in room for smaller projects; 0.70 adds little
in this sample. The largest-growth project stays within the first three places
on all seven dates at 0.65. The October 15 partial slice moves from four to
seven sub-10k projects in the top ten. Its largest grower, `morluto/rea`, moves
from 77.03 / first to approximately 67.77 / second, remaining near the top.

## Versioning and rollout

New metric computations write `daily_hot_v12`. Deployment does not rewrite
historical rows; the next scheduled compute applies the new formula. The
existing explicit backfill operation can still recompute dates when requested.

Community-data repairs retain the stored scale and absolute subscores and each
row's scoring version. v11 and v12 both retain the 4%/20% exposure policy; v9
and v10 retain their older policies. No schema migration is required.
Observed daily growth, rolling growth, eligibility, tie-breaking and
REST/MCP/SSE response shapes keep their contracts; the intended behavior
change is the scale subscore and resulting heat order.
