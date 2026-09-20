"""Local authority never depends on a GitHub response or unverified CI state."""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0,str(Path(__file__).parents[2]/'scripts/ci'))
import local_delivery as d


@pytest.fixture(autouse=True)
def isolate_git_environment(monkeypatch):
    """Keep hook-provided Git state out of disposable test repositories."""
    for name in tuple(os.environ):
        if name.startswith('GIT_'):
            monkeypatch.delenv(name)


@pytest.fixture
def setup(tmp_path):
    repo=tmp_path/'source';repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
    git('init','-b','main');git('config','user.name','test');git('config','user.email','test@example.test')
    (repo/'file').write_text('initial');git('add','.');git('commit','-m','test(ci): initial')
    base=git('rev-parse','HEAD');git('checkout','-b','session/test-local-123')
    (repo/'file').write_text('new');git('commit','-am','feat(ci): next')
    head=git('rev-parse','HEAD')
    common=repo/'.git';(common/'delivery-owners').mkdir()
    branch='session/test-local-123'
    (common/'delivery-owners'/(d.hashlib.sha256(branch.encode()).hexdigest()+'.json')).write_text(json.dumps({'branch':branch,'source':'dev_session.start','thread_id':'owner'}))
    bare=tmp_path/'authority.git';subprocess.run(['git','clone','--bare',str(repo),str(bare)],check=True,capture_output=True)
    prod=tmp_path/'prod';(prod/'.aigcnews-deploy').mkdir(parents=True)
    (prod/'.aigcnews-deploy/state.json').write_text(json.dumps({'active_release':base,'in_progress':None}))
    c={'bare':str(bare),'repository':str(repo),'state':str(tmp_path/'state'),'production':str(prod),
       'runtime':str(tmp_path),'config_path':str(tmp_path/'config'),'github_url':'https://invalid.test/repo'}
    db=d.database(c);d.submit(c,db,branch,head)
    return c,db,base,head


def attest(config,script,args,log,timeout):
    receipt=Path(args[args.index('--output')+1]);sha=args[args.index('--sha')+1]
    receipt.write_text(json.dumps({'sha':sha,'status':'success','cleanup':'success','checks':[{'id':name,'sha':sha,'conclusion':'success'} for name in ['backend-tests','postgres-integration','mcp-go','compose-smoke','frontend-build']]}))


def test_exact_success_lands_without_github(setup):
    c,db,base,head=setup
    with patch.object(d,'trusted_run',side_effect=attest):assert d.ci_once(c,db)
    assert d.git(c,'rev-parse','main')==head
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='landed'


def test_bad_receipt_never_lands(setup):
    c,db,base,head=setup
    def bad(*args):
        attest(*args);Path(args[2][args[2].index('--output')+1]).write_text(json.dumps({'sha':base,'status':'success'}))
    with patch.object(d,'trusted_run',side_effect=bad):d.ci_once(c,db)
    assert d.git(c,'rev-parse','main')==base
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='failed'


def test_head_moves_during_ci_is_not_landed(setup):
    c,db,base,head=setup
    def moved(*args):
        attest(*args);d.git(c,'update-ref','refs/heads/session/test-local-123',base,head)
    with patch.object(d,'trusted_run',side_effect=moved):d.ci_once(c,db)
    assert d.git(c,'rev-parse','main')==base
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='superseded'


def test_mirror_failure_is_recorded_not_raised(setup):
    c,db,base,head=setup
    d.meta(db, 'release', {'status': 'delivered', 'sha': base})
    d.mirror_once(c, db)
    assert d.meta(db,'mirror')['status']=='pending'
    with patch.object(d,'trusted_run',side_effect=attest):d.ci_once(c,db)
    assert d.git(c,'rev-parse','main')==head


def test_submission_is_idempotent(setup):
    c,db,base,head=setup
    d.submit(c,db,'session/test-local-123',head)
    assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==1


def test_failed_release_does_not_auto_loop(setup):
    c,db,base,head=setup
    d.meta(db,'validated_main',{'sha':base})
    d.meta(db,'release',{'sha':base,'status':'failed','error':'migration failed'})
    with patch.object(d,'trusted_run') as run:
        assert not d.release_once(c,db)
        run.assert_not_called()


def test_bare_hook_rejects_main_and_force(setup):
    import local_receive
    c,db,base,head=setup
    with pytest.raises(ValueError,match='only session'):
        local_receive.validate(c,base,head,'refs/heads/main')
    with pytest.raises(ValueError,match='non-fast-forward'):
        local_receive.validate(c,head,base,'refs/heads/session/test-local-123')
    local_receive.validate(c,base,head,'refs/heads/session/test-local-123')


def test_partial_checks_cannot_land(setup):
    c,db,base,head=setup
    def partial(*args):
        attest(*args)
        p=Path(args[2][args[2].index('--output')+1]);v=json.loads(p.read_text())
        v['checks'].pop();p.write_text(json.dumps(v))
    with patch.object(d,'trusted_run',side_effect=partial):d.ci_once(c,db)
    assert d.git(c,'rev-parse','main')==base
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='failed'


def enqueue(db, branch, sha, *, owner='owner', status='queued', error=None):
    stamp=d.now()
    cursor=db.execute('INSERT INTO tasks(branch,sha,status,owner,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                      (branch,sha,status,owner,error,stamp,stamp))
    db.commit()
    return cursor.lastrowid


def test_atomic_claim_across_independent_connections(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    c,db,base,head=setup
    barrier=Barrier(8)
    def contender(_):
        connection=d.database(c)
        try:
            barrier.wait(timeout=10)
            task=d.claim(connection)
            return task['id'] if task is not None else None
        finally:connection.close()
    with ThreadPoolExecutor(max_workers=8) as workers:
        results=list(workers.map(contender,range(8)))
    assert len([r for r in results if r is not None])==1
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='claimed'


def test_claim_transaction_rolls_back_on_error(setup):
    c,db,base,head=setup
    db.execute("CREATE TRIGGER reject_claim BEFORE UPDATE OF status ON tasks BEGIN SELECT RAISE(ABORT,'no claim'); END")
    db.commit()
    with pytest.raises(d.sqlite3.IntegrityError,match='no claim'):d.claim(db)
    assert not db.in_transaction
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='queued'


def test_parallel_dispatcher_uses_worker_owned_connections_and_preserves_main_cas(setup,monkeypatch):
    from threading import Barrier, get_ident
    c,db,base,head=setup
    branch='session/second-worker-123'
    # Two eligible refs, both based on the original main. They finish CI together.
    d.git(c,'update-ref','refs/heads/'+branch,head)
    enqueue(db,branch,head)
    barrier=Barrier(2)
    threads=set()
    connections=[]
    original_database=d.database
    original_git=d.git
    cas=[]
    def database(config):
        connection=original_database(config)
        connections.append((get_ident(),connection))
        return connection
    def run(*args):
        threads.add(get_ident())
        barrier.wait(timeout=10)
        attest(*args)
    def git(config,*args):
        if args[:2]==('update-ref','refs/heads/main'):cas.append(args)
        return original_git(config,*args)
    monkeypatch.setattr(d,'database',database)
    monkeypatch.setattr(d,'discover',lambda *a: None)
    monkeypatch.setattr(d,'trusted_run',run)
    monkeypatch.setattr(d,'git',git)
    d.dispatch_ci(c)
    assert len(threads)==2
    assert len({id(connection) for _,connection in connections})==3
    assert {tid for tid,_ in connections}==threads|{get_ident()}
    assert sorted(r[0] for r in db.execute('SELECT status FROM tasks'))==['landed','needs_update']
    assert cas==[('update-ref','refs/heads/main',head,base)]
    assert d.git(c,'rev-parse','main')==head
    assert d.meta(db,'validated_main')['sha']==head
    assert len(list((Path(c['state'])/'runs').glob('*/ci.json')))==2


def test_dispatcher_singleton_rejects_second_dispatch_before_recovery(setup,monkeypatch):
    c,db,base,head=setup
    db.execute("UPDATE tasks SET status='testing'");db.commit()
    monkeypatch.setattr(d,'discover',lambda *a: pytest.fail('second dispatcher ran'))
    with d.lock(c,'ci'),pytest.raises(BlockingIOError):d.dispatch_ci(c)
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='testing'


def test_restart_marks_claimed_and_testing_failed_without_retry(setup,monkeypatch):
    c,db,base,head=setup
    db.execute("UPDATE tasks SET status='testing'");db.commit()
    enqueue(db,'session/other-claim-123',base,status='claimed')
    monkeypatch.setattr(d,'discover',lambda *a: None)
    monkeypatch.setattr(d,'trusted_run',lambda *a: pytest.fail('interrupted work replayed'))
    d.dispatch_ci(c)
    assert [r[0] for r in db.execute('SELECT status FROM tasks')]==['failed','failed']
    assert d.git(c,'rev-parse','main')==base


def test_worker_connection_failure_persisted_and_not_requeued(setup,monkeypatch):
    c,db,base,head=setup
    monkeypatch.setattr(d,'discover',lambda *a: None)
    def broken(*args):raise RuntimeError('worker DB unavailable')
    monkeypatch.setattr(d,'ci_worker',broken)
    d.dispatch_ci(c)
    row=db.execute('SELECT * FROM tasks').fetchone()
    assert row['status']=='failed'
    assert row['error']=='worker DB unavailable'
    assert d.git(c,'rev-parse','main')==base


def test_main_moves_outside_landing_lock_cas_rejects_stale_write(setup,monkeypatch):
    c,db,base,head=setup
    original=d.git
    def race(config,*args):
        if args[:2]==('update-ref','refs/heads/main'):
            original(config,'update-ref','refs/heads/main',head,base)
        return original(config,*args)
    monkeypatch.setattr(d,'git',race)
    monkeypatch.setattr(d,'trusted_run',attest)
    d.ci_once(c,db)
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='failed'
    assert not d.meta(db,'validated_main')


def test_atomic_snapshot_files_are_thread_safe_private_and_complete(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path=tmp_path/'status.json'
    barrier=Barrier(12)
    def publish(i):
        barrier.wait(timeout=10)
        d.atomic(path,{'worker':i,'payload':str(i)*10000})
    with ThreadPoolExecutor(max_workers=12) as workers:
        list(workers.map(publish,range(12)))
    value=json.loads(path.read_text())
    assert value['payload']==str(value['worker'])*10000
    assert path.stat().st_mode & 0o777==0o600
    assert not list(tmp_path.glob('*.tmp'))


def test_atomic_failure_removes_temporary_and_preserves_previous(tmp_path,monkeypatch):
    path=tmp_path/'status.json';d.atomic(path,{'old':True})
    def failed(*args):raise OSError('disk error')
    monkeypatch.setattr(d.os,'replace',failed)
    with pytest.raises(OSError,match='disk error'):d.atomic(path,{'old':False})
    assert json.loads(path.read_text())=={'old':True}
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize(('status','error','stage'),[
    ('failed','local_ci.py failed; see /logs/ci.log','CI 验证'),
    ('failed','CI validation failed: timeout','CI 验证'),
    ('failed','CI receipt does not attest exact successful SHA','CI 验证'),
    ('needs_update','main changed during CI; merge current local main and revalidate','合并基线'),
    ('failed','unknown infrastructure problem',None),
    ('testing',None,None),
    ('landed',None,None),
])
def test_snapshot_retry_of_only_known_failure_stage(setup,status,error,stage):
    c,db,base,head=setup
    prior=db.execute('SELECT * FROM tasks').fetchone()
    d.update(db,prior,status,error=error)
    task_id=enqueue(db,prior['branch'],base,status='testing')
    tasks=d.snapshot(c,db)['tasks']
    retry=next(t for t in tasks if t['id']==task_id)
    if stage:
        assert retry['retry_of']=={'id':prior['id'],'sha':head,'failure_stage':stage}
    else:assert 'retry_of' not in retry


@pytest.mark.parametrize(('branch','owner'),[
    ('session/different-123','owner'),('session/test-local-123','other-owner'),
    ('session/test-local-123',None),
])
def test_snapshot_never_guesses_retry_across_branch_or_owner(setup,branch,owner):
    c,db,base,head=setup
    prior=db.execute('SELECT * FROM tasks').fetchone()
    d.update(db,prior,'failed',error='local_ci.py failed; see log')
    task_id=enqueue(db,branch,base,owner=owner,status='testing')
    retry=next(t for t in d.snapshot(c,db)['tasks'] if t['id']==task_id)
    assert 'retry_of' not in retry


def test_snapshot_does_not_skip_unknown_failure_to_link_older_failure(setup):
    c,db,base,head=setup
    prior=db.execute('SELECT * FROM tasks').fetchone()
    d.update(db,prior,'failed',error='local_ci.py failed; see log')
    enqueue(db,prior['branch'],base,status='failed',error='unknown')
    latest=enqueue(db,prior['branch'],'f'*40,status='testing')
    retry=next(t for t in d.snapshot(c,db)['tasks'] if t['id']==latest)
    assert 'retry_of' not in retry


def test_dispatcher_holds_singleton_until_worker_finishes(setup,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    c,db,base,head=setup
    entered,release=Event(),Event()
    monkeypatch.setattr(d,'discover',lambda *a: None)
    def run(*args):
        entered.set()
        assert release.wait(10)
        attest(*args)
    monkeypatch.setattr(d,'trusted_run',run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(d.dispatch_ci,c)
        try:
            assert entered.wait(10)
            with pytest.raises(BlockingIOError),d.lock(c,'ci'):pass
            assert not future.done()
        finally:release.set()
        future.result(timeout=10)
    with d.lock(c,'ci'):pass
    assert db.execute('SELECT status FROM tasks').fetchone()[0]=='landed'


def test_failed_candidate_does_not_block_other_worker_or_retry(setup,monkeypatch):
    from threading import Barrier
    c,db,base,head=setup
    branch='session/second-worker-123'
    d.git(c,'update-ref','refs/heads/'+branch,head)
    second_id=enqueue(db,branch,head)
    barrier=Barrier(2)
    calls=[]
    monkeypatch.setattr(d,'discover',lambda *a: None)
    def run(*args):
        receipt=Path(args[2][args[2].index('--output')+1])
        calls.append(receipt.parent.name)
        barrier.wait(timeout=10)
        if receipt.parent.name!=str(second_id):raise RuntimeError('network EOF')
        attest(*args)
    monkeypatch.setattr(d,'trusted_run',run)
    d.dispatch_ci(c)
    assert [r[0] for r in db.execute('SELECT status FROM tasks ORDER BY id')]==['failed','landed']
    d.dispatch_ci(c)
    assert len(calls)==2
    assert d.git(c,'rev-parse','main')==head


def test_snapshot_unknown_owners_are_not_matching_owners(setup):
    c,db,base,head=setup
    db.execute("UPDATE tasks SET owner=NULL,status='failed',error='local_ci.py failed; log'");db.commit()
    task_id=enqueue(db,'session/test-local-123',base,owner=None,status='testing')
    task=next(t for t in d.snapshot(c,db)['tasks'] if t['id']==task_id)
    assert 'retry_of' not in task


@pytest.fixture
def notification_setup(setup,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import ao_delivery_adapter as ao
    import delivery_ownership
    c,db,base,head=setup
    c.update(ao_runtime=str(Path(d.__file__).parent),ao_database=str(Path(c['state'])/'ao.sqlite'))
    task=db.execute('SELECT * FROM tasks').fetchone()
    d.update(db,task,'failed',error='local_ci.py failed; see log')
    close=Mock()
    monkeypatch.setattr(ao,'database',lambda path:SimpleNamespace(close=close))
    monkeypatch.setattr(delivery_ownership,'resolve_owner',lambda *args:'owner')
    return c,db,base,head,ao,close


@pytest.mark.parametrize('result',['accepted','unowned','waiting','paused','duplicate','unconfirmed','obsolete','ownership_changed'])
def test_notify_publishes_exact_return_status_and_only_accepted_is_success(notification_setup,monkeypatch,result):
    c,db,base,head,ao,close=notification_setup
    def send(*args,**kwargs):
        assert kwargs['validate']()
        return result
    monkeypatch.setattr(ao,'send',send)
    d.notify(c,db)
    notification=d.snapshot(c,db)['tasks'][0]['notification']
    assert notification['status']==result
    assert notification['accepted']==(result=='accepted')
    assert notification['sha']==head
    close.assert_called_once()


def test_notify_real_unowned_adapter_does_not_create_binding(setup,monkeypatch):
    import ao_delivery_adapter as ao
    import delivery_ownership
    c,db,base,head=setup
    c.update(ao_runtime=str(Path(d.__file__).parent),ao_database=str(Path(c['state'])/'ao.sqlite'))
    d.update(db,db.execute('SELECT * FROM tasks').fetchone(),'failed',error='local_ci.py failed; log')
    monkeypatch.setattr(delivery_ownership,'resolve_owner',lambda *args:'owner')
    d.notify(c,db)  # Adapter has no binding: returns before remote IO or message send.
    assert d.snapshot(c,db)['tasks'][0]['notification']['status']=='unowned'
    assert d.snapshot(c,db)['tasks'][0]['notification']['accepted'] is False
    adb=ao.database(Path(c['ao_database']))
    try:
        assert adb.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
        assert adb.execute('SELECT count(*) FROM events').fetchone()[0]==0
    finally:adb.close()


@pytest.mark.parametrize('status',['failed','needs_update'])
def test_notify_skips_old_failure_when_new_sha_enqueued(notification_setup,monkeypatch,status):
    c,db,base,head,ao,close=notification_setup
    old=db.execute('SELECT * FROM tasks').fetchone()
    d.update(db,old,status)
    # Even if bare ref has not changed yet, a newer queued SHA suppresses stale repair.
    enqueue(db,old['branch'],base,status='testing')
    monkeypatch.setattr(ao,'send',lambda *a,**kw:pytest.fail('stale repair sent'))
    d.notify(c,db)
    assert d.snapshot(c,db)['tasks'][0]['notification']['status']=='obsolete'


def test_notify_skips_changed_ref_without_new_queue_entry(notification_setup,monkeypatch):
    c,db,base,head,ao,close=notification_setup
    d.git(c,'update-ref','refs/heads/session/test-local-123',base,head)
    monkeypatch.setattr(ao,'send',lambda *a,**kw:pytest.fail('old SHA sent'))
    d.notify(c,db)
    assert d.snapshot(c,db)['tasks'][0]['notification']['status']=='obsolete'


def test_notify_rechecks_newer_sha_in_adapter_callback(notification_setup,monkeypatch):
    c,db,base,head,ao,close=notification_setup
    def send(*args,**kwargs):
        enqueue(db,'session/test-local-123',base,status='queued')
        assert kwargs['validate']() is False
        return 'obsolete'
    monkeypatch.setattr(ao,'send',send)
    d.notify(c,db)
    assert d.snapshot(c,db)['tasks'][0]['notification']['status']=='obsolete'


def test_notify_exception_visible_per_task(notification_setup,monkeypatch):
    c,db,base,head,ao,close=notification_setup
    def send(*args,**kwargs):raise TimeoutError('uncertain send')
    monkeypatch.setattr(ao,'send',send)
    d.notify(c,db)
    notification=d.snapshot(c,db)['tasks'][0]['notification']
    assert notification['status']=='error'
    assert notification['accepted'] is False
    assert notification['error']=='TimeoutError'
    close.assert_called_once()


def test_notify_newer_other_branch_does_not_suppress_current_failure(notification_setup,monkeypatch):
    c,db,base,head,ao,close=notification_setup
    enqueue(db,'session/other-branch-123',base)
    calls=[]
    def send(*args,**kwargs):
        calls.append(args)
        return 'unowned'
    monkeypatch.setattr(ao,'send',send)
    d.notify(c,db)
    assert len(calls)==1
    assert d.snapshot(c,db)['tasks'][0]['notification']['status']=='unowned'


def test_release_failure_notifies_only_exact_carrier(notification_setup,monkeypatch):
    from unittest.mock import Mock
    c,db,base,head,ao,close=notification_setup
    task=db.execute('SELECT * FROM tasks').fetchone()
    d.update(db,task,'landed',landing_sha=head)
    enqueue(db,'session/ancestor-123',base,status='landed')
    d.meta(db,'release',{'sha':head,'status':'failed','finished_at':'attempt1','error':'edge failed'})
    send=Mock(return_value='accepted');monkeypatch.setattr(ao,'send',send)
    d.notify(c,db)
    send.assert_called_once()
    assert send.call_args.args[1]==task['branch']
    assert 'release_failed:attempt1' in send.call_args.args[2]
    assert 'Source may already be active' in send.call_args.args[3]


def test_success_does_not_spend_an_agent_turn(notification_setup,monkeypatch):
    c,db,base,head,ao,close=notification_setup
    d.update(db,db.execute('SELECT * FROM tasks').fetchone(),'delivered',landing_sha=head)
    monkeypatch.setattr(ao,'send',lambda *a,**kw:pytest.fail('success woke agent'))
    d.notify(c,db)


def test_current_failure_stage_is_published_not_only_retry_link(setup):
    c,db,base,head=setup
    task=db.execute('SELECT * FROM tasks').fetchone()
    d.update(db,task,'failed',error='CI validation failed: local_ci.py failed; see log')
    assert d.snapshot(c,db)['tasks'][0]['failure_stage']=='CI 验证'
    d.update(db,task,'needs_update',error='main changed')
    assert d.snapshot(c,db)['tasks'][0]['failure_stage']=='合并基线'


def test_duplicate_notification_preserves_exact_accepted_receipt(tmp_path):
    c = {'state': str(tmp_path)}
    db = d.database(c)
    task = {'id': 1, 'sha': 'a'*40, 'status': 'failed'}
    d.notification_result(db, task, 'accepted', identity='event', turn_id='turn')
    d.notification_result(db, task, 'duplicate', identity='event')
    assert d.meta(db, 'notification:1')['accepted'] is True
    assert d.meta(db, 'notification:1')['turn_id'] == 'turn'
    d.notification_result(db, task, 'duplicate', identity='different')
    assert d.meta(db, 'notification:1')['accepted'] is False


def test_release_retry_only_after_proven_predeploy_environment_recovery(tmp_path, monkeypatch):
    c = {'state': str(tmp_path/'state'), 'production': str(tmp_path/'production')}
    sha = 'a'*40
    previous = {'sha': sha, 'status': 'failed'}
    log = Path(c['state'])/'releases'/sha/'release.log'
    log.parent.mkdir(parents=True)
    log.write_text('ensure_clean_tracked_tree\nthis operation must be run in a work tree')
    state = Path(c['production'])/'.aigcnews-deploy/state.json'
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({'active_release': 'b'*40, 'in_progress': None}))
    monkeypatch.setattr(d, 'command', lambda args, **kw: 'true' if 'rev-parse' in args else '')
    assert d.recovered_worktree_failure(c, previous)
    assert not d.recovered_worktree_failure(c, {**previous, 'attempt': 3})
    state.write_text(json.dumps({'in_progress': {'sha': sha}}))
    assert not d.recovered_worktree_failure(c, previous)
    state.write_text(json.dumps({'in_progress': None}))
    log.write_text('database migration failed')
    assert not d.recovered_worktree_failure(c, previous)


def test_transient_release_retry_keeps_candidate_when_main_advances(setup, monkeypatch):
    c, db, base, head = setup
    d.git(c, 'update-ref', 'refs/heads/main', head, base)
    d.meta(db, 'validated_main', {'sha': head})
    d.meta(db, 'release', {'sha': base, 'status': 'retrying', 'attempt': 1, 'retry_at': 0})
    calls = []
    def finish(config, script, args, log, timeout):
        calls.append(args[args.index('--sha')+1])
        Path(config['production'], '.aigcnews-deploy/state.json').write_text(
            json.dumps({'active_release': base, 'in_progress': None, 'images': {'frontend': 'digest'}}))
        Path(config['production'], '.aigcnews-deploy/edge-config.json').write_text(json.dumps({'sites': ['app']}))
        Path(config['production'], '.aigcnews-deploy/edge-state.json').write_text(json.dumps({
            'source_sha': base, 'frontend_image': 'digest', 'sites': {'app': 'published'}}))
    monkeypatch.setattr(d, 'trusted_run', finish)
    assert d.release_once(c, db)
    assert calls == [base]
    assert d.meta(db, 'release')['status'] == 'delivered'
