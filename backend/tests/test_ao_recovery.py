import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

CI = Path(__file__).parents[2] / 'scripts/ci'
sys.path.insert(0, str(CI))
import ao_recovery as recovery

spec = importlib.util.spec_from_file_location('recovery_adapter', CI / 'ao_delivery_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.fixture
def case(tmp_path):
    landing = 'a' * 40
    pr = {'number': 71, 'merge_commit_sha': landing, 'head': {'sha': 'b' * 40}}
    run = {'id': 123, 'run_attempt': 1, 'event': 'push', 'head_branch': 'main',
           'head_sha': landing, 'path': '.github/workflows/contract-baseline.yml',
           'status': 'completed', 'conclusion': 'failure', 'html_url': 'https://github.com/run/123'}
    client = Mock()
    client.request.side_effect = lambda method, path: ({'object': {'sha': landing}}
        if path == '/git/ref/heads/main' else {'workflow_runs': [run]})
    a = SimpleNamespace(production_state=lambda _: {'active_release': 'c' * 40},
                        merged_task=lambda *args: True, send=Mock(return_value='accepted'))
    return a, client, pr, run


@pytest.mark.parametrize('field,value', [('event', 'pull_request'), ('head_branch', 'other'),
    ('head_sha', 'stale'), ('path', '.github/workflows/other.yml'),
    ('status', 'in_progress'), ('conclusion', 'success')])
def test_only_exact_completed_main_baseline_failure(case, field, value):
    a, client, pr, run = case
    run[field] = value
    assert recovery.failure(a, client, '.', pr) is None


def test_new_main_or_already_active_never_wakes_old_owner(case):
    a, client, pr, _ = case
    client.request.return_value = {'object': {'sha': 'new'}}
    client.request.side_effect = None
    assert recovery.failure(a, client, '.', pr) is None
    a.production_state = lambda _: {'active_release': pr['merge_commit_sha']}
    client.request.reset_mock()
    assert recovery.failure(a, client, '.', pr) is None
    client.request.assert_not_called()


def test_newer_retry_wins_over_failed_attempt(case):
    a, client, pr, run = case
    success = {**run, 'run_attempt': 2, 'conclusion': 'success'}
    client.request.side_effect = [{'object': {'sha': pr['merge_commit_sha']}}, {'workflow_runs': [success, run]}]
    assert recovery.failure(a, client, '.', pr) is None


def test_notification_exact_owner_and_fresh_repair_instructions(case):
    a, client, pr, _ = case
    assert recovery.notify(a, None, client, '.', pr, 'session/old', 'owner', '/old') == 'accepted'
    args, kw = a.send.call_args
    assert args[2] == '71:' + 'b' * 40 + ':main_ci_failure:123:1'
    assert 'fresh branch-backed worktree' in args[3]
    assert kw['expected_owner'] == ('owner', '/old', 'active')


def test_receipt_requires_same_automation_turn_successful_command(tmp_path):
    with adapter.database(tmp_path / 'state.sqlite') as db:
        db.execute('INSERT INTO events(branch,identity,status,receipt) VALUES(?,?,?,?)',
                   ('session/old', 'id', 'accepted', json.dumps({'ao_session': 'owner'})))
        messages = [{'id': 'u', 'role': 'user', 'origin': 'automation',
                     'text': '[delivery:id] fix', 'turnId': 'exact'}]
        activities = [{'id': 'c', 'turnId': 'wrong', 'activityKind': 'command',
                       'status': 'completed', 'detail': {'exitCode': 0}}]
        a = SimpleNamespace(ao_read=Mock(return_value={'messages': messages, 'activities': activities}))
        recovery.receipts(a, db)
        assert db.execute('SELECT status FROM events').fetchone()[0] == 'accepted'
        messages.append({'id': 'a', 'role': 'assistant', 'turnId': 'exact'})
        recovery.receipts(a, db)
        assert db.execute('SELECT status FROM events').fetchone()[0] == 'responded'
        activities[0]['turnId'] = 'exact'
        activities[0]['detail']['exitCode'] = 1
        recovery.receipts(a, db)
        assert db.execute('SELECT status FROM events').fetchone()[0] == 'responded'
        activities[0]['detail']['exitCode'] = 0
        recovery.receipts(a, db)
        status, raw = db.execute('SELECT status,receipt FROM events').fetchone()
        assert status == 'executed'
        assert json.loads(raw)['turn_id'] == 'exact'
        assert json.loads(raw)['command_ids'] == ['c']
        a.ao_read.assert_called_with('owner', '/conversation')


@pytest.fixture
def bound_recovery(tmp_path, monkeypatch, case):
    a, client, pr, run = case
    pr.update(state='closed', merged_at='now')
    monkeypatch.setenv('AO_SESSION_ID', 'owner')
    old = str(tmp_path / 'old')
    new = str(tmp_path / 'new')
    event = '71:' + 'b' * 40 + ':main_ci_failure:123:1'
    a.verify_workspace = Mock()
    a.git = lambda path, *args: (('b' * 40 if path == old else 'a' * 40) if args[0] == 'rev-parse' else '')
    a.peer = Mock(return_value=SimpleNamespace(resolve_owner=lambda *args: 'same-owner'))
    original = client.request.side_effect
    client.request.side_effect = lambda method, path: pr if path == '/pulls/71' else original(method, path)
    monkeypatch.setattr(recovery, 'failure', lambda *args: {'run_id': 123, 'attempt': 1, 'landing': 'a' * 40})
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    with adapter.database(tmp_path / 'state.sqlite') as db:
        db.execute('INSERT INTO tasks(branch,session,worktree,source,stage,pr) VALUES(?,?,?,?,?,?)',
                   ('session/old', 'owner', old, 'original receipt', 'active', 71))
        db.execute('INSERT INTO events(branch,identity,status,receipt) VALUES(?,?,?,?)',
                   ('session/old', event, 'accepted', json.dumps({'ao_session': 'owner'})))
        db.commit()
        yield a, db, client, tmp_path, old, new, event


def invoke_recovery(d):
    a, db, client, root, old, new, event = d
    return recovery.recover(a, db, client, root, 'session/old', 'session/new', new, event)


def test_same_owner_recovery_archives_original_lineage(bound_recovery):
    d = bound_recovery
    assert invoke_recovery(d)['status'] == 'recovery_bound'
    db = d[1]
    assert db.execute('SELECT branch,session,pr FROM tasks').fetchone() == ('session/new', 'owner', None)
    assert db.execute('SELECT old_branch,new_branch FROM recovery_lineage').fetchone() == ('session/old', 'session/new')
    assert db.execute('SELECT branch FROM events').fetchone()[0] == 'session/old'
    with pytest.raises(ValueError):
        invoke_recovery(d)


@pytest.mark.parametrize('reason', ['wrong_session', 'wrong_event_owner', 'dirty', 'wrong_head', 'wrong_creation_owner', 'stale', 'paused'])
def test_recovery_refuses_changed_or_unowned_state(bound_recovery, monkeypatch, reason):
    d = bound_recovery
    a, db, _, root, old, _, _ = d
    if reason == 'wrong_session': monkeypatch.setenv('AO_SESSION_ID', 'other')
    if reason == 'wrong_event_owner':
        db.execute('UPDATE events SET receipt=?', (json.dumps({'ao_session': 'other'}),)); db.commit()
    if reason == 'dirty': a.git = lambda *args: ' M file'
    if reason == 'wrong_head': a.git = lambda _, *args: 'wrong' if args[0] == 'rev-parse' else ''
    if reason == 'wrong_creation_owner':
        a.peer.return_value.resolve_owner = lambda branch, repo: branch
    if reason == 'stale': monkeypatch.setattr(recovery, 'failure', lambda *args: None)
    if reason == 'paused':
        marker = root / '.config/aigcnews/ci-paused'; marker.parent.mkdir(parents=True); marker.touch()
    with pytest.raises(ValueError): invoke_recovery(d)
    assert db.execute('SELECT branch FROM tasks').fetchone()[0] == 'session/old'
    assert db.execute('SELECT COUNT(*) FROM recovery_lineage').fetchone()[0] == 0


def test_unavailable_session_does_not_block_other_receipts(tmp_path):
    with adapter.database(tmp_path / 'state.sqlite') as db:
        for session in ('broken', 'healthy'):
            db.execute('INSERT INTO events(branch,identity,status,receipt) VALUES(?,?,?,?)',
                       (session, session, 'accepted', json.dumps({'ao_session': session})))
        def read(session, resource):
            if session == 'broken': raise OSError('offline')
            return {'messages': [
                {'id': 'u', 'turnId': 't', 'role': 'user', 'origin': 'automation', 'text': '[delivery:healthy]'},
                {'id': 'a', 'turnId': 't', 'role': 'assistant'}]}
        errors = recovery.receipts(SimpleNamespace(ao_read=read), db)
        assert errors == [{'session': 'broken', 'error': 'OSError'}]
        assert dict(db.execute('SELECT branch,status FROM events')) == {'broken': 'accepted', 'healthy': 'responded'}
