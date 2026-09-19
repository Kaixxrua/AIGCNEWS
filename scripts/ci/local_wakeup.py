"""Exact-owner desktop fallback when no AO handoff exists; never replay uncertainty."""
from __future__ import annotations

import json
from pathlib import Path

from delivery_feedback import CodexBridge
from delivery_ownership import git, receipt_path, resolve_owner


def send(db, task, identity, message, repository, *, current, bridge_factory=CodexBridge):
    db.execute('CREATE TABLE IF NOT EXISTS desktop_wakeups (identity TEXT PRIMARY KEY, owner TEXT, status TEXT, turn_id TEXT)')
    db.commit()
    previous=db.execute('SELECT status,turn_id FROM desktop_wakeups WHERE identity=?',(identity,)).fetchone()
    if previous and previous[0] in ('dispatching', 'unconfirmed'):
        # Reconcile a positive exact marker; absence in a bounded response does
        # not prove non-delivery and must not cause duplicate automation turns.
        try:
            with bridge_factory() as bridge:
                thread = bridge.call('thread/read', {'threadId': task['owner'], 'includeTurns': True})['thread']
            marker = '[delivery:'+identity+']'
            for turn in thread.get('turns', []):
                if any(item.get('type') == 'userMessage' and marker in json.dumps(item.get('content', []))
                       for item in turn.get('items', [])):
                    turn_id = turn.get('id')
                    if isinstance(turn_id, str) and turn_id:
                        db.execute("UPDATE desktop_wakeups SET status='accepted',turn_id=? WHERE identity=?",
                                   (turn_id, identity))
                        db.commit()
                        return {'status': 'accepted', 'turn_id': turn_id, 'transport': 'codex'}
        except Exception:
            pass  # Keep uncertainty visible; no unsafe replay.
    if previous:
        return {'status':previous[0], 'turn_id':previous[1], 'transport':'codex'}
    if (Path.home()/'.config/aigcnews/ci-paused').exists():return {'status':'paused'}
    owner=task['owner']

    def eligible():
        if not current() or resolve_owner(task['branch'],repository)!=owner:return False
        record=json.loads(receipt_path(repository,task['branch']).read_text())
        workspace=record['worktree']
        return (git(workspace,'rev-parse','HEAD')==task['sha']
                and not git(workspace,'status','--porcelain')
                and not (Path.home()/'.config/aigcnews/ci-paused').exists())

    if not eligible():return {'status':'waiting_workspace'}
    with bridge_factory() as bridge:
        if not bridge.idle(owner):return {'status':'waiting'}
        if not eligible():return {'status':'obsolete'}
        record=json.loads(receipt_path(repository,task['branch']).read_text())
        prompt=(f"[delivery:{identity}] Exact task owner {owner}. "
                f"Original owned workspace {record['worktree']}, branch {task['branch']}. "
                "Preserve it; for already-landed code create a fresh owned session as instructed below.\n"+message)
        inserted=db.execute("INSERT OR IGNORE INTO desktop_wakeups VALUES(?,?,'dispatching',NULL)",(identity,owner))
        db.commit()
        if not inserted.rowcount:return {'status':'dispatching'}
        try:
            result=bridge.wake(owner,prompt)
            turn=result['turn']['id']
            if not isinstance(turn,str) or not turn:raise ValueError('missing turn receipt')
        except Exception:  # noqa: BLE001 - ambiguous transport must never replay
            db.execute("UPDATE desktop_wakeups SET status='unconfirmed' WHERE identity=?",(identity,));db.commit()
            return {'status':'unconfirmed','transport':'codex'}
        db.execute("UPDATE desktop_wakeups SET status='accepted',turn_id=? WHERE identity=?",(turn,identity));db.commit()
        return {'status':'accepted','turn_id':turn,'transport':'codex'}


def readiness(task, repository, ao, adb, *, desktop_enabled=False, bridge_factory=CodexBridge):
    """Read-only liveness probe. Busy exact owners can receive feedback when idle."""
    from datetime import UTC, datetime
    result={'ready':False,'sha':task['sha'],'owner':task['owner'],
            'checked_at':datetime.now(UTC).isoformat()}
    if not task['owner'] or resolve_owner(task['branch'],repository)!=task['owner']:
        return {**result,'reason':'owner_unverified'}
    if (Path.home()/'.config/aigcnews/ci-paused').exists():return {**result,'reason':'paused'}
    row=adb.execute('SELECT session,stage FROM tasks WHERE branch=?',(task['branch'],)).fetchone()
    if row:
        if row[1]!='active':return {**result,'reason':'ao_held'}
        info=ao.ao_read(row[0])['session']
        return {**result,'ready':info.get('id')==row[0] and not info.get('isTerminated'), 'transport':'ao'}
    if not desktop_enabled:return {**result,'reason':'unowned'}
    with bridge_factory() as bridge:
        thread=bridge.call('thread/read',{'threadId':task['owner'],'includeTurns':False})['thread']
        return {**result,'ready':thread.get('id')==task['owner'] and thread.get('status',{}).get('type') in ('idle','active'),
                'transport':'codex'}
