#!/usr/bin/env python3
"""Install reviewed local-control code; activation is a separate documented cutover."""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
from pathlib import Path


def install(config_path):
    config=json.loads(config_path.read_text());runtime=Path(config['runtime'])
    from notifier_runtime import validate
    notifier_python = validate(config)
    runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
    source=Path(__file__).resolve().parent
    # Copy trusted controllers and all their host-side helpers, never from candidate branches.
    for file in source.glob('*.py'):shutil.copy2(file,runtime/file.name)
    release=runtime/'release';release.mkdir(exist_ok=True)
    for file in source.parent.joinpath('release').glob('*.py'):shutil.copy2(file,release/file.name)
    from local_delivery import database, git, meta
    db=database(config)
    if not meta(db,'observed_refs'):
        meta(db,'observed_refs',dict(line.split(' ',1) for line in git(config,'for-each-ref','--format=%(refname:short) %(objectname)','refs/heads/session/').splitlines()))
    db.close()
    hookdir=Path(config['bare'])/'hooks';hookdir.mkdir(exist_ok=True)
    for name,action in [('pre-receive','pre'),('post-receive','post')]:
        path=hookdir/name
        path.write_text('#!/bin/sh\nexec /usr/bin/python3 '+shlex.quote(str(runtime/'local_receive.py'))+' --config '+shlex.quote(str(config_path))+' '+action+'\n');path.chmod(0o700)
    units=Path.home()/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
    for role in ('ci','release','mirror','notify'):
        # Explicit path config on host; no production credentials enter candidate CI.
        interpreter=notifier_python if role=='notify' else '/usr/bin/python3'
        (units/f'aigcnews-local-{role}.service').write_text(f'''[Unit]
Description=AIGCNEWS local delivery {role}
After=network-online.target
[Service]
Type=simple
ExecStart={interpreter} {runtime}/local_delivery.py --config {config_path} {role} --loop
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
KillMode=control-group
UMask=0077
[Install]
WantedBy=default.target
''')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True)
    install(p.parse_args().config.resolve())
