import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.tests import test_local_delivery as fixtures

setup = fixtures.setup
isolate_git_environment = fixtures.isolate_git_environment
attest = fixtures.attest

sys.path.insert(0, str(Path(__file__).parents[2]/'scripts/ci'))
import local_delivery as d
import local_integration as integration


def enqueue_second(c, db, base):
    repo = c['repository']
    def git(*args):
        return subprocess.check_output(['git', '-C', repo, *args], text=True).strip()
    git('checkout', '-b', 'session/second', base)
    Path(repo, 'second').write_text('independent')
    git('add', '.');git('commit', '-m', 'feat(ci): second')
    sha = git('rev-parse', 'HEAD')
    git('push', c['bare'], 'HEAD:refs/heads/session/second')
    db.execute("INSERT INTO tasks(branch,sha,status,created_at,updated_at,owner) VALUES(?,?,'queued',?,?,?)",
               ('session/second', sha, d.now(), d.now(), 'second-owner'))
    db.commit()
    return sha


def test_parallel_changes_are_validated_once_as_exact_combination(setup, monkeypatch):
    c, db, base, head = setup
    other = enqueue_second(c, db, base)
    calls = []
    def verify(*args):
        calls.append(args[2][args[2].index('--sha')+1]);attest(*args)
    monkeypatch.setattr(d, 'trusted_run', verify)
    assert integration.once(c, db)
    landed = d.git(c, 'rev-parse', 'main')
    assert calls == [landed]
    assert d.ancestor(c, head, landed) and d.ancestor(c, other, landed)
    assert [r[0] for r in db.execute('SELECT status FROM tasks')] == ['landed', 'landed']
    assert d.git(c, 'show', landed+':second') == 'independent'
    assert d.git(c, 'rev-parse', 'session/test-local-123') == head


def test_failed_batch_splits_without_infinite_regrouping(setup, monkeypatch):
    c, db, base, head = setup
    enqueue_second(c, db, base)
    def fail(*args):raise RuntimeError('assertion failed')
    monkeypatch.setattr(d, 'trusted_run', fail)
    assert integration.once(c, db)
    assert d.git(c, 'rev-parse', 'main') == base
    assert [r[0] for r in db.execute('SELECT status FROM tasks')] == ['queued', 'queued']
    assert integration.once(c, db)
    assert [r[0] for r in db.execute('SELECT status FROM tasks ORDER BY id')] == ['failed', 'queued']
    monkeypatch.setattr(d, 'trusted_run', attest)
    assert integration.once(c, db)
    assert [r[0] for r in db.execute('SELECT status FROM tasks ORDER BY id')] == ['failed', 'landed']


def test_recovers_crash_after_git_cas_before_sqlite_commit(setup, monkeypatch):
    c, db, base, head = setup
    monkeypatch.setattr(d, 'trusted_run', attest)
    original = integration.complete
    def crash(*args):raise RuntimeError('power loss before bookkeeping')
    monkeypatch.setattr(integration, 'complete', crash)
    with pytest.raises(RuntimeError, match='power loss'):
        integration.once(c, db)
    assert d.git(c, 'rev-parse', 'main') == head
    assert d.meta(db, 'integration')['phase'] == 'landing'
    monkeypatch.setattr(integration, 'complete', original)
    integration.recover(c, db)
    assert d.meta(db, 'validated_main')['sha'] == head
    assert db.execute('SELECT status FROM tasks').fetchone()[0] == 'landed'


def test_unattested_interrupted_batch_never_lands(setup, monkeypatch):
    c, db, base, head = setup
    task = dict(db.execute('SELECT * FROM tasks').fetchone())
    p = Path(c['state'])/'bad.json'
    p.write_text(json.dumps({'sha': head, 'status': 'success'}))
    d.meta(db, 'integration', {'phase': 'testing', 'sha': head, 'base': base,
                              'receipt': str(p), 'tasks': [task]})
    integration.recover(c, db)
    assert d.git(c, 'rev-parse', 'main') == base
    assert db.execute('SELECT status FROM tasks').fetchone()[0] == 'failed'
