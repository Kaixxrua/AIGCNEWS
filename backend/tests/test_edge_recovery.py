import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
import edge_recovery as e
from local_delivery import meta


@pytest.fixture
def setup(tmp_path, monkeypatch):
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
    config = {'production': str(tmp_path), 'state': str(tmp_path)}
    control = tmp_path / '.aigcnews-deploy'
    control.mkdir()
    (control / 'state.json').write_text(json.dumps({'active_release': 'a' * 40}))
    release = {'sha': 'a' * 40, 'status': 'failed', 'attempt': 3, 'finished_at': 'fixed'}
    meta(db, 'release', release)
    meta(db, 'validated_main', {'sha': 'a' * 40})
    monkeypatch.setattr(e, 'read', lambda *args: {'stage': 'edge'})
    monkeypatch.setattr(e, 'retryable', lambda *args: True)
    return config, db, release


def test_two_spaced_successes_resume_same_version(setup):
    c, db, r = setup
    calls = []
    def check(_):
        calls.append('probe')
    assert not e.consider(c, db, r, check=check, clock=lambda: 100)
    assert not e.consider(c, db, r, check=check, clock=lambda: 110)
    assert e.consider(c, db, r, check=check, clock=lambda: 161)
    assert len(calls) == 2
    assert meta(db, 'release')['sha'] == r['sha']
    assert meta(db, 'release')['status'] == 'retrying'
    assert meta(db, 'release')['recovery_stage'] == 'edge'


def test_failed_probe_waits_and_does_not_publish(setup):
    c, db, r = setup
    def fail(_): raise TimeoutError('private detail')
    assert not e.consider(c, db, r, check=fail, clock=lambda: 100)
    recovery = meta(db, 'edge_recovery:' + r['sha'])
    assert recovery['status'] == 'waiting_external'
    assert recovery['next_probe_at'] == 400
    assert 'private detail' not in json.dumps(recovery)
    assert meta(db, 'release')['status'] == 'failed'


@pytest.mark.parametrize('condition', ['wrong_origin', 'new_candidate', 'deploy_failure', 'permanent'])
def test_unsafe_recovery_never_probes(setup, monkeypatch, condition):
    c, db, r = setup
    if condition == 'wrong_origin':
        (Path(c['production'])/'.aigcnews-deploy/state.json').write_text('{}')
    elif condition == 'new_candidate': meta(db, 'validated_main', {'sha':'b'*40})
    elif condition == 'deploy_failure': monkeypatch.setattr(e, 'read', lambda *a: {'stage':'deploy'})
    else: monkeypatch.setattr(e, 'retryable', lambda *a: False)
    def check(_): pytest.fail('unsafe probe')
    assert not e.consider(c, db, r, check=check)


def test_changed_candidate_during_probe_never_resumed(setup):
    c, db, r = setup
    def check(_): meta(db, 'validated_main', {'sha':'b'*40})
    assert not e.consider(c, db, r, check=check)
    assert meta(db,'release')['status']=='failed'


def test_recovery_budget_does_not_reset_on_new_failure_timestamp(setup):
    c, db, r = setup
    meta(db, 'edge_recovery:' + r['sha'], {'retries':2})
    def check(_): pytest.fail('budget exhausted')
    assert not e.consider(c, db, {**r,'finished_at':'new'}, check=check)
    assert meta(db, 'edge_recovery:' + r['sha'])['status']=='needs_repair'
