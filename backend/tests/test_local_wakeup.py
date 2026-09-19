import importlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0,str(Path(__file__).parents[2]/'scripts/ci'))
w=importlib.import_module('local_wakeup')


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    receipt=tmp_path/'owner.json';receipt.write_text(json.dumps({'worktree':str(tmp_path/'owned')}))
    monkeypatch.setattr(w,'receipt_path',lambda *a:receipt)
    monkeypatch.setattr(w,'resolve_owner',lambda *a:'exact-owner')
    monkeypatch.setattr(w,'git',lambda path,*args:'a'*40 if args==('rev-parse','HEAD') else '')
    bridge=Mock();bridge.idle.return_value=True;bridge.wake.return_value={'turn':{'id':'exact-turn'}}
    factory=Mock();factory.return_value.__enter__=Mock(return_value=bridge)
    factory.return_value.__exit__=Mock(return_value=False)
    db=sqlite3.connect(':memory:')
    task={'owner':'exact-owner','branch':'session/example-123','sha':'a'*40}
    def send(current=lambda:True):
        return w.send(db,task,'event-sha','repair',tmp_path,current=current,bridge_factory=factory)
    return send,bridge,db


def test_exact_owner_and_turn_receipt_no_replay(setup):
    send,bridge,db=setup
    assert send()['turn_id']=='exact-turn'
    assert send()['status']=='accepted'
    bridge.wake.assert_called_once()
    assert bridge.wake.call_args.args[0]=='exact-owner'
    assert 'branch session/example-123' in bridge.wake.call_args.args[1]


def test_busy_owner_waits(setup):
    send,bridge,db=setup;bridge.idle.return_value=False
    assert send()['status']=='waiting'
    bridge.wake.assert_not_called()


def test_unknown_owner_cannot_wake(setup,monkeypatch):
    send,bridge,db=setup;monkeypatch.setattr(w,'resolve_owner',lambda *a:'different')
    assert send()['status']=='waiting_workspace';bridge.wake.assert_not_called()


def test_head_or_dirty_workspace_cannot_wake(setup,monkeypatch):
    send,bridge,db=setup;monkeypatch.setattr(w,'git',lambda *a:'changed')
    assert send()['status']=='waiting_workspace';bridge.wake.assert_not_called()


def test_stale_event_cannot_wake(setup):
    send,bridge,db=setup
    assert send(current=lambda:False)['status']=='waiting_workspace';bridge.wake.assert_not_called()


def test_uncertain_send_never_repeats(setup):
    send,bridge,db=setup;bridge.wake.side_effect=TimeoutError()
    assert send()['status']=='unconfirmed';assert send()['status']=='unconfirmed'
    bridge.wake.assert_called_once()


def test_pause_honored(setup,tmp_path):
    send,bridge,db=setup;p=tmp_path/'.config/aigcnews/ci-paused';p.parent.mkdir(parents=True);p.touch()
    assert send()['status']=='paused';bridge.wake.assert_not_called()


def test_readiness_busy_exact_desktop_can_handoff(tmp_path,monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    monkeypatch.setattr(w,'resolve_owner',lambda *a:'owner')
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE tasks(branch,session,stage)')
    factory=MagicMock();b=factory.return_value.__enter__.return_value
    b.call.return_value={'thread':{'id':'owner','status':{'type':'active'}}}
    t={'owner':'owner','branch':'session/x','sha':'a'*40}
    assert w.readiness(t,tmp_path,None,db,desktop_enabled=True,bridge_factory=factory)['ready']
    b.call.return_value={'thread':{'id':'other','status':{'type':'active'}}}
    assert not w.readiness(t,tmp_path,None,db,desktop_enabled=True,bridge_factory=factory)['ready']
    b.wake.assert_not_called()


def test_held_ao_binding_cannot_fall_back_to_desktop(tmp_path,monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    monkeypatch.setattr(w,'resolve_owner',lambda *a:'owner')
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE tasks(branch,session,stage)')
    db.execute("INSERT INTO tasks VALUES('session/x','ao-1','audit')")
    factory=MagicMock()
    t={'owner':'owner','branch':'session/x','sha':'a'*40}
    assert not w.readiness(t,tmp_path,None,db,desktop_enabled=True,bridge_factory=factory)['ready']
    factory.assert_not_called()
