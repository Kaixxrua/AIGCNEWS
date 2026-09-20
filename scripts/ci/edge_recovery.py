"""Recover only a verified active origin's transient edge failure, without CI replay."""
import importlib.util
import json
import sys
import time
from pathlib import Path

from local_delivery import meta
from release_progress import read, retryable


def probe(config):
    """Read-only configured non-asset smoke checks; never publish or switch a site."""
    control = Path(config['production']) / '.aigcnews-deploy'
    edge = json.loads((control / 'edge-config.json').read_text())
    spec = importlib.util.spec_from_file_location('edge_recovery_controller', edge['controller'])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    inventory = json.loads(Path(edge['inventory']).read_text())
    if not edge.get('sites'):
        raise ValueError('no edge sites')
    for name in edge['sites']:
        module.smoke_check(inventory['sites'][name], {}, 15, include_asset=False)


def consider(config, db, release, *, check=probe, clock=time.time):
    sha = release.get('sha')
    if release.get('status') != 'failed' or not sha:
        return False
    progress = read(config, sha)
    if progress.get('stage') != 'edge' or not retryable(config, sha):
        return False
    control = Path(config['production']) / '.aigcnews-deploy'
    origin = json.loads((control / 'state.json').read_text())
    if origin.get('active_release') != sha or origin.get('in_progress'):
        return False
    if meta(db, 'validated_main').get('sha') != sha:
        return False  # A newer validated candidate follows the normal path.
    key = 'edge_recovery:' + sha
    recovery = meta(db, key)
    now = clock()
    if recovery.get('retries', 0) >= 2 or recovery.get('probes', 0) >= 24:
        recovery.update(status='needs_repair', reason='恢复预算耗尽；需要修复回源或发布配置')
        meta(db, key, recovery)
        return False
    if now < recovery.get('next_probe_at', 0):
        return False
    recovery.update(sha=sha, status='checking', probes=recovery.get('probes', 0) + 1,
                    checked_at=now, next_probe_at=now + 60)
    meta(db, key, recovery)
    try:
        check(config)
    except Exception as exc:  # noqa: BLE001 - persist failed probes without publishing
        recovery.update(status='waiting_external', consecutive_successes=0,
                        reason='回源检查未恢复', error=type(exc).__name__, next_probe_at=now + 300)
        meta(db, key, recovery)
        return False
    # Recheck durable source selection after network I/O, never revive stale releases.
    current = meta(db, 'release')
    origin = json.loads((control / 'state.json').read_text())
    if (current.get('sha') != sha or current.get('status') != 'failed'
            or current.get('finished_at') != release.get('finished_at')
            or origin.get('active_release') != sha or origin.get('in_progress')
            or meta(db, 'validated_main').get('sha') != sha):
        recovery.update(status='superseded', reason='候选或源站已变化，不恢复旧发布')
        meta(db, key, recovery)
        return False
    recovery['consecutive_successes'] = recovery.get('consecutive_successes', 0) + 1
    if recovery['consecutive_successes'] < 2:
        recovery.update(status='confirming', reason='首次回源检查通过，等待第二次确认')
        meta(db, key, recovery)
        return False
    recovery.update(status='retry_queued', reason='连续两次检查通过；仅重试边缘发布',
                    retries=recovery.get('retries', 0) + 1, consecutive_successes=0)
    meta(db, key, recovery)
    meta(db, 'release', {**release, 'status': 'retrying', 'retry_at': now,
                         'recovery_stage': 'edge', 'reason': recovery['reason']})
    return True
