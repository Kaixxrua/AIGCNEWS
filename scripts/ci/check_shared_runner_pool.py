#!/usr/bin/env python3
"""Read-only operator preflight. No cgroup, service or GitHub mutations."""
import json
import os
import subprocess
from pathlib import Path

from shared_runner_pool import limits, owner


def persistence():
    output = subprocess.check_output(
        ['loginctl', 'show-user', str(os.getuid()), '-p', 'Linger', '-p', 'State', '-p', 'RuntimePath'],
        text=True, timeout=10)
    policy = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    if policy.get('Linger') != 'yes' or not policy.get('RuntimePath'):
        raise ValueError('existing user-manager policy does not prove boot/logout persistence')
    return policy


def main():
    policy = persistence()
    unit = os.environ.get('AIGCNEWS_RUNNER_SHARED_UNIT', 'aigcnews-ci-pool.service')
    group = subprocess.check_output(['systemctl', '--user', 'show', unit,
                                     '--property=ControlGroup', '--value'], text=True).strip()
    parent = Path('/sys/fs/cgroup') / group.lstrip('/')
    ownership, overhead = owner(parent, unit)
    ceiling = limits(parent)
    autostart = json.loads(subprocess.check_output(['lxc', 'list', '--format=json'], text=True))
    for item in autostart:
        if (item['name'].startswith('aigcnews-ci') or
                item['expanded_config'].get('user.aigcnews.ci') == 'true'):
            if item['expanded_config'].get('boot.autostart') != 'false':
                raise ValueError('CI boot.autostart must explicitly be false: ' + item['name'])
    print(json.dumps({'parent': str(parent), 'owner': ownership, 'overhead': overhead,
                      'limits': ceiling, 'user_manager_policy': policy, 'boot_order': 'CI autostart disabled; parent READY required'}))


if __name__ == '__main__':
    main()
