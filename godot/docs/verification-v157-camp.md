# v157 — modular camp presentation

This is an optional public presentation layer over the frozen v153 world. It
contains no account, reward, membership, private API or settlement implementation.

## Frozen scene and independent actors

- The v157 assembler preserved 75 runtime payloads byte-for-byte from v153.
  Original/balanced/lite world, water, established lighting, terrain, sky and
  existing wildlife were not redesigned.
- Six hero atlases, six pet atlases and one guardian atlas live in
  `assets/camp/v1/`. `selection-ledger.json` records the four concurrent
  candidates per selected batch, exact original PNG hashes and explicit use of
  the words 八方旅人2 in generation prompts. No PNG pixels were retouched.
- Native alpha and four-pixel guards are checked per registered frame. Most
  sheets use 192×256 cells; the flying dragon uses 256×192 cells in a 4×8 sheet.
  There are 32 animation time slots per actor, not necessarily 32 distinct poses;
  retained/held frames are explicit in the ledger and manifest.
- Only the selected three actors download, after actual core presentation.
  Actor changes replace the selected optional shard, never reload the world.
- Flying pets use a lifted sprite with a ground-sampled root and weak contact
  reference. The corrected sky-pet station is `(-2.10, -3.20)` in arena-local
  coordinates. The hero, ground pets and Boss keep their original stations.

## v157 lighting follow-up

The v156 QHD day/night pair showed a separated dragon/hero silhouette, but
Ranger and the dragon wings were too dark at night. v157 adds only actor-owned
upper/front diffuse moon-bounce lights, culled to separate role layers. Energy
follows the existing eased night blend: 0 / 0.55 / 1.10 at day / halfway / night.
Color is RGB (0.63, 0.75, 0.95). Existing layer-1 world lighting still reaches
the shaded sprites. The added lights have no specular, indirect, fog, bake or
shadow contribution and cannot illuminate the world or other role's sprite.
There is no emissive outline and no unshaded actor replacement.

The 13 actor shards and their compressed copies are identical to v156. Only
the optional runtime and its small pinned wrappers changed.

## Build pins

- Web manifest SHA-256:
  `27b3520d78b74482a22adbb7e08ff961040c6e55c3fa97950bbb36db6b165c43`.
- Optional runtime: `camp-presentation-b795bf0c3222.pck`, 38,110 bytes;
  SHA-256 `b795bf0c3222616c40273adb39bc2aa7920bc6950ec08d29a604ffc02609d9e3`.
- Inputs: `artifacts/camp-presentation/all-03/presentation-pack.json` and
  `artifacts/camp-bootstrap/all-03/selected-pack-bindings.json`.
- Output: `artifacts/v157`, 152 runtime files, 13 actor shards. Prior versions
  remain intact. These counts include all quality/encoding choices, not a
  user's first download.

## Verification

- Native renderer: 1515 checks passed; presentation builder: 14 tests passed;
  bootstrap: 10 tests passed; bridge/boot/integration: 83 tests passed.
- Independent public assembler suite: 40/40 passed. Conflicting bootstrap
  pins, role/case/sidecar name collisions and linked input files are rejected
  before output creation. Legitimate shared multi-quality bootstrap remains
  supported.
- Real-terrain flying station probe: 417 motion phases, six heroes / three
  flying pets / guardian tested against ground footprints and projected bounds.
  This is geometric evidence, not a screenshot or full animation-art review.
- v156 native-QHD diagnostic pair: 2560×1440 canvas and PNG, same paused clock
  232.612, day/night endpoints 0/1, full 16:10 scene with side bars. The night
  character-darkness issue in that pair is not labeled passed.
- Actual v157 Web day/night QHD at paused clock 206.305 confirmed the new
  wrapper loaded, but actor night detail was still too dark. These are retained
  diagnostic images, not accepted final character lighting. Actual GPU tests
  through all twelve detail chunks ruled out a replaced weather node, pause
  gating and disabled Omni support: the fill was simply too weak after distance
  attenuation. The bounded actor-only correction is recorded in
  `verification-v158-camp.md`.

## Reproduction

Use the local compatible Godot binary for the native tests, never the recovered
Linux command paths. `build_camp_presentation.py --self-test --native-test`
and `build_camp_bootstrap.py --self-test` build bounded disposable test fixtures.
The public Web assembler accepts a **new** output version only and pinned
public inputs, never private application files.

Rendering is deliberately cosmetic. Authenticated progress is displayed from
fresh parent snapshots; no local timer, damage or animation can decide rewards.
Idle/cooldown/completed states are ambient presentation, not a newly credited
Boss round. Custom per-character skills/victory cinematics are not claimed.
