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


def private_release(tmp_path: Path) -> tuple[Path, Path]:
    private = tmp_path / "private"
    frontend = tmp_path / "frontend"
    source = private / stage.PRIVATE_SOURCE
    sources = {
        stage.SOURCE_FILES[0]: (
            '<iframe src="/camp-scene/index.html" />\n'
            '<style>.godot-contact-scene iframe { border: 0; }</style>\n'
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
        json.dumps({"algorithm": "sha256", "files": {name: digest(content) for name, content in artifacts.items()}}),
        encoding="utf-8",
    )
    return private, frontend


def test_stages_verified_private_sources_and_godot_release(tmp_path: Path):
    private, frontend = private_release(tmp_path)

    stage.stage(private, frontend)

    assert (frontend / "src" / stage.SOURCE_FILES[0]).read_text(encoding="utf-8").startswith("<iframe")
    assert (frontend / "public/camp-scene/index.wasm").read_bytes() == b"godot-runtime"


def test_rejects_tampered_private_release(tmp_path: Path):
    private, frontend = private_release(tmp_path)
    (private / stage.RELEASE_DIR / "camp-scene/index.wasm").write_bytes(b"tampered")

    with pytest.raises(stage.StageError, match="digest mismatch"):
        stage.stage(private, frontend)


def test_rejects_non_godot_or_bordered_contact_source(tmp_path: Path):
    private, frontend = private_release(tmp_path)
    source = private / stage.PRIVATE_SOURCE
    (source / stage.SOURCE_FILES[0]).write_text(
        '<iframe src="/camp-scene/index.html" /><style>.godot-contact-scene iframe { border: 1px; }</style>',
        encoding="utf-8",
    )

    with pytest.raises(stage.StageError, match="borderless"):
        stage.stage(private, frontend)

    (source / stage.SOURCE_FILES[0]).write_text(
        '<iframe src="/camp-scene/index.html" /><style>.godot-contact-scene iframe { border: 0; }</style>',
        encoding="utf-8",
    )
    (source / stage.SOURCE_FILES[2]).write_text("<ContactHeroVisual />", encoding="utf-8")
    with pytest.raises(stage.StageError, match="protected Godot"):
        stage.stage(private, frontend)
