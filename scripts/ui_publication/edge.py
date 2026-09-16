"""Executed by the existing isolated SSH edge controller container."""
import json
import sys
import tarfile
import subprocess
import time
from pathlib import Path
from edge_transfer import reuse_release_files

sys.path.insert(0, '/work/controller')
import deploy

root = Path('/release')
inventory = deploy.load_inventory(root / 'edge-inventory.json')
phase = sys.argv[1]
state_path = root / 'edges.json'
state = json.loads(state_path.read_text()) if state_path.exists() else {}

base_remote = deploy.remote
def read_resilient_remote(inv, site, action, *args, **kwargs):
    for attempt in range(4):
        try:
            return base_remote(inv, site, action, *args, **kwargs)
        except subprocess.CalledProcessError as error:
            if action not in ('status','verify') or error.returncode != 255 or attempt == 3:
                raise
            print('Retrying SSH read: '+site+'/'+action,flush=True)
            if error.stderr:
                print(str(error.stderr)[-1000:],flush=True)
            time.sleep(3)
deploy.remote = read_resilient_remote

# Reuse SSH's verified multiplexed connections, including Tokyo's ProxyJump.
# Retry only this read-only handshake; activation commands are never blindly retried.
for host in inventory['hosts'].values():
    for attempt in range(4):
        try:
            probe = subprocess.run(['ssh',host['user']+'@'+host['address'],'true'],capture_output=True,timeout=40)
            if probe.returncode == 0:
                break
            if attempt == 3:
                raise RuntimeError('ssh_preflight_failed:'+probe.stderr.decode(errors='replace')[-1500:])
        except subprocess.TimeoutExpired:
            if attempt == 3:
                raise RuntimeError('ssh_preflight_timeout') from None
        time.sleep(3)

if phase == 'snapshot':
    for name in inventory['sites']:
        state[name] = {'before': deploy.parse_status(deploy.remote(inventory, name, 'status', capture=True).stdout)['active']}
    state_path.write_text(json.dumps(state, indent=2))
elif phase == 'publish':
    artifact = Path('/tmp/ui-artifact/dist')
    artifact.mkdir(parents=True)
    with tarfile.open(root / 'frontend-dist.tar.gz') as archive:
        archive.extractall(artifact, filter='data')
    # SSH credentials retain 0600; only public artifacts get web-server-readable modes.
    artifact.chmod(0o755)
    for path in artifact.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    for name in inventory['sites']:
        current = deploy.parse_status(deploy.remote(inventory, name, 'status', capture=True).stdout)['active']
        if current != state[name]['before']:
            raise RuntimeError('concurrent_edge_release:' + name)
        # Journal the exact target before activation, including the crash window during smoke tests.
        original_remote = deploy.remote
        def journal_remote(inv, site, action, *args, **kwargs):
            if action == 'activate':
                state[site]['published'] = args[0]
                state_path.write_text(json.dumps(state, indent=2))
            return original_remote(inv, site, action, *args, **kwargs)
        deploy.remote = journal_remote
        try:
            with reuse_release_files(deploy, current):
                release = deploy.publish(inventory, name, 40, False, True)
        finally:
            deploy.remote = original_remote
        state[name]['published'] = release
        state_path.write_text(json.dumps(state, indent=2))
elif phase == 'republish':
    # Reuse this exact previously uploaded release after a verification-only
    # rollback. Verify every file against our local immutable manifest first.
    files = json.loads((root / 'artifact-manifest.json').read_text())
    original_program = deploy.REMOTE_PROGRAM
    prefix = 'p=incoming/arg; expected=json.loads((p/".deploy-manifest.json").read_text())["files"]; actual={}'
    if original_program.count(prefix) != 1:
        raise RuntimeError('remote_verifier_contract_changed')
    for name, row in state.items():
        current = deploy.parse_status(deploy.remote(inventory, name, 'status', capture=True).stdout)['active']
        if current != row['before'] or not row.get('published'):
            raise RuntimeError('concurrent_or_missing_reusable_release:' + name)
        try:
            deploy.REMOTE_PROGRAM = original_program.replace(prefix, 'p=releases/arg; expected=json.loads(' + repr(json.dumps(files)) + '); actual={}')
            deploy.remote(inventory, name, 'verify', row['published'])
        finally:
            deploy.REMOTE_PROGRAM = original_program
        deploy.remote(inventory, name, 'rollback', row['published'])
        deploy.smoke_check(inventory['sites'][name], files, 40)
        row['reused_verified_upload'] = True
        state_path.write_text(json.dumps(state, indent=2))
elif phase == 'rollback':
    for name, row in reversed(list(state.items())):
        current = deploy.parse_status(deploy.remote(inventory, name, 'status', capture=True).stdout)['active']
        if row.get('published') and current == row['published']:
            deploy.remote(inventory, name, 'rollback', row['before'])
        elif row.get('published') and current != row['before']:
            raise RuntimeError('ambiguous_edge_state_requires_recovery:' + name)
else:
    raise ValueError('unknown edge phase')
print(json.dumps(state), flush=True)
