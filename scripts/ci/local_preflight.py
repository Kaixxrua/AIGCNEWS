#!/usr/bin/env python3
"""Validate the staged tree in the trusted CI environment before commit/push."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from local_ci import REUSABLE_STEPS, command, git


def staged_snapshot(repository):
    repository = Path(repository).resolve()
    if git(repository, 'diff', '--name-only', '--diff-filter=U').strip():
        raise ValueError('resolve merge conflicts before preflight')
    tree = git(repository, 'write-tree').decode().strip()
    parent = git(repository, 'rev-parse', 'HEAD').decode().strip()
    sha = command(['git', '-C', str(repository), '-c', 'user.name=Local preflight',
                   '-c', 'user.email=preflight@localhost', 'commit-tree', tree, '-p', parent],
                  data=b'Local staged-tree validation (no branch update)\n').decode().strip()
    return sha, tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path.cwd())
    parser.add_argument('--config', type=Path, default=Path.home()/'.config/aigcnews/local-delivery.json')
    parser.add_argument('--jobs', nargs='+', choices=sorted(REUSABLE_STEPS), required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if not config.get('template_snapshot') and not config.get('verification_environment_digest'):
        raise SystemExit('preflight reuse unavailable: trusted environment fingerprint is not configured')
    sha, tree = staged_snapshot(args.repository)
    output = Path(config['state'])/'preflight'/f'{sha}.json'
    executable = Path(config['runtime'])/'local_ci.py'
    # Execute the installed controller, never candidate commands on the host.
    subprocess.run(['/usr/bin/python3', str(executable), '--repository', str(args.repository.resolve()),
                    '--sha', sha, '--config', str(args.config.resolve()), '--output', str(output),
                    '--preflight', '--jobs', *args.jobs], check=True)
    if git(args.repository, 'write-tree').decode().strip() != tree:
        raise SystemExit('staged tree changed during validation; rerun preflight')
    print(json.dumps({'tree': tree, 'sha': sha, 'receipt': str(output), 'status': 'validated'}))


if __name__ == '__main__':
    main()
