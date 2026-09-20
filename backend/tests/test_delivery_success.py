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
        return {'turn': {'id': 'ack-turn'}}


@pytest.fixture
def setup(monkeypatch):
    db = sqlite3.connect(':memory:')
    task = {'id': 29, 'sha': 'a'*40, 'status': 'delivered', 'owner': 'original-owner',
            'branch': 'session/test', 'updated_at': '2026-09-19T00:00:00+00:00'}
    monkeypatch.setattr(success, 'owner_matches', lambda *args: True)
    Bridge.calls = []
    Bridge.fail = False
    return db, task


def test_success_wakes_original_thread_once(setup):
    db, task = setup
    assert success.send(db, task, '/repo', Bridge) == 'accepted'
    assert success.send(db, task, '/repo', Bridge) == 'accepted'
    assert [c[0] for c in Bridge.calls] == ['thread/read', 'turn/start']
    assert Bridge.calls[-1][1]['threadId'] == task['owner']
    assert '部署成功通知' in Bridge.calls[-1][1]['input'][0]['text']


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


def test_busy_owner_is_deferred_without_consuming_notification(setup):
    db, task = setup
    class Busy(Bridge):
        def call(self, method, params):
            assert method == 'thread/read'
            return {'thread': {'id': task['owner'], 'status': {'type': 'active'}}}
    assert success.send(db, task, '/repo', Busy) == 'waiting_owner_idle'
    assert db.execute('SELECT COUNT(*) FROM success_notifications').fetchone()[0] == 0
    assert success.send(db, task, '/repo', Bridge) == 'accepted'


def test_missing_turn_receipt_is_not_success_or_replayed(setup):
    db, task = setup
    class NoReceipt(Bridge):
        def call(self, method, params):
            return super().call(method, params) if method == 'thread/read' else {}
    assert success.send(db, task, '/repo', NoReceipt) == 'unconfirmed'
    assert success.send(db, task, '/repo', Bridge) == 'unconfirmed'


def test_wrong_thread_cannot_receive_success(setup):
    db, task = setup
    class Wrong(Bridge):
        def call(self, method, params):
            return {'thread': {'id': 'someone-else'}}
    assert success.send(db, task, '/repo', Wrong) == 'owner_mismatch'
    assert db.execute('SELECT COUNT(*) FROM success_notifications').fetchone()[0] == 0
