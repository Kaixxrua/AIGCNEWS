from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_ui_library import repository, router
from backend.app.core.auth import OptionalUser, RequireUser
from backend.app.repositories.postgres_ui_library_repository import CopyLimitExceeded, CopyRequestConflict
from backend.app.services.ui_discovery import SOURCES, X_HANDLES, DiscoveryError, RepositorySource, discover_web, discover_x, rss_candidates, tree_candidates
from backend.app.services.ui_library import quota_policy


def test_calendar_quota_and_expired_vip():
    now = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    policy = quota_policy({'membership_tier': 'free'}, now)
    assert str(policy['usage_date']) == '2026-09-11'
    assert policy['resets_at'] == '2026-09-12T00:00:00+08:00'
    assert quota_policy({'membership_tier': 'member', 'membership_expires_at': now}, now)['limit'] == 5
    assert quota_policy({'membership_tier': 'member'}, now)['limit'] is None
    assert quota_policy({'membership_tier': 'vip'}, now)['limit'] == 5


def client(user=None):
    app = FastAPI()
    app.include_router(router, prefix='/api')
    repo = MagicMock()
    repo.engagement.return_value = []
    repo.consume_copy.return_value = 5
    repo.copy_usage.return_value = 5
    app.dependency_overrides[repository] = lambda: repo
    app.dependency_overrides[OptionalUser] = lambda: user
    if user is not None:
        app.dependency_overrides[RequireUser] = lambda: user
    return TestClient(app), repo


def test_anonymous_cannot_like_or_copy():
    c, repo = client()
    assert c.put('/api/ui-library/test/like', json={'liked': True}).status_code == 401
    assert c.post('/api/ui-library/test/copy', json={'kind': 'source', 'request_id': str(uuid4())}).status_code == 401
    repo.consume_copy.assert_not_called()
    repo.set_like.assert_not_called()


@pytest.mark.parametrize('period,hours', [('daily', 24), ('weekly', 168), ('monthly', 720)])
def test_rankings_use_rolling_windows(period, hours):
    c, repo = client()
    assert c.get('/api/ui-library/engagement', params={'period': period}).status_code == 200
    _, start, end = repo.engagement.call_args.args
    assert (end-start).total_seconds() == hours * 3600


def test_copy_validates_template_and_enforces_one_combined_allowance(monkeypatch):
    monkeypatch.setattr('backend.app.api.routes_ui_library.known_template', lambda value: value == 'test')
    c, repo = client({'sub': '1', 'membership_tier': 'free'})
    for kind in ['source', 'prompt']:
        response = c.post('/api/ui-library/test/copy', json={'kind': kind, 'request_id': str(uuid4())})
        assert response.status_code == 200
        assert response.json()['remaining'] == 0
        assert repo.consume_copy.call_args.args[-1] == 5
    repo.consume_copy.side_effect = CopyLimitExceeded()
    assert c.post('/api/ui-library/test/copy', json={'kind': 'source', 'request_id': str(uuid4())}).status_code == 429
    repo.consume_copy.side_effect = CopyRequestConflict()
    assert c.post('/api/ui-library/test/copy', json={'kind': 'source', 'request_id': str(uuid4())}).status_code == 409
    assert c.post('/api/ui-library/unknown/copy', json={'kind': 'source', 'request_id': str(uuid4())}).status_code == 404


def test_vip_copy_uses_unlimited_policy(monkeypatch):
    monkeypatch.setattr('backend.app.api.routes_ui_library.known_template', lambda _: True)
    c, repo = client({'sub': '1', 'membership_tier': 'member'})
    assert c.post('/api/ui-library/test/copy', json={'kind': 'prompt', 'request_id': str(uuid4())}).json()['remaining'] is None
    assert repo.consume_copy.call_args.args[-1] is None


def test_tree_discovery_is_pinned_and_never_marks_license_approved():
    source = RepositorySource('sample', 'a/b', ('components/*.tsx',))
    tree = {'sha': 'tree', 'commit_sha': 'commit', 'tree': [
        {'path': 'components/card.tsx', 'type': 'blob', 'mode': '100644', 'sha': 'blob'},
        {'path': 'LICENSE.md', 'type': 'blob', 'mode': '100644', 'sha': 'license'},
        {'path': 'components/link.tsx', 'type': 'blob', 'mode': '120000', 'sha': 'link'},
    ]}
    result = tree_candidates(source, tree)
    assert len(result) == 1
    assert '/blob/commit/' in result[0]['source_url']
    assert result[0]['license_status'] == 'needs_review'
    tree['tree'][1]['sha'] = 'changed-license'
    assert tree_candidates(source, tree)[0]['revision'] != result[0]['revision']
    tree['truncated'] = True
    with pytest.raises(DiscoveryError, match='truncated'):
        tree_candidates(source, tree)


def test_rss_rejects_entities_and_keeps_only_original_site():
    with pytest.raises(DiscoveryError):
        rss_candidates(b'<!DOCTYPE test><rss/>')
    result = rss_candidates(b'<rss><channel><item><title>Demo</title><link>https://tympanus.net/codrops/demo</link></item><item><link>http://127.0.0.1/</link></item></channel></rss>')
    assert len(result) == 1
    assert result[0]['license_status'] == 'needs_review'


def test_one_source_failure_does_not_erase_or_block_other_sources():
    repo = MagicMock()
    def handler(request):
        if request.url.host == 'api.github.com':
            return httpx.Response(403, json={'message': 'limited'})
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=b'<rss><channel><item><title>Demo</title><link>https://tympanus.net/codrops/demo</link></item></channel></rss>')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await discover_web(repo, token='secret-test-token', client=c)
    assert asyncio.run(run()) is False
    assert repo.record_failure.call_count == 5
    assert repo.record_discovery.call_args.args[0] == 'codrops'
    assert 'secret-test-token' not in str(repo.mock_calls)


def test_hyperui_discovers_original_examples_not_blog_articles():
    source = next(source for source in SOURCES if source.id == 'hyperui')
    tree = {'sha': 'commit', 'tree': [
        {'path': path, 'type': 'blob', 'mode': '100644', 'sha': str(i)}
        for i, path in enumerate(['public/examples/marketing/cards/1.html', 'src/content/blog/release.md'])
    ]}
    assert [item['path'] for item in tree_candidates(source, tree)] == ['public/examples/marketing/cards/1.html']


@pytest.mark.parametrize('failure', [None, 'partial', 'wrong_window'])
def test_x_discovery_requires_complete_requested_window(failure):
    from backend.app.services.source_plugins.x_source import XWindowFetchResult, XWindowHandleResult
    repo = MagicMock()
    async def fetch(handles, *, window_start, window_end, count_per_user):
        assert tuple(handles) == X_HANDLES and count_per_user == 20
        assert (window_end - window_start).total_seconds() == 86400
        return XWindowFetchResult(
            requested_handles=X_HANDLES,
            window_start=None if failure == 'wrong_window' else window_start,
            window_end=window_end,
            by_handle={handle: XWindowHandleResult(
                complete=failure != 'partial', reason='timeline_exhausted',
                tweets=(SimpleNamespace(id='123', text='Original demo', urls=['https://example.test/demo', 'http://127.0.0.1/']),
                        SimpleNamespace(id='124', text='No link', urls=[])),
            ) for handle in X_HANDLES},
        )
    transport = SimpleNamespace(fetch_watchlist_tweets_window=AsyncMock(side_effect=fetch))
    assert asyncio.run(discover_x(repo, transport)) is (failure is None)
    if failure:
        repo.record_discovery.assert_not_called()
        assert repo.record_failure.call_count == len(X_HANDLES)
    else:
        assert repo.record_discovery.call_count == len(X_HANDLES)
        for call in repo.record_discovery.call_args_list:
            candidate, = call.args[2]
            assert candidate['links'] == ['https://example.test/demo']
            assert candidate['license_status'] == 'needs_review'
        repo.record_failure.assert_not_called()


def test_discovery_schedule_times_and_x_feature_gate():
    from backend.app.core.scheduler import ApplicationSchedulerRuntime
    from backend.app.core.scheduler_registry import UI_LIBRARY_JOBS, build_trigger
    from backend.tests.test_scheduler_config_live_apply import _config
    fake_scheduler = MagicMock()
    fake_scheduler.running = True
    fake_scheduler.get_job.return_value = None
    runtime = ApplicationSchedulerRuntime(MagicMock(), scheduler=fake_scheduler, x_source_enabled=False)
    for job, minute in zip(UI_LIBRARY_JOBS, [0, 10]):
        fields = {field.name: str(field) for field in build_trigger(job).fields}
        assert fields['hour'] == '9' and fields['minute'] == str(minute)
        assert job.timezone == 'Asia/Shanghai' and job.max_instances == 1 and job.coalesce
    assert runtime.apply_config_update(_config('ui_library_discovery'))
    assert fake_scheduler.add_job.call_args.kwargs['id'] == 'ui_library_discovery'
    fake_scheduler.add_job.reset_mock()
    assert runtime.apply_config_update(_config('ui_library_x_discovery'))
    fake_scheduler.add_job.assert_not_called()
    fake_scheduler.get_job.return_value = MagicMock()
    assert runtime.apply_config_update(_config('ui_library_discovery', enabled=False))
    fake_scheduler.remove_job.assert_called_once_with('ui_library_discovery')


def test_web_discovery_callback_reuses_github_lock(monkeypatch):
    from backend.app.core.scheduler import ApplicationSchedulerRuntime
    runtime = ApplicationSchedulerRuntime(MagicMock(), scheduler=MagicMock())
    called = []
    async def discover(*args, **kwargs):
        assert runtime._github_job_lock.locked()
        called.append(True)
        return True
    monkeypatch.setattr('backend.app.services.ui_discovery.discover_web', discover)
    asyncio.run(runtime._run_ui_library_discovery_job())
    assert called == [True]
