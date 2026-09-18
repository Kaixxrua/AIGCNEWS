import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
import shared_runner_pool as pool


def evidence(**changes):
    return replace(pool.Evidence(('stable',), 0, 0, 12 * pool.GIB, 0, False), **changes)


def ready():
    policy = pool.AdaptiveAdmission()
    assert policy.decide(100, evidence(), 0) == 0
    return policy


def test_burst_is_bounded_and_startup_delay_survives_inventory_changes():
    policy = ready()
    assert policy.decide(1000, evidence(), 60) == 1
    policy.launched(60)
    assert policy.decide(1000, evidence(), 61) == 0
    assert policy.decide(1000, evidence(identity=('new',)), 120) == 0
    assert policy.decide(1000, evidence(identity=('new',)), 180) == 1


def test_idle_queue_and_restart_do_not_launch():
    assert ready().decide(0, evidence(), 60) == 0
    restarted = pool.AdaptiveAdmission()
    assert restarted.decide(100, evidence(), 10000) == 0
    assert restarted.decide(100, evidence(predicted_growth=10 * pool.GIB), 10060) == 0


@pytest.mark.parametrize('state', [evidence(cpu=5.4), evidence(memory=11 * pool.GIB),
                                  evidence(pressure=True)])
def test_saturation_and_pressure_stop_admission_with_hysteresis(state):
    policy = ready()
    assert policy.decide(100, state, 60) == 0
    assert policy.decide(100, evidence(cpu=5), 120) == 0
    assert policy.decide(100, evidence(), 121) == 1


def test_memory_growth_reserved_even_with_idle_actual_load():
    assert ready().decide(100, evidence(predicted_growth=9 * pool.GIB), 60) == 0
    assert ready().decide(100, evidence(predicted_growth=7 * pool.GIB), 60) == 1


def test_reclaim_requires_settling_then_reuses_capacity():
    policy = ready()
    assert policy.decide(100, evidence(identity=('busy',), predicted_growth=10 * pool.GIB), 60) == 0
    assert policy.decide(100, evidence(identity=('reaped',), committed_memory=pool.GIB), 120) == 0
    assert policy.decide(100, evidence(identity=('reaped',), committed_memory=pool.GIB), 180) == 1


def test_actual_cpu_load_not_runner_count_controls_admission():
    policy = ready()
    # Many low-memory payloads do not impose a fixed instance cap.
    state = evidence(committed_memory=pool.GIB, cpu=1)
    assert policy.decide(100, state, 60) == 1
    assert policy.decide(100, replace(state, cpu=4.5), 120) == 0


def parent(tmp_path):
    values = {'cpu.max': '600000 100000', 'memory.max': str(12 * pool.GIB),
              'memory.high': str(int(12 * pool.GIB * .9)), 'memory.swap.max': '0', 'memory.swap.current': '0',
              'memory.current': '1000', 'cpu.stat': 'usage_usec 100',
              'memory.pressure': 'some avg10=0.00 avg60=0.00 avg300=0.00 total=0',
              'cgroup.procs': '', 'memory.events': 'oom 0\noom_kill 0\nhigh 0\nmax 0'}
    p = tmp_path / 'ci'; p.mkdir()
    for k, v in values.items(): (p / k).write_text(v)
    return p


@pytest.mark.parametrize('file,value', [('cpu.max', 'max 100000'), ('cpu.max', '700000 100000'),
                                      ('memory.max', str(13 * pool.GIB)), ('memory.swap.max', '1')])
def test_missing_or_excessive_parent_ceiling_denies(tmp_path, file, value):
    p = parent(tmp_path); (p / file).write_text(value)
    with pytest.raises(ValueError): pool.limits(p)


def item(name='aigcnews-ci', runner=22):
    return {'name': name, 'status': 'RUNNING', 'expanded_config': {
        'user.aigcnews.runner_id': str(runner), 'limits.memory': '1GiB',
        'limits.memory.swap': 'false'}}


def test_control_and_all_registered_ci_must_be_accounted():
    runners = [{'id': 22, 'status': 'online', 'busy': False,
                'labels': [{'name': 'aigcnews-control'}]}]
    pool.registered_coverage([item()], runners, ('aigcnews-ci-ephemeral',))
    with pytest.raises(ValueError): pool.registered_coverage([], runners, ())
    with pytest.raises(KeyError): pool.registered_coverage(
        [{'name': 'aigcnews-ci', 'status': 'RUNNING', 'expanded_config': {}}], runners, ())


def test_membership_rejects_control_outside_parent(tmp_path, monkeypatch):
    root = tmp_path / 'cgroup'; p = root / 'ci'; p.mkdir(parents=True)
    proc = tmp_path / 'proc'; (proc / '42').mkdir(parents=True)
    (proc / '42/cgroup').write_text('0::/other/init.scope')
    monkeypatch.setattr(pool, 'lxc', lambda *args: {'pid': 42})
    with pytest.raises(ValueError, match='outside shared parent'):
        pool.membership([item()], [], (), p, cgroup_root=root, proc=proc)


def test_sampling_rejects_inventory_race_and_counter_reset(tmp_path, monkeypatch):
    p = parent(tmp_path)
    monkeypatch.setattr(pool, 'membership', lambda *args, **kwargs: ((), 0))
    monkeypatch.setattr(pool.time, 'sleep', lambda _: None)
    clock = iter([1, 2, 3, 4]); monkeypatch.setattr(pool.time, 'monotonic', lambda: next(clock))
    inventories = iter([[], [item()]])
    monkeypatch.setattr(pool, 'inventory', lambda: next(inventories))
    with pytest.raises(ValueError, match='inventory changed'): pool.sample(p, [], ())
    monkeypatch.setattr(pool, 'inventory', lambda: [])
    monkeypatch.setattr(pool.time, 'sleep', lambda _: (p / 'cpu.stat').write_text('usage_usec 0'))
    with pytest.raises(ValueError, match='invalid pool measurement'): pool.sample(p, [], ())


def test_parent_config_preserves_other_settings_and_rejects_placement_override():
    text = pool.parent_config(Path('/sys/fs/cgroup/ci'), 'job-one', 'lxc.apparmor.profile = unchanged')
    assert 'lxc.apparmor.profile = unchanged' in text
    assert 'lxc.cgroup.dir.container = ci/job-one' in text
    assert 'lxc.cgroup.dir.monitor = ci/monitors/job-one' in text
    with pytest.raises(ValueError): pool.parent_config(Path('/sys/fs/cgroup/ci'), 'job', 'lxc.cgroup.dir = old')


def test_shared_launch_uses_weights_without_partitioning_or_running_resize(tmp_path, monkeypatch):
    import ephemeral_runner_autoscaler as scaler
    p = parent(tmp_path)
    runtime = scaler.LxdRuntime('template', 'job-', tmp_path)
    runtime.shared_parent = str(p)
    monkeypatch.setattr(pool, 'owner', lambda *args: ((), 0))
    commands = []
    def command(args, **kwargs):
        commands.append(args)
        return scaler.subprocess.CompletedProcess(args, 0, b'', b'')
    runtime.command = command
    monkeypatch.setattr(pool, 'parent_config', lambda *args: 'parent-config')
    monkeypatch.setattr(pool, 'inventory', lambda: [])
    monkeypatch.setattr(pool, 'membership', lambda *args, **kwargs: ((), 0))
    runtime.launch('new-job', 'jit', 7, cpu='6', memory=str(3 * pool.GIB))
    assert ['config', 'set', 'new-job', 'limits.cpu.allowance', '100%'] in commands
    assert ['config', 'set', 'new-job', 'limits.cpu.priority', '5'] in commands
    assert all(args[2] == 'new-job' for args in commands if args[:2] == ['config', 'set'])
    assert commands.index(['config', 'set', 'new-job', 'raw.lxc', 'parent-config']) < commands.index(['start', 'new-job'])


def test_valid_membership_checks_kernel_growth_limit_and_unaccounted_subtrees(tmp_path, monkeypatch):
    root = tmp_path / 'cgroup'; root.mkdir()
    p = parent(root)
    child = p / 'aigcnews-ci'; child.mkdir()
    (child / 'memory.max').write_text(str(pool.GIB))
    proc = tmp_path / 'proc'; (proc / '42').mkdir(parents=True)
    (proc / '42/cgroup').write_text('0::/ci/aigcnews-ci/payload/init.scope')
    monkeypatch.setattr(pool, 'lxc', lambda *args: {'pid': 42})
    assert pool.membership([item()], [], (), p, cgroup_root=root, proc=proc)[1] == pool.GIB
    (p / 'unaccounted').mkdir()
    with pytest.raises(ValueError, match='unaccounted subtree'):
        pool.membership([item()], [], (), p, cgroup_root=root, proc=proc)
    (p / 'unaccounted').rmdir()
    (child / 'memory.max').write_text(str(2 * pool.GIB))
    with pytest.raises(ValueError, match='kernel child memory'):
        pool.membership([item()], [], (), p, cgroup_root=root, proc=proc)


def test_memory_pressure_or_parent_replacement_stops_sample(tmp_path, monkeypatch):
    p = parent(tmp_path)
    monkeypatch.setattr(pool, 'membership', lambda *args, **kwargs: ((), 0))
    monkeypatch.setattr(pool, 'inventory', lambda: [])
    monkeypatch.setattr(pool.time, 'sleep', lambda _: None)
    clock = iter([1, 2, 3, 4]); monkeypatch.setattr(pool.time, 'monotonic', lambda: next(clock))
    (p / 'memory.pressure').write_text('some avg10=1.00 avg60=0.00 avg300=0.00 total=10')
    assert pool.sample(p, [], ()).pressure
    monkeypatch.setattr(pool.time, 'sleep', lambda _: (p / 'cpu.max').write_text('max 100000'))
    with pytest.raises(ValueError): pool.sample(p, [], ())


def test_unavailable_parent_denies_before_any_container_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, 'owner', lambda *args: ((), 0))
    import ephemeral_runner_autoscaler as scaler
    runtime = scaler.LxdRuntime('template', 'job-', tmp_path)
    runtime.shared_parent = str(tmp_path / 'missing')
    calls = []
    runtime.command = lambda *args, **kwargs: calls.append(args)
    with pytest.raises(OSError): runtime.launch('job', 'jit', 1, cpu='6', memory=str(3 * pool.GIB))
    assert calls == []


def test_reconcile_rechecks_inventory_before_registration(monkeypatch, tmp_path):
    import ephemeral_runner_autoscaler as scaler
    monkeypatch.setattr(scaler.Path, 'home', lambda: tmp_path)
    clock = iter([0, 60, 61])
    monkeypatch.setattr(scaler.time, 'monotonic', lambda: next(clock))
    samples = iter([evidence(), evidence(), evidence(identity=('raced',))])
    monkeypatch.setattr(pool, 'sample', lambda *args, **kwargs: next(samples))
    class GitHub:
        def queued_jobs(self, *args): return [1]
        def runners(self): return []
        def generate_jit(self, *args): pytest.fail('must not register on raced evidence')
    class Runtime:
        def instances(self): return []
        def reap(self, **kwargs): return []
    controller = scaler.Autoscaler(GitHub(), Runtime(), label='aigcnews-ci-ephemeral',
                                  prefix='job-', maximum=1, cpu='6', memory='3GiB',
                                  idle_timeout=scaler.timedelta(minutes=5))
    controller.shared_parent = '/not-a-live-pool'
    controller.adaptive = pool.AdaptiveAdmission()
    assert controller.reconcile(apply=True).spawn == 0
    assert controller.reconcile(apply=True).spawn == 0


def test_frozen_and_tagged_control_memory_is_retained():
    control = item('custom-control')
    control['status'] = 'FROZEN'
    control['expanded_config']['user.aigcnews.ci'] = 'true'
    assert pool.active([control]) == [control]
    from runner_resource_budget import reservations
    control['expanded_config']['limits.cpu.allowance'] = '50ms/100ms'
    assert reservations([control]) == (['custom-control'], .5, pool.GIB)
    control['status'] = 'STOPPED'
    assert pool.active([control]) == []


def test_inventory_fingerprint_ignores_live_telemetry_but_not_limits():
    first = item()
    first['state'] = {'cpu': {'usage': 1}}
    second = {**first, 'state': {'cpu': {'usage': 100}}}
    assert pool.fingerprint([first]) == pool.fingerprint([second])
    second = {**second, 'expanded_config': {**first['expanded_config'], 'limits.memory': '2GiB'}}
    assert pool.fingerprint([first]) != pool.fingerprint([second])


def owner_fixture(tmp_path, monkeypatch):
    root = tmp_path / 'cgroup'; root.mkdir()
    p = parent(root)
    proc = tmp_path / 'proc'; (proc / '42').mkdir(parents=True)
    (proc / '42/cgroup').write_text('0::/ci/supervisor')
    for name in ('supervisor', 'monitors'):
        child = p / name; child.mkdir()
        (child / 'memory.max').write_text(str(64 * 1024**2))
        (child / 'memory.swap.max').write_text('0')
        (child / 'cgroup.procs').write_text('42' if name == 'supervisor' else '')
    properties = {'ActiveState': 'active', 'ControlGroup': '/ci', 'MainPID': '42',
                  'InvocationID': 'verified-invocation', 'Delegate': 'yes'}
    monkeypatch.setattr(pool.subprocess, 'run', lambda *args, **kwargs: pool.subprocess.CompletedProcess(
        args, 0, '\n'.join(f'{k}={v}' for k, v in properties.items()), ''))
    return root, p, proc, properties


def test_owner_service_requires_identity_and_bounded_overhead(tmp_path, monkeypatch):
    root, p, proc, properties = owner_fixture(tmp_path, monkeypatch)
    identity, bound = pool.owner(p, 'ci.service', cgroup_root=root, proc=proc)
    assert identity[:2] == ('verified-invocation', 42)
    assert bound == 128 * 1024**2
    properties['InvocationID'] = 'replacement'
    assert pool.owner(p, 'ci.service', cgroup_root=root, proc=proc)[0] != identity
    properties['ActiveState'] = 'deactivating'
    with pytest.raises(ValueError): pool.owner(p, 'ci.service', cgroup_root=root, proc=proc)
    properties['ActiveState'] = 'active'
    (p / 'monitors/memory.max').write_text('max')
    with pytest.raises(ValueError): pool.owner(p, 'ci.service', cgroup_root=root, proc=proc)


def test_supervisor_cannot_hide_extra_processes(tmp_path, monkeypatch):
    root, p, proc, _ = owner_fixture(tmp_path, monkeypatch)
    (p / 'supervisor/cgroup.procs').write_text('42\n99')
    with pytest.raises(ValueError, match='unexpected supervisor'):
        pool.owner(p, 'ci.service', cgroup_root=root, proc=proc)


def test_monitor_pid_is_bound_and_overhead_counted(tmp_path, monkeypatch):
    root, p, proc, _ = owner_fixture(tmp_path, monkeypatch)
    (proc / '43').mkdir()
    (proc / '43/cgroup').write_text('0::/ci/aigcnews-ci/payload')
    (proc / '44').mkdir()
    (proc / '44/cgroup').write_text('0::/ci/monitors/aigcnews-ci')
    (proc / '44/cmdline').write_bytes(b'[lxc monitor] /var/snap/lxd/common/lxd/containers aigcnews-ci')
    monitor = p / 'monitors/aigcnews-ci'; monitor.mkdir()
    (monitor / 'cgroup.procs').write_text('44')
    child = p / 'aigcnews-ci'; child.mkdir()
    (child / 'memory.max').write_text(str(pool.GIB))
    monkeypatch.setattr(pool, 'lxc', lambda *args: {'pid': 43})
    assert pool.membership([item()], [], (), p, cgroup_root=root, proc=proc,
                           owner_unit='ci.service')[1] == pool.GIB + 128 * 1024**2
    (proc / '44/cmdline').write_bytes(b'unrelated-worker')
    with pytest.raises(ValueError, match='monitor PID'):
        pool.membership([item()], [], (), p, cgroup_root=root, proc=proc, owner_unit='ci.service')


def test_owner_stop_waits_for_payload_and_monitor_cleanup(tmp_path):
    import runner_pool_owner as keeper
    (tmp_path / 'supervisor').mkdir()
    (tmp_path / 'monitors').mkdir()
    (tmp_path / 'monitors/cgroup.procs').write_text('')
    assert keeper.drained(tmp_path)
    payload = tmp_path / 'job'; payload.mkdir()
    assert not keeper.drained(tmp_path)
    payload.rmdir()
    monitor = tmp_path / 'monitors/job'; monitor.mkdir()
    assert not keeper.drained(tmp_path)
    monitor.rmdir()
    assert keeper.drained(tmp_path)


def test_owner_never_resizes_existing_subgroups(tmp_path):
    import runner_pool_owner as keeper
    (tmp_path / 'supervisor').mkdir()
    (tmp_path / 'running-job').mkdir()
    with pytest.raises(ValueError, match='start empty'): keeper.prepare(tmp_path)
    assert not (tmp_path / 'cgroup.subtree_control').exists()


def test_expected_mihomo_target_is_verified_without_reconfiguration(tmp_path):
    import ephemeral_runner_autoscaler as scaler
    runtime = scaler.LxdRuntime('template', 'job-', tmp_path)
    runtime.expected_proxy_connect = 'tcp:127.0.0.1:17897'
    proxy = {'type': 'proxy', 'bind': 'container', 'listen': 'tcp:0.0.0.0:7895',
             'connect': runtime.expected_proxy_connect}
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        return scaler.subprocess.CompletedProcess(args, 0, pool.json.dumps(
            {'expanded_devices': {'egress-proxy': proxy}}).encode(), b'')
    runtime.command = command
    runtime.verify_proxy('template')
    proxy['connect'] = 'tcp:172.17.0.1:7897'
    with pytest.raises(scaler.AutoscalerError, match='accepted endpoint'):
        runtime.launch('new-job', 'jit', 1, cpu='1', memory='3GiB')
    assert all(call[0] == 'query' for call in calls)


def test_light_jobs_can_exceed_three_instances_without_static_reservations():
    policy = ready()
    state = evidence(memory=2 * pool.GIB, committed_memory=60 * pool.GIB,
                     predicted_growth=pool.GIB, startup_prediction=pool.GIB // 4)
    assert policy.decide(20, state, 60) == 1
    assert policy.decide(20, replace(state, bootstraps=2), 120) == 0
    assert policy.decide(20, replace(state, oom=True), 121) == 0


def test_task_predictions_learn_peaks_and_persist_oom_hold(tmp_path):
    from runner_workloads import History, category
    history = History(tmp_path / 'history.json')
    assert category({'name': 'Verify current PR base'}) == 'admission'
    assert category({'name': 'MCP Go build and tests'}) == 'mcp'
    assert category({'name': 'Frontend build'}) == 'frontend'
    assert history.predict('admission') < history.predict('frontend')
    history.observe('1', 'frontend', 4 * pool.GIB)
    assert history.predict('frontend') == 5 * pool.GIB
    history.oom('1', 1)
    history.save()
    restored = History(tmp_path / 'history.json')
    assert restored.predict('frontend') == 5 * pool.GIB
    assert restored.data['oom'] == {'1': 1}


def test_mixed_queue_uses_largest_eligible_prediction_and_control_not_bootstrap(tmp_path):
    from runner_workloads import History
    history = History(tmp_path / 'history.json')
    child = tmp_path / 'aigcnews-ci'; child.mkdir()
    for name, value in [('memory.current', '1000'), ('memory.peak', '2000'), ('memory.events', 'oom_kill 0')]:
        (child / name).write_text(value)
    queue = [{'id': 1, 'name': 'Verify current PR base', 'status': 'queued'},
             {'id': 2, 'name': 'Backend tests', 'status': 'queued'}]
    runners = [{'id': 22, 'labels': [{'name': 'aigcnews-control'}]}]
    growth, startup, bootstraps, oom = pool.workload_evidence([item()], queue, tmp_path, history, runners)
    assert startup == 2 * pool.GIB
    assert 0 < growth < pool.GIB
    assert bootstraps == 0 and not oom


def test_parent_high_is_required(tmp_path):
    p = parent(tmp_path)
    (p / 'memory.high').write_text('max')
    with pytest.raises(ValueError): pool.limits(p)


def test_memory_high_accepts_kernel_downward_page_rounding_only(tmp_path):
    p = parent(tmp_path)
    high = int(12 * pool.GIB * .9)
    (p / 'memory.high').write_text(str(high // 4096 * 4096))
    pool.limits(p)
    (p / 'memory.high').write_text(str(high + 1))
    with pytest.raises(ValueError): pool.limits(p)


@pytest.mark.parametrize('field', ['predicted_growth', 'startup_prediction', 'bootstraps', 'memory_ceiling'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1])
def test_invalid_prediction_evidence_never_admits(field, value):
    with pytest.raises(ValueError): ready().decide(10, evidence(**{field: value}), 60)


@pytest.mark.parametrize("inherited_runtime", [None, "/nonexistent-runner-runtime"])
def test_staging_installer_imports_operator_tools_without_activation(tmp_path, monkeypatch, inherited_runtime):
    import os
    import subprocess
    if inherited_runtime is None:
        monkeypatch.delenv('XDG_RUNTIME_DIR', raising=False)
    else:
        monkeypatch.setenv('XDG_RUNTIME_DIR', inherited_runtime)
    stage = tmp_path / 'stage'
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    calls = tmp_path / 'commands.log'
    script = r'''set -euo pipefail
map_args() {
  mapped=()
  for arg in "$@"; do
    mapped+=("${arg//$HOME\/.local\/lib\/aigcnews-ci-autoscaler/$TASK_STAGE}")
  done
}
mkdir() { map_args "$@"; command mkdir "${mapped[@]}"; }
install() { map_args "$@"; command install "${mapped[@]}"; }
systemctl() {
  echo "systemctl $*" >> "$TASK_COMMANDS"
  [[ "$*" == '--user is-active aigcnews-ci-autoscaler.service' ]] || exit 91
  echo inactive
  return 3
}
deny_mutation() { echo "forbidden $*" >> "$TASK_COMMANDS"; exit 92; }
chmod() { deny_mutation chmod "$@"; }
chown() { deny_mutation chown "$@"; }
chgrp() { deny_mutation chgrp "$@"; }
setfacl() { deny_mutation setfacl "$@"; }
loginctl() { deny_mutation loginctl "$@"; }
sudo() { deny_mutation sudo "$@"; }
source scripts/ci/install_shared_runner_pool.sh
python3 "$TASK_STAGE/review_pool_recovery.py" --help
python3 -c "import sys; sys.path.insert(0, sys.argv[1]); import check_shared_runner_pool, review_pool_recovery, autoscaler" "$TASK_STAGE"
'''
    # Only install/mkdir destinations are redirected. HOME and live services
    # remain untouched; real systemd-analyze verifies the staged unit.
    result = subprocess.run(['bash', '-c', script], cwd=Path(__file__).parents[2],
                            env={**os.environ, 'TASK_STAGE': str(stage),
                                 'TASK_COMMANDS': str(calls), 'XDG_RUNTIME_DIR': str(runtime),
                                 'XDG_CONFIG_HOME': str(tmp_path / 'config')},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text().splitlines() == [
        'systemctl --user is-active aigcnews-ci-autoscaler.service']
    assert runtime.stat().st_mode & 0o777 == 0o700
    assert (stage / 'ephemeral_runner_autoscaler.py').is_file()
    dependency = (tmp_path / 'config/systemd/user/aigcnews-ci-autoscaler.service.d/shared-pool.conf').read_text()
    assert 'BindsTo=aigcnews-ci-pool.service' in dependency


def test_persistence_preflight_reads_existing_policy_without_enabling_linger(monkeypatch):
    import check_shared_runner_pool as preflight
    calls = []
    def read(args, **kwargs):
        calls.append(args)
        return 'Linger=yes\nState=active\nRuntimePath=/run/user/1000\n'
    monkeypatch.setattr(preflight.subprocess, 'check_output', read)
    assert preflight.persistence()['Linger'] == 'yes'
    assert calls[0][:2] == ['loginctl', 'show-user']
    monkeypatch.setattr(preflight.subprocess, 'check_output', lambda *args, **kwargs: 'Linger=no\n')
    with pytest.raises(ValueError, match='persistence'): preflight.persistence()
