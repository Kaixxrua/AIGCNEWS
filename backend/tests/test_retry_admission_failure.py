import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
from retry_admission_failure import eligible


def test_recovery_is_atomic_and_only_once(tmp_path, monkeypatch):
    import json
    import sqlite3

    import pytest
    import retry_admission_failure as recovery
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('CREATE TABLE tasks(id INTEGER,sha TEXT,branch TEXT,status TEXT,error TEXT,updated_at TEXT);'
                     'CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);')
    db.execute("INSERT INTO tasks VALUES(1,'abc','session/test','failed','old','old')")
    db.commit()
    root = tmp_path / 'runs/1'
    root.mkdir(parents=True)
    (root / 'ci.json').write_text(json.dumps({'proof': 'retained'}))
    monkeypatch.setattr(recovery.delivery, 'git', lambda *args: 'abc')
    monkeypatch.setattr(recovery, 'eligible', lambda *args: True)
    config = {'integration_enabled': True, 'state': str(tmp_path)}
    recovery.retry(config, db, 1)
    assert db.execute('SELECT status FROM tasks').fetchone()[0] == 'queued'
    db.execute("UPDATE tasks SET status='failed'")
    db.commit()
    with pytest.raises(ValueError, match='already recorded'):
        recovery.retry(config, db, 1)
    assert db.execute('SELECT status FROM tasks').fetchone()[0] == 'failed'


def test_only_exact_clean_unstarted_failures_can_recover():
    sha = 'a' * 40
    checks = [{'id': name, 'sha': sha, 'cleanup': 'success', 'conclusion': 'success'}
              for name in ('backend-tests', 'postgres-integration', 'mcp-go', 'compose-smoke', 'frontend-build')]
    checks[0].update(conclusion='failure', error='TimeoutError: shared admission lock timed out; no automatic replay')
    proof = {'sha': sha, 'status': 'failure', 'checks': checks}
    assert eligible(proof, sha)
    assert not eligible(proof, 'b' * 40)
    checks[0]['steps'] = [{'name': 'test'}]
    assert not eligible(proof, sha)
    checks[0].pop('steps')
    checks[0]['cleanup'] = 'failure'
    assert not eligible(proof, sha)
