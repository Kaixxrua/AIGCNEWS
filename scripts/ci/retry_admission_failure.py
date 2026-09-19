"""One audited recovery of an exact pre-launch lock failure into integration CI."""
import argparse
import json
from pathlib import Path

import local_delivery as delivery


def eligible(proof, sha):
    checks = proof.get('checks', [])
    failed = [c for c in checks if c.get('conclusion') != 'success']
    return (proof.get('sha') == sha and proof.get('status') == 'failure'
            and {c.get('id') for c in checks} == {
                'backend-tests', 'postgres-integration', 'mcp-go', 'compose-smoke', 'frontend-build'}
            and len(checks) == 5 and bool(failed)
            and all(c.get('sha') == sha and c.get('cleanup') == 'success' for c in checks)
            and all(c.get('conclusion') == 'failure' and not c.get('steps')
                    and c.get('error') == 'TimeoutError: shared admission lock timed out; no automatic replay'
                    for c in failed))


def retry(config, db, task_id):
    if not config.get('integration_enabled'):
        raise ValueError('recovery requires current-main integration CI')
    task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not task or task['status'] != 'failed':
        raise ValueError('task is not failed')
    sha = task['sha']
    if delivery.git(config, 'rev-parse', 'refs/heads/' + task['branch']) != sha:
        raise ValueError('task superseded by newer branch head')
    path = Path(config['state']) / 'runs' / str(task_id) / 'ci.json'
    proof = json.loads(path.read_text())
    if not eligible(proof, sha):
        raise ValueError('not a proven clean pre-launch admission failure')
    key = f'admission_recovery:{task_id}:{sha}'
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute('SELECT 1 FROM tasks WHERE branch=? AND id>?', (task['branch'], task_id)).fetchone():
            raise ValueError('newer task already exists')
        if db.execute('SELECT 1 FROM metadata WHERE key=?', (key,)).fetchone():
            raise ValueError('one-time recovery already recorded')
        changed = db.execute("UPDATE tasks SET status='queued',error=NULL,updated_at=? "
                             "WHERE id=? AND sha=? AND status='failed'",
                             (delivery.now(), task_id, sha)).rowcount
        if changed != 1:
            raise ValueError('task changed during recovery')
        db.execute('INSERT INTO metadata(key,value) VALUES(?,?)',
                   (key, json.dumps({'sha': sha, 'at': delivery.now(), 'prior_receipt': proof,
                                     'reason': 'verified pre-launch lock timeout; integrate against current main'})))
        db.commit()
    except BaseException:
        db.rollback()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--task', type=int, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    db = delivery.database(config)
    try:
        retry(config, db, args.task)
    finally:
        db.close()
    print(json.dumps({'task': args.task, 'status': 'queued', 'recovery': 'one-time-admission'}))
