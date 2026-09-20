# Comic integration refinement

Follow-up to the user's close-up review: remove the detached sticker appearance while preserving the approved dashboard composition and mobile baseline.

- Newsletter now uses a newly generated transparent illustration combining the robot, variable ink strokes, hatching and asymmetrical explosion. It replaces the separate flat polygon burst. Imagegen used the user-authorized fallback endpoint/model and reference; the prompt is stored beside the 700px WebP.
- The illustration overlaps the frame, shares the card baseline and leaves live text and subscription controls as HTML. Sidebar gaps increased to 12px at the reference viewport; short desktops use 9px.
- Newsletter mail icon uses a thicker existing Lucide envelope inside a skewed ink accent, per the user's explicit icon refinement request. Dock and other original SVG icons are preserved.
- Featured and statistics cards use organic nonparallel ink outlines and subtle short strokes. Smaller fading halftone fields replace dense patterned blocks and inset shadows.
- Header hollow AI lettering replaced by fragmented brush shapes; slogan underline is irregular ink. Footer corner is anchored to the page edge with a diagonal spine.
- Mobile components are unchanged. Desktop ranks remain reduced; statistics have no growth indicators; avatar upload and fallback remain intact.

Validation: production build and typecheck passed; changed dashboard tests (16) and layout/auth tests (88) passed. Chromium screenshots checked at 1721x914, 1366x768 and 390x844 in both themes, with no page errors or horizontal overflow. Live content varies from the concept. Visual comparisons are qualitative; no unmeasured similarity percentage is asserted.
