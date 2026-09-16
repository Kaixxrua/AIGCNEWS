from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.repositories.postgres_ui_library_repository import (
    CopyLimitExceeded,
    PostgresUiLibraryRepository,
)
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture
def store():
    with postgres_test_sandbox() as sandbox:
        with sandbox.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO users(email, hashed_password, role) VALUES ('ui-test@example.test','test','user') RETURNING id")
            user_id = cur.fetchone()['id']
        yield PostgresUiLibraryRepository(sandbox.database), user_id


def test_parallel_source_and_prompt_requests_share_five_slots(store):
    repo, user = store
    day = datetime.now(timezone.utc).date()
    def consume(index):
        try:
            return repo.consume_copy(user, 'sample', 'source' if index % 2 else 'prompt', str(uuid4()), day, 5)
        except CopyLimitExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(consume, range(16)))
    assert sorted(x for x in results if x is not None) == [1, 2, 3, 4, 5]
    assert repo.copy_usage(user, day) == 5
    assert repo.consume_copy(user, 'sample', 'source', str(uuid4()), day + timedelta(days=1), 5) == 1


def test_receipt_retries_and_vip_do_not_lose_counts(store):
    repo, user = store
    day = datetime.now(timezone.utc).date()
    request_id = str(uuid4())
    assert repo.consume_copy(user, 'sample', 'source', request_id, day, 5) == 1
    assert repo.consume_copy(user, 'sample', 'source', request_id, day, 5) == 1
    for _ in range(7):
        repo.consume_copy(user, 'sample', 'prompt', str(uuid4()), day, None)
    assert repo.copy_usage(user, day) == 8
    with pytest.raises(CopyLimitExceeded):
        repo.consume_copy(user, 'sample', 'source', str(uuid4()), day, 5)


def test_like_toggle_cannot_refresh_old_vote_into_today(store):
    repo, user = store
    repo.set_like(user, 'sample', True)
    now = datetime.now(timezone.utc)
    with repo._database.transaction() as conn, conn.cursor() as cur:
        cur.execute('UPDATE ui_template_likes SET first_liked_at=%s', (now-timedelta(days=2),))
    repo.set_like(user, 'sample', False)
    repo.set_like(user, 'sample', True)
    daily = repo.engagement(user, now-timedelta(hours=24), now)
    weekly = repo.engagement(user, now-timedelta(days=7), now)
    assert daily[0]['likes'] == 1 and daily[0]['score'] == 0
    assert weekly[0]['score'] == 1 and weekly[0]['liked']


def test_discovery_baseline_new_update_and_failure_recovery(store):
    repo, _ = store
    first = {'id': 'a/card', 'revision': '1', 'license_status': 'needs_review'}
    assert repo.record_discovery('a', 'one', [first]) == {'baseline': 1, 'new': 0, 'updated': 0}
    assert repo.record_discovery('a', 'one', [first]) == {'baseline': 0, 'new': 0, 'updated': 0}
    repo.record_failure('a', 'upstream_http_403')
    assert repo.source_state('a')['revision'] == 'one'
    second = {'id': 'a/button', 'revision': '2'}
    assert repo.record_discovery('a', 'two', [{**first, 'revision': '2'}, second]) == {'baseline': 0, 'new': 1, 'updated': 1}
    report = repo.discovery_report()
    assert report['total'] == 2
    assert report['sources'][0]['error'] is None
    assert all(row['review_status'] == 'pending' for row in report['candidates'])


def test_configurable_discovery_source_crud(store):
    repo, _ = store
    created = repo.create_source_config({
        'name': 'Custom components', 'kind': 'github', 'repository': 'acme/ui',
        'path_patterns': ['components/*.tsx'], 'feed_url': None, 'enabled': True,
    })
    assert created['id'] > 0
    assert repo.list_source_configs(enabled_only=True)[0]['repository'] == 'acme/ui'

    updated = repo.update_source_config(created['id'], {
        'name': 'Custom feed', 'kind': 'feed', 'repository': None,
        'path_patterns': [], 'feed_url': 'https://example.test/feed.xml', 'enabled': False,
    })
    assert updated['kind'] == 'feed'
    assert repo.list_source_configs(enabled_only=True) == []
    assert repo.list_source_configs()[0]['feed_url'] == 'https://example.test/feed.xml'
    assert repo.delete_source_config(created['id']) is True
    assert repo.delete_source_config(created['id']) is False
