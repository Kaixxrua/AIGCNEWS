#!/usr/bin/env python3
"""Build local-main immutable images, apply existing locked deploy and edge gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

SHA = re.compile(r'[0-9a-f]{40}')
IMAGE_REPOSITORY = 'ghcr.io/kaixxrua/aigcnews/'
IMAGE_SERVICES = ('backend', 'mcp', 'frontend')
DEFAULT_IMAGE_RETENTION = 5
DEFAULT_BUILD_CACHE_KEEP_BYTES = 20 * 1024 ** 3
DEFAULT_PIP_INDEX = 'https://mirrors.ustc.edu.cn/pypi/simple'


def backend_build_args(config):
    """Use the trusted build-only route; Docker does not persist proxy build args."""
    index = config.get('backend_pip_index_url', DEFAULT_PIP_INDEX)
    proxy = config.get('backend_build_proxy')
    for value, schemes in [(index, {'https'}), (proxy, {'http', 'https'})]:
        if value is None:
            continue
        parsed = urlsplit(value)
        if (parsed.scheme not in schemes or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or any(char.isspace() for char in value)):
            raise ValueError('invalid backend dependency route')
    args = ['--build-arg', 'PIP_INDEX_URL=' + index]
    if proxy:
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            args += ['--build-arg', key + '=' + proxy]
        args += ['--build-arg', 'NO_PROXY=localhost,127.0.0.1,::1',
                 '--build-arg', 'no_proxy=localhost,127.0.0.1,::1']
    return args


def run(args, *, cwd=None, env=None):
    subprocess.run(list(map(str,args)),cwd=cwd,env=env,check=True,timeout=3600)


def _capture(args, *, timeout):
    """Single non-raising shell seam for retention; tests monkeypatch this."""
    return subprocess.run(list(map(str, args)), capture_output=True, text=True,
                          timeout=timeout, check=False)


def retention_keep(config, keep_sha):
    """Commit SHAs whose per-release images must survive pruning.

    The active release, its rollback target and last failed release come from the
    authoritative production state; the newest main commits keep in-flight and
    quick-rollback builds. Returns None when the protected set cannot be
    established, so a caller never prunes against an unknown keep set.
    """
    keep = {keep_sha} if keep_sha and SHA.fullmatch(keep_sha) else set()
    try:
        state = json.loads((Path(config['production']) / '.aigcnews-deploy/state.json').read_text())
    except (OSError, ValueError, KeyError):
        return None
    for key in ('active_release', 'previous_release', 'last_failed_release'):
        value = state.get(key)
        if value and SHA.fullmatch(value):
            keep.add(value)
    recent = config.get('image_retention', DEFAULT_IMAGE_RETENTION)
    try:
        recent = max(int(recent), 0)
    except (TypeError, ValueError):
        recent = DEFAULT_IMAGE_RETENTION
    if recent:
        history = _capture(['git', '--git-dir', config['bare'], 'rev-list', '-n', str(recent),
                            'refs/heads/main'], timeout=30)
        if history.returncode != 0:
            return None
        keep.update(token for token in history.stdout.split() if SHA.fullmatch(token))
    return keep


def prune_release_images(config, keep_sha):
    """Remove superseded per-commit image tags and bound the build cache.

    Runs only after a delivered release. Retention housekeeping must never fail
    an already-published release, so every failure is contained and reported in
    the returned summary rather than raised.
    """
    summary = {'removed': [], 'kept': 0, 'errors': []}
    try:
        keep = retention_keep(config, keep_sha)
        if keep is None:
            summary['status'] = 'skipped: protected set unavailable'
            return summary
        listed = _capture(['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}'], timeout=60)
        if listed.returncode != 0:
            summary['status'] = 'skipped: image listing unavailable'
            return summary
        for line in listed.stdout.splitlines():
            reference = line.strip()
            if not reference.startswith(IMAGE_REPOSITORY):
                continue
            repository, _, tag = reference.rpartition(':')
            service = repository[len(IMAGE_REPOSITORY):]
            # Only ever touch this project's 40-hex commit tags; digests,
            # rollback pins and unrelated images are never candidates.
            if service not in IMAGE_SERVICES or not SHA.fullmatch(tag):
                continue
            if tag in keep:
                summary['kept'] += 1
                continue
            removed = _capture(['docker', 'rmi', reference], timeout=120)
            if removed.returncode == 0:
                summary['removed'].append(reference)
            else:
                summary['errors'].append(reference)
        cache = config.get('build_cache_keep_bytes', DEFAULT_BUILD_CACHE_KEEP_BYTES)
        try:
            cache = int(cache)
        except (TypeError, ValueError):
            cache = DEFAULT_BUILD_CACHE_KEEP_BYTES
        if cache > 0:
            # In-use cache for concurrent builds is protected; only least-recently
            # used records beyond the reservation are reclaimed.
            result = _capture(
                ['docker', 'builder', 'prune', '--force', '--reserved-space', str(cache)],
                timeout=1800,
            )
            if result.returncode:
                summary['errors'].append('build cache prune failed')
        summary['status'] = 'pruned'
    except Exception as exc:  # noqa: BLE001 - housekeeping never fails a delivered release
        summary['status'] = 'error'
        summary['errors'].append(type(exc).__name__)
    return summary


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


def build_identity(config, sha, ui_catalog_sha256=None):
    return hashlib.sha256(json.dumps([sha, config, ui_catalog_sha256, Path(__file__).read_text()], sort_keys=True).encode()).hexdigest()


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
    from local_delivery import SHA, ancestor, database, lock, meta
    from publish_frontend_edges import publish as edge_publish
    from ui_catalog_release import catalog_digest
    def publish(root, source):
        if edge_publish(root, source) != "published":
            raise RuntimeError("edge publication did not finish selected candidate")
    from release_progress import stage
    if not SHA.fullmatch(sha):raise ValueError('invalid source SHA')
    deployment_environment(config)
    with lock(config,'build-release'):
        # Only the controller's durable selected candidate may publish an older
        # validated ancestor. A newer main does not cancel an admitted release.
        with closing(database(config)) as db:
            selected = meta(db, 'release')
        if selected.get('sha') != sha or selected.get('status') != 'deploying':
            raise RuntimeError('release is not the controller-selected candidate')
        from local_delivery import git
        if not ancestor(config, sha, git(config, 'rev-parse', 'refs/heads/main')):
            raise RuntimeError('selected release is no longer on local main')
        production=Path(config['production'])
        state=json.loads((production/'.aigcnews-deploy/state.json').read_text())
        if state.get('in_progress'):raise RuntimeError('unfinished production transition')
        requested_catalog = selected.get('ui_catalog_sha256')
        if (state.get('active_release')==sha
                and (not requested_catalog or state.get('ui_catalog_sha256') == requested_catalog)):
            with stage(config, sha, 'edge'):
                publish(production,sha)
            return
        ui_catalog = catalog_digest(config)
        if requested_catalog and ui_catalog is None:
            raise RuntimeError('selected UI catalog disappeared')
        with closing(database(config)) as db:
            meta(db, 'release', {**selected, 'ui_catalog_sha256': ui_catalog})
        checkpoint = Path(config['state']) / 'releases' / sha / 'verified-images.json'
        identity = build_identity(config, sha, ui_catalog)
        images = verified_images(checkpoint, identity)
        if images:
            with stage(config, sha, 'deploy'):
                result = deploy(production, Release(sha, images['backend'], images['mcp'], images['frontend'], ui_catalog), pinned=True)
                if result not in ('deployed', 'already-active'):
                    raise RuntimeError('candidate superseded at deploy lock')
            with stage(config, sha, 'edge'):
                publish(production, sha)
            return
        with stage(config, sha, 'build'):
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
                env=dict(os.environ,UI_LIBRARY_DATA_ROOT=str(checkout/'frontend/.ui-library-data'),
                         npm_config_cache=str(Path(config['state'])/'dependency-cache/npm'),
                         npm_config_prefer_offline='true', npm_config_audit='false', npm_config_fetch_timeout='30000')
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
                    if service=='backend':args+=backend_build_args(config)
                    run(args+[context],cwd=checkout)
                    digest=json.loads(metadata.read_text())['containerimage.digest']
                    ref=repository+'@'+digest
                    run(['docker','image','inspect',ref])
                    images[service]=ref
                from local_delivery import atomic
                atomic(checkpoint, {'identity': identity, 'images': images})
        with stage(config, sha, 'deploy'):
            result=deploy(production,Release(sha,images['backend'],images['mcp'],images['frontend'],ui_catalog), pinned=True)
            if result not in ('deployed','already-active'):raise RuntimeError('candidate superseded at deploy lock')
        with stage(config, sha, 'edge'):
            publish(production,sha)


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--sha',required=True)
    a=p.parse_args();release(json.loads(a.config.read_text()),a.sha)


if __name__=='__main__':main()
