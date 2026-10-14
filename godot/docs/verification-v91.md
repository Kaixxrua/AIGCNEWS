# v91 — additive crown-to-turf foliage

Work in progress, not full vegetation integration or reference-fidelity completion.
An independent `MeadowEdgeGrowth` child adds 605 rooted low leaf sprays around
the existing fourteen middle-crown guides. Irregular lobes, gaps and decreasing
outer leaf height/density connect crowns to short turf. Existing crowns, source
textures, global light, stars, approved water and camera remain unchanged.

## Executed checks

- New script check-only and main-scene smoke both exited 0. One versioned
  export (`20260910-181652-*`) completed the existing ten-stage material/cache
  workflow. This workflow is not the full 35-stage suite and does not alone
  certify the added geometry. No new GPU-probe efficacy claim is made; the
  leaf shader is byte-identical to the actual-WebGL-tested v90 shader.
- Additional `audit_meadow_edge_growth.gd` exited 0 with PASS. Five v77 bundles,
  nine mesh-array/transform and collision snapshots remain exact. The actual
  new geometry has 605 supported roots, 16,464 triangles, fourteen nonempty
  guide regions, open six-triangle leaf fans and one additional mesh batch.
  Maximum actual horizontal radius .68169m plus .06m wind reserve; root
  support error .000000m. All-vertex road/Boss/river/habitat minimum margins
  1.34258/19.23365/7.903976/4.484672m pass conservative wind-aware checks.
  This certifies roots and clearance, not every leaf tip's ground separation.
  Source has no hard 45k cap; the audit enforces that limit on actual output.
- Main personally viewed matching native PNG2560x1440 day/night captures:
  `artifacts/v91/day-fringe-2k.png`, `night-fringe-2k.png`. Actual canvas same,
  DPR approximately1, clock0 paused, nightBlend0/1, full16:10 composition with
  sidebars; image dimensions and PNG encoding independently decoded. Compared
  to v90 originals at the same settings. Dragon initial random pose differs
  and is excluded from foliage comparison. Overrides restored after capture.
- Main sees restrained additional low leaf tips near crown bases, stronger
  around the left rock-side group than the isolated central group. No obvious
  new closed skirt, glowing rim, blocked road, water or sky regression. The
  dominant dark crown islands still persist, especially at night: this is
  small local progress, not proof that the vegetation task is complete.
  Clear-sky bright stars remain readable in the complete night image and
  moonlit ground remains visible; no new star/lighting changes in this version.
- Ordinary Web tab5 (no diagnostic query): native canvas1920x1080/DPR1.5,
  download1320ms, total ready14662ms, parent build1887ms and separately logged
  additional fringe412ms. No warn/error. Parent sceneBuildMs excludes fringe;
  do not report it alone as total construction time. Single-run observations
  cannot establish a loading optimization.
- Existing three startup samples in ordinary daytime paused state: 50/47/47
  FPS, 158 visible calls, 2,779,962 visible primitives. Not an animation, p95,
  sustained-frame-rate or comparable A/B benchmark. After capture, normal
  viewport restored, night endpoint and animation play verified, clock advances.

## Identity and scope

Independent original-image review supports retaining limited daytime progress
but does not pass full integration: it finds the isolated P crown-foot gain
more legible than R1, differing from the main's relative emphasis. Both reviews
agree the effect is small and actual nighttime benefit is not established.
Neither absence of obvious regressions nor a passing geometry audit is treated
as proof that the scene's pasted-on/dark-island appearance is solved.

PCK118,863,964 bytes; gzip114,083,320, only5278 bytes more gzip than v90.
Actual PCK SHA256 matches manifest:
`74bdda9d7ed6fae29dc6c897f0c4ef664216dd5d8ddbc48cc77903cc46cc59ea`.
New scene dependency is included in the exported pack and its startup marker
is observed in both pack smoke and actual Web runtime.

Protected shader SHA256 values rechecked:

- Leaves `dd218655817268a12de2be516df8d9280edb309502fb3228f0604450b5310335`.
- Water `ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08`.
- Sky `374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b`.

Old static-cache sources were not rewritten. Main scene only references the
new additive child; no resource/signature bypass masks changes to old geometry.
The inherited E:/ Git-root problem remains; scoped snapshots and separate
exports provide the isolation fallback, with no Git writes, SSH or recovered
source modifications. Source snapshots and independent geometry/visual/performance
reviews are kept under artifacts/v91. Broader grey cast, architecture response
and crown-ground harmony remain unfinished; preserve approved water.

Preview: http://127.0.0.1:4231/v91/index.html
Newly opened pages may start by day; click 入夜 to see stars, then 播放 for animation.
