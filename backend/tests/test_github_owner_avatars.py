import httpx

from backend.app.services.ingestion import github_project_logos as logos, source_github


def test_batch_owner_resolution_validates_each_url_and_preserves_partial_success(monkeypatch):
    monkeypatch.setattr(source_github, '_get_token', lambda: 'test-token')
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url == 'https://api.github.com/graphql'
        assert request.headers['authorization'] == 'Bearer test-token'
        return httpx.Response(200, json={'data': {
            'o0': {'avatarUrl': 'https://avatars.githubusercontent.com/u/123?s=128'},
            'o1': {'avatarUrl': 'http://127.0.0.1/private'},
            'o2': {'avatarUrl': 'https://avatars.githubusercontent.com/default'},
            'o3': None,
        }, 'errors': [{'message': 'owner not found'}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = logos.resolve_owner_avatars(['acme', 'bad', 'default', 'missing', 'acme', 'invalid"owner'], client)
    assert result == {'acme': 'https://avatars.githubusercontent.com/u/123?s=128'}
    assert len(seen) == 1
    assert seen[0].content.count(b'repositoryOwner') == 4


def test_avatar_resolution_failure_keeps_existing_fallback(monkeypatch):
    monkeypatch.setattr(source_github, '_get_token', lambda: 'test-token')
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        assert logos.resolve_owner_avatars(['acme'], client) == {}


def test_collection_prefers_readme_logo_then_resolved_cdn_without_github_page(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(source_github, 'fetch_github_readme_snapshot', lambda *args: SimpleNamespace(
        status='succeeded', logo_candidates=('https://raw.githubusercontent.com/acme/demo/main/logo.svg',)))
    seen = []
    def download(url, client):
        seen.append(url)
        if 'raw.githubusercontent.com' in url:
            raise ValueError('unsupported artwork')
        return b'avatar', 'image/webp'
    monkeypatch.setattr(logos, 'download_logo', download)
    avatar = 'https://avatars.githubusercontent.com/u/123?s=128'
    result = logos.collect_logo('acme/demo', None, None, owner_avatar_url=avatar)
    assert result['status'] == 'found'
    assert result['source_url'] == avatar
    assert seen == ['https://raw.githubusercontent.com/acme/demo/main/logo.svg', avatar]


def test_refresh_passes_batched_official_avatars_to_workers(monkeypatch):
    from unittest.mock import Mock
    repository = Mock()
    repository.pending.return_value = [{'repo_id': 'acme/demo', 'full_name': 'acme/demo'}]
    resolve = Mock(return_value={'acme': 'https://avatars.githubusercontent.com/u/123?s=128'})
    collect = Mock(return_value={'status': 'found'})
    monkeypatch.setattr(logos, 'resolve_owner_avatars', resolve)
    monkeypatch.setattr(logos, 'collect_logo', collect)
    assert logos.refresh_project_logos(repository, limit=1, interval=0)['found'] == 1
    assert resolve.call_args.args[0] == ['acme']
    assert collect.call_args.args[4] == 'https://avatars.githubusercontent.com/u/123?s=128'


def test_anonymous_installation_does_not_attempt_authenticated_graphql(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(source_github, '_get_token', lambda: '')
    client = Mock()
    assert logos.resolve_owner_avatars(['acme'], client) == {}
    client.post.assert_not_called()


def test_image_proxy_override_does_not_change_general_api_client(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.setattr(logos, 'settings', SimpleNamespace(
        github_artwork_proxy='socks5://artwork.example:1080', outbound_proxy='http://general.example:3128'))
    factory = Mock(return_value=httpx.MockTransport(lambda request: httpx.Response(200)))
    monkeypatch.setattr(logos, 'GitHubArtworkTransport', factory)
    repository = Mock()
    repository.pending.return_value = []
    logos.refresh_project_logos(repository)
    factory.assert_called_once_with(proxy='socks5://artwork.example:1080')


def test_moved_repository_resolves_canonical_readme_and_avatar(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(source_github, '_get_token', lambda: 'test-token')
    def handler(request):
        assert request.url == 'https://api.github.com/graphql'
        return httpx.Response(200, json={'data': {
            'r0': {'nameWithOwner': 'new-owner/demo', 'owner': {'avatarUrl': 'https://avatars.githubusercontent.com/u/99?s=128'}},
            'r1': None,
            'r2': {'nameWithOwner': 'unsafe/demo', 'owner': {'avatarUrl': 'https://127.0.0.1/private'}},
        }})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        moved = logos.resolve_moved_repository_artwork(['old-owner/demo', 'missing/demo', 'unsafe/demo'], client)
    assert moved == {'old-owner/demo': ('new-owner/demo', 'https://avatars.githubusercontent.com/u/99?s=128')}
    monkeypatch.setattr(logos, 'resolve_owner_avatars', lambda *args: {})
    monkeypatch.setattr(logos, 'resolve_moved_repository_artwork', lambda *args: moved)
    collect = Mock(return_value={'status': 'found'})
    monkeypatch.setattr(logos, 'collect_logo', collect)
    repository = Mock()
    repository.pending.return_value = [{'repo_id': 'opaque-id', 'full_name': 'old-owner/demo'}]
    logos.refresh_project_logos(repository, limit=1, interval=0)
    assert collect.call_args.args[0] == 'new-owner/demo'
    assert collect.call_args.args[4] == 'https://avatars.githubusercontent.com/u/99?s=128'
    assert repository.save.call_args.args[0] == 'opaque-id'
