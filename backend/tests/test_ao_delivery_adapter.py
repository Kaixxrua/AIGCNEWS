import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location("ao_adapter", Path(__file__).parents[2] / "scripts/ci/ao_delivery_adapter.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "verify_workspace", Mock())
    monkeypatch.setattr(adapter, "ao_read", lambda _: {"session": {"id": "standalone-2"}})
    with adapter.database(tmp_path / "state.sqlite") as conn:
        adapter.bind(conn, "session/example", "standalone-2", tmp_path, "original task receipt", tmp_path, 69)
        yield conn


def ready(session):
    return {"session": {"id": session, "activity": {"state": "idle"}}}


def test_migrated_task_is_initially_held(db):
    deliver = Mock()
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "held"
    deliver.assert_not_called()


def test_exact_target_and_idempotency(db):
    db.execute("UPDATE tasks SET stage='active'")
    deliver = Mock(return_value={"accepted": True})
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "accepted"
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "duplicate"
    deliver.assert_called_once()
    assert deliver.call_args.args[0] == "standalone-2"


@pytest.mark.parametrize("info", [
    {"id": "another-task", "activity": {"state": "idle"}},
    {"id": "standalone-2", "activity": {"state": "working"}},
    {"id": "standalone-2", "activity": {"state": "idle"}, "isTerminated": True},
])
def test_busy_or_wrong_target_waits(db, info):
    db.execute("UPDATE tasks SET stage='active'")
    deliver = Mock()
    assert adapter.send(db, "session/example", "event", "message", ".", read=lambda _: {"session": info}, deliver=deliver) == "waiting"
    deliver.assert_not_called()


def test_ambiguous_delivery_never_replays(db):
    db.execute("UPDATE tasks SET stage='active'")
    deliver = Mock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver)
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "duplicate"
    assert db.execute("SELECT status FROM events").fetchone()[0] == "unconfirmed"


def test_branch_change_prevents_send(db, monkeypatch):
    db.execute("UPDATE tasks SET stage='active'")
    monkeypatch.setattr(adapter, "verify_workspace", Mock(side_effect=ValueError("changed")))
    deliver = Mock()
    with pytest.raises(ValueError):
        adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver)
    deliver.assert_not_called()


def test_reconcile_detects_new_main_and_rechecks_head(db, monkeypatch):
    db.execute("UPDATE tasks SET stage='active'")
    monkeypatch.setattr(adapter, "git", lambda _, *args: "a" * 40 if args[0] == "rev-parse" else "")
    pr = {"state": "open", "head": {"ref": "session/example", "sha": "a" * 40,
          "repo": {"full_name": "Kaixxrua/AIGCNEWS"}}, "html_url": "https://github.com/Kaixxrua/AIGCNEWS/pull/69"}
    client = Mock()
    client.request.side_effect = [pr, {"object": {"sha": "b" * 40}}, {"status": "diverged"}, pr]
    sender = Mock(return_value="accepted")
    monkeypatch.setattr(adapter, "send", sender)
    assert adapter.reconcile(db, client, ".")[0]["result"] == "accepted"
    assert sender.call_args.args[2] == "69:" + "a" * 40 + ":base_update"
    client.contract_runs.assert_not_called()


def test_reconcile_does_not_interrupt_dirty_task(db, monkeypatch):
    db.execute("UPDATE tasks SET stage='active'")
    monkeypatch.setattr(adapter, "git", lambda _, *args: "a" * 40 if args[0] == "rev-parse" else " M file")
    client = Mock()
    client.request.return_value = {"state": "open", "head": {"ref": "session/example", "sha": "a" * 40,
        "repo": {"full_name": "Kaixxrua/AIGCNEWS"}}}
    assert adapter.reconcile(db, client, ".") == []
    assert client.request.call_count == 1


@pytest.mark.parametrize("repos,expected", [
    (["Kaixxrua/AIGCNEWS"], 71),
    (["someone/fork"], None),
    (["Kaixxrua/AIGCNEWS", "Kaixxrua/AIGCNEWS"], None),
])
def test_discovery_requires_unique_same_repository_branch(db, monkeypatch, repos, expected):
    db.execute("UPDATE tasks SET stage='active',pr=NULL")
    client = Mock()
    client.open_pulls.return_value = [
        {"number": 71 + i, "head": {"ref": "session/example", "repo": {"full_name": repo}}}
        for i, repo in enumerate(repos)
    ]
    client.request.return_value = {"head": {"ref": "session/example"}, "state": "closed"}
    adapter.reconcile(db, client, ".")
    assert db.execute("SELECT pr FROM tasks").fetchone()[0] == expected


@pytest.mark.parametrize("head,dirty,state", [
    ("wrong", "", "idle"), ("expected", " M file", "idle"),
    ("expected", "", "working"),
])
def test_activation_rejects_changed_or_busy_task(db, monkeypatch, head, dirty, state):
    monkeypatch.setattr(adapter, "database", lambda _: db)
    monkeypatch.setattr(adapter, "git", lambda _, *args: head if args[0] == "rev-parse" else dirty)
    monkeypatch.setattr(adapter, "ao_read", lambda _: {"session": {"id": "standalone-2", "activity": {"state": state}}})
    monkeypatch.setattr("sys.argv", ["adapter", "activate", "--branch", "session/example",
                                   "--expect-head", "expected", "--handoff-evidence", "audit"])
    with pytest.raises(ValueError):
        adapter.main()
    assert db.execute("SELECT stage FROM tasks").fetchone()[0] == "audit"


def test_activation_preserves_owner_and_records_handoff(db, monkeypatch):
    monkeypatch.setattr(adapter, "database", lambda _: db)
    monkeypatch.setattr(adapter, "git", lambda _, *args: "expected" if args[0] == "rev-parse" else "")
    monkeypatch.setattr(adapter, "ao_read", ready)
    monkeypatch.setattr("sys.argv", ["adapter", "activate", "--branch", "session/example",
                                   "--expect-head", "expected", "--handoff-evidence", "writer released"])
    adapter.main()
    session, stage, source = db.execute("SELECT session,stage,source FROM tasks").fetchone()
    assert (session, stage) == ("standalone-2", "active")
    assert "writer released" in source


def test_pause_prevents_dispatch(db, monkeypatch, tmp_path):
    monkeypatch.setattr(adapter.Path, "home", lambda: tmp_path)
    marker = tmp_path / ".config/aigcnews/ci-paused"
    marker.parent.mkdir(parents=True)
    marker.touch()
    db.execute("UPDATE tasks SET stage='active'")
    deliver = Mock()
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "paused"
    deliver.assert_not_called()
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


@pytest.fixture
def native_identity(tmp_path,monkeypatch):
    import sqlite3
    root=tmp_path/'ao';(root/'data').mkdir(parents=True)
    monkeypatch.setattr(adapter,'ROOT',root)
    thread='01a0b42f-7c59-7173-8748-c48452592869'
    path=root/'data/ao.db'
    with sqlite3.connect(path) as native:
        native.executescript('''
          CREATE TABLE sessions(id TEXT,harness TEXT,session_mode TEXT,is_terminated INTEGER,
                                provider_conversation_id TEXT,controller_generation TEXT);
          CREATE TABLE conversations(id TEXT,session_id TEXT,scope TEXT,current_session_id TEXT,active_branch_id TEXT);
          CREATE TABLE conversation_branches(id TEXT,conversation_id TEXT,session_id TEXT,provider_conversation_id TEXT);
        ''')
        native.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',('standalone-11','codex','chat',0,thread,'generation-1'))
        native.execute('INSERT INTO conversations VALUES(?,?,?,?,?)',('conversation-1','standalone-11','session','standalone-11','branch-1'))
        native.execute('INSERT INTO conversation_branches VALUES(?,?,?,?)',('branch-1','conversation-1','standalone-11',thread))
    responses={
        '':{'session':{'id':'standalone-11','harness':'codex','mode':'chat','isTerminated':False,
                       'activity':{'state':'active'}}},
        '/conversation?limit=1':{'sessionId':'standalone-11','harness':'codex','mode':'chat',
                                'controller':'busy','conversationId':'conversation-1','activeBranchId':'branch-1'},
    }
    monkeypatch.setattr(adapter,'ao_read',lambda session,resource='':responses[resource])
    return path,thread,responses


@pytest.mark.parametrize('controller',['ready','busy'])
def test_provider_identity_uses_native_thread_not_api_conversation_or_turn(native_identity,controller):
    path,thread,responses=native_identity
    before=path.read_bytes()
    responses['/conversation?limit=1']['controller']=controller
    responses['/conversation?limit=1']['turns']=[{'providerTurnId':'unrelated-turn-id'}]
    evidence=adapter.provider_identity('standalone-11',thread)
    assert evidence['provider_conversation_id']==thread
    assert evidence['conversation_id']=='conversation-1'
    assert evidence['controller_generation']=='generation-1'
    assert path.read_bytes()==before
    assert not (adapter.ROOT/'delivery.sqlite').exists()


@pytest.mark.parametrize('sql',[
    "UPDATE sessions SET provider_conversation_id='01a0a9b2-7db0-78a2-a960-cfc652157d21'",
    "UPDATE conversation_branches SET provider_conversation_id='01a0a9b2-7db0-78a2-a960-cfc652157d21'",
    "UPDATE conversations SET current_session_id='other'",
    "UPDATE conversation_branches SET session_id='other'",
    "UPDATE sessions SET controller_generation=''",
    "UPDATE sessions SET is_terminated=1",
    "UPDATE conversations SET active_branch_id='missing'",
    "INSERT INTO sessions SELECT 'other',harness,session_mode,is_terminated,provider_conversation_id,controller_generation FROM sessions",
])
def test_provider_identity_rejects_mismatch_ambiguity_and_missing_evidence(native_identity,sql):
    import sqlite3
    path,thread,_=native_identity
    with sqlite3.connect(path) as native:native.execute(sql)
    with pytest.raises(ValueError):adapter.provider_identity('standalone-11',thread)


@pytest.mark.parametrize(('resource','key','value'),[
    ('','id','wrong'),('','harness','claude-code'),('','isTerminated',True),
    ('/conversation?limit=1','sessionId','other'),('/conversation?limit=1','activeBranchId','other'),
    ('/conversation?limit=1','conversationId','other'),('/conversation?limit=1','controller','recovering'),
])
def test_provider_identity_requires_live_api_agreement(native_identity,resource,key,value):
    _,thread,responses=native_identity
    target=responses[resource]['session'] if resource=='' else responses[resource]
    target[key]=value
    with pytest.raises(ValueError):adapter.provider_identity('standalone-11',thread)


def test_missing_native_store_fails_without_creating_database(native_identity):
    import sqlite3
    path,thread,_=native_identity
    path.unlink()
    with pytest.raises(sqlite3.OperationalError):adapter.provider_identity('standalone-11',thread)
    assert not path.exists()


@pytest.fixture
def new_binding(native_identity,tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    path,thread,_=native_identity
    worktree=tmp_path/'new-worktree';worktree.mkdir()
    receipt=tmp_path/'owner.json'
    receipt.write_text(json.dumps({'schema':'aigcnews.delivery-owner.v1','source':'dev_session.start',
                                  'branch':'session/new-task','thread_id':thread,'worktree':str(worktree)}))
    ownership=SimpleNamespace(receipt_path=lambda *a:receipt,resolve_owner=lambda *a:thread)
    monkeypatch.setattr(adapter,'peer',lambda name:ownership)
    monkeypatch.setattr(adapter,'verify_workspace',lambda *a:None)
    monkeypatch.setattr(adapter,'git',lambda path,*a:'' if a[0]=='status' else 'a'*40)
    monkeypatch.setenv('AO_SESSION_ID','standalone-11')
    monkeypatch.setenv('CODEX_THREAD_ID',thread)
    evidence=adapter.provider_identity('standalone-11',thread)
    args=('session/new-task','standalone-11',worktree,tmp_path,thread,'a'*40)
    return args,evidence,ownership


def test_new_binding_activates_proven_creating_task_without_idle_handoff(new_binding):
    import json
    args,evidence,_=new_binding
    result=adapter.auto_bind_new(*args,evidence=evidence)
    assert result=={'session':'standalone-11','stage':'active','provider_thread_id':args[4]}
    with adapter.database(adapter.ROOT/'delivery.sqlite') as db:
        row=db.execute('SELECT branch,session,stage,source FROM tasks').fetchone()
        assert row[:3]==('session/new-task','standalone-11','active')
        assert json.loads(row[3])['provider_identity']==evidence
        assert db.execute('SELECT count(*) FROM events').fetchone()[0]==0


@pytest.mark.parametrize('key',['AO_SESSION_ID','CODEX_THREAD_ID'])
def test_new_binding_rejects_missing_creating_environment(new_binding,monkeypatch,key):
    args,evidence,_=new_binding
    monkeypatch.delenv(key)
    with pytest.raises(ValueError,match='creating AO task'):adapter.auto_bind_new(*args,evidence=evidence)
    assert not (adapter.ROOT/'delivery.sqlite').exists()


def test_new_binding_never_overwrites_manual_handoff(new_binding):
    args,evidence,_=new_binding
    with adapter.database(adapter.ROOT/'delivery.sqlite') as db:
        db.execute("INSERT INTO tasks(branch,session,worktree,source) VALUES('session/old','standalone-11','/old','manual')")
    with pytest.raises(ValueError,match='explicit handoff'):adapter.auto_bind_new(*args,evidence=evidence)
    with adapter.database(adapter.ROOT/'delivery.sqlite') as db:
        assert db.execute('SELECT branch,stage,source FROM tasks').fetchall()==[('session/old','audit','manual')]


def test_new_binding_provider_change_inside_transaction_rolls_back(new_binding,monkeypatch):
    args,evidence,_=new_binding
    calls=[]
    def changed(*a):
        calls.append(1)
        return evidence if len(calls)==1 else {**evidence,'controller_generation':'changed'}
    monkeypatch.setattr(adapter,'provider_identity',changed)
    with pytest.raises(ValueError,match='changed during creation'):adapter.auto_bind_new(*args,evidence=evidence)
    with adapter.database(adapter.ROOT/'delivery.sqlite') as db:
        assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==0


def test_new_binding_rejects_wrong_receipt_owner(new_binding):
    args,evidence,ownership=new_binding
    ownership.resolve_owner=lambda *a:'different-thread'
    with pytest.raises(ValueError,match='owner/worktree'):adapter.auto_bind_new(*args,evidence=evidence)


@pytest.mark.parametrize('change',['head','base','dirty'])
def test_new_binding_rejects_changes_since_creation(new_binding,monkeypatch,change):
    args,evidence,_=new_binding
    def git(path,*a):
        if a[0]=='status':return ' M file' if change=='dirty' else ''
        if a==('rev-parse','HEAD') and change=='head':return 'b'*40
        if a==('rev-parse','origin/main') and change=='base':return 'b'*40
        return 'a'*40
    monkeypatch.setattr(adapter,'git',git)
    with pytest.raises(ValueError,match='creation baseline'):adapter.auto_bind_new(*args,evidence=evidence)
