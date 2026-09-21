import io
import json
from unittest.mock import Mock

import httpx
import pytest

from backend.app.services.ingestion import github_logo_upgrade as upgrade, source_github


def test_graphql_readmes_use_canonical_commit_and_preserve_partial_errors(monkeypatch):
    monkeypatch.setattr(source_github, '_get_token', lambda: 'test')
    oid = 'a' * 40
    def handler(request):
        assert request.url.host == 'api.github.com'
        query = json.loads(request.content)['query']
        assert 'HEAD:README.md' in query and 'HEAD:.github/README.md' in query
        return httpx.Response(200, json={'data': {
            'r0': {'nameWithOwner': 'new/demo', 'defaultBranchRef': {'target': {'oid': oid}},
                   'b0': {'text': '![logo](./logo.svg)', 'isTruncated': False}},
            'r1': None,
        }, 'errors': [{'path': ['r1'], 'message': 'missing'}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = upgrade.readme_candidates(['old/demo', 'gone/demo'], client)
    assert result['old/demo']['candidates'] == [f'https://raw.githubusercontent.com/new/demo/{oid}/logo.svg']
    assert result['gone/demo']['status'] == 'lookup_failed'


@pytest.mark.parametrize('snapshot,status', [
    ({'status': 'lookup_failed'}, 'lookup_failed'),
    ({'status': 'checked', 'candidates': []}, 'no_logo'),
    ({'status': 'checked', 'candidates': ['https://avatars.githubusercontent.com/u/123']}, 'no_logo'),
])
def test_no_upgrade_keeps_avatar(snapshot, status):
    assert upgrade.upgrade_one(snapshot, Mock())['status'] == status


def test_failed_download_can_try_next_logo(monkeypatch):
    download = Mock(side_effect=[ValueError('bad svg'), (b'logo', 'image/webp')])
    monkeypatch.setattr(upgrade, 'download_logo', download)
    result = upgrade.upgrade_one({'status': 'checked', 'candidates': ['https://raw.githubusercontent.com/a.svg', 'https://raw.githubusercontent.com/b.png']}, Mock())
    assert result['status'] == 'found' and result['content'] == b'logo'


def test_upgrade_pass_only_saves_successful_artwork(monkeypatch):
    monkeypatch.setattr(upgrade, 'readme_candidates', lambda names, client: {
        name: {'status': 'checked', 'candidates': [name]} for name in names})
    monkeypatch.setattr(upgrade, 'upgrade_one', lambda snapshot, images: {
        'status': 'found', 'content': b'logo'} if snapshot['candidates'] == ['a/logo'] else {'status': 'no_logo'})
    repository = Mock()
    report = io.StringIO()
    result = upgrade.upgrade_avatars(repository, [{'repo_id': n, 'full_name': n} for n in ['a/logo', 'a/avatar']], report, 2)
    repository.save.assert_called_once_with('a/logo', {'status': 'found', 'content': b'logo'})
    assert result['found'] == 1 and result['no_logo'] == 1
    assert all('content' not in json.loads(line) for line in report.getvalue().splitlines())
