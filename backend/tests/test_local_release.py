import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).parents[2]/'scripts/ci'))
from local_release import deployment_environment, normalize_build_permissions


def test_restricted_systemd_umask_does_not_make_image_code_unreadable(tmp_path):
    source=tmp_path/'build';folder=source/'backend/migrations';folder.mkdir(parents=True)
    script=folder/'0075.sql';script.write_text('select 1;');script.chmod(0o600);folder.chmod(0o700)
    executable=source/'entry';executable.write_text('exit 0');executable.chmod(0o700)
    private=tmp_path/'private';private.write_text('private');private.chmod(0o600)
    (source/'link').symlink_to(private)
    normalize_build_permissions(source)
    assert folder.stat().st_mode & 0o777==0o755
    assert script.stat().st_mode & 0o777==0o644
    assert executable.stat().st_mode & 0o777==0o755
    assert private.stat().st_mode & 0o777==0o600


def test_overlay_must_match_reviewed_production_configuration(tmp_path,monkeypatch):
    path=tmp_path/'overlay.yml';path.write_text('services: {}')
    c={'private_compose':str(path),'private_compose_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    monkeypatch.delenv('AIGCNEWS_PRIVATE_COMPOSE',raising=False)
    deployment_environment(c)
    assert os.environ['AIGCNEWS_PRIVATE_COMPOSE']==str(path)
    path.write_text('changed')
    with pytest.raises(ValueError,match='changed'):deployment_environment(c)


def test_build_checkpoint_requires_exact_identity_and_available_digests(tmp_path, monkeypatch):
    import json

    import local_release as release
    path = tmp_path / 'images.json'
    images = {k: 'ghcr.io/kaixxrua/aigcnews/' + k + '@sha256:' + 'a'*64
              for k in ('backend', 'mcp', 'frontend')}
    path.write_text(json.dumps({'identity': 'exact', 'images': images}))
    calls = []
    monkeypatch.setattr(release, 'run', lambda args: calls.append(args))
    assert release.verified_images(path, 'changed') is None
    assert calls == []
    assert release.verified_images(path, 'exact') == images
    assert len(calls) == 3
    def missing(args):
        raise release.subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(release, 'run', missing)
    assert release.verified_images(path, 'exact') is None


def test_build_checkpoint_rejects_unverified_image_reference(tmp_path):
    import json

    import local_release as release
    path = tmp_path / 'images.json'
    path.write_text(json.dumps({'identity': 'exact', 'images': {'frontend': 'latest'}}))
    assert release.verified_images(path, 'exact') is None


def test_release_rejects_unselected_sha_before_build(tmp_path, monkeypatch):
    import local_delivery as delivery
    import local_release
    config = {'state': str(tmp_path/'state'), 'runtime': str(Path(__file__).parents[2]/'scripts')}
    monkeypatch.setattr(local_release, 'deployment_environment', lambda config: None)
    db = delivery.database(config)
    delivery.meta(db, 'release', {'sha': 'b'*40, 'status': 'deploying'})
    db.close()
    with pytest.raises(RuntimeError, match='controller-selected'):
        local_release.release(config, 'a'*40)
