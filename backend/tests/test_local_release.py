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
