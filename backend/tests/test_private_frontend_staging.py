from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "release" / "stage_private_frontend.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage_private_frontend", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stage = load_module()


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_descriptor(private: Path, release_id: str) -> str:
    descriptor = private / stage.DESCRIPTOR
    descriptor.write_text(
        json.dumps(
            {
                "schema": stage.DESCRIPTOR_SCHEMA,
                "release_id": release_id,
                "manifest_sha256": stage.sha256(private / stage.MANIFEST),
                "source_files": {
                    relative.as_posix(): stage.sha256(private / stage.PRIVATE_SOURCE / relative)
                    for relative in stage.SOURCE_FILES
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return stage.sha256(descriptor)


def private_release(tmp_path: Path) -> tuple[Path, Path, str, str]:
    private = tmp_path / "private"
    frontend = tmp_path / "frontend"
    release_id = "release-123"
    source = private / stage.PRIVATE_SOURCE
    sources = {
        stage.SOURCE_FILES[0]: (
            '<iframe src="/camp-scene/index.html" />\n<style>.godot-contact-scene iframe { border: 0; }</style>\n'
        ),
        stage.SOURCE_FILES[1]: "protected scene test\n",
        stage.SOURCE_FILES[2]: "<GodotContactScene />\n",
        stage.SOURCE_FILES[3]: "protected view test\n",
    }
    for relative, content in sources.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    release = private / stage.RELEASE_DIR
    artifacts = {
        "camp-scene/index.html": b"godot-entry",
        "camp-scene/index.wasm": b"godot-runtime",
        "camp-scene/scene.pck": b"godot-pack",
    }
    for name, content in artifacts.items():
        path = release / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (private / stage.MANIFEST).write_text(
        json.dumps(
            {
                "algorithm": "sha256",
                "release_id": release_id,
                "files": {name: digest(content) for name, content in artifacts.items()},
            }
        ),
        encoding="utf-8",
    )
    return private, frontend, release_id, write_descriptor(private, release_id)


def test_stages_verified_private_sources_and_godot_release(tmp_path: Path):
    private, frontend, release_id, descriptor_digest = private_release(tmp_path)

    stage.stage(private, frontend, release_id, descriptor_digest)

    assert (frontend / "src" / stage.SOURCE_FILES[0]).read_text(encoding="utf-8").startswith("<iframe")
    assert (frontend / "public/camp-scene/index.wasm").read_bytes() == b"godot-runtime"


def test_rejects_tampered_private_release(tmp_path: Path):
    private, frontend, release_id, descriptor_digest = private_release(tmp_path)
    (private / stage.RELEASE_DIR / "camp-scene/index.wasm").write_bytes(b"tampered")

    with pytest.raises(stage.StageError, match="digest mismatch"):
        stage.stage(private, frontend, release_id, descriptor_digest)


def test_rejects_non_godot_or_bordered_contact_source(tmp_path: Path):
    private, frontend, release_id, _ = private_release(tmp_path)
    source = private / stage.PRIVATE_SOURCE
    (source / stage.SOURCE_FILES[0]).write_text(
        '<iframe src="/camp-scene/index.html" /><style>.godot-contact-scene iframe { border: 1px; }</style>',
        encoding="utf-8",
    )

    descriptor_digest = write_descriptor(private, release_id)
    with pytest.raises(stage.StageError, match="borderless"):
        stage.stage(private, frontend, release_id, descriptor_digest)

    (source / stage.SOURCE_FILES[0]).write_text(
        '<iframe src="/camp-scene/index.html" /><style>.godot-contact-scene iframe { border: 0; }</style>',
        encoding="utf-8",
    )
    (source / stage.SOURCE_FILES[2]).write_text("<ContactHeroVisual />", encoding="utf-8")
    descriptor_digest = write_descriptor(private, release_id)
    with pytest.raises(stage.StageError, match="protected Godot"):
        stage.stage(private, frontend, release_id, descriptor_digest)


def test_rejects_unpinned_or_rewritten_private_release(tmp_path: Path):
    private, frontend, release_id, descriptor_digest = private_release(tmp_path)

    with pytest.raises(stage.StageError, match="release ID"):
        stage.stage(private, frontend, "different-release", descriptor_digest)

    descriptor = json.loads((private / stage.DESCRIPTOR).read_text(encoding="utf-8"))
    descriptor["release_id"] = "different-release"
    (private / stage.DESCRIPTOR).write_text(json.dumps(descriptor), encoding="utf-8")
    with pytest.raises(stage.StageError, match="descriptor digest mismatch"):
        stage.stage(private, frontend, release_id, descriptor_digest)


def test_rejects_manifest_replacement_even_when_artifacts_match(tmp_path: Path):
    private, frontend, release_id, descriptor_digest = private_release(tmp_path)
    manifest = json.loads((private / stage.MANIFEST).read_text(encoding="utf-8"))
    (private / stage.MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(stage.StageError, match="manifest digest mismatch"):
        stage.stage(private, frontend, release_id, descriptor_digest)


def test_rejects_symlinks_in_private_release(tmp_path: Path):
    private, frontend, release_id, _ = private_release(tmp_path)
    release = private / stage.RELEASE_DIR
    target = release / "camp-scene/index.wasm"
    target.unlink()
    target.symlink_to("index.html")
    manifest = json.loads((private / stage.MANIFEST).read_text(encoding="utf-8"))
    manifest["files"]["camp-scene/index.wasm"] = digest(b"godot-entry")
    (private / stage.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    descriptor_digest = write_descriptor(private, release_id)

    with pytest.raises(stage.StageError, match="must not contain symlinks"):
        stage.stage(private, frontend, release_id, descriptor_digest)
