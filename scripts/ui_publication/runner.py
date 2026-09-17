"""Daily publication consumer for APScheduler's persisted discovery candidates.

Run under the deployment account using the registered Windows scheduled task.
Builds in a private staging directory. Never installs or runs upstream packages.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from adapter import CSS_SHA, Hold, checked_path, make_item, sha, validate_license, validate_source, write_json
from policy import withdrawn_ids
from quality import approve_rendered_candidate, private_hyperui_seed
from release import Release
from x_adapter import (
    checked_payload as checked_x_payload,
    license_path as x_license_path,
    make_item as make_x_item,
    provider_id as x_provider_id,
    validate_mit_license,
    validate_static_html,
)

HERE = Path(__file__).resolve().parent


@contextlib.contextmanager
def exclusive_lock(path):
    import msvcrt
    with path.open('a+b') as handle:
        handle.seek(0)
        handle.write(b'0')
        handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def bridge(request):
    result = subprocess.run(['docker','exec','-i','aigcnews-local-backend-api-1','python','-c',(HERE / 'db_bridge.py').read_text()], input=json.dumps(request).encode(), capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('publication_database_unavailable')
    return json.loads(result.stdout)


def fetch_repository(repository, revision, path, cache):
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
            or not re.fullmatch('[a-f0-9]{40}', revision) or '..' in Path(path).parts):
        raise Hold('unsafe_upstream_path')
    target = cache / repository.replace('/', '--') / revision / path
    headers_path = target.with_suffix(target.suffix + '.headers')
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f'https://raw.githubusercontent.com/{repository}/{revision}/{quote(path, safe="/")}'
    if not target.exists():
        temp = target.with_suffix(target.suffix + '.download')
        result = subprocess.run(['curl.exe','--fail','--silent','--show-error','--max-time','45','--max-filesize','2097152','--retry','2','--dump-header',str(headers_path),'--output',str(temp),url], capture_output=True, timeout=155)
        if result.returncode:
            raise RuntimeError('upstream_download_failed')
        temp.replace(target)
    raw = target.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise Hold('upstream_too_large')
    headers = {}
    for line in headers_path.read_text(errors='replace').splitlines():
        key, _, value = line.partition(':')
        if key.lower() in ('date','etag','last-modified','content-type'):
            headers[key] = value.strip()
    return raw, {'name':path,'url':url,'sha256':sha(raw),'http_headers':headers}


def fetch(revision, path, cache):
    return fetch_repository('markmead/hyperui', revision, path, cache)


def archive_evidence(data, items, payload, cache):
    revision = payload['source_revision']
    base = data / 'assets/hyperui/evidence' / revision
    manifest = base / 'manifest.json'
    old = json.loads(manifest.read_text()) if manifest.exists() else None
    if old:
        if old['revision'] != revision or old['license'] != 'MIT':
            raise Hold('existing_evidence_mismatch')
        for resource in old['resources']:
            if sha((base / resource['name']).read_bytes()) != resource['sha256']:
                raise Hold('evidence_integrity_failure')
        record = old
    else:
        resources = []
        base.mkdir(parents=True, exist_ok=True)
        for name in ('LICENSE', 'README.md'):
            raw, resource = fetch(revision, name, cache)
            (base / name).write_bytes(raw)
            resources.append(resource)
        record = {'repository':'markmead/hyperui','revision':revision,'captured_at':datetime.now(timezone.utc).isoformat(),
                  'license':'MIT','license_source':'LICENSE','license_grants':['commercial-use','redistribution'],
                  'conditions':['Preserve the original copyright, MIT license and supplied notices.'],
                  'resources':resources,'source_files':{},'license_page_url':f'https://github.com/markmead/hyperui/blob/{revision}/LICENSE',
                  'screenshot':'license-page.png','scope':'Pinned original UI source only. Excludes .agents, external media, Pro products and trademark rights.'}
    for item in items:
        for source in item['files']:
            previous = record['source_files'].get(source['path'])
            if previous and previous != source['sha256']:
                raise Hold('historical_evidence_changed')
            record['source_files'][source['path']] = source['sha256']
            original, response = fetch(revision,source['name'],cache)
            if sha(original) != source['sha256']:
                raise Hold('source_archive_mismatch')
            captured = datetime.fromtimestamp((cache/revision/source['name']).stat().st_mtime,timezone.utc).isoformat()
            record.setdefault('source_captures',{}).setdefault(source['path'],{**response,'captured_at':captured})
    write_json(manifest, record)


def archive_x_evidence(data, item, payload, license_name, cache):
    repository, _, revision = checked_x_payload(payload)
    provider = x_provider_id(payload)
    base = data / 'assets' / provider / 'evidence' / revision
    manifest = base / 'manifest.json'
    if manifest.exists():
        record = json.loads(manifest.read_text())
        if record['repository'].lower() != repository.lower() or record['revision'] != revision:
            raise Hold('existing_evidence_mismatch')
        for resource in record['resources']:
            if sha((base / resource['name']).read_bytes()) != resource['sha256']:
                raise Hold('evidence_integrity_failure')
    else:
        license_raw, resource = fetch_repository(repository, revision, license_name, cache)
        base.mkdir(parents=True, exist_ok=True)
        (base / 'LICENSE').write_bytes(license_raw)
        resource['name'] = 'LICENSE'
        record = {
            'repository': repository, 'revision': revision,
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'license': 'MIT', 'license_source': license_name,
            'license_grants': ['commercial-use', 'redistribution'],
            'conditions': ['Preserve the original copyright and MIT license.'],
            'resources': [resource], 'source_files': {},
            'license_page_url': f'https://github.com/{repository}/blob/{revision}/{quote(license_name, safe="/")}',
            'screenshot': 'license-page.png',
            'scope': 'Pinned static HTML source only; scripts and external resources are excluded.',
        }
    source = item['files'][0]
    original, response = fetch_repository(repository, revision, source['name'], cache)
    if sha(original) != source['sha256']:
        raise Hold('source_archive_mismatch')
    record['source_files'][source['path']] = source['sha256']
    archived_name = 'source-' + item['id'] + Path(source['name']).suffix
    archived = base / archived_name
    archived.write_bytes(original)
    resource = {'name': archived_name, 'url': response['url'], 'sha256': source['sha256'],
                'http_headers': response['http_headers']}
    if not any(entry['name'] == archived_name for entry in record['resources']):
        record['resources'].append(resource)
    record.setdefault('source_captures', {})[source['path']] = {
        **response, 'captured_at': datetime.now(timezone.utc).isoformat(),
        'discovered_via': payload['x_source_url'],
    }
    write_json(manifest, record)


def junction(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Junction creation uses a structured PowerShell parameter list, never untrusted paths.
    script = 'param($destination,$source) New-Item -ItemType Junction -Path $destination -Target $source | Out-Null'
    # -Command doesn't bind param reliably from native argv; use a tiny parameterized script.
    helper = destination.parent / 'junction.ps1'
    helper.write_text(script)
    subprocess.run(['powershell.exe','-NoProfile','-File',str(helper),str(destination),str(source)],check=True,capture_output=True)


def render(release, items, node_modules, ffmpeg):
    if any(item.get('preview_kind')!='html' or not item.get('clip_url','').endswith('.mp4') or not item.get('poster_url','').endswith('.webp') for item in items):
        raise RuntimeError('card_media_metadata_invalid')
    run = release.run
    frontend = run / 'source/frontend'
    frontend.mkdir(parents=True)
    junction(run / 'dist/ui-library', run / 'source/mcp-go/internal/uicatalog/data')
    junction(run / 'dist/ui-library/previews', frontend / '.ui-previews/previews')
    junction(node_modules, frontend / 'node_modules')
    (frontend / 'scripts').mkdir()
    for name in ('build-ui-previews.mjs', 'capture-ui-license-evidence.mjs'):
        shutil.copyfile(release.root / 'frontend/scripts' / name, frontend / 'scripts' / name)
    for name in ('quality-previews.mjs', 'original-react-previews.mjs'):
        builder = release.root / 'frontend/scripts' / name
        if builder.exists():
            shutil.copyfile(builder, frontend / 'scripts' / name)
    shutil.copyfile(HERE / 'capture.mjs', frontend / 'scripts/capture.mjs')
    shutil.copyfile(release.root / 'frontend/scripts/ui-media-capture.mjs', frontend / 'scripts/ui-media-capture.mjs')
    write_json(run / 'ids.json', [item['id'] for item in items])
    env = os.environ.copy()
    env.update(UI_PREVIEW_IDS_FILE=str(run / 'ids.json'), UI_RENDER_REPORT_FILE=str(run / 'render.json'), FFMPEG_PATH=str(ffmpeg))
    node = shutil.which('node') or 'E:/Nodejs/node.exe'
    release.command([node,'scripts/build-ui-previews.mjs'],cwd=frontend,env=env)
    # Evidence screenshots are made by the same trusted browser helper, at commit-pinned URLs.
    release.command([node,'scripts/capture-ui-license-evidence.mjs'],cwd=frontend,env=env)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(run / 'dist'), **kwargs)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env['UI_LIBRARY_BASE_URL'] = f'http://127.0.0.1:{server.server_port}'
    try:
        release.command([node,'scripts/capture.mjs'],cwd=frontend,env=env)
    finally:
        server.shutdown()
        server.server_close()
    from PIL import Image, ImageStat
    rows = json.loads((run / 'render.json').read_text())
    passed = set()
    for row in rows:
        if row['state'] != 'ready' or row['errors']:
            continue
        item = next(item for item in items if item['id'] == row['id'])
        with Image.open(run / 'dist/ui-library' / item['poster_url'].removeprefix('/ui-library/')) as image:
            # Reject blank/near-empty renders rather than publishing an empty card.
            stats = ImageStat.Stat(image.convert('RGB'))
            clip = run / 'dist/ui-library' / item['clip_url'].removeprefix('/ui-library/')
            if max(stats.stddev) > 3 and clip.is_file() and 2048 <= clip.stat().st_size <= 3 * 1024 * 1024:
                passed.add(row['id'])
    return passed


def verify(release, items):
    # Auth remains enforced; MCP and website must expose the identical original source.
    first = items[0]
    if any(item.get('preview_kind')!='html' or not item.get('clip_url','').endswith('.mp4') or not item.get('poster_url','').endswith('.webp') for item in items):
        raise RuntimeError('card_media_metadata_invalid')
    code = (HERE / 'runtime_probe.py').read_text() + '''
import httpx
from pathlib import Path
request=json.loads(INPUT)
with httpx.Client(trust_env=False,timeout=90) as c:
 r=c.post('http://mcp-api-go:8000/api/mcp',headers={'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_ui_template','arguments':{'id':request['id'],'include_source':True}}})
 result=source_probe(r.status_code,r.json(),request)
 assert c.get('http://127.0.0.1:8000/api/ui-library/copy-quota').status_code==401
 result['guest_copy_requires_login']=True
 print(json.dumps(result))
'''.replace('INPUT', repr(json.dumps(first)))
    runtime=json.loads(release.command(['docker','exec','aigcnews-local-backend-api-1','python','-c',code]))
    binary=release.command(['docker','exec','aigcnews-local-mcp-api-go-1','sha256sum','/usr/local/bin/mcp-server']).split()[0]
    if binary != sha((release.run/'mcp-server').read_bytes()):
        raise RuntimeError('deployed_mcp_binary_differs_from_tested_build')
    expected = sha((release.run / 'dist/ui-library/catalog.json').read_bytes())
    for address in ('118.89.101.11','43.165.172.182'):
        target = release.run / ('catalog-' + address + '.json')
        release.command(['curl.exe','--fail','--silent','--show-error','--retry','2','--retry-all-errors','--connect-timeout','10','--max-time','60','--resolve',f'aigcnews.cn:443:{address}','https://aigcnews.cn/ui-library/catalog.json','--output',str(target)])
        if sha(target.read_bytes()) != expected:
            raise RuntimeError('public_catalog_mismatch:' + address)
        source=release.run/('source-'+address+'.txt')
        release.command(['curl.exe','--fail','--silent','--show-error','--retry','2','--retry-all-errors','--connect-timeout','10','--max-time','60','--resolve',f'aigcnews.cn:443:{address}','https://aigcnews.cn/ui-library/'+first['files'][0]['path'],'--output',str(source)])
        if sha(source.read_bytes()) != first['files'][0]['sha256']:
            raise RuntimeError('public_source_mismatch:'+address)
    write_json(release.run / 'verification.json', {'both_edges_catalog_sha256':expected,'public_source_sha256':first['files'][0]['sha256'],'mcp_source_sha256':first['files'][0]['sha256'] if runtime['mcp_original_source'] else None,'runtime':runtime,'exact_tested_binary_sha256':binary,'guest_copy_requires_login':True})
    renderer=release.root/'local/ui-publication/renderer'
    shutil.copyfile(HERE/'verify-browser.mjs',renderer/'verify-browser.mjs')
    env=os.environ.copy();env['UI_VERIFY_ID']=max(items,key=lambda item:item['added_at'])['id']
    release.command([shutil.which('node') or 'E:/Nodejs/node.exe','verify-browser.mjs'],cwd=renderer,env=env,timeout=180)


def execute(args):
    state = args.root / 'local/ui-publication'
    state.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(state / 'worker.lock'):
        latest = state / 'latest.json'
        previous = json.loads(latest.read_text()) if latest.exists() else {}
        if previous.get('status') in ('publishing','recovery_required'):
            recovery = Release.__new__(Release)
            recovery.root, recovery.run = args.root, state / 'runs' / previous['run_id']
            recovery.compose_path = args.root / 'local/compose.yml'
            recovery.catalog_path = args.root / 'mcp-go/internal/uicatalog/data/catalog.json'
            recovery.compose_before = (recovery.run / 'before-compose.yml').read_bytes()
            recovery.catalog_before = (recovery.run / 'before-catalog.json').read_bytes()
            recovery.old_images = json.loads((recovery.run / 'before-images.json').read_text())
            recovery.images = json.loads((recovery.run / 'images.json').read_text())
            recovery.switched = True
            recovery.rollback()
            previous['status'] = 'recovered'
            write_json(recovery.run / 'status.json', previous)
            write_json(latest, previous)
        snapshot = bridge({'action':'snapshot'})
        source = next(iter(snapshot['sources']), None)
        if not source or source['error'] or not source['last_success_at'] or datetime.fromisoformat(source['last_success_at']) < datetime.now(timezone.utc)-timedelta(hours=36):
            raise RuntimeError('discovery_not_fresh_or_failed')
        # One completed batch per Shanghai calendar day. Failed attempts can retry.
        today = (datetime.now(timezone.utc)+timedelta(hours=8)).date().isoformat()
        if not args.force and previous.get('day') == today and previous.get('status') in ('published','no_changes'):
            print('Daily batch already completed', flush=True)
            return
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run = state / 'runs' / run_id
        run.mkdir(parents=True, exist_ok=False)
        status = {'run_id':run_id,'day':today,'status':'preparing','source_candidates':len(snapshot['candidates'])}
        def checkpoint(value):
            status.update(value)
            write_json(run / 'status.json', status)
            temporary = latest.with_suffix('.next.json')
            write_json(temporary, status)
            temporary.replace(latest)
            print(json.dumps(status), flush=True)
        checkpoint({})
        write_json(run / 'candidate-snapshot.json', snapshot)
        release = None
        rows, additions = [], []
        try:
            release = Release(args.root, run)
            release.export()
            checkpoint({'status':'reviewing'})
            data = run / 'dist/ui-library'
            catalog = json.loads((data / 'catalog.json').read_text())
            baseline = {item['id']:item for item in catalog['items']}
            template = private_hyperui_seed(data)
            fingerprints = set()
            for item in catalog['items']:
                if item['provider_id']=='hyperui':
                    raw = (data / item['files'][0]['path']).read_bytes()
                    from adapter import blob_sha
                    try:
                        fingerprints.add(validate_source(raw, blob_sha(raw)))
                    except Hold:
                        pass
                elif item['provider_id'].startswith('xgithub-') and item.get('frameworks') == ['html']:
                    raw = (data / item['files'][0]['path']).read_bytes()
                    from adapter import blob_sha
                    try:
                        fingerprints.add(validate_static_html(raw, blob_sha(raw)))
                    except Hold:
                        pass
            cache = state / 'upstream-cache'
            reviewed = {}
            x_evidence = {}
            withdrawn = withdrawn_ids(args.root)
            for candidate in snapshot['candidates']:
                if len(additions) >= args.limit:
                    break
                payload = candidate['payload']
                row = {'candidate_id':candidate['candidate_id'],'revision':candidate['revision']}
                try:
                    if payload.get('kind') == 'x_github_html':
                        repository, path, revision = checked_x_payload(payload)
                        license_name = x_license_path(payload)
                        license_raw, _ = fetch_repository(repository, revision, license_name, cache)
                        validate_mit_license(payload, license_raw, license_name)
                        raw, _ = fetch_repository(repository, revision, path, cache)
                        digest = validate_static_html(raw, payload['source_blob_sha'])
                        item = make_x_item(data, payload, raw, license_raw, datetime.now(timezone.utc).isoformat())
                        item_id = item['id']
                        if item_id in withdrawn:
                            raise Hold('operator_withdrawn')
                        existing = baseline.get(item_id)
                        if existing:
                            if existing['revision'] != revision or existing['files'][0]['sha256'] != sha(raw):
                                raise Hold('existing_component_update_requires_review')
                            row.update(status='published', reason='already_in_catalog')
                        elif digest in fingerprints:
                            row.update(status='held_duplicate', reason='duplicate_original_body')
                        else:
                            additions.append(item)
                            fingerprints.add(digest)
                            x_evidence[item_id] = (payload, license_name)
                            row.update(status='published', item_id=item_id)
                        rows.append(row)
                        continue
                    path = checked_path(payload['path'])
                    item_id = 'hyperui-' + path.removeprefix('public/examples/').removesuffix('.html').replace('/','-')
                    if item_id in withdrawn:
                        raise Hold('operator_withdrawn')
                    revision = payload['source_revision']
                    if revision not in reviewed:
                        license_raw, _ = fetch(revision,'LICENSE',cache)
                        helper, _ = fetch(revision,'public/component.js',cache)
                        css, _ = fetch(revision,'public/component.css',cache)
                        validate_license(payload,license_raw,helper)
                        if sha(css) != CSS_SHA:
                            raise Hold('stylesheet_changed')
                        reviewed[revision] = True
                    raw, _ = fetch(revision,path,cache)
                    digest = validate_source(raw,payload['source_blob_sha'])
                    existing = baseline.get(item_id)
                    if existing:
                        if existing['revision'] != revision or existing['files'][0]['sha256'] != sha(raw):
                            raise Hold('existing_component_update_requires_review')
                        row.update(status='published', reason='already_in_catalog')
                    elif digest in fingerprints:
                        row.update(status='held_duplicate',reason='duplicate_original_body')
                    else:
                        item = make_item(data,template,payload,raw,datetime.now(timezone.utc).isoformat())
                        additions.append(item)
                        fingerprints.add(digest)
                        row.update(status='published', item_id=item_id)
                except Hold as error:
                    row.update(status='held_quality' if str(error) == 'awaiting_visual_quality_review' else 'held_policy',reason=str(error))
                rows.append(row)
            write_json(run / 'reviews.json', rows)
            if not additions:
                bridge({'action':'record','run_id':run_id,'success':True,'items':rows})
                checkpoint({'status':'no_changes','published':0,'held':sum(row['status']!='published' for row in rows)})
                return
            for revision in {item['revision'] for item in additions}:
                hyperui_items = [item for item in additions if item['revision']==revision and item['provider_id']=='hyperui']
                if hyperui_items:
                    payload = next(c['payload'] for c in snapshot['candidates'] if c['payload']['source_revision']==revision and c['payload'].get('kind') != 'x_github_html')
                    archive_evidence(data,hyperui_items,payload,cache)
            for item in additions:
                if item['id'] in x_evidence:
                    payload, license_name = x_evidence[item['id']]
                    archive_x_evidence(data, item, payload, license_name, cache)
            catalog['items'] += additions
            write_json(data / 'catalog.json',catalog)
            # Screenshot helper reads current provider revision; old evidence remains pinned per item.
            locks = json.loads((data / 'upstreams.json').read_text())
            for item in additions:
                locks.setdefault(item['provider_id'], {})['revision'] = item['revision']
            write_json(data / 'upstreams.json',locks)
            checkpoint({'status':'rendering','approved':len(additions)})
            passed = render(release,additions,args.node_modules,args.ffmpeg)
            quality_holds = {}
            for item in additions:
                if item['id'] not in passed:
                    continue
                try:
                    approve_rendered_candidate(args.root, data, item)
                except Hold as error:
                    passed.remove(item['id'])
                    quality_holds[item['id']] = str(error)
            for row in rows:
                if row.get('item_id') and row['item_id'] not in passed:
                    reason = quality_holds.get(row['item_id'])
                    row.update(status='held_quality' if reason else 'held_render',reason=reason or 'preview_failed_or_blank')
            rejected = {item['id'] for item in additions if item['id'] not in passed}
            catalog['items'] = [item for item in catalog['items'] if item['id'] not in rejected]
            additions = [item for item in additions if item['id'] in passed]
            write_json(data / 'catalog.json',catalog)
            write_json(run / 'reviews.json',rows)
            if not additions:
                bridge({'action':'record','run_id':run_id,'success':True,'items':rows})
                checkpoint({'status':'no_changes','published':0,'reason':'awaiting_visual_quality_review' if quality_holds else 'all_previews_held','held':sum(row['status']!='published' for row in rows)})
                return
            # Remove rejected source and preview files from the public artifact, preserving original archive privately.
            allowed = {'catalog.json','upstreams.json'}
            proof_dirs = set()
            catalog_ids = {item['id'] for item in catalog['items']}
            for item in catalog['items']:
                allowed.update(file['path'] for file in item['files']+item['notices']+item['assets'])
                allowed.update(url.removeprefix('/ui-library/') for url in [item['preview_url'],item['poster_url'],item.get('clip_url','')] if url)
                proof_dirs.add(str(Path(item['rights_evidence_url'].removeprefix('/ui-library/')).parent).replace('\\','/'))
            allowed.update(p.relative_to(data).as_posix() for p in (data/'previews').iterdir() if p.name.split('.')[0] in catalog_ids)
            for path in data.rglob('*'):
                if path.is_file():
                    rel=path.relative_to(data).as_posix()
                    if rel not in allowed and not any(rel.startswith(prefix+'/') for prefix in proof_dirs):
                        path.unlink()
            checkpoint({'status':'building','approved':len(additions)})
            release.prepare([item['id'] for item in additions])
            checkpoint({'status':'publishing'})
            release.publish()
            verify(release,additions)
            release.sync()
            bridge({'action':'record','run_id':run_id,'success':True,'items':rows})
            checkpoint({'status':'published','published':len(additions),'total':len(catalog['items']),'held':sum(row['status']!='published' for row in rows)})
        except Exception as error:
            try:
                if release:
                    release.rollback()
                checkpoint({'status':'failed','error':str(error)})
            except Exception as rollback_error:
                checkpoint({'status':'recovery_required','error':str(error),'rollback_error':str(rollback_error)})
            try:
                bridge({'action':'record','run_id':run_id,'success':False,'error':'publication_' + status['status']})
            except Exception:
                pass
            raise


def resume_prepared(args):
    """Operator retry after a pre-switch build/network failure, retaining source evidence."""
    if not re.fullmatch(r'\d{8}T\d{6}Z',args.resume_run):
        raise ValueError('invalid run ID')
    state=args.root/'local/ui-publication'
    with exclusive_lock(state/'worker.lock'):
        run=state/'runs'/args.resume_run
        status=json.loads((run/'status.json').read_text())
        if status['status']!='failed' or (run/'images.json').exists():
            raise RuntimeError('only_failed_pre_switch_build_can_resume')
        if (run/'before-catalog.json').read_bytes() != (args.root/'mcp-go/internal/uicatalog/data/catalog.json').read_bytes():
            raise RuntimeError('baseline_catalog_changed')
        rows=json.loads((run/'reviews.json').read_text())
        ids={row['item_id'] for row in rows if row['status']=='published' and row.get('item_id')}
        catalog=json.loads((run/'dist/ui-library/catalog.json').read_text())
        items=[item for item in catalog['items'] if item['id'] in ids]
        report=json.loads((run/'render.json').read_text())
        ready={row['id'] for row in report if row['state']=='ready' and not row['errors']}
        media_ready=all(item.get('poster_url','').endswith('.webp') and item.get('clip_url','').endswith('.mp4') for item in items)
        if not ids or not ids.issubset(ready) or len(items)!=len(ids) or not media_ready:
            raise RuntimeError('incomplete_render_evidence')
        release=Release(args.root,run)
        def checkpoint(value):
            status.update(value)
            write_json(run/'status.json',status)
            write_json(state/'latest.json',status)
            print(json.dumps(status),flush=True)
        try:
            checkpoint({'status':'building','error':None})
            release.prepare([item['id'] for item in items])
            checkpoint({'status':'publishing'})
            release.publish()
            verify(release,items)
            release.sync()
            bridge({'action':'record','run_id':args.resume_run,'success':True,'items':rows})
            checkpoint({'status':'published','published':len(items),'total':len(catalog['items']),'held':sum(row['status']!='published' for row in rows)})
        except Exception as error:
            try:
                release.rollback()
                checkpoint({'status':'failed','error':str(error)})
            except Exception as rollback_error:
                checkpoint({'status':'recovery_required','error':str(error),'rollback_error':str(rollback_error)})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--node-modules',type=Path,required=True)
    parser.add_argument('--ffmpeg',type=Path,default=Path('ffmpeg.exe'),help='FFmpeg executable used for WebP and H.264 MP4 generation.')
    parser.add_argument('--limit',type=int,default=64)
    parser.add_argument('--force',action='store_true',help='Allow an explicit extra batch today; never bypasses review gates.')
    parser.add_argument('--resume-run',help='Retry a failed pre-switch build from its audited staging directory.')
    args = parser.parse_args()
    if not 1 <= args.limit <= 128:
        parser.error('limit must be between 1 and 128')
    if args.resume_run:
        resume_prepared(args)
    else:
        execute(args)
