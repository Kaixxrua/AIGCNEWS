"""Host executor contracts; never launch, stop or modify a real LXD instance."""
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
import local_ci as ci


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    ci.git(repo, 'init', '-q')
    source = Path(__file__).parents[2]
    for name in (ci.WORKFLOW, 'frontend/package.json'):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((source / name).read_bytes())
    (repo / 'app.py').write_text('value = 1\n')
    commit(repo)
    return repo


def commit(repo):
    ci.git(repo, 'add', '-A')
    ci.git(repo, '-c', 'user.name=CI', '-c', 'user.email=ci@test', 'commit', '-qm', 'fixture')
    return ci.git(repo, 'rev-parse', 'HEAD').decode().strip()


def config(tmp_path, repository):
    return dict(baseline_repository=str(repository),
                baseline_sha=ci.git(repository, 'rev-parse', 'HEAD').decode().strip(),
                state_dir=str(tmp_path / 'state'), shared_parent='/sys/fs/cgroup/test',
                shared_unit='test.service', template='aigcnews-ci-template', network='lxdbr0',
                proxy_connect='tcp:172.17.0.1:7897', tool_path='/usr/bin:/bin',
                admission_timeout=600, settling_seconds=60, command_timeout=180, check_timeout=1800)


def instance():
    return {'status': 'Stopped', 'expanded_config': {}, 'expanded_devices': {
        'root': {'type': 'disk', 'path': '/', 'pool': 'ci'},
        'eth0': {'type': 'nic', 'name': 'eth0', 'network': 'lxdbr0'},
        'egress-proxy': {'type': 'proxy', 'bind': 'container',
                         'connect': 'tcp:172.17.0.1:7897', 'listen': 'tcp:0.0.0.0:7895'}}}


def test_trusted_workflow_preserves_all_substantive_steps(tmp_path, repository):
    cfg = config(tmp_path, repository)
    jobs, digest = ci.workflow(repository, cfg['baseline_sha'], cfg)
    assert len(digest) == 64
    assert len([s for j in ci.JOBS for s in jobs[j]['steps'] if 'run' in s]) == 25
    assert '--cov-fail-under=70' in str(jobs)
    assert 'test_postgres16_github_project_semantic_source_integration.py' in str(jobs)
    assert 'go test ./... -count=1' in str(jobs)
    assert 'npm run typecheck' in str(jobs)
    assert 'docker build' in str(jobs)


@pytest.mark.parametrize('path', [ci.WORKFLOW, 'backend/tests/test_bypass.py', 'conftest.py',
                                  'frontend/vite.config.ts', 'scripts/ci/bypass.py',
                                  'mcp-go/internal/bypass_test.go'])
def test_candidate_gate_files_do_not_choose_workflow_commands(tmp_path, repository, path):
    cfg = config(tmp_path, repository)
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('skip every test\n')
    sha = commit(repository)
    jobs, _ = ci.workflow(repository, sha, cfg)
    assert 'go test ./... -count=1' in str(jobs)


def test_candidate_npm_scripts_are_overlaid_but_dependencies_preserved(tmp_path, repository):
    cfg = config(tmp_path, repository)
    path = repository / 'frontend/package.json'
    data = json.loads(path.read_text())
    data['scripts']['test:unit'] = 'true'
    path.write_text(json.dumps(data))
    sha = commit(repository)
    ci.workflow(repository, sha, cfg)
    archive = tmp_path / 'controls.tar'
    ci.controls_archive(repository, sha, cfg, archive)
    with tarfile.open(archive) as tar:
        patched = json.load(tar.extractfile('frontend/package.json'))
    assert patched['scripts']['test:unit'] != 'true'
    assert patched['dependencies'] == data['dependencies']


def test_candidate_code_can_change_without_selecting_gates(tmp_path, repository):
    cfg = config(tmp_path, repository)
    (repository / 'app.py').write_text('value = 2\n')
    jobs, _ = ci.workflow(repository, commit(repository), cfg)
    assert set(ci.JOBS).issubset(jobs)


@pytest.mark.parametrize('sha', ['HEAD', 'main', 'a' * 39, '--help', 'A' * 40])
def test_exact_commit_required(repository, sha):
    with pytest.raises(ValueError, match='full lowercase'):
        ci.exact_sha(repository, sha)


def test_symlink_and_submodule_not_exported(repository):
    (repository / 'secret').symlink_to('/etc/shadow')
    with pytest.raises(ValueError, match='unsupported archive'):
        ci.tree(repository, commit(repository))


def test_export_ignore_cannot_remove_tests(tmp_path, repository):
    (repository / '.gitattributes').write_text('app.py export-ignore\n')
    sha = commit(repository)
    archive = tmp_path / 'source.tar'
    archive.write_bytes(ci.git(repository, 'archive', sha))
    with pytest.raises(ValueError, match='omitted tracked'):
        ci.verify_archive(archive, ci.tree(repository, sha))


def test_archive_content_is_verified(tmp_path, repository):
    sha = ci.git(repository, 'rev-parse', 'HEAD').decode().strip()
    archive = tmp_path / 'source.tar'
    archive.write_bytes(ci.git(repository, 'archive', sha))
    ci.verify_archive(archive, ci.tree(repository, sha))
    with tarfile.open(archive, 'w') as tar:
        member = tarfile.TarInfo('app.py')
        member.size = 4
        tar.addfile(member, io.BytesIO(b'fake'))
    with pytest.raises(ValueError, match='differs from exact'):
        ci.verify_archive(archive, ci.tree(repository, sha))


@pytest.mark.parametrize('unsafe', ['host-docker', 'production', 'privileged', 'raw', 'proxy'])
def test_unsafe_templates_fail_closed(tmp_path, repository, unsafe):
    cfg, item = config(tmp_path, repository), instance()
    ci.validate_instance(item, cfg)
    if unsafe in ('host-docker', 'production'):
        item['expanded_devices'][unsafe] = {'type': 'disk', 'source': '/var/run/docker.sock'}
    elif unsafe == 'privileged':
        item['expanded_config']['security.privileged'] = 'true'
    elif unsafe == 'raw':
        item['expanded_config']['raw.lxc'] = 'lxc.mount.entry = / /host none bind 0 0'
    else:
        item['expanded_devices']['egress-proxy']['connect'] = 'unix:/var/run/docker.sock'
    with pytest.raises(ValueError):
        ci.validate_instance(item, cfg)


def test_config_cannot_come_from_candidate(tmp_path, repository):
    path = repository / 'config.json'
    path.write_text(json.dumps(config(tmp_path, repository)))
    with pytest.raises(ValueError, match='outside candidate'):
        ci.trusted_config(path, repository, tmp_path / 'receipt.json')


def test_private_config_and_output_required(tmp_path, repository):
    path = tmp_path / 'trusted.json'
    path.write_text(json.dumps(config(tmp_path, repository)))
    path.chmod(0o666)
    with pytest.raises(ValueError, match='trusted owner'):
        ci.trusted_config(path, repository, tmp_path / 'receipt.json')
    path.chmod(0o600)
    with pytest.raises(ValueError, match='outside candidate'):
        ci.trusted_config(path, repository, repository / 'receipt.json')


def test_real_command_timeout_kills_process_group():
    with pytest.raises(subprocess.TimeoutExpired):
        ci.command([sys.executable, '-c', 'import time; time.sleep(60)'], timeout=.05)


def test_cleanup_never_deletes_foreign_runner(tmp_path, repository, monkeypatch):
    runner = ci.Runner(config(tmp_path, repository), {'instance': 'ours', 'run_id': '123'}, io.BytesIO())
    calls = []
    def lxc(*args, **kwargs):
        calls.append(args)
        return json.dumps([{'name': 'ours', 'expanded_config': {'user.aigcnews.local_ci': 'other'}},
                           {'name': 'existing', 'expanded_config': {}}]).encode()
    monkeypatch.setattr(runner, 'lxc', lxc)
    with pytest.raises(ValueError, match='ownership mismatch'):
        runner.cleanup()
    assert calls == [('list', '--format=json')]


def test_cleanup_only_own_clone(tmp_path, repository, monkeypatch):
    runner = ci.Runner(config(tmp_path, repository), {'instance': 'ours', 'run_id': '123'}, io.BytesIO())
    calls = []
    def lxc(*args, **kwargs):
        calls.append(args)
        return json.dumps([{'name': 'ours', 'expanded_config': {'user.aigcnews.local_ci': '123'}},
                           {'name': 'existing', 'expanded_config': {}}]).encode()
    monkeypatch.setattr(runner, 'lxc', lxc)
    runner.cleanup()
    assert calls[-1] == ('delete', '--force', 'ours')


def mocked_execution(tmp_path, repository, monkeypatch, fail=False):
    cfg = config(tmp_path, repository)
    calls = []
    monkeypatch.setattr(ci.Runner, 'launch', lambda self: calls.append('launch'))
    monkeypatch.setattr(ci.Runner, 'cleanup', lambda self: calls.append('cleanup'))
    monkeypatch.setattr(ci.pool, 'counters', lambda path: {'oom_kill': '0'})
    def check(self, key, job, archive):
        calls.append(key)
        if fail:
            raise TimeoutError('test timeout')
        return [{'name': 'fixture', 'conclusion': 'success'}]
    monkeypatch.setattr(ci.Runner, 'check', check)
    output = tmp_path / 'receipt.json'
    return cfg, calls, output


def test_exact_sha_results_and_restart_do_not_execute_twice(tmp_path, repository, monkeypatch):
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch)
    sha = cfg['baseline_sha']
    assert ci.execute(repository, sha, output, cfg) == 0
    first = json.loads(output.read_text())
    assert first['sha'] == sha
    assert first['conclusion'] == 'success'
    assert first['status'] == 'success'
    assert first['ready'] is True
    assert first['ready_at'] >= first['started_at']
    assert all(c['sha'] == sha and c['conclusion'] == 'success' for c in first['checks'])
    assert ci.execute(repository, sha, output, cfg) == 0
    assert json.loads(output.read_text()) == first
    assert calls.count('launch') == 1
    assert calls.count('backend-tests') == 1


def test_timeout_retains_failure_logs_and_reaps(tmp_path, repository, monkeypatch):
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch, fail=True)
    assert ci.execute(repository, cfg['baseline_sha'], output, cfg) == 1
    receipt = json.loads(output.read_text())
    assert receipt['checks'][0]['conclusion'] == 'failure'
    assert receipt['conclusion'] == 'failure'
    assert receipt['status'] == 'failure'
    assert 'test timeout' in Path(receipt['log']).read_text()
    assert calls[-1] == 'cleanup'


def test_interrupted_attempt_never_automatically_replays(tmp_path, repository, monkeypatch):
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch)
    ci.execute(repository, cfg['baseline_sha'], output, cfg)
    path = next(Path(cfg['state_dir']).glob('*.json'))
    data = json.loads(path.read_text())
    data['conclusion'] = 'running'
    ci.atomic_json(path, data)
    calls.clear()
    assert ci.execute(repository, cfg['baseline_sha'], output, cfg) == 2
    assert calls == ['cleanup']
    assert json.loads(output.read_text())['conclusion'] == 'interrupted'


def test_failed_cleanup_cannot_authorize_success(tmp_path, repository, monkeypatch):
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch)
    def cleanup(self):
        raise RuntimeError('LXD unavailable')
    monkeypatch.setattr(ci.Runner, 'cleanup', cleanup)
    assert ci.execute(repository, cfg['baseline_sha'], output, cfg) == 1
    assert json.loads(output.read_text())['conclusion'] == 'error'


def test_admission_reuses_pool_sampling_and_restart_warmup(tmp_path, repository, monkeypatch):
    cfg = config(tmp_path, repository)
    cfg['admission_timeout'] = 10
    runner = ci.Runner(cfg, {'instance': 'ours'}, io.BytesIO())
    samples = []
    monkeypatch.setattr(ci.time, 'sleep', lambda _: None)
    times = iter(range(100))
    monkeypatch.setattr(ci.time, 'monotonic', lambda: next(times))
    def sample(*args, **kwargs):
        samples.append((args, kwargs))
        return ci.pool.Evidence(('same',), 5.4, 0, 12 * ci.pool.GIB, 0, False)
    monkeypatch.setattr(ci.pool, 'sample', sample)
    with pytest.raises(TimeoutError, match='admission'):
        runner.admit()
    assert samples
    assert samples[0][0][0] == cfg['shared_parent']
    assert samples[0][1]['owner_unit'] == cfg['shared_unit']


def test_launch_uses_shared_six_cpu_parent_without_touching_existing_runner(tmp_path, repository, monkeypatch):
    cfg = config(tmp_path, repository)
    state = {'instance': 'aigcnews-ci-local-test', 'run_id': '123456789abc123456789abc12345678'}
    runner = ci.Runner(cfg, state, io.BytesIO())
    calls = []
    def info(name):
        item = instance()
        item['name'] = name
        if name == runner.name:
            item['expanded_config']['raw.lxc'] = ci.pool.parent_config(
                Path(cfg['shared_parent']), name, '')
        return item
    monkeypatch.setattr(runner, 'info', info)
    monkeypatch.setattr(runner, 'admit', lambda: calls.append(('admitted',)))
    monkeypatch.setattr(runner, 'lxc', lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(runner, 'shell', lambda *a, **kw: None)
    monkeypatch.setattr(ci.pool, 'limits', lambda *a: None)
    monkeypatch.setattr(ci.pool, 'inventory', lambda: ['existing-runner', runner.name])
    monkeypatch.setattr(ci.pool, 'membership', lambda *a, **kw: calls.append(('members', *a)))
    runner.launch()
    assert ('config', 'set', runner.name, 'limits.cpu=6') in calls
    assert ('config', 'set', runner.name, 'limits.cpu.allowance=100%') in calls
    assert any(c[0:3] == ('config', 'set', runner.name) and c[3].startswith('user.aigcnews.runner_id=-') for c in calls)
    assert calls[0] == ('admitted',)
    assert calls[1][-1] == 'user.aigcnews.local_ci=' + state['run_id']
    assert not any(c[0] in ('stop', 'delete') for c in calls)
    assert any(c[0] == 'members' and c[1] == ['existing-runner', runner.name] for c in calls)


def test_clone_cannot_inject_raw_mounts(tmp_path, repository):
    cfg, item = config(tmp_path, repository), instance()
    item['name'] = 'ours'
    item['expanded_config']['raw.lxc'] = 'lxc.mount.entry = / /host none bind 0 0'
    with pytest.raises(ValueError, match='cgroup placement'):
        ci.validate_instance(item, cfg, clone=True)


def test_all_trusted_run_steps_are_dispatched_with_job_environment(tmp_path, repository, monkeypatch):
    cfg = config(tmp_path, repository)
    jobs, _ = ci.workflow(repository, cfg['baseline_sha'], cfg)
    log_path = tmp_path / 'run.log'
    scripts = []
    with log_path.open('ab') as log:
        runner = ci.Runner(cfg, {'instance': 'ours', 'run_id': 'test', 'controls_archive': '/trusted/controls.tar'}, log)
        monkeypatch.setattr(runner, 'lxc', lambda *a, **kw: b'')
        monkeypatch.setattr(runner, 'shell', lambda script, **kw: scripts.append(script))
        for key in ci.JOBS:
            steps = runner.check(key, jobs[key], tmp_path / 'archive')
            expected = [s for s in jobs[key]['steps'] if 'run' in s]
            assert [s['name'] for s in steps] == [s['name'] for s in expected]
            for step in expected:
                assert any(script.endswith(step['run']) for script in scripts)
    assert any('TEST_POSTGRES_RUN_ID=local-test' in s for s in scripts)
    assert any('cd /ci/work/mcp-go' in s and 'go vet ./...' in s for s in scripts)
    assert any('cd /ci/work/frontend' in s and 'npm run test:unit' in s for s in scripts)


def test_unknown_workflow_action_is_not_silently_skipped(tmp_path, repository):
    path = repository / ci.WORKFLOW
    path.write_text(path.read_text().replace('actions/setup-go@v5', 'unknown/gate@v1'))
    commit(repository)
    cfg = config(tmp_path, repository)
    with pytest.raises(ValueError, match='unsupported workflow action'):
        ci.workflow(repository, cfg['baseline_sha'], cfg)


def test_receipt_lock_prevents_overlapping_local_executors(tmp_path, repository, monkeypatch):
    import fcntl
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch)
    root = Path(cfg['state_dir'])
    root.mkdir(mode=0o700)
    with (root / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            ci.execute(repository, cfg['baseline_sha'], output, cfg)
    assert calls == []


def test_trusted_helper_overlay_keeps_candidate_tests_and_ci_changes(tmp_path, repository):
    helper = repository / 'scripts/ci/materialize_ui_catalog_fixture.py'
    helper.parent.mkdir(parents=True)
    helper.write_text('TRUSTED_HELPER = True\n')
    commit(repository)
    cfg = config(tmp_path, repository)
    helper.write_text('raise SystemExit(0)\n')
    new_test = repository / 'backend/tests/test_new_feature.py'
    new_test.parent.mkdir(parents=True)
    new_test.write_text('def test_new_feature():\n    assert True\n')
    (helper.parent / 'local_delivery.py').write_text('CANDIDATE_CONTROLLER = True\n')
    sha = commit(repository)
    ci.workflow(repository, sha, cfg)
    candidate = tmp_path / 'candidate.tar'
    candidate.write_bytes(ci.git(repository, 'archive', sha))
    ci.verify_archive(candidate, ci.tree(repository, sha))
    controls = tmp_path / 'controls.tar'
    manifest = ci.controls_archive(repository, sha, cfg, controls)
    with tarfile.open(controls) as tar:
        assert tar.extractfile('scripts/ci/materialize_ui_catalog_fixture.py').read() == b'TRUSTED_HELPER = True\n'
        assert 'backend/tests/test_new_feature.py' not in tar.getnames()
        assert 'scripts/ci/local_delivery.py' not in tar.getnames()
    assert 'scripts/ci/materialize_ui_catalog_fixture.py' in manifest
    with tarfile.open(candidate) as tar:
        assert 'backend/tests/test_new_feature.py' in tar.getnames()
        assert 'scripts/ci/local_delivery.py' in tar.getnames()


def test_ready_receipt_published_before_first_check(tmp_path, repository, monkeypatch):
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch)
    def check(self, *args):
        receipt = json.loads(output.read_text())
        assert receipt['ready'] is True
        assert receipt['status'] == 'running'
        assert receipt['sha'] == cfg['baseline_sha']
        assert receipt['controls']
        return [{'name': 'fixture', 'conclusion': 'success'}]
    monkeypatch.setattr(ci.Runner, 'check', check)
    assert ci.execute(repository, cfg['baseline_sha'], output, cfg) == 0


def test_launch_failure_never_publishes_ready(tmp_path, repository, monkeypatch):
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch)
    def launch(self):
        raise RuntimeError('pool changed')
    monkeypatch.setattr(ci.Runner, 'launch', launch)
    assert ci.execute(repository, cfg['baseline_sha'], output, cfg) == 1
    receipt = json.loads(output.read_text())
    assert receipt['ready'] is False
    assert receipt['status'] == 'failure'


def test_progress_output_replaces_old_failure_and_publishes_each_completed_check(tmp_path, repository, monkeypatch):
    cfg, calls, output = mocked_execution(tmp_path, repository, monkeypatch)
    output.write_text(json.dumps({'status': 'failure', 'run_id': 'previous'}))
    publications = []
    atomic = ci.atomic_json
    def record(path, data):
        if Path(path) == output:
            publications.append(json.loads(json.dumps(data)))
        atomic(path, data)
    monkeypatch.setattr(ci, 'atomic_json', record)
    assert ci.execute(repository, cfg['baseline_sha'], output, cfg) == 0
    assert publications[0]['status'] == 'running'
    assert publications[0]['run_id'] != 'previous'
    for index, key in enumerate(ci.JOBS):
        assert any(r['status'] == 'running' and r['checks']
                   and r['checks'][index]['id'] == key
                   and r['checks'][index]['conclusion'] == 'success'
                   for r in publications)
