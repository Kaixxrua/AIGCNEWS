#!/usr/bin/env python3
"""Trusted host-side Contract Baseline runner (never execute this from a candidate).

CLI: --repository PATH --sha FULL_SHA --output RECEIPT --config TRUSTED_JSON.
Config required: baseline_repository, baseline_sha, state_dir, shared_parent,
shared_unit, template, network, proxy_connect, tool_path. Optional:
admission_timeout=600, settling_seconds=60, command_timeout=180,
check_timeout=1800. All paths are absolute. Config/state/output must be outside
candidate checkout, private and owned by the controller. Install this module and
shared_runner_pool/runner_resource_budget/runner_pool_receipts/runner_workloads
from the trusted baseline, with PyYAML available on the host.

The trusted workflow supplies ALL substantive run steps. Candidate tests and CI
code may change normally. Only invoked gate helpers, tool configuration and npm
scripts are overlaid from the pinned baseline, whose promotion is explicit via
baseline_sha. The receipt records all overlays. GitHub PR admission is replaced
by exact local SHA validation; base freshness belongs to the controller.
Exit 0 = success, 1 = persisted failure/error, 2 = denied or prior failed attempt.
Consumers must require exit 0, exact SHA, all checks successful and cleanup success. Receipts are
immutable per repository/SHA/config; all workers must share state_dir; restarting an incomplete run FAILS CLOSED,
reaps only its owned job clones, and returns the same durable receipt (no new run).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import shlex
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import shared_runner_pool as pool


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


JOBS = ('backend-tests', 'postgres-integration', 'mcp-go', 'compose-smoke', 'frontend-build')
WORKFLOW = '.github/workflows/contract-baseline.yml'
SHA = re.compile(r'[0-9a-f]{40}')


TRANSIENT_DOWNLOAD = re.compile(
    r'(?i)(?:unexpected EOF|\bEOF\b|connection reset|temporary failure in name resolution|'
    r'TLS handshake timeout|i/o timeout|EAI_AGAIN|ECONNRESET|ETIMEDOUT|EIDLETIMEOUT|'
    r'502 Bad Gateway|503 Service Unavailable|504 Gateway Timeout)')


def retryable_download(key, step, output):
    # Never replay test suites, migrations, or checksum/integrity failures.
    allowed = (step.startswith('Install ') or step == 'Build frontend image from clean checkout'
               or (key == 'mcp-go' and step in ('Verify go.mod/go.sum tidy', 'Build', 'Vet')))
    denied = re.search(r'(?i)checksum mismatch|SECURITY ERROR|integrity checksum|EINTEGRITY', output)
    return bool(allowed and not denied and TRANSIENT_DOWNLOAD.search(output))


# Read-only verification steps whose outputs are not needed by subsequent steps.
# Dependency installation, fixtures, builds and DB operations must execute anew.
REUSABLE_STEPS = {
    'backend-tests': {'Lint backend with ruff'},
    'frontend-build': {'Run frontend unit tests', 'Lint frontend', 'Type-check frontend'},
    'mcp-go': {'Vet', 'Test (parity corpus gate included)'},
}


def step_cache(path, identity):
    try:
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
        value = json.loads(path.read_text())
        if value['key'] != identity or not 0 <= time.time() - value['at'] <= 3600:
            return None
        if value.get('cleanup') != 'success' or value.get('oom_kill', 0):
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def verification_key(repository, sha, config, state, key):
    # Full tree is conservative: even an unrelated source edit invalidates reuse.
    # Commit messages/parents may change without invalidating identical content.
    payload = [git(repository, 'rev-parse', sha + '^{tree}').decode().strip(),
               config, state['workflow_sha256'], state['controls'], key,
               hashlib.sha256(Path(__file__).read_bytes()).hexdigest()]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def cached_check(path, identity):
    try:
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
        value = json.loads(path.read_text())
        check = value['check']
        if (value['key'] != identity or not 0 <= time.time() - value['at'] <= 3600
                or check['conclusion'] != 'success' or check['cleanup'] != 'success'
                or check.get('oom_kill', 0) or not check.get('steps')
                or any(x.get('conclusion') != 'success' for x in check['steps'])):
            return None
        return check
    except (OSError, ValueError, KeyError, TypeError):
        return None


def command(argv, *, timeout=180, data=None, log=None):
    # Never inherit host credentials/proxies/Docker/Git configuration into jobs.
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'XDG_RUNTIME_DIR',
                                      'DBUS_SESSION_BUS_ADDRESS') if k in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_NO_REPLACE_OBJECTS='1')
    with subprocess.Popen(argv, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                          stdout=log or subprocess.PIPE, stderr=subprocess.STDOUT,
                          env=env, start_new_session=True) as process:
        try:
            output, _ = process.communicate(data, timeout=timeout)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        if process.returncode:
            raise RuntimeError(f'command failed ({process.returncode}): {argv[:3]}: '
                               + (output or b'').decode(errors='replace')[-4000:])
        return output or b''


def git(repository, *args):
    return command(['git', '-C', str(repository), *args])


def exact_sha(repository, sha):
    if not SHA.fullmatch(sha):
        raise ValueError('full lowercase 40-character commit SHA required')
    if git(repository, 'rev-parse', '--verify', sha + '^{commit}').decode().strip() != sha:
        raise ValueError('commit identity mismatch')


def tree(repository, sha):
    entries = git(repository, 'ls-tree', '-r', '-z', sha).split(b'\0')
    result = {}
    for entry in filter(None, entries):
        info, path = entry.split(b'\t', 1)
        mode, kind, digest = info.decode().split()
        path = path.decode()
        # Reject archive symlink/submodule escapes; don't resolve candidate links on host.
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError(f'unsupported archive entry: {path}')
        result[path] = (mode, digest)
    return result


def verify_archive(path, files):
    """No export-ignore/export-subst or archive links may alter the tested tree."""
    seen = set()
    with tarfile.open(path) as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile() or member.name not in files or member.name in seen:
                raise ValueError('unsafe or unexpected archive member')
            data = archive.extractfile(member).read()
            digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if digest != files[member.name][1]:
                raise ValueError('archive differs from exact SHA')
            seen.add(member.name)
    if seen != files.keys():
        raise ValueError('archive omitted tracked files')


def workflow(repository, sha, config):
    import yaml
    baseline = Path(config['baseline_repository'])
    trusted_sha = config['baseline_sha']
    exact_sha(baseline, trusted_sha)
    raw = git(baseline, 'show', f'{trusted_sha}:{WORKFLOW}')
    spec = yaml.safe_load(raw)
    if set(spec['jobs']) != {*JOBS, 'pr-admission'}:
        raise ValueError('unsupported Contract Baseline jobs; update trusted runner')
    for key in JOBS:
        job = spec['jobs'][key]
        if any(k in job for k in ('if', 'strategy', 'container')):
            raise ValueError('unsupported conditional/matrix/container job')
        for step in job['steps']:
            if any(k in step for k in ('if', 'continue-on-error')):
                raise ValueError('conditional or optional gate rejected')
            if 'run' not in step and step.get('uses') not in {
                'actions/checkout@v4', './.github/actions/check-pr-base',
                'actions/setup-python@v5', 'actions/setup-go@v5', 'actions/setup-node@v4'}:
                raise ValueError('unsupported workflow action')
    return spec['jobs'], hashlib.sha256(raw).hexdigest()


def controls_archive(repository, sha, config, destination):
    """Freeze gate commands/helpers, not candidate test contents or CI modules."""
    baseline, rev = config['baseline_repository'], config['baseline_sha']
    files = tree(baseline, rev)
    controls = {}
    for path in files:
        name = Path(path).name
        if (path == 'scripts/ci/materialize_ui_catalog_fixture.py'
                or path.startswith('frontend/scripts/')
                or path == WORKFLOW
                or name in {'pytest.ini', 'pyproject.toml', '.coveragerc', 'ruff.toml', '.ruff.toml'}
                or (path.startswith('frontend/') and '/' not in path[len('frontend/'):]
                    and ('.config.' in name or name.startswith('tsconfig')))):
            controls[path] = git(baseline, 'show', f'{rev}:{path}')
    package = json.loads(git(repository, 'show', f'{sha}:frontend/package.json'))
    trusted_package = json.loads(git(baseline, 'show', f'{rev}:frontend/package.json'))
    package['scripts'] = trusted_package.get('scripts', {})
    controls['frontend/package.json'] = (json.dumps(package, indent=2) + '\n').encode()
    # Candidate npm config must not change script-shell or suppress gate execution.
    for path in ('.npmrc', 'frontend/.npmrc'):
        controls[path] = git(baseline, 'show', f'{rev}:{path}') if path in files else b''
    with tarfile.open(destination, 'w') as archive:
        for path, content in controls.items():
            item = tarfile.TarInfo(path)
            item.size = len(content)
            item.mode = 0o755 if files.get(path, ('100644',))[0] == '100755' else 0o644
            archive.addfile(item, io.BytesIO(content))
    return {path: hashlib.sha256(content).hexdigest() for path, content in controls.items()}


def trusted_config(path, repository, output):
    path = path.resolve()
    if path.is_relative_to(repository.resolve()):
        raise ValueError('config must be outside candidate repository')
    stat = path.stat()
    if stat.st_uid not in (0, os.getuid()) or stat.st_mode & 0o022:
        raise ValueError('config must have trusted owner and no group/other writes')
    config = json.loads(path.read_text())
    for key in ('baseline_repository', 'baseline_sha', 'state_dir', 'shared_parent',
                'shared_unit', 'template', 'network', 'proxy_connect', 'tool_path'):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ValueError(f'missing configuration: {key}')
    for key in ('baseline_repository', 'state_dir', 'shared_parent'):
        if not Path(config[key]).is_absolute():
            raise ValueError(f'{key} must be absolute')
    for p in (Path(config['state_dir']).resolve(), output.resolve()):
        if p.is_relative_to(repository.resolve()):
            raise ValueError('receipt/state must be outside candidate checkout')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', config['template']):
        raise ValueError('invalid template name')
    for key, default in (('admission_timeout', 600), ('settling_seconds', 60),
                         ('queue_timeout', 3600), ('command_timeout', 180), ('check_timeout', 1800)):
        value = config.setdefault(key, default)
        if type(value) is not int or not 1 <= value <= 7200:
            raise ValueError(f'invalid timeout: {key}')
    snapshot = config.get('template_snapshot')
    if snapshot:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', snapshot):
            raise ValueError('invalid template snapshot')
        raw = json.loads(command(['lxc', 'query', f"/1.0/instances/{config['template']}/snapshots/{snapshot}"]))
        config['verification_environment_digest'] = hashlib.sha256(
            json.dumps(raw, sort_keys=True).encode()).hexdigest()
    return config


def validate_instance(item, config, *, clone=False):
    settings = item['expanded_config']
    if settings.get('security.privileged', 'false') != 'false':
        raise ValueError('privileged template/clone forbidden')
    for key, value in settings.items():
        if (value and (key.startswith(('raw.', 'cloud-init.', 'user.user-data', 'user.vendor-data'))
                       or key == 'security.protection.delete')
                and (key != 'raw.lxc' or not clone)):
            raise ValueError(f'unsafe template setting {key}')
    if clone and settings.get('raw.lxc') != pool.parent_config(
            Path(config['shared_parent']), item['name'], ''):
        raise ValueError('clone cgroup placement changed')
    devices = item['expanded_devices']
    expected = {
        'root': {'type': 'disk', 'path': '/', 'pool': devices.get('root', {}).get('pool')},
        'eth0': {'type': 'nic', 'name': 'eth0', 'network': config['network']},
        'egress-proxy': {'type': 'proxy', 'bind': 'container',
                         'connect': config['proxy_connect'], 'listen': 'tcp:0.0.0.0:7895'},
    }
    if not expected['root']['pool'] or devices != expected:
        raise ValueError('template/clone devices include unapproved mounts or network')
    if not clone and item['status'].upper() != 'STOPPED':
        raise ValueError('template must be stopped')


class Runner:
    def __init__(self, config, state, log):
        self.config, self.state, self.log = config, state, log
        self.name = state['instance']
        self.progress = lambda steps: None

    def lxc(self, *args, data=None, timeout=None):
        return command(['lxc', *args], timeout=timeout or self.config['command_timeout'],
                       data=data)

    def info(self, name):
        return json.loads(self.lxc('query', f'/1.0/instances/{name}'))

    def shell(self, script, *, timeout=None):
        return command(['lxc', 'exec', self.name, '--', 'env', '-i',
                        'HOME=/root', 'PATH=/ci/venv/bin:' + self.config['tool_path'],
                        'GOPROXY=https://proxy.golang.org|https://goproxy.cn|direct',
                        'bash', '--noprofile', '--norc', '-euo', 'pipefail', '-s'],
                       data=script.encode(), timeout=timeout or self.config['command_timeout'],
                       log=self.log)

    def admit(self):
        policy = pool.AdaptiveAdmission(settling_seconds=self.config['settling_seconds'])
        deadline = time.monotonic() + self.config['admission_timeout']
        last_error = ''
        while time.monotonic() < deadline:
            try:
                evidence = pool.sample(self.config['shared_parent'], [], (),
                                       owner_unit=self.config['shared_unit'])
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                last_error = str(exc)
                self.log.write(('Admission evidence unavailable: ' + last_error + '\n').encode())
                self.log.flush()
                policy = pool.AdaptiveAdmission(settling_seconds=self.config['settling_seconds'])
                time.sleep(2)
                continue
            if policy.decide(1, evidence, time.monotonic()):
                return evidence
            time.sleep(2)
        raise TimeoutError('shared pool admission timed out; no runner interrupted; ' + last_error)

    def verify_membership(self):
        for attempt in range(3):
            try:
                pool.membership(pool.inventory(), [], (), Path(self.config['shared_parent']),
                                owner_unit=self.config['shared_unit'])
                break
            except ValueError as exc:
                # LXD list/state can straddle another clone's start/cleanup.
                # Re-sample read-only evidence; never waive membership checks.
                if str(exc) != 'missing CI init PID' or attempt == 2:
                    raise
                time.sleep(1)


    def launch(self):
        validate_instance(self.info(self.config['template']), self.config)
        self.admit()
        source = self.config['template'] + ('/' + self.config['template_snapshot'] if self.config.get('template_snapshot') else '')
        self.lxc('copy', source, self.name, '--config',
                 'user.aigcnews.local_ci=' + self.state['run_id'])
        settings = {'boot.autostart': 'false', 'user.aigcnews.ci': 'true',
                    'user.aigcnews.local_ci': self.state['run_id'],
                    'user.aigcnews.runner_id': str(-int(self.state['run_id'][:12], 16)),
                    'limits.cpu': '6', 'limits.cpu.allowance': '100%',
                    'limits.cpu.priority': '5', 'limits.memory': '12GiB',
                    'limits.memory.swap': 'false', 'security.privileged': 'false',
                    'raw.lxc': pool.parent_config(Path(self.config['shared_parent']), self.name, '')}
        self.lxc('config', 'set', self.name,
                 *(key + '=' + value for key, value in settings.items()))
        validate_instance(self.info(self.name), self.config, clone=True)
        # Prevent cloned runner units from registering/starting before any boot.
        self.lxc('file', 'push', '-p', '-',
                 f'{self.name}/etc/systemd/system/aigcnews-ephemeral-runner.service',
                 data=b'[Unit]\nConditionPathExists=/run/local-ci-never-start-jit\n[Service]\nExecStart=/bin/false\n')
        self.lxc('start', self.name)
        pool.limits(Path(self.config['shared_parent']))
        self.verify_membership()

    def initialize(self):
        # Only clone-local bootstrap remains; admission/membership stay serialized.
        # LXD exec can run before boot-time tmpfiles cleanup removes /tmp.
        # Wait for that unit before ensurepip stages its wheel there.
        self.shell('systemctl start systemd-tmpfiles-setup.service\n')
        self.shell('''
# Clone only; no host directories/sockets are mounted.
systemctl disable --now 'actions.runner.*.service' 2>/dev/null || true
# Retain toolchains under /opt, but no inherited home credentials or startup files.
find /root /home -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
mkdir -p /home/runner
chown runner:runner /home/runner
rm -f /opt/actions-runner/.credentials* /opt/actions-runner/.runner* /run/aigcnews-jitconfig
rm -rf /opt/actions-runner/_work/* /opt/actions-runner/_diag/*
mkdir -p /ci /ci/tmp
python -c 'import sys; assert sys.version_info[:2] == (3, 12)'
python -m venv --system-site-packages /ci/venv
node --version | grep '^v22\\.'
go version | grep 'go1.26\\.'
systemctl start docker
for i in {1..30}; do docker info >/dev/null 2>&1 && break; sleep 1; done
docker info >/dev/null
''')

    def cleanup(self):
        items = json.loads(self.lxc('list', '--format=json'))
        found = next((i for i in items if i['name'] == self.name), None)
        if found is None:
            return
        if found['expanded_config'].get('user.aigcnews.local_ci') != self.state['run_id']:
            raise ValueError('cleanup ownership mismatch; container preserved')
        self.lxc('delete', '--force', self.name)

    def check(self, key, job, archive):
        self.lxc('file', 'push', str(archive), f'{self.name}/ci/source.tar')
        self.lxc('file', 'push', self.state['controls_archive'], f'{self.name}/ci/controls.tar')
        # Each job gets a fresh tree (and Go tidy gets a real clean Git index).
        self.shell('rm -rf /ci/work; mkdir /ci/work; tar -xf /ci/source.tar -C /ci/work\n'
                   'tar -xf /ci/controls.tar -C /ci/work\n'
                   'cd /ci/work; git init -q; git add -A\n'
                   'git -c user.name=CI -c user.email=ci@localhost commit -qm baseline\n')
        env = {'GITHUB_WORKSPACE': '/ci/work', 'RUNNER_TEMP': '/ci/tmp',
               'GOPROXY': 'https://proxy.golang.org|https://goproxy.cn|direct',
               'CI': 'true', 'HTTP_PROXY': 'http://127.0.0.1:7895',
               'HTTPS_PROXY': 'http://127.0.0.1:7895', 'NO_PROXY': 'localhost,127.0.0.1,::1',
               'RUNNER_TOOL_CACHE': '/opt/hostedtoolcache',
               # Immutable template seed; each disposable clone owns all writes.
               'GOMODCACHE': '/opt/aigcnews-dependencies/go',
               'GOCACHE': '/ci/go-build',
               'npm_config_cache': '/opt/aigcnews-dependencies/npm',
               'npm_config_prefer_offline': 'true', 'npm_config_audit': 'false',
               'npm_config_fetch_timeout': '30000',
               'PIP_CACHE_DIR': '/opt/aigcnews-dependencies/pip',
               'PIP_FIND_LINKS': '/opt/aigcnews-dependencies/wheels',
               'PIP_DEFAULT_TIMEOUT': '30',
               'UV_CACHE_DIR': '/opt/aigcnews-dependencies/uv'}
        env.update(job.get('env', {}))
        if key == 'postgres-integration':
            env['TEST_POSTGRES_RUN_ID'] = 'local-' + self.state['run_id']
            service = job['services']['postgres']
            self.shell('docker run -d --name local-ci-postgres -p 127.0.0.1:5432:5432 '
                       + ' '.join('-e ' + shlex.quote(k + '=' + str(v)) for k, v in service['env'].items())
                       + ' ' + shlex.quote(service['image']) + '\n'
                       'for i in {1..40}; do docker exec local-ci-postgres pg_isready '
                       '-U aigcnews_test -d aigcnews_test && exit 0; sleep 2; done; exit 1')
        deadline = time.monotonic() + min(job['timeout-minutes'] * 60, self.config['check_timeout'])
        results = [{'name': step['name'], 'conclusion': 'pending'}
                   for step in job['steps'] if 'run' in step]
        self.progress(results)
        index = 0
        for step in job['steps']:
            if 'run' not in step:
                continue
            values = env | step.get('env', {})
            if any('${{' in str(v) for v in values.values()) or '${{' in step['run']:
                raise ValueError('unhandled GitHub expression')
            cwd = step.get('working-directory', job.get('defaults', {}).get('run', {}).get('working-directory', '.'))
            if Path(cwd).is_absolute() or '..' in Path(cwd).parts:
                raise ValueError('invalid workflow working directory')
            script = '\n'.join('export ' + k + '=' + shlex.quote(str(v)) for k, v in values.items())
            script += '\ncd ' + shlex.quote('/ci/work/' + cwd) + '\n' + step['run']
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'{key} timed out')
            self.log.write(('\nSTEP ' + key + ': ' + step['name'] + '\n').encode())
            self.log.flush()
            result = results[index]
            previous = self.state.get('step_reuse', {}).get(step['name'])
            if previous and step['name'] in REUSABLE_STEPS.get(key, set()):
                result.update(conclusion='success', reused_from=previous)
                self.progress(results)
                index += 1
                continue
            result.update(conclusion='running', started_at=time.time())
            self.progress(results)
            try:
                for attempt in range(1, 4):
                    offset = self.log.tell()
                    result['attempts'] = attempt
                    self.progress(results)
                    try:
                        self.shell(script, timeout=max(1, deadline - time.monotonic()))
                        break
                    except RuntimeError:
                        self.log.flush()
                        with Path(self.log.name).open('rb') as evidence:
                            evidence.seek(offset)
                            output = evidence.read()[-65536:].decode(errors='replace')
                        if (attempt == 3 or deadline - time.monotonic() < 10
                                or not retryable_download(key, step['name'], output)):
                            raise
                        self.log.write(f'\nTransient download failure; retry {attempt + 1}/3\n'.encode())
                        time.sleep(attempt * 2)
                result['conclusion'] = 'success'
            except BaseException as exc:
                result.update(conclusion='failure', error=f'{type(exc).__name__}: {exc}')
                raise
            finally:
                result['finished_at'] = time.time()
                self.progress(results)
            index += 1
        if not results:
            raise ValueError('empty gate')
        return results


@contextmanager
def admission_lock(root, timeout):
    """Serialize sample/settle/create/start only; never hold during job checks.

    All local workers for a pool must share state_dir. Waits are bounded and
    interruptible; after acquiring the lock launch performs fresh pool sampling
    and restart warmup, including containers started by earlier workers.
    """
    with (root / 'admission.lock').open('a') as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('shared admission lock timed out; no automatic replay') from None
                time.sleep(.2)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Progress:
    """Serialize per-job receipts and aggregate progress within one identity."""
    def __init__(self, state, receipt, output):
        self.state, self.receipt, self.output = state, receipt, output
        self.lock = threading.RLock()

    def publish(self):
        with self.lock:
            for check in self.state['checks']:
                if 'receipt' in check:
                    atomic_json(Path(check['receipt']), check)
            atomic_json(self.receipt, self.state)
            atomic_json(self.output, self.state)

    def update(self, check, **changes):
        with self.lock:
            # Step lists are private to Runner; freeze before another step mutates.
            check.update(json.loads(json.dumps(changes)))
            check['status'] = check['conclusion']
            self.publish()


def launch_with_retry(runner, config, check, progress):
    """Retry only before launch; a partial launch must be cleaned, never replayed."""
    budget = config.get('queue_timeout', 3600)
    deadline = time.monotonic() + budget
    history = []
    for attempt in range(1, 4):
        entered = False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('admission retry budget exhausted')
        progress.update(check, admission_attempt=attempt, admission_history=list(history),
                        retry_at=None, conclusion='admitting')
        try:
            with admission_lock(Path(config['state_dir']), min(budget / 3, remaining)):
                entered = True
                progress.update(check, admission_acquired_at=time.time(), phase='launching')
                runner.launch()
            return
        except TimeoutError as exc:
            if entered:
                raise
            history.append({'attempt': attempt, 'error': str(exc), 'at': time.time()})
            delay = min(2 ** attempt, max(0, deadline - time.monotonic()))
            progress.update(check, admission_history=list(history),
                            retry_at=time.time() + delay if attempt < 3 else None)
            if attempt == 3 or delay <= 0:
                raise
            time.sleep(delay)


def run_job(config, state, check, job, archive, progress):
    with Path(check['log']).open('ab') as log:
        runner = Runner(config, {**state, **check}, log)
        runner.progress = lambda steps: progress.update(check, steps=steps)
        try:
            progress.update(check, conclusion='admitting', started_at=time.time())
            launch_with_retry(runner, config, check, progress)
            progress.update(check, launched_at=time.time(), phase='initializing')
            runner.initialize()
            progress.update(check, initialized_at=time.time(), phase='checking')
            with progress.lock:
                state.update(ready=True, ready_at=state.get('ready_at', time.time()))
                progress.update(check, ready=True, conclusion='running')
            steps = runner.check(check['id'], job, archive)
            child = Path(config['shared_parent']) / runner.name
            oom = int(pool.counters(child / 'memory.events').get('oom_kill', 0))
            progress.update(check, steps=steps, oom_kill=oom)
            if oom:
                raise RuntimeError('job container experienced OOM')
            if not steps or any(step['conclusion'] != 'success' for step in steps):
                raise RuntimeError('job steps incomplete')
            progress.update(check, conclusion='success')
        except BaseException as exc:  # noqa: BLE001 - preserve failed job and reclaim its clone
            error = f'{type(exc).__name__}: {exc}'
            log.write((error + '\n').encode())
            progress.update(check, conclusion='failure', error=error)
        finally:
            try:
                runner.cleanup()
                progress.update(check, cleanup='success')
            except Exception as exc:  # noqa: BLE001 - failed cleanup forbids success
                progress.update(check, conclusion='error', cleanup='failure', cleanup_error=str(exc))
            progress.update(check, finished_at=time.time())


def recover(config, state, progress):
    """Reap all recorded clones after interruption; never launch/replay jobs.

    A v1 receipt is still understood, allowing rollout without replacing the
    identity or accidentally rerunning an existing candidate.
    """
    checks = state['checks'] if state.get('schema_version') == 2 else [state]
    interrupted = state['conclusion'] == 'running'
    errors = []
    for check in checks:
        if 'instance' not in check:
            continue
        try:
            with Path(check['log']).open('ab') as log:
                Runner(config, {**state, **check}, log).cleanup()
            if interrupted:
                check['cleanup'] = 'success'
                if check.get('conclusion') not in ('success', 'failure', 'error'):
                    check['conclusion'] = 'interrupted'
        except Exception as exc:  # noqa: BLE001 - attempt other owned clones too
            check.update(cleanup='failure', cleanup_error=str(exc))
            errors.append(str(exc))
        if check is not state:
            check['status'] = check['conclusion']
    if interrupted:
        state.update(conclusion='interrupted', error='previous attempt interrupted; no automatic replay')
    if errors:
        state.update(conclusion='error', cleanup='failure', cleanup_error='; '.join(errors))
    elif interrupted:
        state['cleanup'] = 'success'
    state['status'] = state['conclusion']
    progress.publish()
    return 0 if state['status'] == 'success' else 2


def execute(repository, sha, output, config, selected=None, preflight=False):
    repository, output = Path(repository).resolve(), Path(output).resolve()
    selected = tuple(selected or JOBS)
    if not selected or len(set(selected)) != len(selected) or any(k not in JOBS for k in selected):
        raise ValueError('invalid selected checks')
    root = Path(config['state_dir'])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError('state directory must be private and controller-owned')
    identity = hashlib.sha256(json.dumps([str(repository), sha, config] + ([list(selected)] if selected != JOBS else []) + (['preflight'] if preflight else []), sort_keys=True).encode()).hexdigest()
    receipt_path = root / (identity + '.json')
    with (root / (identity + '.execution.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if receipt_path.exists():
            state = json.loads(receipt_path.read_text())
            return recover(config, state, Progress(state, receipt_path, output))
        state = {'schema_version': 2, 'sha': sha, 'repository': str(repository),
                 'preflight': preflight, 'baseline_sha': config['baseline_sha'], 'run_id': uuid.uuid4().hex,
                 'config_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                 'conclusion': 'running', 'status': 'running', 'ready': False,
                 'checks': [], 'log': str(root / (identity + '.log')), 'started_at': time.time()}
        progress = Progress(state, receipt_path, output)
        progress.publish()
        with Path(state['log']).open('ab') as log:
            try:
                exact_sha(repository, sha)
                jobs, digest = workflow(repository, sha, config)
                state['workflow_sha256'] = digest
                archive = root / (identity + '.tar')
                with archive.open('wb') as stream:
                    command(['git', '-C', str(repository), 'archive', '--format=tar', sha], log=stream)
                verify_archive(archive, tree(repository, sha))
                control_path = root / (identity + '.controls.tar')
                state['controls'] = controls_archive(repository, sha, config, control_path)
                state['controls_archive'] = str(control_path)
                job_root = root / (identity + '.jobs')
                job_root.mkdir(mode=0o700, exist_ok=True)
                for key in selected:
                    run_id = uuid.uuid4().hex
                    state['checks'].append({
                        'name': jobs[key]['name'], 'id': key, 'sha': sha,
                        'run_id': run_id, 'candidate_run_id': state['run_id'],
                        'instance': 'aigcnews-ci-local-' + run_id,
                        'conclusion': 'pending', 'status': 'pending', 'cleanup': 'pending', 'ready': False,
                        'steps': [], 'log': str(job_root / (key + '.log')),
                        'receipt': str(job_root / (key + '.json'))})
                cache_root = root / 'verified-checks'
                cache_root.mkdir(mode=0o700, exist_ok=True)
                for check in state['checks']:
                    fingerprint = verification_key(repository, sha, config, state, check['id'])
                    check['verification_key'] = fingerprint
                    step_path = cache_root / (fingerprint + '.steps.json')
                    step_proof = (step_cache(step_path, fingerprint)
                                  if re.fullmatch(r'[0-9a-f]{64}', config.get('verification_environment_digest', ''))
                                  else None)
                    check['step_reuse'] = (step_proof or {}).get('steps', {})
                    prior = (cached_check(cache_root / (fingerprint + '.json'), fingerprint)
                             if re.fullmatch(r'[0-9a-f]{64}', config.get('verification_environment_digest', ''))
                             else None)
                    if prior and not preflight:
                        check.update(conclusion='success', status='success', cleanup='success',
                                     ready=True, steps=prior['steps'], oom_kill=0,
                                     reused_from={'sha': prior['sha'], 'run_id': prior['run_id']})
                        check.pop('instance', None)
                        state['ready'] = True
                if preflight:
                    # Run prerequisites through the last reusable verification step.
                    # Unselected later gates stay absent, never report partial CI as full.
                    for key in selected:
                        runnable = jobs[key]['steps']
                        indexes = [i for i, st in enumerate(runnable)
                                   if st.get('name') in REUSABLE_STEPS.get(key, set())]
                        if not indexes:
                            raise ValueError('no reusable preflight steps for ' + key)
                        jobs[key] = {**jobs[key], 'steps': runnable[:max(indexes) + 1]}
                progress.publish()  # Persist ownership of all five clones before any launch.
                # Five job orchestrators, not a CPU allocation. Every launch still
                # passes the same measured shared-pool admission and hard ceiling.
                with ThreadPoolExecutor(max_workers=len(JOBS)) as workers:
                    futures = [workers.submit(run_job, config, state, check, jobs[check['id']], archive, progress)
                               for check in state['checks'] if not check.get('reused_from')]
                    for future in futures:
                        future.result()
                for check in state['checks']:
                    if (not preflight and not check.get('reused_from') and check['conclusion'] == 'success'
                            and check['cleanup'] == 'success'):
                        atomic_json(cache_root / (check['verification_key'] + '.json'),
                                    {'key': check['verification_key'], 'at': time.time(), 'check': check})
                    if check['cleanup'] == 'success' and not check.get('oom_kill'):
                        completed = {step['name']: {'sha': sha, 'run_id': check['run_id']}
                                     for step in check['steps'] if step.get('conclusion') == 'success'
                                     and not step.get('reused_from')
                                     and step['name'] in REUSABLE_STEPS.get(check['id'], set())}
                        if completed:
                            atomic_json(cache_root / (check['verification_key'] + '.steps.json'),
                                        {'key': check['verification_key'], 'at': time.time(),
                                         'cleanup': 'success', 'oom_kill': 0, 'steps': completed})
                state['oom_kill'] = sum(c.get('oom_kill', 0) for c in state['checks'])
                clean = all(c['cleanup'] == 'success' for c in state['checks'])
                passed = all(c['conclusion'] == 'success' for c in state['checks'])
                state['cleanup'] = 'success' if clean else 'failure'
                state['conclusion'] = 'success' if clean and passed else ('failure' if clean else 'error')
                failures = [c.get('error') or c.get('cleanup_error') for c in state['checks']
                            if c['conclusion'] != 'success']
                if failures:
                    state['error'] = '; '.join(filter(None, failures))
                log.writelines((check['id'] + ': ' + check['conclusion'] + ' log=' + check['log']
                               + ' ' + (check.get('error') or check.get('cleanup_error') or '') + '\n').encode() for check in state['checks'])
            except BaseException as exc:  # noqa: BLE001 - executor drains workers before final failure
                state.update(conclusion='failure', error=f'{type(exc).__name__}: {exc}')
                log.write((state['error'] + '\n').encode())
                state['cleanup'] = ('success' if all(c.get('cleanup') == 'success' for c in state['checks'])
                                    else 'failure')
            finally:
                state['status'] = state['conclusion']
                state['finished_at'] = time.time()
                progress.publish()
        return 0 if state['conclusion'] == 'success' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('repository', 'sha', 'output', 'config'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--preflight', action='store_true', help='Run reusable local validation steps and prerequisites')
    parser.add_argument('--jobs', nargs='+', choices=JOBS, help='Preflight: run selected full gates; never a full CI attestation')
    args = parser.parse_args()
    def interrupted(signum, _frame):
        raise InterruptedError(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        config = trusted_config(Path(args.config), Path(args.repository), Path(args.output))
        return execute(args.repository, args.sha, args.output, config, args.jobs, args.preflight)
    except Exception as exc:  # noqa: BLE001 - CLI fails closed
        print(f'local-ci denied: {type(exc).__name__}: {exc}', file=__import__('sys').stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
