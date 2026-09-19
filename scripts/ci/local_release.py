#!/usr/bin/env python3
"""Build local-main immutable images, apply existing locked deploy and edge gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(args, *, cwd=None, env=None):
    subprocess.run(list(map(str,args)),cwd=cwd,env=env,check=True,timeout=3600)


def normalize_build_permissions(checkout):
    # systemd uses umask 0077; image USER app must read source and migrations.
    # Only the disposable build context is normalized, never private source paths.
    for path in checkout.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)


def deployment_environment(config):
    overlay=Path(config['private_compose'])
    if not overlay.is_absolute() or not overlay.is_file():
        raise ValueError('verified production overlay missing')
    if hashlib.sha256(overlay.read_bytes()).hexdigest()!=config['private_compose_sha256']:
        raise ValueError('production overlay changed; reconcile before switching')
    os.environ['AIGCNEWS_PRIVATE_COMPOSE']=str(overlay)


def build_identity(config, sha):
    return hashlib.sha256(json.dumps([sha, config, Path(__file__).read_text()], sort_keys=True).encode()).hexdigest()


def verified_images(path, identity):
    try:
        data = json.loads(path.read_text())
        if data['identity'] != identity or set(data['images']) != {'backend', 'mcp', 'frontend'}:
            return None
        import re
        for service, ref in data['images'].items():
            if not re.fullmatch('ghcr.io/kaixxrua/aigcnews/' + service + r'@sha256:[0-9a-f]{64}', ref):
                return None
            run(['docker', 'image', 'inspect', ref])
        return data['images']
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def release(config,sha):
    sys.path.insert(0,str(Path(config['runtime'])/'release'))
    from deploy_production import Release, deploy
    from local_delivery import SHA, command, lock
    from publish_frontend_edges import publish
    if not SHA.fullmatch(sha):raise ValueError('invalid source SHA')
    deployment_environment(config)
    with lock(config,'build-release'):
        current=command(['git','--git-dir',config['bare'],'rev-parse','refs/heads/main'])
        if current!=sha:raise RuntimeError('release superseded before build')
        production=Path(config['production'])
        state=json.loads((production/'.aigcnews-deploy/state.json').read_text())
        if state.get('in_progress'):raise RuntimeError('unfinished production transition')
        if state.get('active_release')==sha:
            publish(production,sha)
            return
        checkpoint = Path(config['state']) / 'releases' / sha / 'verified-images.json'
        identity = build_identity(config, sha)
        images = verified_images(checkpoint, identity)
        if images:
            result = deploy(production, Release(sha, images['backend'], images['mcp'], images['frontend']))
            if result not in ('deployed', 'already-active'):
                raise RuntimeError('candidate superseded at deploy lock')
            publish(production, sha)
            return
        with tempfile.TemporaryDirectory(prefix='local-release-',dir=config['state']) as name:
            checkout=Path(name)/'source'
            run(['git','clone','--no-hardlinks','--no-checkout',config['bare'],checkout])
            run(['git','checkout','--detach',sha],cwd=checkout)
            catalog=production/'mcp-go/internal/uicatalog/data'
            previews=production/'frontend/.ui-previews/previews'
            if not (catalog/'catalog.json').is_file() or not previews.is_dir():
                raise RuntimeError('private UI catalog or previews unavailable')
            for target in [checkout/'mcp-go/internal/uicatalog/data',checkout/'frontend/.ui-library-data']:
                shutil.copytree(catalog,target,dirs_exist_ok=True)
            shutil.copytree(previews,checkout/'frontend/.ui-previews/previews',dirs_exist_ok=True)
            # Trusted installed contract, never sourced from a pending task.
            run([sys.executable,str(Path(config['runtime'])/'release/stage_private_frontend.py'),'--private-root',config['private_root'],'--frontend-root',str(checkout/'frontend'),
                        '--expected-release-id',config['private_release_id'],
                        '--expected-descriptor-sha256',config['private_descriptor_sha256']])
            normalize_build_permissions(checkout)
            env=dict(os.environ,UI_LIBRARY_DATA_ROOT=str(checkout/'frontend/.ui-library-data'))
            run(['npm','ci'],cwd=checkout/'frontend',env=env)
            run(['npm','run','typecheck'],cwd=checkout/'frontend',env=env)
            run(['npm','run','test:unit','--','src/components/contact/GodotContactScene.test.ts',
                 'src/views/ContactPageView.test.ts'],cwd=checkout/'frontend',env=env)
            images={}
            for service,context,dockerfile in [('backend','backend','backend/Dockerfile'),('mcp','.','mcp-go/Dockerfile'),('frontend','frontend','frontend/Dockerfile')]:
                repository='ghcr.io/kaixxrua/aigcnews/'+service
                metadata=Path(name)/(service+'.json')
                args=['docker','buildx','build','--builder','default','--load','--provenance=false',
                      '--metadata-file',metadata,'--tag',repository+':'+sha,'--file',dockerfile]
                if service=='mcp':args+=['--build-arg','GOPROXY=https://proxy.golang.org|https://goproxy.cn|direct']
                run(args+[context],cwd=checkout)
                digest=json.loads(metadata.read_text())['containerimage.digest']
                ref=repository+'@'+digest
                run(['docker','image','inspect',ref])
                images[service]=ref
            from local_delivery import atomic
            atomic(checkpoint, {'identity': identity, 'images': images})
            result=deploy(production,Release(sha,images['backend'],images['mcp'],images['frontend']))
            if result not in ('deployed','already-active'):raise RuntimeError('candidate superseded at deploy lock')
            publish(production,sha)


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--sha',required=True)
    a=p.parse_args();release(json.loads(a.config.read_text()),a.sha)


if __name__=='__main__':main()
