#!/usr/bin/env python3
"""Assemble the 20260929-contact-poster private release from the previous one.

camp-scene is hardlinked from the old release (never modified in place); only new
poster files are added. Sources come from the dev checkout. Manifest/descriptor are
regenerated in the same format (json.dumps indent=2, sort_keys, trailing newline).
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HOME = Path.home()
OLD = HOME / ".private-releases/aigcnews-godot-20260920-contact-quality"
NEW = HOME / ".private-releases/aigcnews-godot-20260929-contact-poster"
RELEASE_ID = "20260929-contact-poster"
DEV_SRC = HOME / "aigcnews-deploy/contact-poster-e9ee690/frontend/src"
POSTERS = Path(sys.argv[1])  # directory with contact-poster-{960,1600,2400}.webp
SOURCE_FILES = (
    "components/contact/GodotContactScene.vue",
    "components/contact/GodotContactScene.test.ts",
    "views/ContactPageView.vue",
    "views/ContactPageView.test.ts",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


old_manifest = json.loads((OLD / "cn-current-godot-release-source-manifest.json").read_text())
scene = NEW / "cn-current-godot-release/camp-scene"

for width in (960, 1600, 2400):
    name = f"contact-poster-{width}.webp"
    target = scene / name
    if target.exists():
        target.unlink()  # new files only; never an inherited hardlink
    assert f"camp-scene/{name}" not in old_manifest["files"]
    shutil.copyfile(POSTERS / name, target)
    target.chmod(0o644)

files = {}
for path in sorted(scene.rglob("*")):
    if path.is_symlink():
        raise SystemExit(f"symlink in scene: {path}")
    if path.is_file():
        files[path.relative_to(scene.parent).as_posix()] = sha256(path)
inherited = {k: v for k, v in files.items() if not k.startswith("camp-scene/contact-poster-")}
if inherited != old_manifest["files"]:
    raise SystemExit("inherited camp-scene differs from the previous release manifest")

manifest_path = NEW / "cn-current-godot-release-source-manifest.json"
dump(manifest_path, {"algorithm": "sha256", "files": files, "release_id": RELEASE_ID})

source_root = NEW / "frontend-current-parent-v4/frontend/src"
source_digests = {}
for relative in SOURCE_FILES:
    target = source_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEV_SRC / relative, target)
    source_digests[relative] = sha256(target)

descriptor_path = NEW / "aigcnews-private-release.json"
dump(descriptor_path, {
    "manifest_sha256": sha256(manifest_path),
    "release_id": RELEASE_ID,
    "schema": "aigcnews.private-frontend-release.v1",
    "source_files": source_digests,
})
print("release_id", RELEASE_ID)
print("descriptor_sha256", sha256(descriptor_path))
print("manifest_sha256", sha256(manifest_path))
print("files", len(files), "posters", sorted(k for k in files if "contact-poster" in k))
