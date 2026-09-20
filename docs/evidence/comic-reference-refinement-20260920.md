# Reference integration refinement

The newsletter frame now uses a slightly irregular ink path. The robot preserves its aspect ratio, breaks the frame at the right edge and shares the lower baseline. Removed the opaque description rectangle; separated description, checklist and CTA without covering live text. Desktop checklist-to-button gap is 11px at 1721×914 and 6px at 1366×768. Sidebar ends above the dock at both sizes.

Removed the repeated full-page dot texture. Cyan/ink halftone fades and broken diagonal strokes now sit at the masthead and footer edges, matching the reference's localized print treatment. Dark mode suppresses these accents and retains muted ink. Mobile rules and original Dock icons remain unchanged.

Verification: production build, typecheck, ESLint and diff checks passed; dashboard/layout run 59 tests and additional layout run 42 tests passed. Chromium light/dark checks at 1721×914, 1366×768 and 390×844 found no page errors or horizontal overflow. Actual screenshots were reviewed against the approved references; no unmeasured percentage is claimed. Publication proceeds through the authorized automatic delivery pipeline.
