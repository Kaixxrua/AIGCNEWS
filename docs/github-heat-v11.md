# GitHub heat v11: top-ten exposure with a three-day reset

Superseded by [v12](github-heat-v12.md), which strengthens scale correction
while retaining this exposure policy. This document preserves the v11 contract.

v11 raises the top-ten exposure discount to **4 percentage points per prior
top-ten day, capped at 20%**. A new run starts without a discount; uninterrupted
appearances therefore receive 0%, 4%, 8%, 12%, 16%, then 20% from day six.

The count resets only after **three consecutive completed calendar-day boards
outside the top ten**. One or two off-board days preserve the count without
adding to it. Re-entry before the reset continues the existing run; re-entry
after the reset starts from zero. A missing daily slice counts as an absent day.

For example, three top-ten days followed by two off-board days still supply
three prior appearances (12% discount). After a third off-board day, the next
day has zero prior appearances and no exposure discount. Off-board days never
increase the discount.

`hot_score = v8_heat × (1 − min(0.04 × prior_top_days, 0.20))`

The run is reconstructed from prior public daily top-ten boards, using the
same eligibility and ordering even for targeted refreshes. Fifteen prior
calendar days suffice: five appearances separated by at most two absent days
already reach the cap. The stored `previous_top_streak_days` remains capped at
five; no schema change is needed.

Today's rank and earlier intraday computations never count. The discount
applies once to freshly computed heat after the existing suspicion adjustment.
Growth counts and REST/MCP/SSE response shapes are unchanged.

The next scheduled metric compute writes `daily_hot_v11`; deployment does not
rewrite historical scores. Community-data repairs retain each row's version:
v9 keeps 2%/8%, v10 keeps 3%/15%, and v11 uses 4%/20%.
