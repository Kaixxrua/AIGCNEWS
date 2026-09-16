#!/usr/bin/env python3
"""Stage the private Godot contact-page overlay into an ephemeral frontend checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


class StageError(RuntimeError):
    pass


PRIVATE_SOURCE = Path("frontend-current-parent-v4/frontend/src")
SOURCE_FILES = (
    Path("components/contact/GodotContactScene.vue"),
    Path("components/contact/GodotContactScene.test.ts"),
    Path("views/ContactPageView.vue"),
    Path("views/ContactPageView.test.ts"),
)
RELEASE_DIR = Path("cn-current-godot-release")
MANIFEST = Path("cn-current-godot-release-source-manifest.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"invalid private release manifest: {exc}") from None
    files = document.get("files")
    if document.get("algorithm") != "sha256" or not isinstance(files, dict):
        raise StageError("private release manifest must contain a sha256 file map")
    if not all(
        isinstance(name, str)
        and isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
        for name, value in files.items()
    ):
        raise StageError("private release manifest contains invalid entries")
    return files


def verify_scene(release: Path, manifest: dict[str, str]) -> None:
    expected = {name: digest for name, digest in manifest.items() if name.startswith("camp-scene/")}
    if "camp-scene/index.html" not in expected or "camp-scene/index.wasm" not in expected:
        raise StageError("private release manifest lacks the Godot entrypoint or runtime")
    if not any(name.endswith(".pck") for name in expected):
        raise StageError("private release manifest lacks Godot packs")

    scene = release / "camp-scene"
    actual = {
        path.relative_to(release).as_posix()
        for path in scene.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise StageError(f"private Godot release inventory mismatch; missing={missing[:3]} extra={extra[:3]}")
    for name, digest in expected.items():
        path = release / name
        if path.is_symlink() or sha256(path) != digest:
            raise StageError(f"private Godot release digest mismatch: {name}")


def verify_sources(source: Path) -> None:
    for relative in SOURCE_FILES:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise StageError(f"private frontend source is unavailable: {relative}")
    scene = (source / SOURCE_FILES[0]).read_text(encoding="utf-8")
    view = (source / SOURCE_FILES[2]).read_text(encoding="utf-8")
    if "/camp-scene/index.html" not in scene or "<iframe" not in scene:
        raise StageError("private contact component does not load the Godot release")
    normalized = "".join(scene.split())
    if ".godot-contact-sceneiframe" not in normalized or "border:0" not in normalized:
        raise StageError("private contact component does not preserve the borderless iframe contract")
    if "GodotContactScene" not in view or "ContactHeroVisual" in view:
        raise StageError("private contact view is not the protected Godot implementation")


def stage(private_root: Path, frontend_root: Path) -> None:
    private_root = private_root.resolve()
    frontend_root = frontend_root.resolve()
    source = private_root / PRIVATE_SOURCE
    release = private_root / RELEASE_DIR
    verify_sources(source)
    verify_scene(release, load_manifest(private_root / MANIFEST))

    destination_source = frontend_root / "src"
    for relative in SOURCE_FILES:
        target = destination_source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)

    target_scene = frontend_root / "public" / "camp-scene"
    if target_scene.exists():
        shutil.rmtree(target_scene)
    shutil.copytree(release / "camp-scene", target_scene, copy_function=shutil.copy2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        stage(args.private_root, args.frontend_root)
    except StageError as exc:
        print(f"private frontend staging rejected: {exc}")
        return 1
    print("private Godot frontend staged and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
