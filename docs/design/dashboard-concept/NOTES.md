# Dashboard concept reproduction

Source: user-provided concept image, 1724 × 912, attachment
`codex-clipboard-058dbd95-6c07-4c47-8151-6521f95e6e7d.png`.
No source website or implementation was provided. Existing Vue components,
routes and live data are retained; layout is reconstructed from the image.

## Reference geometry

- Borderless 70px masthead; two paper panels with a 14px gutter.
- Ranking toolbar begins at y=195; three 164px feature cards begin at y=259.
- Remaining seven rows are approximately 52px tall, without large gutters.
- Right sidebar: 234px calendar, 186px brief, 75px integration counters,
  98px UI inspiration preview.
- Warm neutral paper, fine borders, black lead card and acid-green accents.

## Requested differences

- Six real metrics, including total visitors and total UI catalog items.
- Existing Dock is unchanged.
- Cyberpunk logo glitch remains, limited to one changed glyph for readability.
- Brief geometry remains animated; reduced-motion and hidden-page pause apply.
- UI inspiration replaces hot topics; the radar is removed.
- Follow-up: retain the original hard borders and offset black shadows on
  principal cards while keeping the concept geometry.
- Project logos take precedence over owner avatars; every GitHub row shows the
  existing backend heat score, or a pending marker if no growth snapshot exists.

## Verification and limits

Compared desktop at 1724 × 912; inspected 390 × 844 mobile and dark theme.
Checked responsive overflow, subscription route and real catalog fallback.
Real owner avatars, summaries, counts and rankings intentionally differ from
the illustrative content. No invented logos, summaries or hardcoded counts.
Build uses the repository CI catalog fixture, not mutable production previews.
