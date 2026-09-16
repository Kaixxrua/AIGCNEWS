# v99 — volumetric foothill crowns and sunlight breaks

Work-in-progress scene only. User's approximately8.7/10 threshold is NOT yet
accepted; Boss, character assets and AIGCNEWS integration remain deferred.

## Implemented

- Reject v98's bright flat crown strip. Use100 distinct branched crowns with600
  closed leaf masses/outward normals,17200triangles,one private material/batch.
- Lower new far slopes to55% of v98 height. Same terrain/collision surface and
  finite far-only footprint; central road, Boss clearing and river heights exact.
- Shared animated world-space sunlight transmission for near dry soil, plants
  and rocks. It projects along the day key ray, not the screen; sky bounce and
  local lamps are independent. No new shadow-map pass or full-screen grade.
- Original water/sky/weather/focus source unchanged. Existing cloud-pigment
  modulation retained at night, outside the near field and on submerged ground.

## Executed evidence, not visual acceptance

See v98 logs for the procedural bake and revised real-volume audit:5current
bundles/signature3424d1630a47b6f1b2b0531ab2b3cedb3dd622e42ab69787202a8fad14a104f3;
87970protected terrain vertices exact;600closed positive-volume leaf lobes.

Native GPU probe actually executed through run_sunbreak_probe.gd with its main
viewport3D disabled and only a private320x192 test viewport rendered. It is NOT
a QHD screenshot. sunbreak-gpu-native-ground.log:PASS424checks/40records, five
actual material families; native night/day-clear BRDF parity, sun-only change,
sky-bounce/ambient/omni/zero/emission controls. Maximum registered parity error
is bounded by the unchanged2/255 gate; original failed run is retained.
Root cause of that failure was terrain's implicit GLES Lambert response, versus
the other wrappers' explicit Burley response; fixed only the terrain branch.
This does not certify all GPUs, animation, full-scene water pixels or performance.

First v99 export missed the new private woodland shader from the selected-resource
manifest. Its pack-check failed; no browser preview of that broken pack was opened.
Explicitly included the shader and re-exported. Session39321 exited0, clean logs
export-complete/pack-complete:scene ready,100crowns,128/128city feet,65/65village
feet,9/9bridge probes. PCK118912572bytes/gzip114147766, SHA256
be05e533d86a087b39373af2af6b2b937aaea53af6ea3980361cd2c4103aae04.
No full35-stage suite or old reflectance-only whole-terrain pass is claimed.

Browser candidate: http://127.0.0.1:4231/v99/index.html?rev=1
Actual whole-frame QHD day/night captures completed: artifacts/v99/day-sunbreak-2k.png
and night-sunbreak-2k.png. Canvas and decoded PNG2560x1440, DPR1, paused clock0,
night endpoints0/1; complete side-letterboxed composition. Independent review in
artifacts/v99/visual-review.md agrees that near daylight organisation improved,
but the new distant crowns resemble grey-green balls/rocks in both endpoints.
Reject that procedural woodland candidate. Keep the useful sunlight response,
soften its too-round patches, and replace the failed crowns with unique image
groves in v100. Night moonlight/lamps remain readable; no overall brightness
regression was apparent. These observations do not certify identical pixels,
all animations or performance. Target8.7 remains unaccepted.
