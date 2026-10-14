# v110 — local physical erosion mouth (incorporated into v111 candidate)

Current public-to-this-machine WIP remains v109, subjectively about8.4/10.
This candidate has no visual acceptance yet. No Boss, combat or backend work.
Water/weather/sky/focus source protection remains in force.

## Production changes

- One asymmetric incision in terrace0, centred at world XZ
  (-36.388867,-20.323368), tangent(-.885018018,.465556773), outward
  (.465556773,.885018018). Compact support: tangent coordinate(-1.15,1.85),
  outward(-2.10,1.45), maximum downward displacement.82m. The shared height
  field affects actual ground and the four local wall sections49–52; grass
  cap front vertices share the last wall bed and rear vertices follow terrain.
  No painted gap, deleted-face hole, new PNG or change to the central play space.
- Limestone triangle-normal blend reduced from.65 to.30 to soften the hard
  facets independently flagged in v109; slope pigment and all previous gates
  retained. Actual shader SHA256
  `969c5e622f07475ab9cb7a34fb2365700f66d6d1a5bb7bb897828ba2e28143bd`.
- AO sidecar is newly baked for the changed real meshes at
  `assets/baked/v110/rock-occlusion.bin`. Old v104 source is preserved;
  runtime path and export inclusion switch together. No runtime AO rays.

## Historical first-shape evidence (superseded; not acceptance)

- Fresh cache5bundles52015826bytes, signature
  `27260890d7f624f033e80327573de9513a54e50bf3afeb2c5fb4b4a95ab01857`.
- New offline AO:317556 prefix vertices,317544 unique samples,6350880 rays,
  318544byte sidecar;113024ms on this run, with source caches unchanged.
- Native GPU `rock-planes-gpu.log`:26 controlled cases PASS with the new.30
  source pin. This verifies response, gates and endpoints, not actual cliff
  aesthetics or performance.
- Geometry audit first failed because it did not support the actual packed
  tangent channel. The next run expanded all four tangent components but still
  incorrectly demanded derived terrain tangents remain identical where their
  source normals changed. Both failed logs are preserved. The independent audit
  now uses the existing fixed normal-domain support only, tests tangent finite/
  unit/orthogonal/handedness properties there and exact equality outside. It
  does not relax position, collision or vegetation scope. Final result pending.
- The completed second run measured78 changed ground corners (max.80813m),
  1701 changed rock corners (max.82m), and only two moved understory groups;
  creeping/ledge-growth and prop-stitch batches recorded zero moved groups.
  Do not call that failed run a full PASS or infer visible quality from projected
  displacement. New final gate, exported-pack check and QHD review follow.

## Corrected shape, 2026-09-11

The first geometry also had21 rising rock corners and3 triangle orientation
reversals. Those were production defects, not audit tolerance issues. The builder
now samples the original wall/block shape first, then applies bounded downward
shifts. Original random draws, block sizes and winding remain intact. It asserts
positive old/new face-normal dot before exporting each moved face.

`artifacts/v110/ledge-notch-shape-fixed-fullscope.log`: PASS,54,540,079 checks,
five meshes and two actual colliders, zero failures. Source signature
`6e3eaff5704868647b8b1b7023f168f5886e82d1d78d975d4dd09e9fd2c2bc52`.
78 ground corners moved(max.80813m),1470 rock corners(max.82m); all changes
outside the fixed local domains remain forbidden. Only two living-blade groups
translated; four groups changed their soil-dependent normal/tangent frames.
The audit reconstructs the original art-normal formula from the actual source
normals, and preserves rigid leaf geometry. Normal-only groups are not treated
as floating-point-only differences. No creeping or prop-stitch groups moved.

This corrected cache passed before v111 added its ground atmosphere controller.
The v111 rebuild and freshly regenerated AO have separate logs. The first-shape
AO is preserved as `artifacts/v110/rock-occlusion.first-shape.bin`; its old bake
is not evidence for the corrected geometry. v110 was not separately published
or assigned a new visual score.
