"""Exactly owned completion callbacks, starting one acknowledgement turn."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from delivery_feedback import CodexBridge
from delivery_ownership import receipt_path


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
    prior = db.execute('SELECT status FROM success_notifications WHERE identity=?', (identity,)).fetchone()
    if prior:
        return prior[0]
    if task.get('status') != 'delivered' or not owner_matches(task, repository):
        return 'unowned'
    text = (f"部署成功通知｜交付 #{task['id']}\n"
            f"本任务提交：{task['sha']}\n"
            f"已核验上线提交：{task.get('landing_sha') or task['sha']}（可能由包含该提交的后续版本承接）\n"
            f"任务完成时间：{task['updated_at']}\n"
            "本地交付控制器已确认源站与边缘发布成功。这是已完成交付的成功回调，不是新的开发指令。请仅用一句中文向用户确认该交付已上线，然后结束。不要运行工具、测试、修改代码、提交、推送或再次部署；不要重新跟进交付。")
    with bridge_factory() as bridge:
        thread = bridge.call('thread/read', {'threadId': task['owner'], 'includeTurns': False})['thread']
        if thread.get('id') != task['owner']:
            return 'owner_mismatch'
        if thread.get('status', {}).get('type') == 'notLoaded':
            resumed = bridge.call('thread/resume', {'threadId': task['owner']})['thread']
            if resumed.get('id') != task['owner']:
                return 'owner_mismatch'
            thread = resumed
        if thread.get('status', {}).get('type') != 'idle':
            return 'waiting_owner_idle'
        record = {'at': datetime.now(UTC).isoformat(), 'transport': 'turn/start',
                  'sha': task['sha'], 'starts_turn': True}
        inserted = db.execute('INSERT OR IGNORE INTO success_notifications VALUES(?,?,?,?)',
                              (identity, task['owner'], 'dispatching', json.dumps(record)))
        db.commit()
        if not inserted.rowcount:
            return 'dispatching'
        try:
            response = bridge.call('turn/start', {'threadId': task['owner'], 'input': [
                {'type': 'text', 'text': f'[{identity}]\n{text}', 'text_elements': []}]})
            turn_id = response.get('turn', {}).get('id')
            if not turn_id:
                raise ValueError('missing acknowledgement turn ID')
            record['turn_id'] = turn_id
        except Exception:  # noqa: BLE001 - unknown delivery must never cause blind replay
            db.execute('UPDATE success_notifications SET status=? WHERE identity=?', ('unconfirmed', identity))
            db.commit()
            return 'unconfirmed'
        db.execute('UPDATE success_notifications SET status=?, detail=? WHERE identity=?',
                   ('accepted', json.dumps(record), identity))
        db.commit()
        return 'accepted'
