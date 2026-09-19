#!/usr/bin/env python3
"""Trusted bare-repository hooks: only owned, non-forced session submissions."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def validate(config, old, new, ref):
    if not re.fullmatch(r'refs/heads/session/[a-z0-9][a-z0-9-]{1,127}',ref):
        raise ValueError('only session branches may be pushed; local main belongs to the validated controller')
    if not re.fullmatch('[0-9a-f]{40}',new) or new=='0'*40:
        raise ValueError('branch deletion is not a submission')
    branch=ref.removeprefix('refs/heads/')
    common=subprocess.check_output(['git','-C',config['repository'],'rev-parse','--path-format=absolute','--git-common-dir'],
                                  env={k:v for k,v in __import__('os').environ.items() if not k.startswith('GIT_')},text=True).strip()
    record=json.loads((Path(common)/'delivery-owners'/(hashlib.sha256(branch.encode()).hexdigest()+'.json')).read_text())
    if record.get('branch')!=branch or record.get('source')!='dev_session.start':
        raise ValueError('immutable owner missing')
    # Keep Git quarantine env here so unaccepted new objects can be inspected.
    if old!='0'*40 and subprocess.run(['git','--git-dir',config['bare'],'merge-base','--is-ancestor',old,new],capture_output=True).returncode:
        raise ValueError('non-fast-forward submission is forbidden')


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('action',choices=['pre','post'])
    a=p.parse_args();config=json.loads(a.config.read_text())
    records=[line.split() for line in sys.stdin if line.strip()]
    if a.action=='pre':
        for old,new,ref in records:validate(config,old,new,ref)
    else:
        from local_delivery import database, submit
        db=database(config)
        for _old,new,ref in records:submit(config,db,ref.removeprefix('refs/heads/'),new)


if __name__=='__main__':main()
