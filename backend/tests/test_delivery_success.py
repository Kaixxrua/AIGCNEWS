import json
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
    assert len(Bridge.calls) == count + 1
    assert Bridge.calls[-1][0] == 'thread/read'


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


def test_subagent_success_reaches_root_without_rebinding_execution_owner(setup):
    db, task = setup
    class Child(Bridge):
        def call(self, method, params):
            result = super().call(method, params)
            if method == 'thread/read' and params['threadId'] == task['owner']:
                result['thread'].update(threadSource='subagent', parentThreadId='root',
                                        canAcceptDirectInput=False)
            return result
    assert success.send(db, task, '/repo', Child) == 'accepted'
    assert Bridge.calls[-1][1]['threadId'] == 'root'
    owner, detail = db.execute('SELECT owner,detail FROM success_notifications').fetchone()
    assert owner == task['owner']
    assert json.loads(detail)['owner_chain'] == [task['owner'], 'root']


@pytest.mark.parametrize('parent', [None, 'original-owner'])
def test_missing_or_cyclic_parent_never_sends(setup, parent):
    db, task = setup
    class Invalid(Bridge):
        def call(self, method, params):
            assert method == 'thread/read'
            return {'thread': {'id': task['owner'], 'threadSource': 'subagent',
                               'parentThreadId': parent}}
    assert success.send(db, task, '/repo', Invalid) == 'owner_mismatch'


def test_uncertain_send_reconciles_positive_user_message_only(setup, tmp_path, monkeypatch):
    db, task = setup
    Bridge.fail = True
    assert success.send(db, task, '/repo', Bridge) == 'unconfirmed'
    record = json.loads(db.execute('SELECT detail FROM success_notifications').fetchone()[0])
    assert record['error_type'] == 'TimeoutError'
    path = tmp_path / '.codex/sessions/receipt.jsonl'
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(success.Path, 'home', lambda: tmp_path)
    identity = f"delivered:{task['id']}:{task['sha']}"
    events = [{'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'confirmed'}},
              {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
               'content': [{'text': f'[{identity}]\ncompletion'}]}}]
    path.write_text('\n'.join(json.dumps(e) for e in events))
    class Evidence(Bridge):
        def call(self, method, params):
            assert method == 'thread/read'
            return {'thread': {'id': task['owner'], 'path': str(path)}}
    assert success.send(db, task, '/repo', Evidence) == 'accepted'
    assert json.loads(db.execute('SELECT detail FROM success_notifications').fetchone()[0])['turn_id'] == 'confirmed'


def test_claude_owned_delivery_never_starts_a_codex_turn(tmp_path, monkeypatch):
    owner = 'claude:6f1c2a3b-0d4e-4f5a-8b6c-7d8e9f0a1b2c'
    task = {'id': 30, 'sha': 'b'*40, 'status': 'delivered', 'owner': owner,
            'branch': 'session/claude-task', 'updated_at': '2026-09-24T00:00:00+00:00'}
    receipt = tmp_path/'owner.json'
    receipt.write_text(json.dumps({'schema': 'aigcnews.delivery-owner.v2', 'source': 'dev_session.start',
                                   'branch': task['branch'], 'thread_id': owner,
                                   'worktree': str(tmp_path), 'provider': 'claude'}))
    monkeypatch.setattr(success, 'receipt_path', lambda *args: receipt)
    Bridge.calls = []
    assert success.send(sqlite3.connect(':memory:'), task, '/repo', Bridge) == 'unowned'
    assert not Bridge.calls
