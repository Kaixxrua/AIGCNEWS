# Desktop comic fusion and neutral night review

## Implemented requirements

- Desktop uses the approved fusion composition: 110px masthead, six statistics, source tabs, three featured projects, seven remaining ranks, and the calendar/newsletter sidebar.
- The masthead uses a curved stepped ink rule, a speech bubble with a tail, and the user's approved lettering with intermittent displacement slices. Reduced-motion disables the slices. No neon split colors.
- Main light cards use asymmetric ink borders, local halftone fields, slanted accents and heavier display headings. Night uses neutral charcoal, muted borders and restrained lime accents.
- Featured ranks are 38px (33px on short desktops), regular ranks 23px. Statistics have no invented percentage/trend indicators.
- Newsletter robot is an independent compressed transparent image. Its visible shoulder extends approximately 8–12px beyond the card, without overlapping the counters underneath.
- Existing SVG navigation icons and the 1px × 32px account divider remain intact.
- Username appears above user group. Real authenticated avatar upload persists a normalized 256px PNG; missing/broken avatars use the first username character.
- Below 1024px the baseline dashboard, overview and ranking components are retained. Only one dashboard lifecycle mounts at a time.

## Visual checks

Compared real Chromium screenshots with `original-layout-fusion.png` and `fusion-night-neutral-v4.png`, including the user's separate close-ups of the stepped rule, speech bubble, robot overflow and logo. Live project content differs from the concept, and user-requested icon preservation and removal of statistical trends intentionally differ. No automated perceptual similarity percentage is claimed.

| Viewport | Themes | Result |
| --- | --- | --- |
| 1721 × 914 | Light, dark | All ten ranks visible; final row bottom 834px, sidebar bottom 819px, dock top 842px |
| 1366 × 768 | Light, dark | All ten ranks visible; final row bottom 688px, sidebar bottom 682px, dock below content |
| 390 × 844 | Light, dark | Baseline mobile layout preserved; no desktop robot or new ink frames |

All six runs had no page errors or horizontal document overflow. Mobile source comparison against the baseline matches after normalizing component import/name changes.

## Validation

- Frontend production build, TypeScript and changed-component ESLint passed.
- Final focused frontend run: 8 files, 52 tests passed. Earlier expanded layout/auth run: 16 files, 105 tests passed; dashboard regression run: 28 tests passed.
- After integrating `03eb7d03`, migration/auth/avatar/PostgreSQL HTTP suite: 76 tests passed. Covers migration 0076 → 0077, real HTTP/JWT upload and retrieval, disabled users, owner isolation, invalid/oversized images and token revocation.
- Browser avatar test passed: initial fallback, invalid format rejection, upload preview/save, header update, reload restoration, broken-image fallback, Escape close and focus restoration.
- Logo and generated robot total approximately 102 KB; no image service is called at runtime. Public avatar cache lifetime remains one hour.

Production publication is delegated to the repository's exact-SHA automatic delivery pipeline; local verification is not a claim of deployment.
