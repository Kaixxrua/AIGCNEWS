from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts/release"))
spec = importlib.util.spec_from_file_location("publish_frontend_edges", ROOT / "scripts/release/publish_frontend_edges.py")
edge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)

SHA = "a" * 40
IMAGE = "example/frontend@sha256:" + "b" * 64


def test_rejects_unfinished_or_mutable_origin_and_skips_superseded():
    assert edge.active_image({"active_release": "c" * 40}, SHA) is None
    with pytest.raises(edge.DeployError, match="unfinished"):
        edge.active_image({"in_progress": SHA}, SHA)
    with pytest.raises(edge.DeployError, match="immutable"):
        edge.active_image({"active_release": SHA, "images": {"frontend": "latest"}}, SHA)
    assert edge.active_image({"active_release": SHA, "images": {"frontend": IMAGE}}, SHA) == IMAGE


def configure(tmp_path):
    control = tmp_path / ".aigcnews-deploy"
    control.mkdir()
    (control / "state.json").write_text(json.dumps({
        "schema": edge.read_state.__globals__["SCHEMA"], "active_release": SHA,
        "images": {"frontend": IMAGE}, "in_progress": None,
    }))
    controller = tmp_path / "private.py"
    controller.touch()
    inventory = tmp_path / "private-inventory.json"
    inventory.write_text(json.dumps({
        "hosts": {"cn": {}}, "groups": {"all": ["app", "other"]},
        "sites": {"app": {"host": "cn", "smoke_checks": [{"path": "/"}]}, "other": {"host": "cn"}},
    }))
    config = {"controller": str(controller), "inventory": str(inventory), "sites": ["app"]}
    (control / "edge-config.json").write_text(json.dumps(config))
    return control, config


def test_only_selected_sites_use_exported_artifact(tmp_path):
    _, config = configure(tmp_path)
    prepared = edge.prepare_inventory(config, tmp_path / "artifact/dist")
    assert set(prepared["sites"]) == {"app"}
    assert prepared["sites"]["app"]["smoke_checks"] == [{"path": "/"}]
    assert prepared["sites"]["app"]["artifact_dir"] == "dist"
    assert prepared["groups"] == {}
    config["sites"] = ["missing"]
    with pytest.raises(edge.DeployError, match="unknown"):
        edge.prepare_inventory(config, tmp_path / "dist")


@pytest.mark.parametrize("fail", [False, True])
def test_records_publish_result_and_removes_export_container(tmp_path, fail):
    control, _ = configure(tmp_path)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "cp"]:
            (Path(args[-1]) / "index.html").write_text("release")
        if "publish" in args and fail:
            raise edge.subprocess.CalledProcessError(1, args)
        return edge.subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(edge, "command", return_value="c" * 64), patch.object(edge.subprocess, "run", side_effect=run), patch.object(edge, "confirmed_site", return_value=True):
        if fail:
            with pytest.raises(edge.subprocess.CalledProcessError):
                edge.publish(tmp_path, SHA)
        else:
            assert edge.publish(tmp_path, SHA) == "published"
    state = json.loads((control / "edge-state.json").read_text())
    assert state["sites"]["app"] == ("failed" if fail else "published")
    assert ["docker", "rm", "c" * 64] in calls


def test_dry_run_never_publishes_or_updates_edge_state(tmp_path):
    control, _ = configure(tmp_path)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "cp"]:
            (Path(args[-1]) / "index.html").write_text("release")
        return edge.subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(edge, "command", return_value="c" * 64), patch.object(edge.subprocess, "run", side_effect=run), patch.object(edge, "confirmed_site", return_value=True):
        assert edge.publish(tmp_path, SHA, dry_run=True) == "validated"
    assert not (control / "edge-state.json").exists()
    assert any("plan" in args for args in calls)
    assert not any("publish" in args for args in calls)


def test_retry_skips_only_reconfirmed_published_site(tmp_path, monkeypatch):
    control, _ = configure(tmp_path)
    (control/'edge-state.json').write_text(json.dumps({
        'source_sha': SHA, 'frontend_image': IMAGE, 'sites': {'app': 'published'},
        'site_releases': {'app': '20260919T081804368945Z-c072f8734541'},
    }))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ['docker', 'cp']:
            (Path(args[-1])/'index.html').write_text('release')
        return edge.subprocess.CompletedProcess(args, 0, stdout='', stderr='')
    monkeypatch.setattr(edge, 'command', lambda *args: 'c'*64)
    monkeypatch.setattr(edge.subprocess, 'run', run)
    monkeypatch.setattr(edge, 'confirmed_site', lambda *args: True)
    assert edge.publish(tmp_path, SHA) == 'published'
    assert not any('publish' in args for args in calls)
    monkeypatch.setattr(edge, 'confirmed_site', lambda *args: False)
    with pytest.raises(edge.DeployError, match='confirmed exact artifact'):
        edge.publish(tmp_path, SHA)
    assert any('publish' in args for args in calls)


def test_timeout_records_failed_site(tmp_path, monkeypatch):
    control, _ = configure(tmp_path)
    def run(args, **kwargs):
        if args[:2] == ['docker', 'cp']:
            (Path(args[-1])/'index.html').write_text('release')
        if 'publish' in args:
            raise edge.subprocess.TimeoutExpired(args, 600)
        return edge.subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(edge, 'command', lambda *args: 'c'*64)
    monkeypatch.setattr(edge.subprocess, 'run', run)
    with pytest.raises(edge.subprocess.TimeoutExpired):
        edge.publish(tmp_path, SHA)
    assert json.loads((control/'edge-state.json').read_text())['sites']['app'] == 'failed'
