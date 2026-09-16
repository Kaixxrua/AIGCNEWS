# v101 — grove aerial perspective and broken rock lip

Six new groves now use reduced day-only optical depth (.30 canopy, .70 at the
root fade). Read the actual Environment fog colour/energy and linearise once;
night endpoint returns to the original cutout wrapper. No global environment or
water shader edits. Enable source atlas mipmaps; PNG pixels/hash remain unchanged.
Three separated ledge grass/stone groups use actual old terrain/geology support,
76rooted sprays and6embedded rocks, no copiedPNG, no changed existing collisions.

Executed asset import, true procedural bake, Web export, packed-scene validation;
terminal session40165 exit0. Cache signature
72eb4130c019b78bd5f64b559abd21f31c0e1f37457c3ba0781bc7284bbf0134.
PCK121454216bytes/gzip116689163, SHA256
c81f33d03e85672ded057da4f858407e68af684141da5bbd0db031fb09abe261.
Packed scene3134ms; no error markers. Same route12.66deg/Boss0m and rooted
bridge/city/village checks. No full suite or GPU shader-isolation probe rerun.

ActualWeb day/night images: artifacts/v101/day-integration-2k.png and
night-integration-2k.png; canvas2560x1440,DPR1,clock0paused,night0/1, full composition.
Both decodedPNG dimensions/format verified2560x1440; complete framing inspected.
Browser warn/error readback empty. Single startup readback244788ms, download2397ms,
sceneBuild10466ms. This slow uncontrolled run is recorded, not called a speed pass.
Browser startup samples show42/39/40fps,169draw calls and2802380primitives before
controlled QHD review; these are not a QHD performance benchmark.

Main/independent day judgment: evident reduced grey wash and natural tree shapes;
overall8.0–8.4 range, not8.7. Main remaining weakness is fragmented bright mountain
texture and insufficient broad slope light. Ledge additions partly break the
straight lip, but central upright leaves remain too stiff; v102 will recline some.
No Boss/character/AIGCNEWS work begun. Day/night review is visual, not inferred from
test counts. Source review also found fog colour/energy missing from the controller
cache key (not changing in the captured endpoints); fixed in v102 source with null
Environment fallback. v101 archived pack is not silently replaced.
