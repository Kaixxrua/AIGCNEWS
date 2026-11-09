import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
import release_image_cache as cache


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    root = tmp_path / 'source'
    root.mkdir()
    for context in cache.CONTEXTS.values():
        (root / context).mkdir()
        (root / context / 'source').write_text('original')
    (root / '.dockerignore').write_text('*\n!mcp-go\n')
    subprocess.run(['git', 'init', '-q', root], check=True)
    commit(root)
    return root


def commit(root):
    subprocess.run(['git', '-C', root, 'add', '.'], check=True)
    subprocess.run(['git', '-C', root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture'], check=True)


def keys(root, config=None, toolchain=None):
    return {service: cache.image_key(root, service, config or {}, toolchain or ['fixed'])
            for service in cache.CONTEXTS}


@pytest.mark.parametrize('context,changed', [('backend', {'backend'}), ('mcp-go', {'mcp'}),
                                            ('frontend', {'frontend'})])
def test_prepared_context_change_rebuilds_only_affected_image(checkout, context, changed):
    before = keys(checkout)
    (checkout / context / 'source').write_text('changed')
    commit(checkout)
    after = keys(checkout)
    assert {service for service in before if before[service] != after[service]} == changed


def test_shared_files_toolchain_and_config_invalidate_all_images(checkout):
    before = keys(checkout)
    assert all(before[k] != keys(checkout, {'private_descriptor_sha256': 'changed'})[k] for k in before)
    assert all(before[k] != keys(checkout, toolchain=['new docker'])[k] for k in before)
    (checkout / 'deploy.sh').write_text('changed')
    commit(checkout)
    assert all(before[k] != keys(checkout)[k] for k in before)


def test_untracked_private_bytes_permissions_and_deletions_invalidate(checkout):
    asset = checkout / 'frontend/private.wasm'
    asset.write_bytes(b'private-v1')
    before = keys(checkout)['frontend']
    asset.write_bytes(b'private-v2')
    assert keys(checkout)['frontend'] != before
    before = keys(checkout)['frontend']
    asset.chmod(0o755)
    assert keys(checkout)['frontend'] != before
    before = keys(checkout)['frontend']
    asset.unlink()
    assert keys(checkout)['frontend'] != before


def test_changed_root_docker_context_disables_go_reuse(checkout):
    (checkout / '.dockerignore').write_text('!backend\n')
    assert keys(checkout)['mcp'] is None
    (checkout / 'mcp-go/Dockerfile.dockerignore').write_text('*\n!mcp-go\n')
    assert keys(checkout)['mcp']


def test_build_inputs_never_follow_private_symlinks(checkout, tmp_path):
    private = tmp_path / 'secret'
    private.write_text('secret')
    (checkout / 'frontend/link').symlink_to(private)
    with pytest.raises(ValueError, match='unsupported build input'):
        keys(checkout)


def test_cache_requires_owned_private_current_record_and_available_digest(tmp_path, monkeypatch):
    path = tmp_path / 'record.json'
    image = 'ghcr.io/kaixxrua/aigcnews/frontend@sha256:' + 'a' * 64
    monkeypatch.setattr(cache, 'image_available', lambda ref: ref == image)
    cache.record_image(path, 'key', image, 'b' * 40)
    assert cache.cached_image(path, 'key', 'frontend')['image'] == image
    assert not cache.cached_image(path, 'different', 'frontend')
    assert not cache.cached_image(path, 'key', 'backend')
    path.chmod(0o644)
    assert not cache.cached_image(path, 'key', 'frontend')
    path.chmod(0o600)
    data = json.loads(path.read_text())
    data['at'] -= cache.MAX_AGE + 1
    path.write_text(json.dumps(data))
    assert not cache.cached_image(path, 'key', 'frontend')
    cache.record_image(path, 'key', image, 'b' * 40)
    monkeypatch.setattr(cache, 'image_available', lambda ref: False)
    assert not cache.cached_image(path, 'key', 'frontend')
    cache.record_image(path, 'key', 'frontend:latest', 'b' * 40)
    assert not cache.cached_image(path, 'key', 'frontend')
