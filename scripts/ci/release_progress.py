"""Durable release stages; retries are restricted to side-effect-safe phases."""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from pathlib import Path

from local_delivery import atomic

TRANSIENT = re.compile(r'(?i)timeout|timed out|connection reset|temporary failure|unexpected EOF|TLS handshake|502|503|504')


def path(config, sha):
    return Path(config['state']) / 'releases' / sha / 'progress.json'


def read(config, sha):
    try:
        value = json.loads(path(config, sha).read_text())
        return value if value.get('sha') == sha else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def stage(config, sha, name):
    previous = read(config, sha)
    log = path(config, sha).parent / 'release.log'
    offset = log.stat().st_size if log.exists() else 0
    value = {'log_offset': offset, 'sha': sha, 'stage': name, 'status': 'running', 'at': time.time(),
             'completed': previous.get('completed', [])}
    atomic(path(config, sha), value)
    try:
        yield
    except BaseException as exc:
        # Transport ambiguity during a production switch is never replayable.
        value.update(status='failed', error=type(exc).__name__, at=time.time())
        atomic(path(config, sha), value)
        raise
    else:
        value.update(status='success', at=time.time(),
                     completed=list(dict.fromkeys([*value['completed'], name])))
        atomic(path(config, sha), value)


def retryable(config, sha):
    progress = read(config, sha)
    if progress.get('stage') not in ('build', 'edge'):
        return False
    log = Path(config['state']) / 'releases' / sha / 'release.log'
    try:
        with log.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(progress.get('log_offset', 0), stream.tell() - 65536))
            tail = stream.read().decode(errors='replace')
        denied = re.search(r'(?i)checksum mismatch|EINTEGRITY|SECURITY ERROR|assertion failed|health check failed', tail)
        return bool(TRANSIENT.search(tail)) and not denied
    except OSError:
        return False
