import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]/'scripts/ci'))
import delivery_success as success


class Bridge:
    calls = []
    fail = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/read':
            return {'thread': {'id': params['threadId'], 'status': {'type': 'idle'}}}
        if self.fail:
            raise TimeoutError('ambiguous send')
        return {}


@pytest.fixture
def setup(monkeypatch):
    db = sqlite3.connect(':memory:')
    task = {'id': 29, 'sha': 'a'*40, 'status': 'delivered', 'owner': 'original-owner',
            'branch': 'session/test', 'updated_at': '2026-09-19T00:00:00+00:00'}
    monkeypatch.setattr(success, 'owner_matches', lambda *args: True)
    Bridge.calls = []
    Bridge.fail = False
    return db, task


def test_success_injects_original_thread_once_without_model_turn(setup):
    db, task = setup
    assert success.send(db, task, '/repo', Bridge) == 'accepted'
    assert success.send(db, task, '/repo', Bridge) == 'accepted'
    assert [c[0] for c in Bridge.calls] == ['thread/read', 'thread/inject_items']
    assert Bridge.calls[-1][1]['threadId'] == task['owner']
    assert '部署成功通知' in Bridge.calls[-1][1]['items'][0]['content'][0]['text']


def test_missing_owner_or_failed_task_cannot_send(setup, monkeypatch):
    db, task = setup
    assert success.send(db, {**task, 'status': 'failed'}, '/repo', Bridge) == 'unowned'
    monkeypatch.setattr(success, 'owner_matches', lambda *args: False)
    assert success.send(db, task, '/repo', Bridge) == 'unowned'
    assert not Bridge.calls


def test_uncertain_response_never_replayed(setup):
    db, task = setup
    Bridge.fail = True
    assert success.send(db, task, '/repo', Bridge) == 'unconfirmed'
    count = len(Bridge.calls)
    assert success.send(db, task, '/repo', Bridge) == 'unconfirmed'
    assert len(Bridge.calls) == count
