#!/usr/bin/env python3
"""Daily Linux refresh: pull new components from reviewed upstream UI sources.

Replaces the retired Windows publication task for the pinned importer families.
For every registered source it compares the upstream HEAD with the last checked
revision. When it moved, the reviewed importer runs again at the new commit and
only components that did not exist before are considered:

* the license file must be byte-identical to the reviewed one (legal gate);
* ids present at the reviewed baseline but absent from the catalog were
  deliberately rejected earlier and never return;
* withdrawn ids, and ids this refresher published that were later removed,
  never return;
* a candidate must build offline, report ready inside a network-blocked
  browser, produce a non-blank poster and a playable H.264 clip.

Already published components keep their pinned bytes: new files are stored
under ``sources/<provider>/r<rev12>/``. The staged catalog is verified with the
Go MCP catalog loader before anything touches production. Production files are
written under the local delivery ``build-release.lock``; the delivery controller
detects the new catalog digest and publishes website and MCP images automatically.

Never executes upstream package scripts, never fetches arbitrary URLs.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib
import json
import mimetypes
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE_ROOT = HERE.parents[1]
SCRIPTS = CODE_ROOT / 'scripts'

# Importer modules sharing ui_import_common.store(); value = dependency view.
FAMILIES = {
    'import_batch_registry_sources': 'packages',
    'import_batch_json_registry_sources': 'packages',
    'import_batch_directory_sources': 'packages',
    'import_batch4_demo_sources': 'versions',
    'import_batch_html_sources': 'packages',
}
# Withdrawn by the operator on 2026-09-11 (3447 ids); never auto-publish again.
WITHDRAWN_PROVIDERS = ('hyperui', 'galaxy', 'uiverse')
ID = re.compile(r'[a-z0-9][a-z0-9._-]{0,240}')
SHA = re.compile(r'[0-9a-f]{40}')
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')


class Hold(Exception):
    """A provider or candidate that must wait for a human."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def write_json(path: Path, value, *, indent=2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.next')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=indent) + '\n', encoding='utf-8')
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def git_env() -> dict[str, str]:
    # Hooks export GIT_DIR/GIT_INDEX_FILE; never let them redirect cache clones.
    return {key: value for key, value in os.environ.items()
            if not key.startswith('GIT_') or key == 'GIT_SSH_COMMAND'}


def run(args, *, cwd=None, env=None, timeout=1800, log: Path | None = None) -> str:
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, capture_output=True,
                            timeout=timeout, text=True)
    if log:
        with log.open('a', encoding='utf-8') as stream:
            stream.write('$ ' + ' '.join(map(str, args))[:400] + '\n' + result.stdout[-20000:] + result.stderr[-20000:])
    if result.returncode:
        raise RuntimeError(f'command_failed:{Path(str(args[0])).name}:{result.returncode}')
    return result.stdout


# ---------------------------------------------------------------- selection


def fingerprint(item: dict) -> str:
    return sha(json.dumps(sorted((f['name'], f['sha256']) for f in item['files'])).encode())


def blocked_ids(state: dict, catalog_ids: set[str]) -> set[str]:
    """Operator withdrawals plus refresher publications later removed by hand."""
    withdrawn = set(state['withdrawn'])
    withdrawn |= set(state['published']) - catalog_ids
    return withdrawn


def select_new(items: list[dict], *, catalog_ids: set[str], known: set[str], blocked: set[str],
               held: dict[str, dict], seen: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Return (fresh candidates, skipped rows) for one provider import.

    ``seen`` holds source fingerprints already in the catalog; aliases that
    re-export identical sources under another name are skipped.
    """
    fresh, skipped = [], []
    seen = set(seen or ())
    for item in items:
        item_id = item['id']
        reason = None
        if not ID.fullmatch(item_id):
            reason = 'invalid_id'
        elif item_id.startswith(tuple(p + '-' for p in WITHDRAWN_PROVIDERS)) or item['provider_id'] in WITHDRAWN_PROVIDERS:
            reason = 'withdrawn_provider'
        elif item_id in catalog_ids:
            continue
        elif item_id in blocked:
            reason = 'withdrawn'
        elif item_id in known:
            reason = 'rejected_at_reviewed_baseline'
        elif held.get(item_id, {}).get('fingerprint') == fingerprint(item):
            reason = 'held_unchanged:' + held[item_id]['reason']
        elif fingerprint(item) in seen:
            reason = 'duplicate_source'
        if reason:
            skipped.append({'id': item_id, 'status': 'skipped', 'reason': reason})
        else:
            seen.add(fingerprint(item))
            fresh.append(item)
    return fresh, skipped


def round_robin(groups: dict[str, list[dict]], limit: int) -> list[dict]:
    queues = {key: list(value) for key, value in sorted(groups.items())}
    chosen: list[dict] = []
    while len(chosen) < limit and any(queues.values()):
        for key in list(queues):
            if queues[key] and len(chosen) < limit:
                chosen.append(queues[key].pop(0))
    return chosen


# ---------------------------------------------------------------- upstreams


class Upstreams:
    def __init__(self, cache: Path, log: Path):
        self.cache, self.log = cache, log

    def head(self, repository: str) -> str:
        if not REPOSITORY.fullmatch(repository):
            raise Hold('invalid_repository')
        out = run(['git', 'ls-remote', f'https://github.com/{repository}', 'HEAD'], env=git_env(), timeout=90, log=self.log)
        revision = out.split()[0] if out.split() else ''
        if not SHA.fullmatch(revision):
            raise Hold('upstream_head_unavailable')
        return revision

    def checkout(self, repository: str, revision: str) -> Path:
        if not REPOSITORY.fullmatch(repository) or not SHA.fullmatch(revision):
            raise Hold('unsafe_upstream')
        target = self.cache / repository.replace('/', '--') / revision
        if (target / '.refresh-complete').exists():
            return target
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        env = git_env()
        run(['git', 'init', '-q', target], env=env, log=self.log)
        run(['git', '-C', target, 'fetch', '-q', '--depth', '1', f'https://github.com/{repository}', revision],
            env=env, timeout=1800, log=self.log)
        run(['git', '-C', target, '-c', 'advice.detachedHead=false', 'checkout', '-q', '--detach', 'FETCH_HEAD'], env=env, log=self.log)
        (target / '.refresh-complete').write_text(now())
        return target

    def prune(self, keep: dict[str, set[str]]) -> None:
        for repo_dir in self.cache.iterdir() if self.cache.is_dir() else []:
            repository = repo_dir.name.replace('--', '/', 1)
            for revision_dir in repo_dir.iterdir():
                if revision_dir.name not in keep.get(repository, set()):
                    shutil.rmtree(revision_dir, ignore_errors=True)


@contextlib.contextmanager
def importer_context(data: Path, scope: str, node_modules: Path):
    sys.path.insert(0, str(SCRIPTS))
    common = importlib.import_module('ui_import_common')
    batch4 = importlib.import_module('import_batch4_demo_sources')
    saved = (common.DATA, common.SOURCE_SCOPE, batch4.FRONTEND_MODULES)
    common.DATA, common.SOURCE_SCOPE, batch4.FRONTEND_MODULES = data, scope, node_modules
    try:
        yield common
    finally:
        common.DATA, common.SOURCE_SCOPE, batch4.FRONTEND_MODULES = saved


def registry() -> dict[str, tuple[str, dict]]:
    sys.path.insert(0, str(SCRIPTS))
    sources: dict[str, tuple[str, dict]] = {}
    for module_name in FAMILIES:
        module = importlib.import_module(module_name)
        for provider_id, source in module.SOURCES.items():
            if provider_id in sources:
                raise RuntimeError('duplicate refresh provider: ' + provider_id)
            sources[provider_id] = (module_name, source)
    return sources


def checkout_parts(module_name: str, provider_id: str, source: dict) -> tuple[str, str]:
    """(link name under the upstreams dir, repository-relative importer root)."""
    if module_name == 'import_batch4_demo_sources':
        return provider_id, ''
    checkout = source.get('checkout', provider_id)
    link, _, subdir = checkout.partition('/')
    return link, subdir


def license_path(module_name: str, provider_id: str, source: dict) -> str:
    _, subdir = checkout_parts(module_name, provider_id, source)
    path = posixpath.normpath(posixpath.join(subdir, source['license_source']))
    if path.startswith('..') or path.startswith('/'):
        raise Hold('license_outside_repository')
    return path


def import_at(module_name: str, provider_id: str, source: dict, checkout: Path, revision: str,
              data: Path, scope: str, node_modules: Path, previous: dict, report: dict) -> list[dict]:
    module = importlib.import_module(module_name)
    upstreams = data.parent / ('upstreams-' + provider_id + '-' + revision[:12])
    shutil.rmtree(upstreams, ignore_errors=True)
    upstreams.mkdir(parents=True)
    link, _ = checkout_parts(module_name, provider_id, source)
    (upstreams / link).symlink_to(checkout, target_is_directory=True)
    pinned = dict(source, revision=revision)
    original = module.SOURCES[provider_id]
    module.SOURCES[provider_id] = pinned
    try:
        with importer_context(data, scope, node_modules) as common:
            if FAMILIES[module_name] == 'versions':
                dependencies = module.installed_versions()
            else:
                dependencies = common.node_modules_packages(node_modules)
            return module.import_provider(provider_id, upstreams, previous, dependencies, None, report)
    finally:
        module.SOURCES[provider_id] = original
        shutil.rmtree(upstreams, ignore_errors=True)


# ---------------------------------------------------------------- staging


def break_link(path: Path) -> None:
    """Staging is a hardlink farm; give a file its own inode before writing."""
    if path.is_file() and path.stat().st_nlink > 1:
        temporary = path.with_name(path.name + '.own')
        shutil.copy2(path, temporary)
        os.replace(temporary, path)


def break_links(root: Path) -> None:
    if root.is_file():
        break_link(root)
    elif root.is_dir():
        for path in root.rglob('*'):
            break_link(path)


def stage_data(production: Path, staging: Path, log: Path) -> None:
    staging.parent.mkdir(parents=True, exist_ok=True)
    run(['cp', '-al', production, staging], timeout=3600, log=log)
    for name in ('catalog.json', 'upstreams.json', 'licenses'):
        break_links(staging / name)


def gc_scope(staging: Path, provider_id: str, scope: str, keep: set[str]) -> None:
    root = staging / 'sources' / provider_id / scope
    if not root.is_dir():
        return
    for path in sorted(root.rglob('*'), reverse=True):
        rel = path.relative_to(staging).as_posix()
        if path.is_file() and rel not in keep:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def prepare_frontend(run_dir: Path, node_modules: Path) -> Path:
    frontend = run_dir / 'frontend'
    shutil.copytree(CODE_ROOT / 'frontend/scripts', frontend / 'scripts')
    shutil.copy2(HERE / 'refresh_media.mjs', frontend / 'scripts/refresh_media.mjs')
    shutil.copy2(CODE_ROOT / 'frontend/package.json', frontend / 'package.json')
    (frontend / 'node_modules').symlink_to(node_modules, target_is_directory=True)
    return frontend


def ensure_node_modules(state: Path, log: Path) -> Path:
    lock = (CODE_ROOT / 'frontend/package-lock.json').read_bytes()
    target = state / 'node' / sha(lock)[:16]
    if (target / '.refresh-complete').exists():
        return target / 'node_modules'
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    shutil.copy2(CODE_ROOT / 'frontend/package.json', target / 'package.json')
    (target / 'package-lock.json').write_bytes(lock)
    run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--prefer-offline'], cwd=target, timeout=3600, log=log)
    run(['node', 'node_modules/playwright/cli.js', 'install', 'chromium'], cwd=target, timeout=3600, log=log)
    (target / '.refresh-complete').write_text(now())
    for old in (state / 'node').iterdir():
        if old != target:
            shutil.rmtree(old, ignore_errors=True)
    return target / 'node_modules'


class PreviewHandler(SimpleHTTPRequestHandler):
    data: Path
    previews: Path

    def log_message(self, *args):
        pass

    def translate_path(self, path):
        path = path.split('?', 1)[0].split('#', 1)[0]
        if not path.startswith('/ui-library/'):
            return str(self.data / '__missing__')
        relative = posixpath.normpath(path[len('/ui-library/'):])
        if relative.startswith('..') or relative.startswith('/'):
            return str(self.data / '__missing__')
        if relative.startswith('previews/') and '/' not in relative[len('previews/'):]:
            generated = self.previews / relative[len('previews/'):]
            if generated.is_file():
                return str(generated)
        return str(self.data / relative)

    def guess_type(self, path):
        return mimetypes.guess_type(str(path))[0] or 'application/octet-stream'


@contextlib.contextmanager
def serve(data: Path, previews: Path):
    handler = type('Handler', (PreviewHandler,), {'data': data, 'previews': previews})
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()


def node_job(frontend: Path, job: dict, run_dir: Path, name: str, *, log: Path, browser_libs: Path | None,
             timeout=7200) -> list[dict]:
    job_path = run_dir / f'{name}-job.json'
    report = run_dir / f'{name}-report.json'
    write_json(job_path, {**job, 'report': str(report)})
    env = dict(os.environ)
    if browser_libs:
        # Hosts without root keep Chromium's shared libraries in user space.
        env['LD_LIBRARY_PATH'] = os.pathsep.join(filter(None, [str(browser_libs), env.get('LD_LIBRARY_PATH')]))
    run(['node', 'scripts/refresh_media.mjs', job_path], cwd=frontend, env=env, timeout=timeout, log=log)
    return read_json(report, [])


def evidence_record(repository: str, revision: str, license_name: str, license_file: str,
                    readme: str | None, checkout: Path, target: Path, sources: dict[str, str]) -> dict:
    """License + README bytes from the pinned commit, merged with any prior record."""
    target.mkdir(parents=True, exist_ok=True)
    manifest = target / 'manifest.json'
    old = read_json(manifest)
    if old:
        if old['revision'] != revision or old['license'] != license_name:
            raise Hold('existing_evidence_mismatch')
        for name, digest in old['source_files'].items():
            if sources.get(name, digest) != digest:
                raise Hold('historical_evidence_changed')
        return {**old, 'source_files': {**old['source_files'], **sources}}
    resources = []
    for relative in [license_file] + ([readme] if readme else []):
        raw = (checkout / relative).read_bytes()
        name = posixpath.basename(relative)
        (target / name).write_bytes(raw)
        resources.append({'name': name, 'url': f'https://raw.githubusercontent.com/{repository}/{revision}/{relative}',
                          'sha256': sha(raw), 'http_headers': {}, 'retrieved_via': 'git fetch of the pinned commit'})
    if len({r['name'] for r in resources}) < 2:
        raise Hold('missing_readme_evidence')
    return {
        'repository': repository, 'revision': revision, 'captured_at': now(), 'license': license_name,
        'license_source': license_file, 'license_grants': ['commercial-use', 'redistribution'],
        'conditions': ['Preserve the original copyright, license and supplied notices.'],
        'resources': resources, 'source_files': sources,
        'license_page_url': f'https://github.com/{repository}/blob/{revision}/{license_file}',
        'screenshot': 'license-page.png',
        'scope': 'Only the pinned source and separately listed licensed assets; excludes unrelated Pro products, external media, and trademark rights.',
    }


def find_readme(checkout: Path) -> str | None:
    for name in ('README.md', 'readme.md', 'Readme.md', 'README.mdx', 'README'):
        if (checkout / name).is_file():
            return name
    return None


def verify_go_catalog(staging: Path, run_dir: Path, log: Path) -> None:
    module = run_dir / 'mcp-go'
    shutil.copytree(CODE_ROOT / 'mcp-go', module, ignore=shutil.ignore_patterns('data'))
    data = module / 'internal/uicatalog/data'
    data.mkdir()
    for name in ('catalog.json', 'icons.json', 'upstreams.json'):
        shutil.copy2(staging / name, data / name)
    for name in ('sources', 'licenses', 'assets'):
        run(['cp', '-al', staging / name, data / name], timeout=3600, log=log)
    run(['go', 'test', '-count=1', '-run', 'TestPinnedSourcesAndLocalFileBoundary', './internal/uicatalog/'],
        cwd=module, env=git_env(), timeout=3600, log=log)
    shutil.rmtree(module, ignore_errors=True)


def verify_web_contract(staging: Path, previews: Path, items: list[dict]) -> None:
    """Mirror frontend/build/uiLibraryAssets.ts checks for the new items."""
    proofs: dict[str, dict] = {}
    for item in items:
        expected = f"/ui-library/assets/{item['provider_id']}/evidence/{item['revision']}/manifest.json"
        if item['rights_evidence_url'] != expected:
            raise RuntimeError('rights_evidence_url_mismatch:' + item['id'])
        proof = proofs.get(expected)
        if proof is None:
            path = staging / expected.removeprefix('/ui-library/')
            proof = json.loads(path.read_text(encoding='utf-8'))
            for resource in proof['resources'] + [{'name': proof['screenshot'], 'sha256': proof.get('screenshot_sha256', '')}]:
                if '/' in resource['name'] or sha((path.parent / resource['name']).read_bytes()) != resource['sha256']:
                    raise RuntimeError('evidence_integrity:' + item['id'])
            proofs[expected] = proof
        for file in item['files'] + item['notices'] + item['assets']:
            if sha((staging / file['path']).read_bytes()) != file['sha256']:
                raise RuntimeError('source_integrity:' + file['path'])
        for file in item['files']:
            if proof['source_files'].get(file['path']) != file['sha256']:
                raise RuntimeError('source_not_in_evidence:' + file['path'])
        for url in (item['poster_url'], item['clip_url']):
            if not (staging / url.removeprefix('/ui-library/')).is_file():
                raise RuntimeError('missing_media:' + url)
        if not (previews / (item['id'] + '.html')).is_file():
            raise RuntimeError('missing_preview:' + item['id'])


# ---------------------------------------------------------------- production


@contextlib.contextmanager
def flock(path: Path, *, wait: bool, timeout: float = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        if not wait:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            # Block in the kernel so the lock is taken the moment a release
            # ends; polling loses the gap between back-to-back releases.
            def expire(*_):
                raise TimeoutError('release_lock_timeout')
            previous = signal.signal(signal.SIGALRM, expire)
            signal.alarm(max(1, int(timeout)))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
        yield


def copy_new(source: Path, target: Path) -> bool:
    """Copy a file that must be new or byte-identical; never overwrite content."""
    if target.exists():
        if sha(target.read_bytes()) != sha(source.read_bytes()):
            raise RuntimeError('refuse_to_overwrite:' + str(target))
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.next')
    shutil.copyfile(source, temporary)
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)
    return True


def commit(production_data: Path, production_previews: Path, staging: Path, previews: Path,
           items: list[dict], catalog_sha: str, locks_update: dict[str, dict]) -> None:
    current = (production_data / 'catalog.json').read_bytes()
    if sha(current) != catalog_sha:
        raise RuntimeError('production_catalog_changed_during_refresh')
    evidence_dirs = set()
    for item in items:
        paths = [f['path'] for f in item['files'] + item['notices'] + item['assets']]
        paths += [item['poster_url'].removeprefix('/ui-library/'), item['clip_url'].removeprefix('/ui-library/')]
        for relative in paths:
            copy_new(staging / relative, production_data / relative)
        evidence_dirs.add(Path(item['rights_evidence_url'].removeprefix('/ui-library/')).parent)
        for preview in previews.glob(item['id'] + '.*'):
            if preview.name.startswith(item['id'] + '.') and not preview.name.endswith('.build.json'):
                copy_new(preview, production_previews / preview.name)
    for directory in evidence_dirs:
        for path in (staging / directory).iterdir():
            if path.name == 'manifest.json':
                continue
            copy_new(path, production_data / directory / path.name)
        # The manifest only ever grows (historical source hashes are asserted).
        write_json(production_data / directory / 'manifest.json',
                   read_json(staging / directory / 'manifest.json'))
    catalog = json.loads(current)
    catalog['items'] += items
    locks = read_json(production_data / 'upstreams.json', {})
    locks.update(locks_update)
    write_json(production_data / 'upstreams.json', locks)
    write_json(production_data / 'catalog.json', catalog)


def record_database(container: str, run_id: str, success: bool, error: str | None, log: Path) -> None:
    request = {'action': 'record', 'run_id': run_id, 'success': success, 'error': error, 'items': []}
    try:
        subprocess.run(['docker', 'exec', '-i', container, 'python', '-c', (HERE / 'db_bridge.py').read_text()],
                       input=json.dumps(request).encode(), capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        with log.open('a', encoding='utf-8') as stream:
            stream.write(f'database record skipped: {type(exc).__name__}\n')


# ---------------------------------------------------------------- driver


def load_state(state_dir: Path) -> dict:
    withdrawn = read_json(state_dir / 'withdrawn.json', {'version': 1, 'ids': []})
    if withdrawn.get('version') != 1 or not all(isinstance(v, str) and ID.fullmatch(v) for v in withdrawn.get('ids', [])):
        raise ValueError('invalid_withdrawal_policy')
    return {
        'withdrawn': withdrawn['ids'],
        'published': read_json(state_dir / 'published.json', {}),
        'held': read_json(state_dir / 'held.json', {}),
        'providers': read_json(state_dir / 'providers.json', {}),
    }


def save_state(state_dir: Path, state: dict) -> None:
    write_json(state_dir / 'published.json', state['published'])
    write_json(state_dir / 'held.json', state['held'])
    write_json(state_dir / 'providers.json', state['providers'])


def refresh(args) -> dict:
    state_dir: Path = args.state
    production = args.production
    production_data = production / 'mcp-go/internal/uicatalog/data'
    production_previews = production / 'frontend/.ui-previews/previews'
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_dir = state_dir / 'runs' / run_id
    run_dir.mkdir(parents=True)
    log = run_dir / 'commands.log'
    status = {'run_id': run_id, 'started_at': now(), 'status': 'checking', 'providers': {}, 'rows': []}

    def checkpoint(**values):
        status.update(values)
        write_json(run_dir / 'status.json', status)
        write_json(state_dir / 'latest.json', status)

    checkpoint()
    state = load_state(state_dir)

    def persist():
        # A dry run verifies only; holds and checked revisions stay untouched.
        if not args.dry_run:
            save_state(state_dir, state)

    catalog_raw = (production_data / 'catalog.json').read_bytes()
    catalog = json.loads(catalog_raw)
    catalog_ids = {item['id'] for item in catalog['items']}
    catalog_files = {file['path'] for item in catalog['items']
                     for key in ('files', 'notices', 'assets') for file in item.get(key, [])}
    previous = {item['id']: item for item in catalog['items']}
    fingerprints = {fingerprint(item) for item in catalog['items'] if item.get('files')}
    locks = read_json(production_data / 'upstreams.json', {})
    blocked = blocked_ids(state, catalog_ids)
    sources = registry()
    if args.providers:
        sources = {key: value for key, value in sources.items() if key in args.providers}
    upstreams = Upstreams(state_dir / 'cache/repos', log)
    node_modules = ensure_node_modules(state_dir, log)
    staging = run_dir / 'data'
    stage_data(production_data, staging, log)
    scratch = run_dir / 'baseline-data'
    groups: dict[str, list[dict]] = {}
    heads: dict[str, str] = {}
    keep_revisions: dict[str, set[str]] = {}
    for provider_id, (module_name, source) in sorted(sources.items()):
        row = status['providers'].setdefault(provider_id, {})
        memo = state['providers'].setdefault(provider_id, {})
        try:
            head = upstreams.head(source['repository'])
            row['head'] = heads[provider_id] = head
            keep_revisions.setdefault(source['repository'], set()).add(head)
            if memo.get('checked_revision') == head and not args.recheck:
                row['result'] = 'unchanged'
                continue
            checkout = upstreams.checkout(source['repository'], head)
            license_file = license_path(module_name, provider_id, source)
            license_bytes = (checkout / license_file).read_bytes() if (checkout / license_file).is_file() else b''
            if not license_bytes:
                raise Hold('license_removed_requires_review')
            if sha(license_bytes) != source['license_sha256']:
                raise Hold('license_changed_requires_review')
            if 'known' not in memo:
                lock = locks.get(provider_id)
                known: set[str] = set()
                if lock:
                    # Ids the reviewed revision produced but the catalog lacks were
                    # rejected by the gates or by a human; they must not return.
                    baseline = upstreams.checkout(source['repository'], lock['revision'])
                    keep_revisions[source['repository']].add(lock['revision'])
                    shutil.rmtree(scratch, ignore_errors=True)
                    scratch.mkdir()
                    known = {item['id'] for item in import_at(module_name, provider_id, source, baseline, lock['revision'],
                                                              scratch, '', node_modules, previous, {})}
                memo['known'] = sorted(known)
                memo['baseline_revision'] = lock['revision'] if lock else None
            scope = f'r{head[:12]}/'
            report: dict = {}
            items = import_at(module_name, provider_id, source, checkout, head, staging, scope, node_modules, previous, report)
            row['import'] = {key: {'imported': value['imported'], 'rejected': {r: len(v) for r, v in value['rejected'].items()}}
                             for key, value in report.items()}
            fresh, skipped = select_new(items, catalog_ids=catalog_ids, known=set(memo['known']),
                                        blocked=blocked, held=state['held'], seen=fingerprints)
            for item in fresh:
                item['poster_url'] = f"/ui-library/posters/{item['id']}-{head[:12]}.webp"
                item['clip_url'] = f"/ui-library/clips/{item['id']}-{head[:12]}.mp4"
                item['_checkout'] = str(checkout)
                item['_license_file'] = license_file
            groups[provider_id] = fresh
            row.update(fresh=len(fresh), skipped=len(skipped))
            status['rows'] += skipped
        except Hold as exc:
            row['result'] = 'held:' + str(exc)
            memo['hold'] = str(exc)
        except Exception as exc:  # one broken upstream never stops the others
            row['result'] = f'error:{type(exc).__name__}:{str(exc)[:200]}'
    checkpoint(status='selecting')
    chosen = round_robin(groups, args.limit)
    chosen_ids = {item['id'] for item in chosen}
    for provider_id, fresh in groups.items():
        if all(item['id'] in chosen_ids for item in fresh):
            # Fully drained; otherwise revisit the same head next run.
            state['providers'][provider_id]['checked_revision'] = heads[provider_id]
            state['providers'][provider_id].pop('hold', None)
        head = heads[provider_id]
        # A previous batch can already use files in this exact revision scope.
        # Retain its complete file closure alongside the newly selected batch.
        keep = catalog_files | {f['path'] for item in fresh if item['id'] in chosen_ids for f in item['files']}
        gc_scope(staging, provider_id, f'r{head[:12]}/', keep)
    if not chosen:
        persist()
        upstreams.prune(keep_revisions)
        checkpoint(status='no_changes', finished_at=now())
        return status

    # Build previews and media for the chosen candidates only.
    checkpoint(status='rendering', chosen=len(chosen))
    staged_catalog = json.loads((staging / 'catalog.json').read_text(encoding='utf-8'))
    public = [{k: v for k, v in item.items() if not k.startswith('_')} for item in chosen]
    staged_catalog['items'] += public
    write_json(staging / 'catalog.json', staged_catalog)
    frontend = prepare_frontend(run_dir, node_modules)
    previews = frontend / '.ui-previews/previews'
    ids_file = run_dir / 'ids.json'
    write_json(ids_file, sorted(chosen_ids))
    build_failed: set[str] = set()
    env = dict(os.environ, UI_LIBRARY_DATA_ROOT=str(staging), UI_PREVIEW_IDS_FILE=str(ids_file))
    try:
        run(['node', 'scripts/build-ui-previews.mjs'], cwd=frontend, env=env, timeout=7200, log=log)
    except RuntimeError:
        # The builder stops at the first failure; retry one by one to isolate it.
        for item in public:
            write_json(ids_file, [item['id']])
            try:
                run(['node', 'scripts/build-ui-previews.mjs'], cwd=frontend, env=env, timeout=900, log=log)
            except RuntimeError:
                build_failed.add(item['id'])
    renderable = [item for item in public if item['id'] not in build_failed
                  and (previews / (item['id'] + '.html')).is_file()]
    results: dict[str, dict] = {}
    if renderable:
        with serve(staging, previews) as base:
            rows = node_job(frontend, {'mode': 'media', 'items': renderable, 'data': str(staging), 'base': base,
                                       'ffmpeg': args.ffmpeg, 'workers': args.workers}, run_dir, 'media', log=log,
                            browser_libs=args.browser_libs)
        results = {row['id']: row for row in rows}
    passed = []
    for item in public:
        result = results.get(item['id'])
        if item['id'] in build_failed or not (previews / (item['id'] + '.html')).is_file():
            reason = 'preview_build_failed'
        elif not result or result.get('state') != 'ready' or result.get('errors'):
            reason = 'render_failed'
        elif result.get('poster_stddev', 0) <= 3:
            reason = 'blank_poster'
        else:
            passed.append(item)
            continue
        state['held'][item['id']] = {'fingerprint': fingerprint(item), 'reason': reason,
                                     'revision': item['revision'], 'at': now()}
        status['rows'].append({'id': item['id'], 'status': 'held', 'reason': reason,
                               'errors': (result or {}).get('errors', [])[:3]})

    # Rights evidence per provider revision.
    checkpoint(status='evidence', passed=len(passed))
    by_evidence: dict[str, list[dict]] = {}
    for item in passed:
        by_evidence.setdefault(item['rights_evidence_url'], []).append(item)
    screenshots = []
    final: list[dict] = []
    locks_update: dict[str, dict] = {}
    for url, members in by_evidence.items():
        first = next(c for c in chosen if c['id'] == members[0]['id'])
        provider_id = first['provider_id']
        module_name, source = sources[provider_id]
        target = staging / Path(url.removeprefix('/ui-library/')).parent
        break_links(target)
        try:
            record = evidence_record(source['repository'], first['revision'], first['license'], first['_license_file'],
                                     find_readme(Path(first['_checkout'])), Path(first['_checkout']), target,
                                     {f['path']: f['sha256'] for item in members for f in item['files']})
        except Hold as exc:
            for item in members:
                state['held'][item['id']] = {'fingerprint': fingerprint(item), 'reason': str(exc),
                                             'revision': item['revision'], 'at': now()}
                status['rows'].append({'id': item['id'], 'status': 'held', 'reason': str(exc)})
            continue
        write_json(target / 'manifest.json', record)
        if not record.get('screenshot_sha256'):
            screenshots.append({'url': record['license_page_url'], 'out': str(target / 'license-page.png'),
                                'license': record['license'], 'manifest': str(target / 'manifest.json')})
        final += members
        locks_update[provider_id] = {'repository': source['repository'], 'revision': first['revision'],
                                     'license_source': first['_license_file']}
    if screenshots:
        shot_rows = {row['manifest']: row for row in node_job(frontend, {'mode': 'evidence', 'pages': screenshots},
                                                              run_dir, 'evidence', log=log,
                                                              browser_libs=args.browser_libs, timeout=1800)}
        for page in screenshots:
            row = shot_rows.get(page['manifest'])
            manifest = Path(page['manifest'])
            if row and row.get('sha256'):
                record = read_json(manifest)
                record.update(screenshot_sha256=row['sha256'], screenshot_captured_at=now())
                write_json(manifest, record)
            else:
                evidence_url = '/ui-library/' + manifest.relative_to(staging).as_posix()
                dropped = [item for item in final if item['rights_evidence_url'] == evidence_url]
                final = [item for item in final if item['rights_evidence_url'] != evidence_url]
                for item in dropped:
                    status['rows'].append({'id': item['id'], 'status': 'deferred', 'reason': 'license_screenshot_failed'})
                    locks_update.pop(item['provider_id'], None)
                    # Not held: retry on the next run once GitHub is reachable.
                    state['providers'][item['provider_id']].pop('checked_revision', None)
    if not final:
        persist()
        checkpoint(status='no_changes', finished_at=now())
        return status

    # Drop everything that did not pass from the staged catalog, then verify.
    checkpoint(status='verifying', approved=len(final))
    final_ids = {item['id'] for item in final}
    staged_catalog['items'] = [item for item in staged_catalog['items'] if item['id'] in catalog_ids or item['id'] in final_ids]
    write_json(staging / 'catalog.json', staged_catalog)
    locks_staged = read_json(staging / 'upstreams.json', {})
    locks_staged.update(locks_update)
    write_json(staging / 'upstreams.json', locks_staged)
    verify_web_contract(staging, previews, final)
    verify_go_catalog(staging, run_dir, log)
    if args.dry_run:
        checkpoint(status='dry_run_verified', finished_at=now(), would_publish=sorted(final_ids))
        return status

    checkpoint(status='publishing')
    with flock(args.release_lock, wait=True, timeout=3 * 3600):
        commit(production_data, production_previews, staging, previews, final, sha(catalog_raw), locks_update)
    for item in final:
        state['published'][item['id']] = {'revision': item['revision'], 'at': now()}
        state['held'].pop(item['id'], None)
        status['rows'].append({'id': item['id'], 'status': 'published'})
    save_state(state_dir, state)
    upstreams.prune(keep_revisions)
    shutil.rmtree(staging, ignore_errors=True)
    checkpoint(status='published', published=len(final), total=len(catalog['items']) + len(final), finished_at=now())
    return status


def main() -> None:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--production', type=Path, default=home / 'AIGCNEWS-production')
    parser.add_argument('--state', type=Path, default=home / '.local/state/aigcnews-ui-refresh')
    parser.add_argument('--release-lock', type=Path, default=home / '.local/state/aigcnews-local-delivery/build-release.lock')
    parser.add_argument('--backend-container', default='aigc-backend')
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or 'ffmpeg')
    runtime_libs = home / '.cache/ms-playwright/runtime-libs/root/usr/lib/x86_64-linux-gnu'
    parser.add_argument('--browser-libs', type=Path, default=runtime_libs if runtime_libs.is_dir() else None,
                        help='extra LD_LIBRARY_PATH for the headless browser')
    parser.add_argument('--limit', type=int, default=48, help='new components per run (1-128)')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--providers', nargs='*', help='restrict to these provider ids')
    parser.add_argument('--recheck', action='store_true', help='re-import even when the upstream head is unchanged')
    parser.add_argument('--dry-run', action='store_true', help='stage and verify, but do not touch production')
    args = parser.parse_args()
    if not 1 <= args.limit <= 128:
        parser.error('limit must be between 1 and 128')
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with flock(args.state / 'refresh.lock', wait=False):
            try:
                status = refresh(args)
            except Exception as exc:
                latest = read_json(args.state / 'latest.json', {})
                latest.update(status='failed', error=f'{type(exc).__name__}:{str(exc)[:300]}', finished_at=now())
                write_json(args.state / 'latest.json', latest)
                if not args.dry_run and latest.get('run_id'):
                    record_database(args.backend_container, latest['run_id'], False, 'refresh_failed',
                                    args.state / 'runs' / latest['run_id'] / 'commands.log')
                raise
    except BlockingIOError:
        print('another UI refresh is running', file=sys.stderr)
        return
    if not args.dry_run:
        record_database(args.backend_container, status['run_id'], True, None,
                        args.state / 'runs' / status['run_id'] / 'commands.log')
    print(json.dumps({key: status.get(key) for key in ('run_id', 'status', 'chosen', 'passed', 'published', 'total')}))


if __name__ == '__main__':
    main()
