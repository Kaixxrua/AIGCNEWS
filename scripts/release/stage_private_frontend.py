#!/usr/bin/env python3
"""Stage the private Godot contact-page overlay into an ephemeral frontend checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
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
DESCRIPTOR = Path("aigcnews-private-release.json")
DESCRIPTOR_SCHEMA = "aigcnews.private-frontend-release.v1"
RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class PrivateRelease:
    release_id: str
    manifest_sha256: str
    source_files: dict[str, str]
    scene_files: dict[str, str]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_symlink_components(root: Path, path: Path, label: str) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise StageError(
                f"{label} must not contain symlinks: {current.relative_to(root)}"
            )


def valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def load_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise StageError(f"{label} is unavailable")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"invalid {label}: {exc}") from None
    if not isinstance(document, dict):
        raise StageError(f"{label} must be a JSON object")
    return document


def load_release(
    private_root: Path,
    expected_release_id: str,
    expected_descriptor_sha256: str,
) -> PrivateRelease:
    if not RELEASE_ID_PATTERN.fullmatch(expected_release_id):
        raise StageError("expected private release ID is invalid")
    if not valid_digest(expected_descriptor_sha256):
        raise StageError("expected private release descriptor digest is invalid")

    descriptor_path = private_root / DESCRIPTOR
    if not descriptor_path.is_file() or descriptor_path.is_symlink():
        raise StageError("private release descriptor is unavailable")
    if sha256(descriptor_path) != expected_descriptor_sha256:
        raise StageError("private release descriptor digest mismatch")
    descriptor = load_json(descriptor_path, "private release descriptor")
    if descriptor.get("schema") != DESCRIPTOR_SCHEMA:
        raise StageError("private release descriptor has an unsupported schema")
    release_id = descriptor.get("release_id")
    if release_id != expected_release_id:
        raise StageError("private release ID does not match the pinned release")
    manifest_digest = descriptor.get("manifest_sha256")
    if not valid_digest(manifest_digest):
        raise StageError("private release descriptor has an invalid manifest digest")
    source_files = descriptor.get("source_files")
    expected_sources = {path.as_posix() for path in SOURCE_FILES}
    if not isinstance(source_files, dict) or set(source_files) != expected_sources:
        raise StageError(
            "private release descriptor must pin the protected frontend source inventory"
        )
    if not all(valid_digest(value) for value in source_files.values()):
        raise StageError("private release descriptor contains invalid source digests")

    manifest_path = private_root / MANIFEST
    if (
        not manifest_path.is_file()
        or manifest_path.is_symlink()
        or sha256(manifest_path) != manifest_digest
    ):
        raise StageError("private release manifest digest mismatch")
    document = load_json(manifest_path, "private release manifest")
    files = document.get("files")
    if (
        document.get("algorithm") != "sha256"
        or document.get("release_id") != release_id
        or not isinstance(files, dict)
    ):
        raise StageError("private release manifest must contain a sha256 file map")
    if not all(
        isinstance(name, str) and valid_digest(value) for name, value in files.items()
    ):
        raise StageError("private release manifest contains invalid entries")
    return PrivateRelease(
        release_id,
        manifest_digest,
        {str(name): str(digest) for name, digest in source_files.items()},
        {str(name): str(digest) for name, digest in files.items()},
    )


def verify_scene(release: Path, manifest: dict[str, str]) -> None:
    expected = {
        name: digest
        for name, digest in manifest.items()
        if name.startswith("camp-scene/")
    }
    if (
        "camp-scene/index.html" not in expected
        or "camp-scene/index.wasm" not in expected
    ):
        raise StageError(
            "private release manifest lacks the Godot entrypoint or runtime"
        )
    if not any(name.endswith(".pck") for name in expected):
        raise StageError("private release manifest lacks Godot packs")

    scene = release / "camp-scene"
    symlinks = [path for path in scene.rglob("*") if path.is_symlink()]
    if symlinks:
        raise StageError(
            f"private Godot release must not contain symlinks: {symlinks[0].relative_to(release)}"
        )
    actual = {
        path.relative_to(release).as_posix()
        for path in scene.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise StageError(
            f"private Godot release inventory mismatch; missing={missing[:3]} extra={extra[:3]}"
        )
    for name, digest in expected.items():
        path = release / name
        if path.is_symlink() or sha256(path) != digest:
            raise StageError(f"private Godot release digest mismatch: {name}")


def verify_sources(source: Path, expected: dict[str, str]) -> None:
    for relative in SOURCE_FILES:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise StageError(f"private frontend source is unavailable: {relative}")
        if sha256(path) != expected[relative.as_posix()]:
            raise StageError(f"private frontend source digest mismatch: {relative}")
    scene = (source / SOURCE_FILES[0]).read_text(encoding="utf-8")
    view = (source / SOURCE_FILES[2]).read_text(encoding="utf-8")
    if "/camp-scene/index.html" not in scene or "<iframe" not in scene:
        raise StageError("private contact component does not load the Godot release")
    normalized = "".join(scene.split())
    if ".godot-contact-sceneiframe" not in normalized or "border:0" not in normalized:
        raise StageError(
            "private contact component does not preserve the borderless iframe contract"
        )
    if "GodotContactScene" not in view or "ContactHeroVisual" in view:
        raise StageError(
            "private contact view is not the protected Godot implementation"
        )


def stage(
    private_root: Path,
    frontend_root: Path,
    expected_release_id: str,
    expected_descriptor_sha256: str,
) -> None:
    private_root = private_root.resolve()
    frontend_root = frontend_root.resolve()
    source = private_root / PRIVATE_SOURCE
    release = private_root / RELEASE_DIR
    reject_symlink_components(private_root, source, "private frontend source path")
    reject_symlink_components(private_root, release, "private Godot release path")
    private_release = load_release(
        private_root, expected_release_id, expected_descriptor_sha256
    )

    destination_source = frontend_root / "src"
    for relative in SOURCE_FILES:
        target = destination_source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    verify_sources(destination_source, private_release.source_files)

    target_scene = frontend_root / "public" / "camp-scene"
    if target_scene.exists():
        shutil.rmtree(target_scene)
    shutil.copytree(
        release / "camp-scene",
        target_scene,
        symlinks=True,
        copy_function=shutil.copy2,
    )
    verify_scene(target_scene.parent, private_release.scene_files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--expected-descriptor-sha256", required=True)
    args = parser.parse_args()
    try:
        stage(
            args.private_root,
            args.frontend_root,
            args.expected_release_id,
            args.expected_descriptor_sha256,
        )
    except StageError as exc:
        print(f"private frontend staging rejected: {exc}")
        return 1
    print("private Godot frontend staged and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
