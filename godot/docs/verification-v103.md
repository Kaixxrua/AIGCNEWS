# v103 — mountain proportions and actual soil contact

Scene-only work; 8.7 visual target remains pending. No Boss/player/integration.

The mountain keeps its original PNG, full UV domain, single surface and
1365 vertices/2560 triangles. Left source-u is narrowed .68 around .196;
the right segment is monotonic C1 Hermite. Relief depth is scaled 1.25.
Root registration now queries the actual terrain triangles, with analytical
height only outside the ground mesh. The first audit failed with a .06652m
positive soil gap; that log is retained. The fix produced 57 supported sampled
feet with maximum gap -.04998m, not a claim about every alpha edge.

`audit_mountain_mass.gd` passed finite geometry, independent X registration,
UV area/winding, recomputed normals and actual camera-depth order. Mountain
depth301.7527–348.092m; castle far292.1835m; visible-alpha top .05509.
The unchanged dragon skyline audit passed 32 source-alpha poses and blended
turns, with its existing clearance/viewport/far-plane thresholds.

Night-only broad mountain response reduces painted highlight emission and
adds a restrained world-space normal response to the actual moon. It does not
change global exposure, moon energy, water or fog. Day code is unchanged from
v102, but changed geometry can independently affect day lighting.

Export and packed-scene checks passed. The first Web preparation missed its
CSS copy and stopped; the missing existing CSS was copied and preparation
rerun successfully. PCK121458072bytes/gzip116691044; SHA256
bb566c3affb2f3b57f8267c4c78bf96be4522a393c9f95044c734509e9a4793a.
Five static caches retain signature72eb4130c019b78bd5f64b559abd21f31c0e1f37457c3ba0781bc7284bbf0134.
These are scoped checks, not the entire historical suite.

Actual Web captures: artifacts/v103/day-mass-2k.png and night-mass-2k.png.
Canvas2560x1440, DPR1, clock0 paused, exact night0/1; complete16:10 framing
with side letterboxing. Both PNGs independently decoded2560x1440.
Load one-shot reported download2165ms, scene3930ms, load42058ms. This is not
a controlled performance comparison. Dragon initial pose is random between
versions and is excluded from static environment comparisons.

Main and independent day review found clearer peak/valley spacing but limited
depth gain and some thin, fin-like ridge shapes. Score range8.0–8.4, not8.7.
Main night review: readable land/forest/moonlight and visible stars/windows;
no obvious new mountain-root gap. Independent night review agreed that the
scene remains readable with no obvious water/road/window regression, but keeps
the same8.0–8.4 range and flags the thin left ridge as unfinished visual work.
