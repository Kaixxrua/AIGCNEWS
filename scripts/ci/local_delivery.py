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
                            timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr[-1500:]}')
    return result.stdout.strip()


def git(config, *args):
    return command(['git','--git-dir',config['bare'],*args])


def ancestor(config, old, new):
    if not SHA.fullmatch(old or '') or not SHA.fullmatch(new or ''):
        return False
    p=subprocess.run(['git','--git-dir',config['bare'],'merge-base','--is-ancestor',old,new],capture_output=True)
    if p.returncode not in (0,1):
        raise RuntimeError('commit ancestry unavailable')
    return p.returncode==0


def atomic(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temporary.chmod(0o600);temporary.replace(path)


@contextlib.contextmanager
def lock(config, name):
    with (Path(config['state'])/(name+'.lock')).open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
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


def snapshot(config,db):
    production=json.loads((Path(config['production'])/'.aigcnews-deploy/state.json').read_text())
    data={'schema':'aigcnews.local-delivery.v1','mode':'local' if config.get('enabled') else 'staged','generated_at':now(),
          'main_sha':git(config,'rev-parse','refs/heads/main'),
          'active_release':production.get('active_release'),'production_in_progress':production.get('in_progress'),
          'tasks':[dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY id')],
          'release':meta(db,'release'),'mirror':meta(db,'mirror')}
    atomic(Path(config['state'])/'status.json',data)
    return data


def trusted_run(config, script, args, logfile, timeout):
    with Path(logfile).open('a') as log:
        process=subprocess.run([sys.executable,str(Path(config['runtime'])/script),*map(str,args)],
                               stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
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


def ci_once(config,db):
    task=db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
    if not task:return False
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
        with lock(config,'landing'):
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
    except Exception as exc:
        update(db,task,'failed',error=str(exc))
    return True


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
    except Exception as exc:
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
    except Exception as exc:
        meta(db,'mirror',{'status':'pending','sha':main,'error':str(exc),'last_attempt':now()})


def notify(config,db):
    """Only pre-bound AO owners; uncertain sends are not replayed."""
    sys.path.insert(0,config['ao_runtime'])
    import ao_delivery_adapter as ao
    import delivery_ownership
    adb=ao.database(Path(config['ao_database']))
    try:
        for task in db.execute("SELECT * FROM tasks WHERE status IN ('needs_update','failed','delivered')"):
            if not task['owner'] or delivery_ownership.resolve_owner(task['branch'],config['repository']) != task['owner']:continue
            identity=f"local:{task['id']}:{task['sha']}:{task['status']}"
            msg=(f"Local delivery {task['id']} for exact SHA {task['sha']} is {task['status']}. "
                 f"Evidence: {task['ci_receipt'] or task['error'] or task['landing_sha']}. "
                 'GitHub is an asynchronous mirror; do not wait on GitHub Actions. ')
            if task['status']=='delivered':msg+='Production includes this task. Notify only, do not edit or redeploy.'
            else:msg+='Fetch local origin/main, merge it into your owned session branch, fix the reported issue, validate and push normally. Never force push or edit another worktree.'
            try:
                ao.send(adb,task['branch'],identity,msg,Path(config['repository']),
                        validate=lambda t=task:command(['git','-C',config['repository'],'rev-parse',t['branch']])==t['sha'])
            except Exception as exc:
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
    db=database(config)
    if args.action=='submit':submit(config,db,args.branch,args.sha,args.pr);snapshot(config,db);return
    if args.action=='status':print(json.dumps(snapshot(config,db),ensure_ascii=False));return
    with lock(config,args.action):
        if args.action=='ci':
            # A killed validation never grants a successful receipt automatically.
            db.execute("UPDATE tasks SET status='failed',error='controller interrupted during CI; inspect logs before retry',updated_at=? WHERE status='testing'",(now(),));db.commit()
        if args.action=='release' and meta(db,'release').get('status')=='deploying':
            meta(db,'release',{**meta(db,'release'),'status':'failed','error':'controller interrupted; inspect production ownership before retry'})
        while True:
            try:
                if args.action=='ci':
                    discover(config,db)
                    ci_once(config,db)
                elif args.action=='release':release_once(config,db)
                elif args.action=='mirror':mirror_once(config,db)
                else:notify(config,db)
                snapshot(config,db)
            except Exception as exc:
                print(f'{args.action}: {exc}',file=sys.stderr,flush=True)
            if not args.loop:break
            time.sleep(60 if args.action=='mirror' else 10)


if __name__=='__main__':main()
