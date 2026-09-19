#!/usr/bin/env python3
"""Prepare a new stopped CI template from admitted main; never mutate live runners.

Creates an isolated clone, warms dependency caches, removes working source and
secrets, and records a new stopped template/snapshot for explicit activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from local_ci import SHA, Runner, admission_lock, atomic_json, command, git, trusted_config


def prepare(config_path, sha):
    if not SHA.fullmatch(sha):
        raise ValueError('full source SHA required')
    raw = json.loads(Path(config_path).read_text())
    root = Path(raw['state'])/'dependency-seeds'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = trusted_config(Path(config_path), Path(raw['bare']), root/'receipt.json')
    main = git(raw['bare'], 'rev-parse', 'refs/heads/main').decode().strip()
    command(['git', '--git-dir', raw['bare'], 'merge-base', '--is-ancestor', sha, main])
    locks = ('mcp-go/go.mod', 'mcp-go/go.sum', 'frontend/package.json',
             'frontend/package-lock.json', 'backend/requirements.lock', 'backend/requirements.txt')
    identity = hashlib.sha256(b''.join(git(raw['bare'], 'show', sha+':'+p) for p in locks)).hexdigest()
    run_id = uuid.uuid4().hex
    state = {'run_id': run_id, 'instance': 'aigcnews-ci-local-'+run_id}
    with (root/(identity+'.log')).open('ab') as log:
        runner = Runner(config, state, log)
        keep = False
        try:
            with admission_lock(Path(config['state_dir']), config['queue_timeout']):
                runner.launch()
            runner.shell('mkdir -p /ci/dependencies/mcp-go /ci/dependencies/frontend /ci/dependencies/backend')
            for p in locks:
                runner.lxc('file', 'push', '-', runner.name+'/ci/dependencies/'+p,
                           data=git(raw['bare'], 'show', sha+':'+p))
            env = """export HTTP_PROXY=http://127.0.0.1:7895 HTTPS_PROXY=http://127.0.0.1:7895
export NO_PROXY=localhost,127.0.0.1
export GOMODCACHE=/opt/aigcnews-dependencies/go
export npm_config_cache=/opt/aigcnews-dependencies/npm
export PIP_CACHE_DIR=/opt/aigcnews-dependencies/pip UV_CACHE_DIR=/opt/aigcnews-dependencies/uv
mkdir -p /opt/aigcnews-dependencies
"""
            runner.shell(env+'''cd /ci/dependencies/mcp-go
go mod download
go mod verify
cd ../frontend
npm ci --ignore-scripts --no-audit --prefer-offline --fetch-timeout=30000
cd ../backend
python -m pip download --timeout 30 --retries 2 -r requirements.lock -d /opt/aigcnews-dependencies/wheels
''', timeout=3600)
            # Seed nested Docker's frontend dependency mount without a production socket.
            runner.shell(env+'''cd /ci/dependencies/frontend
cat > Dockerfile <<'DOCKER'
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,id=aigcnews-npm,target=/root/.npm,sharing=locked npm ci --ignore-scripts --no-audit --fetch-timeout=30000
DOCKER
docker build --build-arg HTTP_PROXY=http://host.docker.internal:7895 --build-arg HTTPS_PROXY=http://host.docker.internal:7895 --add-host host.docker.internal:host-gateway -t aigcnews-dependency-seed .
''', timeout=1800)
            runner.shell('rm -rf /ci /root/.ssh /root/.gitconfig /root/.npmrc; systemctl stop docker')
            runner.lxc('stop', runner.name, '--timeout', '30')
            runner.lxc('config', 'unset', runner.name, 'raw.lxc')
            runner.lxc('snapshot', runner.name, 'dependencies')
            receipt = {'sha': sha, 'locks_sha256': identity, 'template': runner.name,
                       'template_snapshot': 'dependencies', 'status': 'prepared'}
            atomic_json(root/(identity+'.json'), receipt)
            keep = True
            return receipt
        finally:
            if not keep:
                runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.config, args.sha)))


if __name__ == '__main__':
    main()
