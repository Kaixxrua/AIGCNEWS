# v84 — rejected building pigment trial

Direct architecture pigment attenuation (.80–.96 by source luminance) passed the material-only ten-stage build, sky CPU/source, architecture CPU and window sampling checks, but failed actual WebGL architecture response. The moon-direction roof mean was .002597 (< .006 original gate); the day difference was .013021. Controls remained unchanged; canopy/render/leaf-transfer passed. Do not deliver this trial or lower the gate.

Source is frozen in `artifacts/v84/meadow_cutout_surface.rejected-pigment.gdshaderinc`; prior v83 source in `meadow_cutout_surface.v83-before.gdshaderinc`. Full-frame `day-rejected-pigment-2k.png` is a verified 2560×1440 PNG at canvas 2560×1440, DPR approximately 1, paused clock 0. It is diagnostic evidence, not accepted art.

The independent sky change adds star-only attenuation through cloud fringes, preserving exact v83 clear-star code and prior non-star sky/source guards. This sky change continues into v85; v84's building pigment change does not.

Build session 17138 exited 0; extra audit session 49838 exited 0. Actual GPU failure was recorded in browser tab 22 on 2026-09-10 at 08:23:44 UTC. v84 PCK SHA `354543d05b0039ec29218078939ade15eccea3ae6c66cde24b9c0db03fe67e54`.
