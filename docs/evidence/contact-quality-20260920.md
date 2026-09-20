# Contact page quality repair

The embedded scene's FPS governor reduced the framebuffer to 10%, hid almost
all landscape geometry and replaced terrain materials after transient low FPS.
The user requires the selected picture quality to remain unchanged at low FPS.

`scripts/release/preserve_contact_quality.py` creates a new immutable private
release with an inert governor. The presentation owner disposes it immediately;
it cannot sample FPS, change resolution, hide geometry/effects or stop animation.
Manual original/balanced/lite selection remains available. The script verifies
the original pinned release, updates runtime/wrapper hashes and compression
sidecars, and produces a new release descriptor without changing its input.

- Input release: `20260918T041933296926Z-6cf37a1`.
- Corrected release: `20260920-contact-quality`.
- Descriptor SHA-256: `41e5718b453371a51c7e41fe9009fc60240d9136779dddd34116cd39a8c9d21b`.
- The local delivery configuration pins this corrected release for standard deployment.
- 29 engine, scene, actor and detail packs remain byte-identical. Inside the
  three changed packs, only the governor and two wrapper bindings differ.
- 15 packaging/staging regression tests and Ruff passed. A native Godot check
  confirmed no processing callback, unchanged viewport scale and visible geometry.
- Browser candidate acceptance: all 12 detail chunks loaded, landscape and
  demo actors visible, no console errors; even at 1 FPS the governor stays inactive.
  This validates quality preservation, not a frame-rate improvement.

The configured QR PNG also returned 404 because the active backend's site-media
mount was empty. The exact existing PNG was restored to that mount. The public
endpoint returned 200 and the browser decoded the 1028-pixel image successfully.
No administrator content or contact link was changed.

Browser screenshot and the previous delivery configuration are retained outside
the repository under the local delivery state directory's `contact-quality-20260920/`.
Production scene delivery remains owned by the standard automation queue.
