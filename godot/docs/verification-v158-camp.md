# v158 — final actor moon-bounce correction

See `verification-v157-camp.md` for the public modular-art, frozen-scene,
one-way presentation and atlas-registration contracts. No private application
implementation is included in either scene package.

## Change and evidence

- Only new actor moon-bounce energy changes: day/half/night is **0/4/8**.
  Position, diffuse color, falloff, role-isolated culling and shaded sprites are
  unchanged. There is no emissive outline, texture edit or world-light change.
- v157's 1.10 energy was attenuated too far below a useful fill level. Actual
  core15 → all 12 detail chunks → paused animation → night tests confirmed
  valid weather references and light updates. The issue was not pause gating,
  weather replacement or a compiler disabling Omni lights.
- Stable native GPU on/off control increased the Ranger body luminance from
  approximately 37.1 to 69.4/255. This is measured image evidence for the
  correction, not a general-purpose art score or a production timing claim.
- Probe: `artifacts/camp-bootstrap/night-gpu-detail-04/actual-core-result.json`,
  476 checks, no failures. Its 2304×1440 native GPU images are diagnostic scene
  renders, not the requested 2560×1440 Web acceptance captures.
- Renderer 1515 checks; builder 14, bootstrap 10, JS bridge/boot/integration 83
  tests pass. The 39 actor shard/encoding files are byte-identical to v157.
  The Web assembler retains 75 frozen v153 runtime payloads, all quality tiers
  and all existing world/water/wildlife behavior.

## Pins

- `artifacts/v158/camp-web-manifest.json`:
  `394b2f7771114140e8e4089dd9e50ac0b878348cf641dad92dde27afcf544061`.
- Optional runtime `camp-presentation-f28af50eaeca.pck`, **38,270 bytes**:
  `f28af50eaeca223beed50bb244a866079b7c174927a9c47c1b720fc476601a81`.
- Inputs: `artifacts/camp-presentation/all-04/presentation-pack.json` and
  `artifacts/camp-bootstrap/all-04/selected-pack-bindings.json`.
- 152 runtime files / 13 optional actors is the full staging inventory, not
  a first-load download. Only the selected trio is requested after core-ready.

## Web acceptance

- Final captures: `artifacts/camp-integration-v158/day-dragon-qhd.png` and
  `artifacts/camp-integration-v158/night-dragon-qhd.png`. Both PNG and actual
  Web canvas are **2560×1440**, DPR approximately 1, with the complete 16:10
  composition letterboxed. Neither image is resized from a smaller render.
- Both use the final lite wrapper `camp-bootstrap-lite-9e302772a0c7.pck`,
  paused weather clock **231.044**, motion disabled, and night blend 0/1.
  The displayed trio is Ranger / Dragon / guardian in idle presentation.
- Main-agent inspection and independent visual review accept this bounded
  pair: Ranger clothing and Dragon body/wing detail are readable at night;
  their silhouettes remain separated. No conspicuous overexposure, emissive
  outline or abnormal fill-light patch is visible on terrain, vegetation or
  water. Daylight retains the approved world appearance.
- This is not an all-actor, all-quality-tier or full combat-animation visual
  acceptance. Earlier v156/v157 images remain failed night-readability
  diagnostic baselines and are never relabeled as v158 evidence.
