from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.services import github_owner_avatar as avatars


@pytest.fixture(autouse=True)
def clear_cache():
    avatars._cache.clear()
    yield
    avatars._cache.clear()


def test_shared_owner_requests_coalesce_and_expire(monkeypatch):
    now = [0]
    monkeypatch.setattr(avatars.time, 'monotonic', lambda: now[0])
    download = Mock(return_value={'content': b'avatar'})
    monkeypatch.setattr(avatars, '_download', download)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(avatars.get_owner_avatar, ['Acme', 'acme'] * 8))
    assert all(result == {'content': b'avatar'} for result in results)
    download.assert_called_once_with('acme')
    now[0] = 3601
    avatars.get_owner_avatar('acme')
    assert download.call_count == 2


def test_failures_expire_and_cache_size_is_bounded(monkeypatch):
    now = [0]
    monkeypatch.setattr(avatars.time, 'monotonic', lambda: now[0])
    download = Mock(return_value=None)
    monkeypatch.setattr(avatars, '_download', download)
    monkeypatch.setattr(avatars, '_MAX_ENTRIES', 2)
    assert avatars.get_owner_avatar('a') is None
    assert avatars.get_owner_avatar('a') is None
    assert download.call_count == 1
    now[0] = 301
    download.return_value = {'content': b'recovered'}
    assert avatars.get_owner_avatar('a')['content'] == b'recovered'
    avatars.get_owner_avatar('b')
    avatars.get_owner_avatar('c')
    assert list(avatars._cache) == ['b', 'c']


@pytest.mark.parametrize('owner', ['../acme', 'acme/repo', 'https://127.0.0.1', 'a' * 40, ''])
def test_invalid_owner_cannot_trigger_outbound_request(monkeypatch, owner):
    download = Mock()
    monkeypatch.setattr(avatars, '_download', download)
    assert avatars.get_owner_avatar(owner) is None
    download.assert_not_called()


def test_uses_validated_artwork_downloader_and_recovers_from_upstream_failure(monkeypatch):
    monkeypatch.setattr(avatars, 'resolve_owner_avatars', lambda owners, api: {'acme': 'https://avatars.githubusercontent.com/u/123?s=128'})
    download = Mock(return_value=(b'sanitized avatar', 'image/webp'))
    monkeypatch.setattr(avatars, 'download_logo', download)
    result = avatars.get_owner_avatar('acme')
    assert result['content'] == b'sanitized avatar'
    assert len(result['sha256']) == 64
    assert download.call_args.args[0] == 'https://avatars.githubusercontent.com/u/123?s=128'
    download.side_effect = httpx.ConnectError('offline')
    assert avatars.get_owner_avatar('other') is None
    assert download.call_args.args[0] == 'https://github.com/other.png?size=128'


def test_busy_downloads_do_not_cache_a_failure(monkeypatch):
    slots = Mock()
    slots.acquire.return_value = False
    monkeypatch.setattr(avatars, '_downloads', slots)
    download = Mock()
    monkeypatch.setattr(avatars, '_download', download)
    assert avatars.get_owner_avatar('acme') is None
    assert 'acme' not in avatars._cache
    download.assert_not_called()
    slots.release.assert_not_called()


def test_avatar_route_is_separate_from_artwork_and_rejects_unknown_or_removed_projects(monkeypatch):
    from backend.app.api.routes_github_projects import get_github_logo_repository, router

    repository = Mock()
    repository.avatar_owner.return_value = 'new-owner'
    avatar = Mock(return_value={'content': b'avatar', 'content_type': 'image/webp', 'sha256': 'avatar-hash'})
    monkeypatch.setattr(avatars, 'get_owner_avatar', avatar)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_github_logo_repository] = lambda: repository
    with TestClient(app) as client:
        path = '/api/projects/github/logo/old-owner/demo?avatar=true'
        response = client.get(path)
        assert response.status_code == 200 and response.content == b'avatar'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'sandbox' in response.headers['content-security-policy']
        assert response.headers['cache-control'] == 'public, max-age=3600'
        avatar.assert_called_once_with('new-owner')
        repository.get.assert_not_called()
        assert client.get(path, headers={'if-none-match': '"avatar-hash"'}).status_code == 304
        avatar.return_value = None
        failure = client.get(path)
        assert failure.status_code == 503 and failure.headers['cache-control'] == 'no-store'
        repository.avatar_owner.return_value = None
        avatar.reset_mock()
        assert client.get(path).status_code == 404
        avatar.assert_not_called()
