"""Private-host rollout for the account-scoped SUB2API sleep-state adapter.

Run as root on the SUB2API host. Secrets stay in root-owned runtime files or
process memory; command output contains only health and routing evidence.
"""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path('/opt/sub2api-cn')
RELEASE = ROOT / 'releases/sleep-state-20260921'
STATE = RELEASE / 'state'
BACKUP = ROOT / 'backups/sleep-state-20260921'
APP = 'sub2api-cn-sub2api-1'
STAGE = 'sub2api-sleep-state-stage'
IMAGE = 'sub2api:cn-v025-sleep-state-20260921-r3'
OLD_IMAGE = 'sub2api:cn-v0.2.5-preserve-ui-20260918'
FLAG = 'openai_sleep_state_enabled'
ACCOUNT = 821


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout.strip()


def sql(query):
    return run('docker', 'exec', '-i', 'sub2api-cn-postgres-1', 'psql',
               '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-U', 'sub2api', '-d', 'sub2api', input=query)


def inspect(name):
    return json.loads(run('docker', 'inspect', name))[0]


def save(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def compose(*args):
    return run('docker', 'compose', '--project-directory', str(ROOT), *args)


def prepare():
    if BACKUP.exists():
        raise RuntimeError('Existing rollout backup: inspect it before another preparation')
    app = inspect(APP)
    assert app['Config']['Image'] == OLD_IMAGE, 'Production image changed'
    account = json.loads(sql(f"SELECT json_build_object('email',credentials->>'email',"
                            f"'type',type,'extra',extra,'proxy_id',proxy_id) FROM accounts WHERE id={ACCOUNT}"))
    assert account['email'] == 'kaixxrua@gmail.com' and account['type'] == 'oauth'
    assert account['proxy_id'] == 4 and not account['extra'].get(FLAG)
    BACKUP.mkdir(mode=0o700)
    shutil.copy2(ROOT / 'compose.yaml', BACKUP / 'compose.yaml')
    save(BACKUP / 'account-flag.json', {'present': FLAG in account['extra'], 'value': account['extra'].get(FLAG)})
    save(BACKUP / 'image.json', {'id': app['Image'], 'tag': OLD_IMAGE})
    proxy = json.loads(sql("SELECT json_build_object('protocol',protocol,'host',host,'port',port,"
                          "'username',username,'password',password) FROM proxies WHERE id=4"))
    host = proxy['host']
    for entry in app['HostConfig'].get('ExtraHosts') or []:
        name, address = entry.split(':', 1)
        if name == host:
            host = address
    auth = ''
    if proxy['username']:
        auth = urllib.parse.quote(proxy['username'], safe='') + ':' + urllib.parse.quote(proxy['password'] or '', safe='') + '@'
    proxy_url = f"{proxy['protocol']}://{auth}{host}:{proxy['port']}"
    STATE.mkdir(mode=0o700)
    config = {
        'listen': '127.0.0.1:17841', 'upstream': 'https://chatgpt.com/backend-api/codex',
        'upstream_kind': 'official', 'model': 'gpt-6-astra', 'account_mode': 'auto',
        'direct': False, 'proxy_urls': [proxy_url], 'external_proxy_only': True,
        'state_fallback': 'passthrough', 'state_refresh_mode': 'on_demand',
        'max_probes_per_round': 1, 'probe_timeout_seconds': 20,
        'probe_cooldown_seconds': 180, 'state_ttl_seconds': 3600,
        'refresh_before_seconds': 1200,
    }
    save(STATE / 'config.json', config)
    os.chown(STATE, 1000, 1000)
    os.chown(STATE / 'config.json', 1000, 1000)
    start_stage()


def start_stage():
    assert inspect(APP)['Config']['Image'] == OLD_IMAGE, 'Production image changed'
    run('docker', 'build', '-t', IMAGE, str(RELEASE))
    run('docker', 'run', '-d', '--name', STAGE, '--network', 'container:' + APP,
        '--user', '1000:1000', '--read-only', '--tmpfs', '/tmp',
        '-v', str(STATE) + ':/state', '--entrypoint', '/app/ccodex-sleep-state',
        IMAGE, 'serve', '--no-config', '--data-dir', '/state')
    print(json.dumps({'stage': STAGE, 'account_id': ACCOUNT, 'backup': str(BACKUP)}))


def namespace_probe(mode):
    pid = str(inspect(APP)['State']['Pid'])
    try:
        return run('nsenter', '-t', pid, '-n', 'python3', str(Path(__file__).resolve()), mode)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.stderr.strip().splitlines()[-1]) from None


def request(url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        return opener.open(req, timeout=180)
    except urllib.error.HTTPError as error:
        # Retain only structured error classification, never complete upstream bodies.
        try:
            detail = json.load(error).get('error', {})
            if isinstance(detail, dict):
                detail = {key: detail.get(key) for key in ('type', 'code', 'message')}
            else:
                detail = {'code': detail}
        except (ValueError, AttributeError):
            detail = {'code': 'non_json_error'}
        raise RuntimeError(f'Probe returned HTTP {error.code}: {detail}') from None


def status():
    runtime = json.loads((STATE / 'runtime.json').read_text())
    with request('http://127.0.0.1:17841/_sleep/status', headers={
            'Authorization': 'Bearer ' + runtime['control_token']}) as response:
        data = json.load(response)
    return data


def completed_events(response):
    events = []
    for line in response:
        if not line.startswith(b'data: '):
            continue
        payload = line[6:].strip()
        if payload != b'[DONE]':
            events.append(json.loads(payload).get('type'))
    assert 'response.completed' in events, 'SSE did not complete'
    assert not any(item in events for item in ['error', 'response.failed']), 'SSE failed'


def probe(integrated=False, compact=False, model='gpt-5.6-sol'):
    headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream',
               'User-Agent': 'codex_cli_rs/0.153.0', 'originator': 'codex_cli_rs',
               'version': '0.153.0', 'session_id': 'sleep-state-rollout-20260921'}
    if integrated:
        key = sql("SELECT key FROM api_keys WHERE id=81 AND group_id=14 AND status='active' AND deleted_at IS NULL")
        assert key, 'Dedicated test key unavailable'
        assert sql('SELECT string_agg(account_id::text,\',\' ORDER BY account_id) FROM account_groups WHERE group_id=14') == str(ACCOUNT)
        headers['Authorization'] = 'Bearer ' + key
        url = 'http://127.0.0.1:8080/v1/responses'
    else:
        creds = json.loads(sql(f'SELECT credentials FROM accounts WHERE id={ACCOUNT}'))
        headers['Authorization'] = 'Bearer ' + creds['access_token']
        headers['ChatGPT-Account-ID'] = creds['chatgpt_account_id']
        url = 'http://127.0.0.1:17841/backend-api/codex/responses'
    body = {'model': model, 'instructions': 'Follow the user instruction.',
            'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Reply with exactly OK.'}]}],
            'store': False, 'stream': True, 'reasoning': {'effort': 'low'}}
    if compact:
        url += '/compact'
        body.pop('stream')
        body.pop('store')
        body['input'].append({'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'OK'}]})
    before = status().get('requests_total', 0)
    with request(url, body, headers) as response:
        if compact:
            result = json.load(response)
            assert any(item.get('type') == 'compaction' for item in result.get('output', [])), 'Compaction output missing'
            assert result.get('usage', {}).get('input_tokens', 0) > 0, 'Compaction usage missing'
        else:
            completed_events(response)
    if compact:
        body['input'] = result['output'] + [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Reply with exactly OK again.'}]}]
        body.update({'stream': True, 'store': False})
        with request(url.removesuffix('/compact'), body, headers) as response:
            completed_events(response)
    after = status()
    assert after.get('requests_total', 0) > before, 'Sidecar did not observe the request'
    evidence = {'integrated': integrated, 'compact': compact, 'completed': True, 'model': model,
                'requests_before': before, 'requests_after': after.get('requests_total'),
                'injection_enabled': after.get('injection_enabled'), 'sessions': after.get('sessions')}
    # Status is upstream's redacted diagnostic schema, never response headers/state blobs.
    name = ('compact.json' if integrated else 'stage-compact.json') if compact else ('integrated.json' if integrated else 'stage.json')
    save(BACKUP / name, evidence)
    print(json.dumps(evidence))


def rollback():
    original = json.loads((BACKUP / 'account-flag.json').read_text())
    sql(f"UPDATE accounts SET extra=extra-'{FLAG}',updated_at=NOW() WHERE id={ACCOUNT}")
    if original['present']:
        value = json.dumps(original['value']).replace("'", "''")
        sql(f"UPDATE accounts SET extra=jsonb_set(extra,'{{{FLAG}}}','{value}'::jsonb) WHERE id={ACCOUNT}")
    # Stop the sidecar before changing the network namespace it shares.
    compose('stop', 'sleep-state')
    compose('rm', '-f', 'sleep-state')
    shutil.copy2(BACKUP / 'compose.yaml', ROOT / 'compose.yaml')
    compose('up', '-d', '--no-deps', 'sub2api')
    save(BACKUP / 'active.json', {'phase': 'rolled_back', 'account_id': ACCOUNT, 'time': time.time()})
    print(json.dumps({'rolled_back': True, 'account_id': ACCOUNT}))


def activate():
    assert json.loads((BACKUP / 'stage.json').read_text())['completed']
    assert json.loads((BACKUP / 'stage-compact.json').read_text())['completed']
    assert inspect(APP)['Config']['Image'] == OLD_IMAGE, 'Production changed since preparation'
    assert (ROOT / 'compose.yaml').read_bytes() == (BACKUP / 'compose.yaml').read_bytes(), 'Compose changed'
    config = yaml.safe_load((ROOT / 'compose.yaml').read_text())
    config['services']['sub2api']['image'] = IMAGE
    config['services']['sleep-state'] = {
        'image': IMAGE, 'entrypoint': ['/app/ccodex-sleep-state'],
        'command': ['serve', '--no-config', '--data-dir', '/state'],
        'network_mode': 'service:sub2api', 'depends_on': ['sub2api'],
        'restart': 'unless-stopped', 'user': '1000:1000', 'read_only': True,
        'tmpfs': ['/tmp'], 'volumes': [str(STATE) + ':/state'],
        'logging': {'driver': 'json-file', 'options': {'max-size': '5m', 'max-file': '2'}},
    }
    run('docker', 'stop', STAGE)
    run('docker', 'rm', STAGE)
    try:
        save(ROOT / 'compose.yaml', config)
        compose('config', '--quiet')
        sql(f"UPDATE accounts SET extra=jsonb_set(extra,'{{{FLAG}}}','true'::jsonb),updated_at=NOW() WHERE id={ACCOUNT}")
        compose('up', '-d', '--no-deps', 'sub2api', 'sleep-state')
        for _ in range(60):
            try:
                with request('http://127.0.0.1:18086/health') as response:
                    assert response.status == 200
                break
            except (OSError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError('Production health timeout')
        print(namespace_probe('probe-integrated'))
        print(namespace_probe('probe-compact'))
        save(BACKUP / 'active.json', {'phase': 'active', 'image': inspect(APP)['Image'], 'account_id': ACCOUNT, 'time': time.time()})
    except Exception:
        rollback()
        raise


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'restage', 'stage-test', 'activate', 'rollback',
                                          'probe-stage', 'probe-stage-compact', 'probe-integrated', 'probe-compact', 'status'])
    parser.add_argument('--model', default='gpt-5.6-sol', choices=['gpt-5.6-sol', 'gpt-6-astra', 'gpt-5.6-terra'])
    args = parser.parse_args()
    if args.action.startswith('probe-'):
        probe(integrated=not args.action.startswith('probe-stage'), compact=args.action.endswith('compact'), model=args.model)
    elif args.action == 'status':
        print(json.dumps(status()))
    else:
        with (ROOT / 'upgrade.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'stage-test':
                print(namespace_probe('probe-stage'))
                print(namespace_probe('probe-stage-compact'))
            else:
                {'prepare': prepare, 'restage': start_stage, 'activate': activate, 'rollback': rollback}[args.action]()
