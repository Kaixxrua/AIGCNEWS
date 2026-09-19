"""Local authority never depends on a GitHub response or unverified CI state."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0,str(Path(__file__).parents[2]/'scripts/ci'))
import local_delivery as d


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
    original=d.command
    def offline(args,**kwargs):
        if 'push' in args:raise RuntimeError('GitHub unavailable')
        return original(args,**kwargs)
    with patch.object(d,'command',side_effect=offline):d.mirror_once(c,db)
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
