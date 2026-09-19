"""Single-writer fixed integration batches, with recoverable Git/SQLite landing."""
from __future__ import annotations

import json
import time
from pathlib import Path

import local_delivery as d

CHECKS = {'backend-tests', 'postgres-integration', 'mcp-go', 'compose-smoke', 'frontend-build'}


def attested(receipt, sha):
    try:
        proof = json.loads(Path(receipt).read_text())
        checks = proof.get('checks', [])
        return (not proof.get('preflight') and proof.get('sha') == sha
                and proof.get('status') == proof.get('cleanup') == 'success'
                and len(checks) == len(CHECKS) and {c.get('id') for c in checks} == CHECKS
                and all(c.get('sha') == sha and c.get('conclusion') == 'success' for c in checks))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def record(db, key, value):
    # Caller owns the transaction: landing rows and validated_main commit together.
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, json.dumps(value)))


def complete(db, batch):
    with db:
        for task in batch['tasks']:
            db.execute("UPDATE tasks SET status='landed',landing_sha=?,updated_at=?,error=NULL WHERE id=?",
                       (batch['sha'], d.now(), task['id']))
        record(db, 'validated_main', {'sha': batch['sha'], 'receipt': batch['receipt'], 'at': d.now()})
        record(db, 'integration', {**batch, 'phase': 'landed'})


def recover(config, db):
    batch = d.meta(db, 'integration')
    if batch.get('phase') not in ('testing', 'landing'):
        # Claimed rows can survive a crash while constructing the combination.
        db.execute("UPDATE tasks SET status='queued' WHERE status='claimed'")
        db.commit()
        return
    main = d.git(config, 'rev-parse', 'refs/heads/main')
    if attested(batch['receipt'], batch['sha']):
        with d.lock(config, 'landing', wait=True):
            main = d.git(config, 'rev-parse', 'refs/heads/main')
            if main == batch['sha']:
                complete(db, batch)
                return
            if main == batch['base'] and all(
                    d.git(config, 'rev-parse', 'refs/heads/'+t['branch']) == t['sha'] for t in batch['tasks']):
                d.git(config, 'update-ref', 'refs/heads/main', batch['sha'], main)
                complete(db, batch)
                return
    # No evidence of a successful integration: never invent a completed landing.
    for task in batch['tasks']:
        d.update(db, task, 'failed', error='integration interrupted; exact successful receipt unavailable')
    d.meta(db, 'integration', {**batch, 'phase': 'failed'})


def select(config, db):
    limit = config.get('integration_batch_size', 4)
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError('integration_batch_size must be 1..8')
    db.execute('BEGIN IMMEDIATE')
    try:
        rows = [dict(r) for r in db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY id LIMIT ?", (limit,))]
        # A failed batch is diagnosed one member at a time, never regrouped forever.
        single = set(d.meta(db, 'integration_single').get('ids', []))
        if rows and any(t['id'] in single for t in rows):
            rows = rows[:1]
        for task in rows:
            db.execute("UPDATE tasks SET status='claimed',updated_at=? WHERE id=?", (d.now(), task['id']))
        db.commit()
        return rows
    except BaseException:
        db.rollback()
        raise


def combine(config, current, task):
    if d.ancestor(config, current, task['sha']):
        return task['sha']
    if d.ancestor(config, task['sha'], current):
        return current
    # merge-tree works in the bare object database, never edits an agent worktree.
    tree = d.git(config, 'merge-tree', '--write-tree', current, task['sha']).splitlines()[0]
    if not d.SHA.fullmatch(tree):
        raise RuntimeError('integration did not return a tree')
    return d.git(config, '-c', 'user.name=AIGCNEWS Integration', '-c',
                 'user.email=integration@localhost', 'commit-tree', tree,
                 '-p', current, '-p', task['sha'], '-m',
                 'chore(integration): combine verified queue inputs')


def once(config, db):
    recover(config, db)
    selected = select(config, db)
    if not selected:
        return False
    base = candidate = d.git(config, 'rev-parse', 'refs/heads/main')
    tasks = []
    for task in selected:
        if d.git(config, 'rev-parse', 'refs/heads/'+task['branch']) != task['sha']:
            d.update(db, task, 'superseded', error='newer commit submitted')
            continue
        try:
            candidate = combine(config, candidate, task)
        except RuntimeError:
            d.update(db, task, 'needs_update', error='integration conflict; resolve against current main', base_sha=base)
            continue
        tasks.append(task)
    if not tasks:
        return True
    identity = str(time.time_ns())
    root = Path(config['state'])/'integrations'/identity
    root.mkdir(parents=True)
    batch = {'id': identity, 'base': base, 'sha': candidate, 'tasks': tasks,
             'receipt': str(root/'ci.json'), 'phase': 'testing'}
    d.git(config, 'update-ref', 'refs/integrations/'+identity, candidate)
    d.meta(db, 'integration', batch)
    for task in tasks:
        d.update(db, task, 'testing', base_sha=base, ci_receipt=batch['receipt'], error=None)
        d.meta(db, f"integration_task:{task['id']}", {'sha': candidate, 'batch': identity})
    d.snapshot(config, db)
    try:
        d.trusted_run(config, 'local_ci.py', ['--repository', config['bare'], '--sha', candidate,
                      '--output', batch['receipt'], '--config', config['config_path']], root/'ci.log', 7200)
        if not attested(batch['receipt'], candidate):
            raise RuntimeError('CI receipt does not attest exact integrated SHA')
    except Exception as exc:
        d.meta(db, 'integration', {**batch, 'phase': 'failed'})
        if len(tasks) > 1:
            singles = set(d.meta(db, 'integration_single').get('ids', []))
            d.meta(db, 'integration_single', {'ids': sorted(singles | {t['id'] for t in tasks})})
        for task in tasks:
            d.update(db, task, 'queued' if len(tasks) > 1 else 'failed', error='CI validation failed: '+str(exc))
        return True
    with d.lock(config, 'landing', wait=True):
        current = d.git(config, 'rev-parse', 'refs/heads/main')
        unchanged = all(d.git(config, 'rev-parse', 'refs/heads/'+t['branch']) == t['sha'] for t in tasks)
        if current != base or not unchanged:
            d.meta(db, 'integration', {**batch, 'phase': 'superseded'})
            for task in tasks:
                d.update(db, task, 'queued', error='integration input changed before landing')
            return True
        d.meta(db, 'integration', {**batch, 'phase': 'landing'})
        d.git(config, 'update-ref', 'refs/heads/main', candidate, base)
        complete(db, batch)
    return True
