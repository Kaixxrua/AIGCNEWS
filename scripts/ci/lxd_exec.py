"""Run a CI step once through LXD's recorded-output task API, without websockets."""
from __future__ import annotations

import json
import re
import subprocess
import time
from urllib.parse import urlsplit

OPERATION = re.compile(r'/1\.0/operations/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
TRANSIENT = re.compile(r'(?i)broken pipe|unexpected EOF|connection reset|connection refused|websocket|timed out|context deadline exceeded')


def recorded_exec(command, instance, argv, log, timeout):
    """Never replay a POST or command; only retry bounded, read-only observations.

    The caller owns the clone and must reap it on failure/interruption/timeout.
    An absent operation, missing exit status or unreadable output fails closed.
    """
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]*', instance):
        raise ValueError('invalid exec instance')
    deadline = time.monotonic() + timeout

    def query(path, *, payload=None):
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('recorded LXD exec deadline exhausted')
            args = ['lxc', 'query', '--force-local', '--raw', path]
            if payload is not None:
                args += ['-X', 'POST', '-d', json.dumps(payload)]
            try:
                return command(args, timeout=min(15, remaining))
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                # Submission may have reached LXD even when its response is lost.
                if (payload is not None or attempt == 2
                        or (not isinstance(exc, subprocess.TimeoutExpired) and not TRANSIENT.search(str(exc)))):
                    raise
                log.write(b'\nTransient LXD read failure; reconnecting to the same operation\n')
                log.flush()
                time.sleep(min(attempt + 1, max(0, deadline - time.monotonic())))
        raise AssertionError('unreachable')

    instance_path = '/1.0/instances/' + instance
    response = json.loads(query(instance_path + '/exec', payload={
        'command': argv, 'wait-for-websocket': False,
        'interactive': False, 'record-output': True,
    }))
    operation = response.get('operation', '')
    if response.get('type') != 'async' or not OPERATION.fullmatch(operation):
        raise RuntimeError('LXD did not return an exact exec operation')
    operation_id = operation.rsplit('/', 1)[1]
    log.write(('\nLXD recorded exec: ' + operation_id + '\n').encode())
    log.flush()
    while True:
        value = json.loads(query(operation))
        state = value.get('metadata', {})
        if (value.get('type') != 'sync' or state.get('id') != operation_id
                or state.get('resources', {}).get('instances') != [instance_path]):
            raise RuntimeError('LXD exec operation identity changed')
        code = state.get('status_code')
        if type(code) is not int:
            raise RuntimeError('LXD exec operation status is missing')
        if code in (100, 103):
            time.sleep(min(2, max(0, deadline - time.monotonic())))
            continue
        metadata = state.get('metadata') or {}
        output = metadata.get('output') or {}
        if set(output) != {'1', '2'}:
            raise RuntimeError('LXD exec output receipt is incomplete')
        for descriptor, suffix in (('1', 'stdout'), ('2', 'stderr')):
            path = output[descriptor]
            parsed = urlsplit(path)
            if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
                    or path not in (f'{instance_path}/logs/exec_{operation_id}.{suffix}',
                                    f'{instance_path}/logs/exec-output/exec_{operation_id}.{suffix}')):
                raise RuntimeError('LXD exec output belongs to another operation')
            log.write(query(path))
            log.flush()
        result = metadata.get('return')
        if code != 200 or type(result) is not int or result != 0:
            raise RuntimeError(f'LXD recorded command failed: status={code}, exit={result}')
        return b''
