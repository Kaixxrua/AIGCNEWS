# 2K visual acceptance captures

The user requested 2560×1440 (QHD) for future screenshots on 2026-09-10. This applies to the actual Godot canvas and captured file, not an upscaled thumbnail. Keep the existing 16:10 composition with side letterboxing inside the 16:9 image.

## Acceptance checks

- Use the selected browser's documented viewport and CDP capabilities, through computer-use. Read its documentation first. Do not start another headless browser or alter the game to make a screenshot look better.
- Check the DOM canvas width/height, devicePixelRatio, viewport and visible canvas dataset. Compare builds at the same resolution, framing, day/night endpoint and animation clock.
- Save original capture bytes. Check the actual decoded file dimensions **and format**. A `.png` filename does not turn a JPEG into PNG.
- Inspect the entire frame: both side bars, complete castle, foreground cliff and right tree must be present. File dimensions alone cannot detect a crop or tiled capture.
- Inspect saved images with `detail: original`, including the original detail flag when forwarding the image from the orchestration tool. Do not judge leaf/alpha edges from a presentation thumbnail.
- Restore temporary viewport/device-metric overrides before handing the browser back. Use `tab.markHandoff()` for continuing work or `markDeliverable()` for a user-facing result; temporary tabs otherwise close at turn end.

## Local Windows capture calibration, verified 2026-09-10

On this host, the in-app browser reported a CSS viewport of 2560×1440 and canvas 2560×1440 at DPR approximately 1, but legacy layout metrics were 3840×2160. Ordinary capture could produce a cropped 2228×1440 JPEG; full-page capture could tile parts of the scene. These are **invalid evidence**, even when a resulting file happens to be 2560×1440.

The following documented CDP workflow produced complete native 2560×1440 PNGs on this host. The scale corrects the observed 1.5 display mapping; it is not a universal setting and must be rechecked after a display/browser change.

1. Set the browser viewport to 2560×1440. Reload a changed build and confirm it has loaded.
2. Read `Page.getLayoutMetrics`; compare legacy and CSS viewport dimensions.
3. For this observed 1.5 mapping, send `Emulation.setDeviceMetricsOverride` with width 2560, height 1440, deviceScaleFactor 1, mobile false, scale 2/3, screenWidth 2560, screenHeight 1440, positionX/Y 0.
4. Capture with `Page.captureScreenshot`: format `png`, fromSurface true, captureBeyondViewport false, no clip or post-capture resizing. Save the returned bytes directly.
5. Verify the image and DOM as above. Under this calibration a locator mouse click could miss; focusing the observed day/night button and pressing Enter worked and the new endpoint was verified in the visible DOM. Do not blindly repeat missed clicks or call game internals.
   A later focus-operation timeout returned the page to DPR 1.5 / canvas 3840×2160 even though the time switch had succeeded. Reobserve the button and recheck canvas/DPR after actions; if the override was lost, recalibrate before capture. Keep mismatched captures labelled diagnostic, never in a 2K comparison pair.
6. Clear device metrics and reset the temporary browser viewport after capture.

2026-09-10 v85 follow-up: canvas dimensions can report the new size before the compositor has redrawn it. Capturing in the same call as the override produced a 2560×1440 PNG showing a cropped old-scale frame. Keep it labelled invalid; separate calibration and capture calls, allow the rendered surface to settle while doing other work, and still personally inspect complete framing. `artifacts/v85/day-fill-invalid-crop.png` is not acceptance evidence; `day-fill-2k.png` and `night-fill-2k.png` are the later complete captures.

Verified third-trial examples are `artifacts/v77/day-compound-2k.png` and `night-compound-2k.png`: actual 2560×1440 PNGs, canvas 2560×1440, DPR approximately 1, paused clock 0, day/night blend 0/1. Both have the complete composition. These confirm capture quality, **not acceptance of the pending vegetation or lighting changes**.
