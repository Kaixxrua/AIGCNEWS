# v102 — broad mountain lighting

Scene target still pending. No Boss, player or integration work.

- Mountain day source highlight shoulder starts .34, shoulder width .24; source
  values below the threshold retained, RGB ratios preserved, no texture blur.
- Existing geometric/source-aligned normals and native Lambert-wrap unchanged.
  Rebalance day ALBEDO multipliers3–4 and EMISSION .28–.42 (previous1.70–2.30 and
  .52–.68), to reveal broad slope response instead of bright painted flecks.
  This is shader-space tuning, not a claim of linear radiometric conservation.
- Subtle source-foot forest blue reduction only. day<=0 return preserved.
- Middle rock-lip group reclines approximately one third of previously upright
  leaves. Same roots, random sequence, plant count and stones; outside reflection.
- Grove fog cache now includes linear colour/energy and handles null Environment;
  no changes to the captured day/night endpoint parameters from v101.

Historical v101 source snapshots in artifacts/v102. Scope: existing five baked
groups unaffected; runtime-only ledge leaf orientation, grove controller and
mountain shader changes. Verify current five-cache signature before exporting;
do not claim the entire35stage suite or visual acceptance from a source check.

Actual nativeQHD day comparison completed: artifact day-mountain-2k.png,
canvas2560x1440/DPR1/day0/clock0 paused, PNG independently decoded2560x1440.
Main and independent review found fewer bright rock flecks but only limited
volume improvement (8.1–8.4 subjective range). No v102 night capture was made;
do not claim a new night visual pass from unchanged shader endpoints alone.

Executed current-cache metadata check:5/5 signature matches v101, no rebake.
Serialized export/pack/payload preparation session97081 exit0, logs clean;
all6groves and3ledge groups present, scene ready and existing play-space,
city/village/bridge probes pass. No full suite. PCK121455240/gzip116689850bytes,
SHA256e5b4f9cf393c1a0b2760b067aeabdff302d3dd4b6abb17e4396196ae21552ccf.
