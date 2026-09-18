"""Exact landing failure notifications and observable AO execution receipts."""
import json


def failure(adapter, github, repository, pr):
    landing = pr['merge_commit_sha']
    if adapter.production_state(repository).get('active_release') == landing:
        return None
    if github.request('GET', '/git/ref/heads/main')['object']['sha'] != landing:
        return None  # A newer landing has its own owner; never blame every ancestor.
    runs = github.request('GET', '/actions/workflows/contract-baseline.yml/runs'
                          f'?event=push&head_sha={landing}&per_page=100').get('workflow_runs', [])
    runs = [r for r in runs if r.get('event') == 'push' and r.get('head_branch') == 'main'
            and r.get('head_sha') == landing and r.get('path') == '.github/workflows/contract-baseline.yml']
    latest = max(runs, key=lambda r: (r['id'], r.get('run_attempt', 1)), default=None)
    if not latest or latest.get('status') != 'completed' or latest.get('conclusion') != 'failure':
        return None
    return {'run_id': latest['id'], 'attempt': latest.get('run_attempt', 1),
            'landing': landing, 'url': latest['html_url']}


def notify(adapter, db, github, repository, pr, branch, session, path):
    if not adapter.merged_task(pr, branch, pr['head']['sha'], pr['number']):
        return 'unverified'
    evidence = failure(adapter, github, repository, pr)
    if evidence is None:
        return 'waiting'
    identity = f"{pr['number']}:{pr['head']['sha']}:main_ci_failure:{evidence['run_id']}:{evidence['attempt']}"
    message = (
        f"Post-merge main CI failed. Exact delivery owner: {session}, PR #{pr['number']}. "
        f"Evidence: {json.dumps(evidence)}. You own investigation, not necessarily the defective code. "
        "Read current failure logs and verify the latest main/run before acting. "
        "The user authorizes scoped repair and standard automatic delivery without another approval. "
        "Do not modify this already-merged worktree. Create a fresh branch-backed worktree with "
        "scripts/dev_session.py start, preserving your CODEX_THREAD_ID. Then run the installed "
        "ao_delivery_adapter.py recover --old-branch <this branch> --branch <new branch> "
        "--worktree <new worktree> --event <delivery identity> before editing. "
        "Fix only the verified cause, preserve other tasks and production behavior, run meaningful checks, "
        "commit and normal push; follow the standard PR/CI/merge/production pipeline. "
        "No force-push, blind rerun, weakened gates, direct merge or manual deployment. "
        "Report the exact blocker if safe repair is impossible."
    )
    def validate():
        current = github.request('GET', f"/pulls/{pr['number']}")
        return (adapter.merged_task(current, branch, pr['head']['sha'], pr['number'])
                and current.get('merge_commit_sha') == pr['merge_commit_sha']
                and failure(adapter, github, repository, current) == evidence)
    return adapter.send(db, branch, identity, message, repository,
                        expected_owner=(session, path, 'active'), validate=validate)


def receipts(adapter, db):
    """Execution means an observed completed command, not successful repair."""
    errors = []
    for branch, identity, status, raw in db.execute(
        "SELECT branch,identity,status,receipt FROM events WHERE status IN ('accepted','responded')"
    ).fetchall():
        receipt = json.loads(raw or '{}')
        session = receipt.get('ao_session')
        if not session:
            continue
        try:
            conversation = adapter.ao_read(session, '/conversation')
        except (OSError, ValueError) as exc:
            errors.append({'session': session, 'error': type(exc).__name__})
            continue
        marker = f'[delivery:{identity}]'
        messages = conversation.get('messages', [])
        trigger = next((m for m in messages if m.get('role') == 'user'
                        and m.get('origin') == 'automation' and marker in m.get('text', '')), None)
        if not trigger or not trigger.get('turnId'):
            continue
        turn = trigger['turnId']
        responses = [m for m in messages if m.get('turnId') == turn and m.get('role') == 'assistant']
        commands = [a for a in conversation.get('activities', []) if a.get('turnId') == turn
                    and a.get('activityKind') == 'command' and a.get('status') == 'completed'
                    and a.get('detail', {}).get('exitCode') == 0]
        new_status = 'executed' if commands else ('responded' if responses else status)
        receipt.update(turn_id=turn, trigger_message_id=trigger['id'],
                       response_ids=[m['id'] for m in responses], command_ids=[a['id'] for a in commands])
        db.execute('UPDATE events SET status=?,receipt=? WHERE branch=? AND identity=?',
                   (new_status, json.dumps(receipt), branch, identity))
    db.commit()
    return errors


def recover(adapter, db, github, repository, old_branch, branch, worktree, identity):
    import os
    from pathlib import Path

    delivery_ownership = adapter.peer("delivery_ownership")

    row = db.execute('SELECT session,worktree,stage,source,pr FROM tasks WHERE branch=?', (old_branch,)).fetchone()
    if not row or row[2] != 'active' or os.environ.get('AO_SESSION_ID') != row[0]:
        raise ValueError('recovery requires the exact active AO owner')
    event = db.execute('SELECT status,receipt FROM events WHERE branch=? AND identity=?',
                       (old_branch, identity)).fetchone()
    if not event or event[0] not in {'accepted', 'responded', 'executed'}:
        raise ValueError('verified recovery notification required')
    if json.loads(event[1]).get('ao_session') != row[0]:
        raise ValueError('event owner mismatch')
    pr = github.request('GET', f'/pulls/{row[4]}')
    evidence = failure(adapter, github, repository, pr)
    expected = (f"{pr['number']}:{pr['head']['sha']}:main_ci_failure:{evidence['run_id']}:{evidence['attempt']}"
                if evidence else None)
    if identity != expected or not adapter.merged_task(pr, old_branch, pr['head']['sha'], row[4]):
        raise ValueError('failure has changed or recovery was superseded')
    for path, ref in [(row[1], old_branch), (worktree, branch)]:
        adapter.verify_workspace(path, ref, repository)
        if adapter.git(path, 'status', '--porcelain'):
            raise ValueError('recovery worktrees must be clean')
    if branch == old_branch or adapter.git(worktree, 'rev-parse', 'HEAD') != evidence['landing']:
        raise ValueError('create a fresh worktree from the current failed main')
    if adapter.git(row[1], 'rev-parse', 'HEAD') != pr['head']['sha']:
        raise ValueError('original task changed')
    old_owner = delivery_ownership.resolve_owner(old_branch, repository)
    if not old_owner or delivery_ownership.resolve_owner(branch, repository) != old_owner:
        raise ValueError('creation-time task ownership mismatch')
    if (Path.home() / '.config/aigcnews/ci-paused').exists():
        raise ValueError('operator pause')
    # Retain the original delivery lineage; update only this exact owner binding.
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute('SELECT session,worktree,stage,source,pr FROM tasks WHERE branch=?', (old_branch,)).fetchone() != row:
            raise ValueError('ownership changed during recovery')
        db.execute('INSERT INTO recovery_lineage(old_branch,new_branch,event,binding) VALUES(?,?,?,?)',
                   (old_branch, branch, identity, json.dumps(row)))
        db.execute('UPDATE tasks SET branch=?,worktree=?,pr=NULL,source=source || ? WHERE branch=?',
                   (branch, str(Path(worktree).resolve()), f' ; recovery {identity} from {old_branch}', old_branch))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'session': row[0], 'branch': branch, 'status': 'recovery_bound'}
