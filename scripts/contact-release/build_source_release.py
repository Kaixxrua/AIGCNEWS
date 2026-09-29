#!/usr/bin/env python3
"""Assemble a private release that only changes the four protected contact sources.

usage: build_source_release.py <previous release dir> <new release id>

camp-scene is hardlinked file by file from the previous release (nothing is modified
in place) and must match its manifest exactly; the four sources come from this
repository's root. The manifest is rewritten with the new release id, the descriptor
is written both into the new release and to the repository root, and the descriptor
SHA-256 for local-delivery.json is printed. Output format matches the earlier
releases (json.dumps indent=2, sort_keys, trailing newline).
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_FILES = {
    "components/contact/GodotContactScene.vue": "GodotContactScene.vue",
    "components/contact/GodotContactScene.test.ts": "GodotContactScene.test.ts",
    "views/ContactPageView.vue": "ContactPageView.vue",
    "views/ContactPageView.test.ts": "ContactPageView.test.ts",
}
MANIFEST = "cn-current-godot-release-source-manifest.json"
DESCRIPTOR = "aigcnews-private-release.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


if len(sys.argv) != 3:
    raise SystemExit(__doc__)
old = Path(sys.argv[1]).expanduser().resolve()
release_id = sys.argv[2]
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release_id):
    raise SystemExit(f"invalid release id: {release_id}")
new = old.parent / f"aigcnews-godot-{release_id}"
if new.exists():
    raise SystemExit(f"release directory already exists: {new}")

old_descriptor = json.loads((old / DESCRIPTOR).read_text())
if sha256(old / MANIFEST) != old_descriptor["manifest_sha256"]:
    raise SystemExit("previous release manifest does not match its descriptor")
old_files = json.loads((old / MANIFEST).read_text())["files"]

old_scene = old / "cn-current-godot-release/camp-scene"
scene = new / "cn-current-godot-release/camp-scene"
for path in sorted(old_scene.rglob("*")):
    if path.is_symlink():
        raise SystemExit(f"symlink in previous scene: {path}")
    target = scene / path.relative_to(old_scene)
    if path.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    elif path.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(path, target)

files = {}
for path in sorted(scene.rglob("*")):
    if path.is_file():
        files[path.relative_to(scene.parent).as_posix()] = sha256(path)
if files != old_files:
    raise SystemExit("hardlinked camp-scene differs from the previous release manifest")

manifest_path = new / MANIFEST
dump(manifest_path, {"algorithm": "sha256", "files": files, "release_id": release_id})

source_root = new / "frontend-current-parent-v4/frontend/src"
source_digests = {}
for relative, name in SOURCE_FILES.items():
    target = source_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((REPO / name).read_bytes())
    source_digests[relative] = sha256(target)

descriptor = {
    "manifest_sha256": sha256(manifest_path),
    "release_id": release_id,
    "schema": "aigcnews.private-frontend-release.v1",
    "source_files": source_digests,
}
dump(new / DESCRIPTOR, descriptor)
dump(REPO / DESCRIPTOR, descriptor)
changed = sorted(k for k, v in source_digests.items() if old_descriptor["source_files"].get(k) != v)
print("release_dir", new)
print("release_id", release_id)
print("descriptor_sha256", sha256(new / DESCRIPTOR))
print("manifest_sha256", descriptor["manifest_sha256"])
print("scene_files", len(files), "changed_sources", changed)
