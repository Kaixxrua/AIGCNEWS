# v89 — dark leaf-body reflectance trial

Not accepted. Added a middle-leaf-only convex ALBEDO blend toward olive
(.10,.15,.055)*vertex tone, weight .42*(1-smoothstep(.025,.14,pigment luma)).
No emission, added texture sampling, geometry or global lighting change.

Main session46005 exited0: source/indexed-mesh CPU audit, GPU script parse,
then ten-stage material-only build/export/pack checks passed. This is not
the full 35-stage regression suite. All five original v77 caches passed.

Actual WebGL tab2, 09:52:51–09:53:09 UTC, fixed root600: all12 records
completed; overall FAIL for the same moon-direction dark-half gain gate.
Day gain .016735 (v88 .016841); moon gain .003494 (v88 .003496), below2/255.
Highlight statistics unchanged; zero clipping, wood/other/foothill deltas0,
every zero-light maximum0. This evidence shows negligible additional effect
on the selected fixture, not proof of the exact cause in every scene crown.

Diagnostic load22,635ms/download1,666ms/scene2,489ms. Not a performance
comparison. PCK118,859,064 bytes, gzip114,078,329, SHA256
`48cc2b8c9d8aa5d18da6eb17d97dfe8a066e29ee1f6f69f80fbe5e1135970595`.
Frozen shader SHA256
`c629716e36e2f86cd517f48b2e85cd96d22e0ee38713fb266767075923d656f0`.
Exact shader/audits remain in artifacts/v89 final copies. Rejected BODY
block is removed for v90. Next trial isolates stronger thin-leaf BACKLIGHT
relative to v88 (.18 instead of .06) while keeping old wood response,
global lighting, approved water and all existing GPU gates unchanged.
