#!/usr/bin/env python3
"""Host-local delivery authority. Candidate code never chooses its gate commands.

origin is a local bare repository after cutover; github is only a mirror.
CI, landing and release each have independent durable receipts and process locks.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

SHA = re.compile(r'[0-9a-f]{40}')
BRANCH = re.compile(r'session/[a-z0-9][a-z0-9-]{1,127}')
DEFAULT = Path.home() / '.config/aigcnews/local-delivery.json'


def now():
    return datetime.now(UTC).isoformat()


def command(args, *, timeout=60, **kwargs):
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_TERMINAL_PROMPT'] = '0'
    result = subprocess.run(list(map(str,args)), env=env, text=True, capture_output=True,
                            timeout=timeout, check=False, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr[-1500:]}')
    return result.stdout.strip()


def git(config, *args):
    return command(['git','--git-dir',config['bare'],*args])


def ancestor(config, old, new):
    if not SHA.fullmatch(old or '') or not SHA.fullmatch(new or ''):
        return False
    p=subprocess.run(['git','--git-dir',config['bare'],'merge-base','--is-ancestor',old,new],capture_output=True,check=False)
    if p.returncode not in (0,1):
        raise RuntimeError('commit ancestry unavailable')
    return p.returncode==0


def atomic(path, data):
    """Unique same-directory temporary, safe across threads and processes."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd, temporary=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


@contextlib.contextmanager
def lock(config, name, *, wait=False):
    root=Path(config['state']);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/(name+'.lock')).open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        yield


def database(config):
    root=Path(config['state']);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    db=sqlite3.connect(root/'queue.sqlite',timeout=10)
    db.row_factory=sqlite3.Row
    db.executescript('''
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY, branch TEXT NOT NULL, sha TEXT NOT NULL,
        base_sha TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, owner TEXT, title TEXT, pr INTEGER,
        ci_receipt TEXT, error TEXT, landing_sha TEXT,
        UNIQUE(branch,sha));
      CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT);
    ''')
    return db


def meta(db,key,value=None):
    if value is not None:
        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(key,json.dumps(value)))
        db.commit()
    row=db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else {}


def update(db, task, status, **fields):
    fields.update(status=status,updated_at=now())
    db.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),task['id']))
    db.commit()


def submit(config, db, branch, sha, pr=None):
    if not SHA.fullmatch(sha) or not (BRANCH.fullmatch(branch) or branch=='main'):
        raise ValueError('invalid delivery identity')
    if git(config,'rev-parse',f'refs/heads/{branch}')!=sha:
        raise ValueError('ref moved before enqueue')
    owner=None
    if branch!='main':
        common=command(['git','-C',config['repository'],'rev-parse','--path-format=absolute','--git-common-dir'])
        receipt=Path(common)/'delivery-owners'/(hashlib.sha256(branch.encode()).hexdigest()+'.json')
        record=json.loads(receipt.read_text())
        if record.get('branch')!=branch or record.get('source')!='dev_session.start':
            raise ValueError('creation-time task ownership missing')
        owner=record['thread_id']
    stamp=now()
    db.execute('INSERT OR IGNORE INTO tasks(branch,sha,status,created_at,updated_at,owner,title,pr) VALUES(?,?,?,?,?,?,?,?)',
               (branch,sha,'queued',stamp,stamp,owner,git(config,'show','-s','--format=%s',sha),pr))
    db.commit()


def failure_stage(task):
    if task['status']=='needs_update':return '合并基线'
    error=task.get('error') or ''
    if task['status']=='failed' and error.startswith((
            'CI validation failed:', 'local_ci.py failed;',
            'CI receipt does not attest exact successful SHA')):
        return 'CI 验证'
    return None


def snapshot_tasks(db):
    tasks=[dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY id')]
    previous={}
    for task in tasks:
        task['handoff']=meta(db,f"handoff:{task['id']}")
        task['notification']=meta(db,f"notification:{task['id']}") or {'status':'not_attempted','accepted':False}
        # Null ownership is unknown, not proof that two tasks share an owner.
        if not task.get('owner'):continue
        key=(task['branch'],task['owner'])
        prior=previous.get(key)
        if prior is not None and (stage:=failure_stage(prior)):
            task['retry_of']={'id':prior['id'],'sha':prior['sha'],'failure_stage':stage}
        # Only the immediately preceding delivery for this owner/branch can be
        # linked. Never leap over an unknown failure or successful delivery.
        previous[key]=task
    return tasks


def snapshot(config,db):
    # Serialize reads as well as replacement so an older worker snapshot cannot
    # overwrite a newer one after waiting for the publication lock.
    with lock(config,'snapshot',wait=True):
        production=json.loads((Path(config['production'])/'.aigcnews-deploy/state.json').read_text())
        data={'schema':'aigcnews.local-delivery.v1','mode':'local' if config.get('enabled') else 'staged','generated_at':now(),
              'main_sha':git(config,'rev-parse','refs/heads/main'),
              'active_release':production.get('active_release'),'production_in_progress':production.get('in_progress'),
              'tasks':snapshot_tasks(db),
              'release':meta(db,'release'),'mirror':meta(db,'mirror')}
        atomic(Path(config['state'])/'status.json',data)
        return data


def trusted_run(config, script, args, logfile, timeout):
    with Path(logfile).open('a') as log:
        process=subprocess.run([sys.executable,str(Path(config['runtime'])/script),*map(str,args)],
                               stdout=log,stderr=subprocess.STDOUT,timeout=timeout,check=False)
    if process.returncode:
        raise RuntimeError(f'{script} failed; see {logfile}')


def discover(config,db):
    refs = dict(line.split(' ',1) for line in git(config,'for-each-ref','--format=%(refname:short) %(objectname)','refs/heads/session/').splitlines())
    observed = meta(db,'observed_refs')
    for branch,sha in refs.items():
        if observed.get(branch)==sha:continue
        submit(config,db,branch,sha)
        observed[branch]=sha
    meta(db,'observed_refs',observed)


def claim(db):
    """Commit ownership before dispatch; no Git/network calls in the transaction."""
    db.execute('BEGIN IMMEDIATE')
    try:
        task=db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if task is not None:
            changed=db.execute("UPDATE tasks SET status='claimed',updated_at=? WHERE id=? AND status='queued'",
                               (now(),task['id'])).rowcount
            if changed != 1:raise RuntimeError('queue claim lost')
            task=db.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone()
        db.commit()
        return task
    except BaseException:
        db.rollback()
        raise


def ci_once(config,db):
    task=claim(db)
    if task is None:return False
    run_claimed(config,db,task)
    return True


def run_claimed(config,db,task):
    try:
        return validate_and_land(config,db,task)
    except Exception as exc:  # noqa: BLE001 - persist infrastructure errors, never requeue
        update(db,task,'failed',error=str(exc))
        return True


def validate_and_land(config,db,task):
    main=git(config,'rev-parse','refs/heads/main')
    if git(config,'rev-parse','refs/heads/'+task['branch'])!=task['sha']:
        update(db,task,'superseded',error='newer commit submitted');return True
    if task['branch']!='main' and ancestor(config,task['sha'],main):
        update(db,task,'landed',landing_sha=task['sha']);return True
    if not ancestor(config,main,task['sha']):
        update(db,task,'needs_update',base_sha=main,error='Merge local origin/main, resolve conflicts and push a new SHA before CI')
        return True
    root=Path(config['state'])/'runs'/str(task['id']);root.mkdir(parents=True,exist_ok=True)
    receipt=root/'ci.json'
    update(db,task,'testing',base_sha=main,ci_receipt=str(receipt),error=None);snapshot(config,db)
    phase='CI'
    try:
        trusted_run(config,'local_ci.py',['--repository',config['bare'],'--sha',task['sha'],
                    '--output',receipt,'--config',config['config_path']],root/'ci.log',7200)
        proof=json.loads(receipt.read_text())
        expected={'backend-tests','postgres-integration','mcp-go','compose-smoke','frontend-build'}
        checks=proof.get('checks',[])
        if (proof.get('sha')!=task['sha'] or proof.get('status')!='success' or proof.get('cleanup')!='success'
                or {c.get('id') for c in checks}!=expected or len(checks)!=len(expected)
                or any(c.get('sha')!=task['sha'] or c.get('conclusion')!='success' for c in checks)):
            raise RuntimeError('CI receipt does not attest exact successful SHA')
        phase='landing'
        with lock(config,'landing',wait=True):
            latest=git(config,'rev-parse','refs/heads/main')
            head=git(config,'rev-parse','refs/heads/'+task['branch'])
            if head!=task['sha']:
                update(db,task,'superseded',error='head changed during CI');return True
            if latest!=main:
                update(db,task,'needs_update',error='main changed during CI; merge current local main and revalidate');return True
            if task['branch']!='main':
                # Validated source contains main; CAS preserves all existing changes.
                git(config,'update-ref','refs/heads/main',task['sha'],main)
            update(db,task,'landed',landing_sha=task['sha'])
            meta(db,'validated_main',{'sha':task['sha'],'receipt':str(receipt),'at':now()})
    except Exception as exc:  # noqa: BLE001 - persist failed validation/landing without retry
        update(db,task,'failed',error=('CI validation failed: ' if phase=='CI' else '')+str(exc))
    return True


def ci_worker(config, task_id):
    """Open and close the SQLite connection in the owning worker thread."""
    db=database(config)
    try:
        task=db.execute("SELECT * FROM tasks WHERE id=? AND status='claimed'",(task_id,)).fetchone()
        if task is None:raise RuntimeError('worker task is not claimed')
        run_claimed(config,db,task)
    finally:
        db.close()


def recover_ci(db):
    # Called only while holding the dispatcher singleton. Crashed claims and
    # validations require inspection; a restart never blindly reruns them.
    db.execute("UPDATE tasks SET status='failed',error='controller interrupted during CI; inspect logs before retry',"
               "updated_at=? WHERE status IN ('claimed','testing')",(now(),))
    db.commit()


def dispatch_ci(config, *, loop=False):
    """Singleton dispatcher; threads orchestrate, local_ci admits real workloads.

    No CPU-per-worker arithmetic or fixed runner count. local_ci's shared
    admission lock, measurements and parent cgroup decide container starts.
    All workers inherit the same configuration/state_dir and distinct outputs.
    """
    with lock(config,'ci'):
        db=database(config)
        workers={}
        failures={}
        failure_lock=threading.Lock()

        def worker(task_id):
            try:
                ci_worker(config,task_id)
            except Exception as exc:  # noqa: BLE001 - dispatcher persists worker startup/DB failures
                with failure_lock:
                    failures[task_id]=str(exc)

        def collect():
            for task_id, thread in list(workers.items()):
                if thread.is_alive():continue
                thread.join()
                with failure_lock:
                    error=failures.pop(task_id,None)
                if error:
                    task=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
                    update(db,task,'failed',error=error)
                del workers[task_id]

        try:
            recover_ci(db)
            while True:
                collect()
                try:
                    discover(config,db)
                    while (task:=claim(db)) is not None:
                        thread=threading.Thread(target=worker,args=(task['id'],),
                                                name=f"local-ci-{task['id']}")
                        try:thread.start()
                        except Exception as exc:
                            update(db,task,'failed',error=str(exc))
                            raise
                        workers[task['id']]=thread
                    snapshot(config,db)
                except Exception as exc:  # noqa: BLE001 - keep active workers and singleton alive
                    print(f'ci dispatcher: {exc}',file=sys.stderr,flush=True)
                if not loop:break
                time.sleep(1)
        finally:
            # Never release singleton/recover claims while this process still has
            # live workers. Normal shutdown drains, it does not kill their CI.
            for thread in workers.values():thread.join()
            collect()
            try:snapshot(config,db)
            finally:db.close()


def release_once(config,db):
    candidate=meta(db,'validated_main').get('sha')
    if not candidate:return False
    main=git(config,'rev-parse','refs/heads/main')
    if candidate!=main:return False
    previous=meta(db,'release')
    if previous.get('sha')==candidate and previous.get('status') in ('failed','delivered'):
        return False
    # Reuse the single production writer and its ownership-aware rollback.
    root=Path(config['state'])/'releases'/candidate;root.mkdir(parents=True,exist_ok=True)
    meta(db,'release',{'sha':candidate,'status':'deploying','started_at':now()});snapshot(config,db)
    try:
        trusted_run(config,'local_release.py',['--config',config['config_path'],'--sha',candidate],root/'release.log',7200)
        state=json.loads((Path(config['production'])/'.aigcnews-deploy/state.json').read_text())
        if state.get('active_release')!=candidate or state.get('in_progress'):
            raise RuntimeError('release command returned without exact production receipt')
        meta(db,'release',{'sha':candidate,'status':'delivered','finished_at':now()})
        for task in db.execute("SELECT * FROM tasks WHERE status='landed'").fetchall():
            if ancestor(config,task['sha'],candidate):update(db,task,'delivered')
    except Exception as exc:  # noqa: BLE001 - persist/report external operation failure
        meta(db,'release',{'sha':candidate,'status':'failed','error':str(exc),'finished_at':now()})
    return True


def mirror_once(config,db):
    # No force, no API; mirror failure cannot change CI/production decisions.
    main=git(config,'rev-parse','refs/heads/main')
    branches=[r[0] for r in db.execute("SELECT DISTINCT branch FROM tasks WHERE branch != 'main'")]
    refs=['refs/heads/main', *['refs/heads/'+b for b in branches]]
    refs_hash=hashlib.sha256(git(config,'for-each-ref','--format=%(refname) %(objectname)',*refs).encode()).hexdigest()
    if meta(db,'mirror').get('refs_hash')==refs_hash and meta(db,'mirror').get('status')=='synced':return
    try:
        command(['git','--git-dir',config['bare'],'push',config['github_url'],
                 *[ref+':'+ref for ref in refs]],timeout=90)
        meta(db,'mirror',{'status':'synced','sha':main,'refs_hash':refs_hash,'last_success':now()})
    except Exception as exc:  # noqa: BLE001 - persist/report external operation failure
        meta(db,'mirror',{'status':'pending','sha':main,'error':str(exc),'last_attempt':now()})


def notification_current(config,db,task):
    if task['status'] in ('failed','needs_update'):
        newer=db.execute('SELECT 1 FROM tasks WHERE branch=? AND id>? AND sha!=? LIMIT 1',
                         (task['branch'],task['id'],task['sha'])).fetchone()
        if newer:return False
    return git(config,'rev-parse','refs/heads/'+task['branch'])==task['sha']


def notification_result(db,task,status,**details):
    meta(db,f"notification:{task['id']}",{
        'status':status,'accepted':status=='accepted','sha':task['sha'],
        'task_status':task['status'],'at':now(),**details})


def notify(config,db):
    """Only pre-bound AO owners; report every outcome, never invent a binding."""
    sys.path.insert(0,config['ao_runtime'])
    import ao_delivery_adapter as ao
    import delivery_ownership
    adb=ao.database(Path(config['ao_database']))
    try:
        if config.get('handoff_enabled',False):
            from local_wakeup import readiness
            for pending in db.execute("SELECT * FROM tasks WHERE status IN ('queued','claimed','testing','landed')").fetchall():
                try:
                    proof=readiness(pending,config['repository'],ao,adb,
                                    desktop_enabled=config.get('desktop_wakeup',False))
                except Exception as exc:  # noqa: BLE001 - unavailable route never permits handoff
                    proof={'ready':False,'sha':pending['sha'],'owner':pending['owner'],
                           'checked_at':now(),'reason':type(exc).__name__}
                meta(db,f"handoff:{pending['id']}",proof)
        # Success updates the dashboard only; do not spend a model turn on it.
        tasks=[dict(row) for row in db.execute("SELECT * FROM tasks WHERE status IN ('needs_update','failed')").fetchall()]
        release=meta(db,'release')
        if release.get('status')=='failed':
            carrier=db.execute("SELECT * FROM tasks WHERE landing_sha=? AND owner IS NOT NULL ORDER BY id DESC LIMIT 1",
                               (release.get('sha'),)).fetchone()
            if carrier:
                carrier=dict(carrier)
                carrier.update(status='release_failed',error=release.get('error'),ci_receipt=None)
                tasks.append(carrier)
        for task in tasks:
            identity=f"local:{task['id']}:{task['sha']}:{task['status']}"
            if task['status']=='release_failed':identity+=':'+str(release.get('finished_at'))
            try:
                # Check before invoking AO and again via its validation callback.
                # Any newer SHA on this branch makes old repair instructions stale.
                if not notification_current(config,db,task):
                    notification_result(db,task,'obsolete',identity=identity)
                    continue
                if not task['owner'] or delivery_ownership.resolve_owner(task['branch'],config['repository']) != task['owner']:
                    notification_result(db,task,'unowned',identity=identity)
                    continue
                msg=(f"Local delivery {task['id']} for exact SHA {task['sha']} is {task['status']}. "
                     f"Evidence: {task['ci_receipt'] or task['error'] or task['landing_sha']}. "
                     'GitHub is an asynchronous mirror; do not wait on GitHub Actions. ')
                if task['status']=='release_failed':
                    msg+='This is the exact release carrier, not every included ancestor. Inspect source and edge receipts separately. Source may already be active. Diagnose first; do not repeat a successful deployment or weaken health checks. Use a fresh branch-backed session for code fixes to a landed task. Submit through the existing pipeline and stop after verified handoff. '
                else:msg+='Fetch local origin/main, merge it into your owned session branch, fix the reported issue, validate and push normally. Never force push or edit another worktree. Stop after verified handoff; do not poll deployment.'
                result=ao.send(adb,task['branch'],identity,msg,Path(config['repository']),
                               validate=lambda t=task:notification_current(config,db,t))
                if result=='unowned' and config.get('desktop_wakeup',False):
                    from local_wakeup import send as desktop_send
                    outcome=desktop_send(db,task,identity,msg,config['repository'],
                                         current=lambda t=task:notification_current(config,db,t))
                    status=outcome.pop('status')
                    notification_result(db,task,status,identity=identity,**outcome)
                else:
                    notification_result(db,task,result if isinstance(result,str) else 'unknown',identity=identity)
            except Exception as exc:  # noqa: BLE001 - per-task visible failure, no success claim
                notification_result(db,task,'error',identity=identity,error=type(exc).__name__)
                meta(db,'notification_error',{'id':task['id'],'error':type(exc).__name__,'at':now()})
    finally:adb.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=DEFAULT)
    parser.add_argument('action',choices=['submit','ci','release','mirror','status','notify'])
    parser.add_argument('--branch');parser.add_argument('--sha');parser.add_argument('--pr',type=int)
    parser.add_argument('--loop',action='store_true')
    args=parser.parse_args()
    config=json.loads(args.config.read_text());config['config_path']=str(args.config.resolve())
    if args.action=='ci':
        dispatch_ci(config,loop=args.loop)
        return
    db=database(config)
    if args.action=='submit':submit(config,db,args.branch,args.sha,args.pr);snapshot(config,db);return
    if args.action=='status':print(json.dumps(snapshot(config,db),ensure_ascii=False));return
    with lock(config,args.action):
        if args.action=='release' and meta(db,'release').get('status')=='deploying':
            meta(db,'release',{**meta(db,'release'),'status':'failed','error':'controller interrupted; inspect production ownership before retry'})
        while True:
            try:
                if args.action=='release':release_once(config,db)
                elif args.action=='mirror':mirror_once(config,db)
                else:notify(config,db)
                snapshot(config,db)
            except Exception as exc:  # noqa: BLE001 - persist/report external operation failure
                print(f'{args.action}: {exc}',file=sys.stderr,flush=True)
            if not args.loop:break
            time.sleep(60 if args.action=='mirror' else 10)


if __name__=='__main__':main()
