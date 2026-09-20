"""Deployment, Actions and retry contracts for the GitHub archive."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]/'scripts/ci'))
import github_archive as a
import local_delivery as d

from backend.tests import test_local_delivery as fixtures

setup = fixtures.setup
isolate_git_environment = fixtures.isolate_git_environment


class API:
    repo = 'owner/repo'

    def __init__(self, base):
        self.remote = base
        self.enabled = False
        self.prs = []
        self.refs = {'main': base}
        self.writes = []

    def disabled(self):
        if self.enabled:
            raise RuntimeError('Actions enabled')

    def call(self, method, path, body=None):
        if path == 'git/ref/heads/main':
            return {'object': {'sha': self.refs['main']}}
        if path.startswith('pulls?'):
            return self.prs
        if method == 'GET' and path.startswith('pulls/'):
            return self.prs[int(path.split('/')[1])-1]
        assert method == 'POST' and path == 'pulls'
        self.writes.append(body)
        pr = {'number': len(self.prs)+1, 'html_url': 'https://github.com/owner/repo/pull/1',
              'state': 'open', 'merged_at': None,
              'head': {'sha': self.refs[body['head']], 'ref': body['head'], 'repo': {'full_name': self.repo}},
              'base': {'ref': body['base'], 'repo': {'full_name': self.repo}}}
        self.prs.append(pr)
        return pr

    def push(self, config, api, *refs):
        self.disabled()
        self.writes.append(refs)
        for ref in refs:
            sha, name = ref.split(':refs/heads/')
            self.refs[name] = sha
            for pr in self.prs:
                if pr['base']['ref'] == name and d.ancestor(config, pr['head']['sha'], sha):
                    pr.update(state='closed', merged_at='2026-09-20T00:00:00Z')


def ready(setup):
    c, db, base, head = setup
    d.git(c, 'update-ref', 'refs/heads/main', head)
    db.execute("UPDATE tasks SET status='delivered',landing_sha=sha"); db.commit()
    d.meta(db, 'release', {'status': 'delivered', 'sha': head})
    control = Path(c['production'])/'.aigcnews-deploy'
    (control/'state.json').write_text(json.dumps({'active_release': head, 'images': {'frontend': 'digest'}}))
    (control/'edge-state.json').write_text(json.dumps({'source_sha': head, 'frontend_image': 'digest', 'sites': {'public': 'published'}}))
    (control/'edge-config.json').write_text(json.dumps({'sites': ['public']}))
    return c, db, base, head


@pytest.mark.parametrize('status', ['deploying', 'failed', 'retrying'])
def test_no_github_before_success(setup, status):
    c, db, base, head = ready(setup)
    d.meta(db, 'release', {'status': status, 'sha': head})
    with patch.object(a, 'GitHub') as api:
        a.mirror(c, db)
        api.assert_not_called()
    assert d.meta(db, 'mirror')['status'] == 'waiting_for_deployment'


def test_partial_edge_never_writes(setup):
    c, db, base, head = ready(setup)
    (Path(c['production'])/'.aigcnews-deploy/edge-state.json').write_text('{}')
    with patch.object(a, 'GitHub') as api:
        a.mirror(c, db)
        api.assert_not_called()
    assert d.meta(db, 'mirror')['status'] == 'pending'


def test_enabled_actions_fail_closed(setup):
    c, db, base, head = ready(setup)
    api = API(base); api.enabled = True
    with patch.object(a, 'GitHub', return_value=api), patch.object(a, 'push', side_effect=api.push):
        a.mirror(c, db)
    assert not api.writes
    assert d.meta(db, 'mirror')['status'] == 'pending'


@pytest.mark.parametrize('historical', [False, True])
def test_deployed_pr_and_main_are_idempotent(setup, historical):
    c, db, base, head = ready(setup)
    api = API(head if historical else base)
    with patch.object(a, 'GitHub', return_value=api), patch.object(a, 'push', side_effect=api.push):
        a.mirror(c, db)
        count = len(api.writes)
        a.mirror(c, db)
    assert len(api.writes) == count
    assert len(api.prs) == 1
    assert api.prs[0]['merged_at']
    assert api.refs['main'] == head
    assert (api.prs[0]['base']['ref'] != 'main') == historical
    assert db.execute('SELECT pr FROM tasks').fetchone()[0] == 1
    assert d.meta(db, 'mirror')['status'] == 'synced'


def test_create_timeout_recovers_without_duplicate(setup):
    c, db, base, head = ready(setup)
    api = API(base)
    original = api.call
    def timeout(method, path, body=None):
        result = original(method, path, body)
        if method == 'POST':
            raise TimeoutError('response lost')
        return result
    with patch.object(a, 'GitHub', return_value=api), patch.object(a, 'push', side_effect=api.push):
        with patch.object(api, 'call', side_effect=timeout):
            a.mirror(c, db)
        assert d.meta(db, 'mirror')['status'] == 'pending'
        a.mirror(c, db)
    assert len(api.prs) == 1
    assert d.meta(db, 'mirror')['status'] == 'synced'


def test_remote_divergence_never_pushes(setup):
    c, db, base, head = ready(setup)
    api = API('f'*40)
    with patch.object(a, 'GitHub', return_value=api), patch.object(a, 'push') as push:
        a.mirror(c, db)
        push.assert_not_called()
    assert d.meta(db, 'mirror')['status'] == 'pending'


def test_push_rechecks_actions_and_never_forces(setup):
    c, db, base, head = setup
    api = API(base)
    with patch.object(d, 'command') as command:
        a.push(c, api, head+':refs/heads/main')
        args = command.call_args.args[0]
        assert '--atomic' in args
        assert not any(x.startswith('--force') or x.startswith('+') for x in args)
        api.enabled = True
        with pytest.raises(RuntimeError):
            a.push(c, api, head+':refs/heads/main')
        assert command.call_count == 1
