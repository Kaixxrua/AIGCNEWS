# v100 — unique woodland and softer sunlight

Scene-only candidate, not an8.7 acceptance claim. Boss and integration deferred.

Replace the100 rejected procedural ball crowns with six distinct tree groves
from one selected native1254x1254 RGBA atlas. Four concurrent built-in imagegen
candidates explicitly prompted with 八方旅人2; full provenance/prompts preserved
in artifacts/v100/grove-generation.md. Image unmodified, each crop used once.

Groves retain native proportions, bowed root-band geometry and existing shared
foliage lighting/wind. Low alpha basal supports follow the real terrain mesh;
this does not establish that every painted background trunk is at ground level.
Daylight cover now has domain-warped unequal footprints and wider penumbra.
Sun-only light selection/BRDF, night endpoint and water shader unchanged.

Executed: editor asset import; one real procedural bake; selected-resource Web
export; clean packed-scene run. logs in artifacts/v100. Five cache bundles,
signature96ebe65649f0874aea42884e93ee9ed5feac8d589c00dc4623c0872ec47a550f.
Packed ready3345ms,80unique art regions; six groves13824triangles. Central route
max slope12.66deg, Boss clearing deviation0m,31/31collision probes,
128/128city feet,65/65village feet,9/9bridge probes. No full regression suite.
PCK120743416bytes / gzip115979336; SHA256
d3a759c9b21ae537681455b7606e86310eebc958c84fc8520167c6dacb042578.
This is +1830844bytes raw over v99, not a speed-optimisation claim.

Actual Web QHD day/night reviewed (day-groves-2k.png, night-groves-2k.png): canvas
and decoded PNG2560x1440, DPR1, clock0paused, endpoints0/1, complete letterboxes.
Readback browser warnings/errors empty. Download2007ms, total108763ms,
sceneBuild6428ms single run, not a controlled performance comparison.
Main and independent reviewer found net forest-shape improvement over v97/v99,
but day forest was pale/washed out; night remained readable. Keep as WIP, not8.7.
v101 adds local day fog control rather than globally dimming the scene.
