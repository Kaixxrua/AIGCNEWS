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


@pytest.mark.parametrize('edge_retry', [False, True])
def test_same_code_publishes_new_content_but_edge_retry_keeps_its_original_content(tmp_path, monkeypatch, edge_retry):
    import json

    import local_delivery as delivery
    import local_release
    from ui_catalog_release import catalog_digest

    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / 'scripts/release'))
    import deploy_production
    import publish_frontend_edges
    sha = 'a'*40
    production = tmp_path / 'production'
    control = production / '.aigcnews-deploy'
    control.mkdir(parents=True)
    catalog = production / 'mcp-go/internal/uicatalog/data/catalog.json'
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(b'{"items":[{"id":"new"}]}')
    config = {'state': str(tmp_path/'state'), 'production': str(production),
              'runtime': str(Path(__file__).parents[2]/'scripts')}
    digest = catalog_digest(config)
    old_digest = 'b'*64
    (control / 'state.json').write_text(json.dumps({
        'active_release': sha, 'in_progress': None, 'ui_catalog_sha256': old_digest}))
    db = delivery.database(config)
    delivery.meta(db, 'release', {'sha': sha, 'status': 'deploying',
                                 'ui_catalog_sha256': old_digest if edge_retry else digest})
    db.close()
    monkeypatch.setattr(local_release, 'deployment_environment', lambda config: None)
    monkeypatch.setattr(delivery, 'git', lambda *args: sha)
    monkeypatch.setattr(delivery, 'ancestor', lambda *args: True)
    images = {key: 'example/'+key+'@sha256:'+'c'*64 for key in ('backend', 'mcp', 'frontend')}
    calls = []

    def cached(path, identity):
        assert not edge_retry
        assert identity == local_release.build_identity(config, sha, digest)
        assert identity != local_release.build_identity(config, sha, old_digest)
        return images

    def deploy(root, release, **kwargs):
        assert release.ui_catalog_sha256 == digest
        calls.append('deploy')
        return 'deployed'

    monkeypatch.setattr(local_release, 'verified_images', cached)
    monkeypatch.setattr(local_release, 'run', lambda *a, **kw: pytest.fail('unexpected build'))
    monkeypatch.setattr(deploy_production, 'deploy', deploy)
    monkeypatch.setattr(publish_frontend_edges, 'publish', lambda *args: calls.append('edge') or 'published')
    local_release.release(config, sha)
    assert calls == (['edge'] if edge_retry else ['deploy', 'edge'])


class _Result:
    def __init__(self, returncode=0, stdout=''):
        self.returncode = returncode
        self.stdout = stdout


def _write_state(tmp_path, **fields):
    import json
    control = tmp_path / 'production' / '.aigcnews-deploy'
    control.mkdir(parents=True)
    (control / 'state.json').write_text(json.dumps(fields))
    return {'production': str(tmp_path / 'production'), 'bare': str(tmp_path / 'bare.git')}


def test_retention_keep_requires_production_state(tmp_path):
    import local_release as release
    config = {'production': str(tmp_path / 'missing'), 'bare': str(tmp_path / 'bare.git')}
    assert release.retention_keep(config, 'a' * 40) is None


def test_retention_keep_protects_active_rollback_and_recent(tmp_path, monkeypatch):
    import local_release as release
    active, previous, failed = 'a' * 40, 'b' * 40, 'c' * 40
    recent = ['d' * 40, 'e' * 40]
    config = _write_state(tmp_path, active_release=active, previous_release=previous,
                          last_failed_release=failed)
    config['image_retention'] = 2

    def fake(args, *, timeout):
        assert args[:4] == ['git', '--git-dir', config['bare'], 'rev-list']
        assert args[4:6] == ['-n', '2']
        return _Result(0, '\n'.join(recent) + '\n')

    monkeypatch.setattr(release, '_capture', fake)
    keep = release.retention_keep(config, 'f' * 40)
    assert keep == {active, previous, failed, 'f' * 40, *recent}


def test_retention_keep_none_when_history_unavailable(tmp_path, monkeypatch):
    import local_release as release
    config = _write_state(tmp_path, active_release='a' * 40)
    monkeypatch.setattr(release, '_capture', lambda args, *, timeout: _Result(128, ''))
    assert release.retention_keep(config, 'a' * 40) is None


def test_prune_removes_only_superseded_project_commit_tags(tmp_path, monkeypatch):
    import local_release as release
    keep_sha, stale_sha = 'a' * 40, '9' * 40
    config = _write_state(tmp_path, active_release=keep_sha)
    config['image_retention'] = 0  # protected set is exactly {keep_sha}
    config['build_cache_keep_bytes'] = 15 * 1024 ** 3
    prefix = release.IMAGE_REPOSITORY
    listing = '\n'.join([
        prefix + 'backend:' + keep_sha,       # protected -> kept
        prefix + 'backend:' + stale_sha,      # superseded -> removed
        prefix + 'frontend:' + stale_sha,     # superseded -> removed
        prefix + 'mcp:' + stale_sha,          # superseded -> removed
        prefix + 'backend:latest',            # not a commit tag -> ignored
        'redis:7-alpine',                     # unrelated image -> ignored
        'ghcr.io/kaixxrua/aigcnews/other:' + stale_sha,  # unknown service -> ignored
    ])
    calls = []

    def fake(args, *, timeout):
        calls.append(list(args))
        if args[:3] == ['docker', 'image', 'ls']:
            return _Result(0, listing)
        return _Result(0, '')

    monkeypatch.setattr(release, '_capture', fake)
    summary = release.prune_release_images(config, keep_sha)
    removed = {c[2] for c in calls if c[:2] == ['docker', 'rmi']}
    assert removed == {prefix + 'backend:' + stale_sha,
                       prefix + 'frontend:' + stale_sha,
                       prefix + 'mcp:' + stale_sha}
    assert summary['status'] == 'pruned'
    assert summary['kept'] == 1
    assert set(summary['removed']) == removed
    prune = [c for c in calls if c[:3] == ['docker', 'builder', 'prune']]
    assert prune and prune[0][-2:] == ['--keep-storage', str(15 * 1024 ** 3)]


def test_prune_skips_builder_prune_when_cache_budget_zero(tmp_path, monkeypatch):
    import local_release as release
    config = _write_state(tmp_path, active_release='a' * 40)
    config['image_retention'] = 0
    config['build_cache_keep_bytes'] = 0
    calls = []

    def fake(args, *, timeout):
        calls.append(list(args))
        if args[:3] == ['docker', 'image', 'ls']:
            return _Result(0, '')
        return _Result(0, '')

    monkeypatch.setattr(release, '_capture', fake)
    release.prune_release_images(config, 'a' * 40)
    assert not any(c[:3] == ['docker', 'builder', 'prune'] for c in calls)


def test_prune_never_raises_and_reports_when_protected_set_unavailable(tmp_path, monkeypatch):
    import local_release as release
    config = {'production': str(tmp_path / 'missing'), 'bare': str(tmp_path / 'bare.git')}
    calls = []
    monkeypatch.setattr(release, '_capture', lambda args, *, timeout: calls.append(list(args)) or _Result(0, ''))
    summary = release.prune_release_images(config, 'a' * 40)
    assert summary['status'].startswith('skipped')
    assert summary['removed'] == []
    assert not any(c[:2] == ['docker', 'rmi'] for c in calls)


def test_prune_contains_docker_failures(tmp_path, monkeypatch):
    import local_release as release
    config = _write_state(tmp_path, active_release='a' * 40)
    config['image_retention'] = 0
    listing = release.IMAGE_REPOSITORY + 'backend:' + '9' * 40

    def fake(args, *, timeout):
        if args[:3] == ['docker', 'image', 'ls']:
            return _Result(0, listing)
        if args[:2] == ['docker', 'rmi']:
            return _Result(1, '')  # image still referenced; skip, do not raise
        return _Result(0, '')

    monkeypatch.setattr(release, '_capture', fake)
    summary = release.prune_release_images(config, 'a' * 40)
    assert summary['status'] == 'pruned'
    assert summary['removed'] == []
    assert summary['errors'] == [release.IMAGE_REPOSITORY + 'backend:' + '9' * 40]
