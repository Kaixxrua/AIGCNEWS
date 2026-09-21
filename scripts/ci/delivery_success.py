"""Exactly owned completion callbacks, starting one acknowledgement turn."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from delivery_feedback import CodexBridge
from delivery_ownership import receipt_path


def recipient(bridge, owner):
    """Follow only platform subagent ancestry, never ordinary fork relationships."""
    chain = []
    for _ in range(16):
        if owner in chain:
            raise ValueError('notification ancestry cycle')
        chain.append(owner)
        thread = bridge.call('thread/read', {'threadId': owner, 'includeTurns': False})['thread']
        if thread.get('id') != owner:
            raise ValueError('notification owner mismatch')
        if thread.get('threadSource') != 'subagent':
            if thread.get('canAcceptDirectInput') is False:
                raise ValueError('notification recipient cannot accept input')
            return thread, chain
        owner = thread.get('parentThreadId')
        if not owner:
            raise ValueError('subagent parent unavailable')
    raise ValueError('notification ancestry depth exceeded')


def reconcile(db, identity, owner, detail, bridge_factory):
    """Positive durable evidence can confirm a lost response; absence never permits replay."""
    record = json.loads(detail)
    target = record.get('recipient', owner)
    try:
        with bridge_factory() as bridge:
            thread = bridge.call('thread/read', {'threadId': target, 'includeTurns': False})['thread']
        if thread.get('id') != target or not thread.get('path'):
            return 'unconfirmed'
        path = Path(thread['path']).resolve()
        if not path.is_relative_to((Path.home() / '.codex/sessions').resolve()):
            return 'unconfirmed'
        turn_id = None
        with path.open() as stream:
            for line in stream:
                event = json.loads(line)
                payload = event.get('payload', {})
                if payload.get('type') == 'task_started':
                    turn_id = payload.get('turn_id')
                if (event.get('type') == 'response_item' and payload.get('type') == 'message'
                        and payload.get('role') == 'user' and turn_id
                        and any(c.get('text', '').startswith(f'[{identity}]\n')
                                for c in payload.get('content', []))):
                    record.update(turn_id=turn_id, reconciled=True)
                    db.execute('UPDATE success_notifications SET status=?, detail=? WHERE identity=?',
                               ('accepted', json.dumps(record), identity))
                    db.commit()
                    return 'accepted'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'unconfirmed'


def owner_matches(task, repository):
    # Creation receipt survives completed worktree GC. No title/branch guessing.
    try:
        value = json.loads(receipt_path(repository, task['branch']).read_text())
        return (value.get('schema') == 'aigcnews.delivery-owner.v1'
                and value.get('source') == 'dev_session.start'
                and value.get('branch') == task['branch']
                and value.get('thread_id') == task.get('owner') and bool(task.get('owner')))
    except (OSError, ValueError, KeyError):
        return False


def send(db, task, repository, bridge_factory=CodexBridge):
    db.execute('CREATE TABLE IF NOT EXISTS success_notifications ('
               'identity TEXT PRIMARY KEY, owner TEXT, status TEXT, detail TEXT)')
    db.commit()
    identity = f"delivered:{task['id']}:{task['sha']}"
    prior = db.execute('SELECT status,owner,detail FROM success_notifications WHERE identity=?', (identity,)).fetchone()
    if prior:
        if prior[0] in ('unconfirmed', 'dispatching'):
            return reconcile(db, identity, prior[1], prior[2], bridge_factory)
        return prior[0]
    if task.get('status') != 'delivered' or not owner_matches(task, repository):
        return 'unowned'
    text = (f"部署成功通知｜交付 #{task['id']}\n"
            f"本任务提交：{task['sha']}\n"
            f"已核验上线提交：{task.get('landing_sha') or task['sha']}（可能由包含该提交的后续版本承接）\n"
            f"任务完成时间：{task['updated_at']}\n"
            "本地交付控制器已确认源站与边缘发布成功。这是已完成交付的成功回调，不是新的开发指令。请仅用一句中文向用户确认该交付已上线，然后结束。不要运行工具、测试、修改代码、提交、推送或再次部署；不要重新跟进交付。")
    with bridge_factory() as bridge:
        try:
            thread, chain = recipient(bridge, task['owner'])
        except ValueError:
            return 'owner_mismatch'
        target = thread['id']
        if thread.get('status', {}).get('type') == 'notLoaded':
            resumed = bridge.call('thread/resume', {'threadId': target})['thread']
            if resumed.get('id') != target:
                return 'owner_mismatch'
            thread = resumed
        if thread.get('status', {}).get('type') != 'idle':
            return 'waiting_owner_idle'
        record = {'at': datetime.now(UTC).isoformat(), 'transport': 'turn/start',
                  'sha': task['sha'], 'starts_turn': True, 'recipient': target, 'owner_chain': chain}
        inserted = db.execute('INSERT OR IGNORE INTO success_notifications VALUES(?,?,?,?)',
                              (identity, task['owner'], 'dispatching', json.dumps(record)))
        db.commit()
        if not inserted.rowcount:
            return 'dispatching'
        try:
            response = bridge.call('turn/start', {'threadId': target, 'input': [
                {'type': 'text', 'text': f'[{identity}]\n{text}', 'text_elements': []}]})
            turn_id = response.get('turn', {}).get('id')
            if not turn_id:
                raise ValueError('missing acknowledgement turn ID')
            record['turn_id'] = turn_id
        except Exception as exc:  # noqa: BLE001 - unknown delivery must never cause blind replay
            record['error_type'] = type(exc).__name__
            record['error_stage'] = 'turn/start'
            db.execute('UPDATE success_notifications SET status=?, detail=? WHERE identity=?',
                       ('unconfirmed', json.dumps(record), identity))
            db.commit()
            return 'unconfirmed'
        db.execute('UPDATE success_notifications SET status=?, detail=? WHERE identity=?',
                   ('accepted', json.dumps(record), identity))
        db.commit()
        return 'accepted'
