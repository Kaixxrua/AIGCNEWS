#!/usr/bin/env python3
"""Publish the preserved current release with remote hard-link reuse."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path


DEPLOY_MODULE = Path('/home/kaixxrua/deploy-static/deploy.py')
SSH_CONTROL_PATH = os.environ.get('DEPLOY_SSH_CONTROL_PATH')
PUBLISH_PATHS = (
    'assets/contact-godot-interaction-v2.css',
    'index.html',
    'sw.js',
)


def load_deploy():
    spec = importlib.util.spec_from_file_location('deploy_static', DEPLOY_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {DEPLOY_MODULE}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if SSH_CONTROL_PATH:
        original_ssh_base = module.ssh_base
        module.ssh_base = lambda host: original_ssh_base(host) + [
            '-o', f'ControlPath={SSH_CONTROL_PATH}',
        ]
    return module


def publish(deploy, inventory, name: str, timeout: float) -> str:
    site = inventory['sites'][name]
    host = inventory['hosts'][site['host']]
    source = deploy.build_artifact(site, True)
    local_files = deploy.validate_artifact(source)
    activated = False

    with deploy.site_lock(name):
        previous = deploy.parse_status(
            deploy.remote(inventory, name, 'status', capture=True).stdout
        )['active']
        current_manifest_result = subprocess.run(
            deploy.ssh_base(host) + ['cat', f"{site['root']}/current/.deploy-manifest.json"],
            check=True,
            capture_output=True,
            text=True,
        )
        current_manifest = json.loads(current_manifest_result.stdout)
        if current_manifest.get('release_id') != previous:
            raise deploy.DeployError('active release changed while preparing publication')
        current_files = current_manifest.get('files', {})
        files = dict(current_files)
        for path in PUBLISH_PATHS:
            if path not in local_files:
                raise deploy.DeployError(f'publication file is absent: {path}')
            files[path] = local_files[path]
        changed = sorted(path for path in PUBLISH_PATHS if current_files.get(path) != files[path])
        release, manifest = deploy.make_manifest(files)
        deploy.remote(inventory, name, 'prepare', release)
        try:
            subprocess.run(
                deploy.ssh_base(host)
                + [
                    'cp', '-al', '--',
                    f"{site['root']}/current/.",
                    f"{site['root']}/incoming/{release}/",
                ],
                check=True,
            )
            destination = (
                f"{host['user']}@{host['address']}:"
                f"{site['root']}/incoming/{release}/"
            )
            with tempfile.NamedTemporaryFile() as changed_file:
                changed_file.write(b'\0'.join(path.encode() for path in changed) + b'\0')
                changed_file.flush()
                subprocess.run(
                    [
                        'rsync', '-a', '--checksum', '--protect-args', '--from0',
                        f'--files-from={changed_file.name}',
                        '-e',
                        (
                            f"ssh -i {host['identity_file']} -p {host['port']} "
                            '-o BatchMode=yes -o StrictHostKeyChecking=yes'
                            + (f' -o ControlPath={SSH_CONTROL_PATH}' if SSH_CONTROL_PATH else '')
                        ),
                        f'{source}/', destination,
                    ],
                    check=True,
                )
            with tempfile.NamedTemporaryFile() as manifest_file:
                manifest_file.write(manifest)
                manifest_file.flush()
                subprocess.run(
                    [
                        'rsync', '-a', '--protect-args',
                        '-e',
                        (
                            f"ssh -i {host['identity_file']} -p {host['port']} "
                            '-o BatchMode=yes -o StrictHostKeyChecking=yes'
                            + (f' -o ControlPath={SSH_CONTROL_PATH}' if SSH_CONTROL_PATH else '')
                        ),
                        manifest_file.name,
                        f'{destination}.deploy-manifest.json',
                    ],
                    check=True,
                )
            deploy.remote(inventory, name, 'verify', release)
            deploy.remote(inventory, name, 'activate', release)
            activated = True
            deploy.smoke_check(site, files, timeout)
            deploy.remote(inventory, name, 'prune', str(site['retain_old']))
        except BaseException:
            if activated and previous is not None:
                deploy.remote(inventory, name, 'rollback', previous)
            deploy.remote(inventory, name, 'cleanup', release)
            raise
    return release


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('sites', nargs='+')
    args = parser.parse_args()

    deploy = load_deploy()
    inventory = deploy.load_inventory(args.inventory)
    for site in args.sites:
        print(f'{site}: {publish(deploy, inventory, site, args.timeout)}', flush=True)


if __name__ == '__main__':
    main()
