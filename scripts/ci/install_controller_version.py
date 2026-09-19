#!/usr/bin/env python3
"""Stage an immutable controller bundle; activate only when controller jobs drain."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from local_delivery import atomic


def stage(source, config):
    source = Path(source).resolve()
    files = sorted((source/'scripts/ci').glob('*.py')) + sorted((source/'scripts/release').glob('*.py'))
    hashes = {str(p.relative_to(source/'scripts')): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    identity = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    target = Path(config['runtime']).parent/'aigcnews-controller-versions'/identity
    if not target.exists():
        target.mkdir(parents=True, mode=0o700)
        for p in files:
            relative = p.relative_to(source/'scripts')
            dest = target/(relative.name if relative.parts[0] == 'ci' else relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        atomic(target/'version.json', {'identity': identity, 'files': hashes, 'staged_at': time.time()})
    for relative, expected in hashes.items():
        entry = Path(relative)
        installed = target/(entry.name if entry.parts[0] == 'ci' else entry)
        if not installed.is_file() or hashlib.sha256(installed.read_bytes()).hexdigest() != expected:
            raise RuntimeError('controller bundle is incomplete or modified: '+relative)
    return target


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    args = p.parse_args()
    config = json.loads(args.config.read_text())
    target = stage(args.source, config)
    subprocess.run(['/usr/bin/python3', '-m', 'compileall', '-q', str(target)], check=True)
    print(json.dumps({'runtime': str(target), 'status': 'staged',
                      'activation': 'Drain old controller jobs, update trusted runtime and service paths, then restart.'}))


if __name__ == '__main__':
    main()
