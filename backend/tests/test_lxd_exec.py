"""Recorded exec preserves one command, authoritative exit status and owned logs."""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
from lxd_exec import recorded_exec

ID = '11111111-2222-3333-4444-555555555555'
OP = '/1.0/operations/' + ID
INSTANCE = '/1.0/instances/ci-owned'


def operation(result=0, status=200):
    return {'type': 'sync', 'metadata': {
        'id': ID, 'status_code': status, 'resources': {'instances': [INSTANCE]},
        'metadata': {'return': result, 'output': {
            '1': f'{INSTANCE}/logs/exec-output/exec_{ID}.stdout',
            '2': f'{INSTANCE}/logs/exec-output/exec_{ID}.stderr',
        }},
    }}


def fake_executor(states):
    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        if '-X' in argv:
            return json.dumps({'type': 'async', 'operation': OP}).encode()
        if argv[4] == OP:
            value = states.pop(0)
            if isinstance(value, Exception):
                raise value
            return json.dumps(value).encode()
        return b'test output\n' if argv[4].endswith('.stdout') else b'test stderr\n'

    return command, calls


def test_disconnect_reconnects_to_same_operation_without_replaying_tests(monkeypatch):
    monkeypatch.setattr('lxd_exec.time.sleep', lambda seconds: None)
    command, calls = fake_executor([RuntimeError('websocket: unexpected EOF'), operation(status=103), operation()])
    log = io.BytesIO()
    recorded_exec(command, 'ci-owned', ['env', '-i', 'bash', '-c', 'pytest'], log, 60)
    posts = [c for c in calls if '-X' in c]
    assert len(posts) == 1
    payload = json.loads(posts[0][-1])
    assert payload['wait-for-websocket'] is False
    assert payload['record-output'] is True
    assert payload['command'] == ['env', '-i', 'bash', '-c', 'pytest']
    assert b'test output' in log.getvalue() and b'test stderr' in log.getvalue()


@pytest.mark.parametrize('result', [1, 137, None, True, '0'])
def test_nonzero_or_missing_exit_code_is_never_success_or_replayed(result):
    command, calls = fake_executor([operation(result)])
    with pytest.raises(RuntimeError, match='command failed'):
        recorded_exec(command, 'ci-owned', ['pytest'], io.BytesIO(), 60)
    assert sum('-X' in c for c in calls) == 1


def test_lost_submission_response_is_not_retried():
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError('broken pipe')
    with pytest.raises(RuntimeError, match='broken pipe'):
        recorded_exec(command, 'ci-owned', ['pytest'], io.BytesIO(), 60)
    assert len(calls) == 1


@pytest.mark.parametrize('case', ['operation', 'instance', 'foreign_log', 'missing_output'])
def test_unverifiable_operation_or_output_fails_closed(case):
    state = operation()
    if case == 'operation':
        state['metadata']['id'] = 'another-operation'
    elif case == 'instance':
        state['metadata']['resources']['instances'] = ['/1.0/instances/foreign']
    elif case == 'foreign_log':
        state['metadata']['metadata']['output']['1'] = 'https://example.com/log'
    else:
        del state['metadata']['metadata']['output']
    command, calls = fake_executor([state])
    with pytest.raises(RuntimeError):
        recorded_exec(command, 'ci-owned', ['pytest'], io.BytesIO(), 60)
    assert len(calls) == 2


def test_poll_deadline_is_not_extended(monkeypatch):
    values = iter([0, 0, 61])
    monkeypatch.setattr('lxd_exec.time.monotonic', lambda: next(values))
    command, calls = fake_executor([])
    with pytest.raises(TimeoutError, match='deadline'):
        recorded_exec(command, 'ci-owned', ['pytest'], io.BytesIO(), 60)
    assert len(calls) == 1
