"""Upgrade cached owner avatars only when official repository artwork is found."""
from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.parse import quote

import httpx
from PIL import Image

from backend.app.core.config import settings
from backend.app.services.ingestion.github_artwork_transport import GitHubArtworkTransport
from backend.app.services.ingestion.github_project_logos import _REPO, discover_logos, download_logo

README_PATHS = ('README.md', 'readme.md', 'README.MD', '.github/README.md', 'docs/README.md', 'README.markdown')


def readme_candidates(names, client, *, fallback=False):
    """Batch immutable README snapshots; failed lookups never mean no logo exists."""
    from backend.app.services.ingestion.source_github import _build_headers, _get_token

    if not _get_token():
        raise ValueError('GitHub token required for batched README lookup')
    if len(names) > 25 or any(not _REPO.fullmatch(name) for name in names):
        raise ValueError('invalid repository batch')
    paths = README_PATHS[1:] if fallback else README_PATHS[:1]
    fields = []
    for i, name in enumerate(names):
        owner, repo = name.split('/')
        blobs = ' '.join(f'b{j}: object(expression: {json.dumps("HEAD:" + path)}) '
                         '{ ... on Blob { text isTruncated } }' for j, path in enumerate(paths))
        fields.append(f'r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(repo)}) '
                      '{ nameWithOwner defaultBranchRef { target { oid } } ' + blobs + ' }')
    with client.stream('POST', 'https://api.github.com/graphql', headers=_build_headers(),
                       json={'query': 'query { ' + ' '.join(fields) + ' }'}) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 16_000_000:
                raise ValueError('README response too large')
    payload = json.loads(body)
    data = payload.get('data') or {}
    errors = payload.get('errors') or []
    result = {}
    missing = []
    for i, name in enumerate(names):
        key = f'r{i}'
        row = data.get(key)
        if not row or any(not e.get('path') or e['path'][0] == key for e in errors):
            result[name] = {'status': 'lookup_failed'}
            continue
        canonical = row.get('nameWithOwner', '')
        oid = ((row.get('defaultBranchRef') or {}).get('target') or {}).get('oid', '')
        if not _REPO.fullmatch(canonical) or not re.fullmatch(r'[a-f0-9]{40}', oid):
            result[name] = {'status': 'lookup_failed'}
            continue
        candidates = []
        truncated = False
        has_readme = False
        for j, path in enumerate(paths):
            blob = row.get(f'b{j}') or {}
            text = blob.get('text')
            if blob.get('isTruncated'):
                truncated = True
                continue
            if isinstance(text, str):
                has_readme = True
                base = f'https://raw.githubusercontent.com/{canonical}/{oid}/{quote(path)}'
                candidates.extend(discover_logos(text, base))
                break
        if not fallback and not has_readme and not truncated:
            missing.append(name)
        result[name] = {'status': 'lookup_failed' if truncated and not candidates else 'checked',
                        'candidates': list(dict.fromkeys(candidates))[:4]}
    if missing:
        try:
            result.update(readme_candidates(missing, client, fallback=True))
        except (ValueError, httpx.HTTPError) as exc:
            result.update({name: {'status': 'lookup_failed', 'error': type(exc).__name__} for name in missing})
    return result


def upgrade_one(snapshot, images):
    if snapshot['status'] != 'checked':
        return {k: v for k, v in snapshot.items() if k != 'candidates'}
    errors = []
    for url in snapshot['candidates']:
        # A README may itself link an owner avatar: that is not an upgrade.
        if 'avatars.githubusercontent.com/' in url or re.match(r'https://github.com/[^/]+\.png', url):
            continue
        try:
            content, mime = download_logo(url, images)
            return {'status': 'found', 'source_url': url, 'content': content,
                    'content_type': mime, 'sha256': hashlib.sha256(content).hexdigest()}
        except (ValueError, OSError, httpx.HTTPError, ET.ParseError,
                Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            errors.append({'url': url, 'error': type(exc).__name__,
                           'reason': str(exc)[:160] if isinstance(exc, ValueError) else '',
                           'http_status': exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None})
    return {'status': 'download_failed' if errors else 'no_logo', 'errors': errors}


def _fetch_readme_batch(names, api):
    for attempt in range(3):
        try:
            return readme_candidates(names, api)
        except httpx.HTTPError as exc:
            transient = isinstance(exc, (httpx.TransportError,)) or (
                isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {502, 503, 504})
            if not transient or attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def _readme_batches(rows, api, workers=4):
    batches = iter(rows[offset:offset + 25] for offset in range(0, len(rows), 25))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}

        def submit():
            batch = next(batches, None)
            if batch:
                pending[pool.submit(_fetch_readme_batch, [r['full_name'] for r in batch], api)] = batch

        for _ in range(workers):
            submit()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                batch = pending.pop(future)
                try:
                    snapshots = future.result()
                except (ValueError, httpx.HTTPError) as exc:
                    snapshots = {row['full_name']: {'status': 'lookup_failed', 'error': type(exc).__name__,
                                                   'http_status': exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None}
                                 for row in batch}
                yield batch, snapshots
                submit()


def upgrade_avatars(repository, rows, report, workers=16):
    """One complete snapshot pass; only successful upgrades write the logo table."""
    counts = {'selected': 0, 'found': 0, 'no_logo': 0, 'lookup_failed': 0, 'download_failed': 0}
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as api, httpx.Client(
        timeout=15, follow_redirects=False, trust_env=False,
        transport=GitHubArtworkTransport(settings.github_artwork_proxy or settings.outbound_proxy or None),
    ) as images, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}

        def persist(done):
            for future in done:
                row = futures.pop(future)
                result = future.result()
                if result['status'] == 'found':
                    repository.save(row['repo_id'], result)
                record = {**row, **{k: v for k, v in result.items() if k != 'content'}}
                report.write(json.dumps(record) + '\n')
                report.flush()
                counts['selected'] += 1
                counts[result['status']] += 1
            if done:
                print(json.dumps(counts), flush=True)

        for batch, snapshots in _readme_batches(rows, api, max(1, min(workers // 4, 8))):
            for row in batch:
                futures[pool.submit(upgrade_one, snapshots[row['full_name']], images)] = row
            persist({future for future in futures if future.done()})
            while len(futures) >= max(100, workers * 4):
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                persist(done)
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            persist(done)
    return counts
