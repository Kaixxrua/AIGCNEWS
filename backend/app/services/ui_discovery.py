"""Daily discovery only: never execute upstream code or auto-publish candidates."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from typing import Any
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import httpx

from backend.app.repositories.postgres_ui_library_repository import PostgresUiLibraryRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepositorySource:
    id: str
    repo: str
    paths: tuple[str, ...]


SOURCES = (
    RepositorySource('uiverse', 'uiverse-io/galaxy', ('*.html',)),
    RepositorySource('motion-primitives', 'ibelick/motion-primitives', ('components/core/*.tsx',)),
    RepositorySource('magic-ui', 'magicuidesign/magicui', ('apps/www/registry/magicui/*.tsx',)),
    RepositorySource('hyperui', 'markmead/hyperui', ('public/examples/*.html',)),
    RepositorySource('magic-portfolio', 'magicuidesign/portfolio', ('src/app/page.tsx',)),
)
X_HANDLES = ('ibelick', 'dillionverma', 'akella')
CODROPS_FEED = 'https://tympanus.net/codrops/feed/'
MAX_BYTES = 12 * 1024 * 1024


class DiscoveryError(Exception):
    """Only stable, non-secret error codes cross into stored diagnostics."""


async def read_upstream(client: httpx.AsyncClient, url: str, token: str = '') -> bytes:
    host = urlsplit(url).hostname
    if urlsplit(url).scheme != 'https' or host not in {'api.github.com', 'tympanus.net'}:
        raise DiscoveryError('unapproved_upstream')
    headers = {'User-Agent': 'AIGCNEWS-UI-Discovery/1.0'}
    if host == 'api.github.com':
        headers['Accept'] = 'application/vnd.github+json'
        if token:
            headers['Authorization'] = f'Bearer {token}'
    async with client.stream('GET', url, headers=headers, follow_redirects=False) as response:
        if response.status_code != 200:
            raise DiscoveryError(f'upstream_http_{response.status_code}')
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise DiscoveryError('upstream_too_large')
        return bytes(data)


def tree_candidates(source: RepositorySource, tree: dict[str, Any]) -> list[dict[str, Any]]:
    if tree.get('truncated'):
        raise DiscoveryError('github_tree_truncated')
    revision = tree.get('commit_sha', tree['sha'])
    blobs = [entry for entry in tree['tree'] if entry.get('type') == 'blob' and entry.get('mode') == '100644']
    licenses = [{'path': entry['path'], 'sha': entry['sha']} for entry in blobs
                if entry['path'].rsplit('/', 1)[-1].lower().startswith(('license', 'licence', 'notice'))]
    license_revision = hashlib.sha256(json.dumps(licenses, sort_keys=True).encode()).hexdigest()
    candidates = []
    for entry in blobs:
        path = entry['path']
        if not any(fnmatch(path, pattern) for pattern in source.paths):
            continue
        candidates.append({
            'id': f'{source.repo}:{path}', 'revision': f"{entry['sha']}:{license_revision}",
            'title': path.rsplit('/', 1)[-1].rsplit('.', 1)[0], 'repo': source.repo, 'path': path,
            'source_url': f'https://github.com/{source.repo}/blob/{revision}/{quote(path, safe="/")}',
            'source_revision': revision, 'source_blob_sha': entry['sha'],
            'license_files': licenses, 'license_status': 'needs_review',
        })
    if not candidates:
        raise DiscoveryError('source_layout_changed_or_empty')
    return candidates


def rss_candidates(raw: bytes) -> list[dict[str, Any]]:
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise DiscoveryError('unsafe_feed_xml')
    root = ElementTree.fromstring(raw)
    result = []
    for item in root.findall('./channel/item'):
        url = item.findtext('link', '')
        if urlsplit(url).hostname != 'tympanus.net' or urlsplit(url).scheme != 'https':
            continue
        title = item.findtext('title', '')
        result.append({'id': url, 'revision': hashlib.sha256(ElementTree.tostring(item)).hexdigest(),
                       'title': title, 'source_url': url, 'published_at': item.findtext('pubDate', ''),
                       'license_status': 'needs_review', 'kind': 'article_link'})
    if not result:
        raise DiscoveryError('empty_or_invalid_feed')
    return result


async def discover_web(repo: PostgresUiLibraryRepository, *, token: str = '', proxy: str = '',
                       client: httpx.AsyncClient | None = None) -> bool:
    if client is None:
        async with httpx.AsyncClient(timeout=30, trust_env=False, proxy=proxy or None) as owned:
            return await discover_web(repo, token=token, client=owned)
    succeeded = True
    for source in (*SOURCES, None):
        source_id = source.id if source else 'codrops'
        try:
            async with asyncio.timeout(90):
                if source:
                    commit = json.loads(await read_upstream(client, f'https://api.github.com/repos/{source.repo}/commits/HEAD', token))
                    commit_sha = commit['sha']
                    raw = await read_upstream(client, f'https://api.github.com/repos/{source.repo}/git/trees/{commit_sha}?recursive=1', token)
                    tree = json.loads(raw)
                    tree['commit_sha'] = commit_sha
                    candidates = tree_candidates(source, tree)
                    revision = tree.get('commit_sha', tree['sha'])
                else:
                    raw = await read_upstream(client, CODROPS_FEED)
                    candidates = rss_candidates(raw)
                    revision = hashlib.sha256(raw).hexdigest()
                counts = await asyncio.to_thread(repo.record_discovery, source_id, revision, candidates)
                logger.info('[UI Discovery] %s %s', source_id, counts)
        except Exception as exc:
            succeeded = False
            code = str(exc) if isinstance(exc, DiscoveryError) else type(exc).__name__
            await asyncio.to_thread(repo.record_failure, source_id, code)
            logger.warning('[UI Discovery] %s failed: %s', source_id, code)
    return succeeded


async def discover_x(repo: PostgresUiLibraryRepository, transport: Any) -> bool:
    from backend.app.services.source_plugins.x_source import XWindowFetchResult
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    try:
        async with asyncio.timeout(300):
            result = await transport.fetch_watchlist_tweets_window(X_HANDLES, window_start=start, window_end=now, count_per_user=20)
        if (not isinstance(result, XWindowFetchResult) or not result.complete
                or set(result.by_handle) != set(X_HANDLES)
                or result.window_start != start or result.window_end != now):
            raise DiscoveryError('x_window_incomplete')
        for handle in X_HANDLES:
            candidates = []
            for tweet in result.by_handle[handle].tweets:
                tweet_id = str(getattr(tweet, 'id', ''))
                if not tweet_id.isdigit():
                    continue
                links = [str(url) for url in getattr(tweet, 'urls', []) or []
                         if urlsplit(str(url)).scheme == 'https']
                if not links:
                    continue
                # Links remain untrusted candidates. No arbitrary URL fetching.
                candidates.append({'id': f'x:{tweet_id}', 'revision': hashlib.sha256(json.dumps(links).encode()).hexdigest(),
                                   'title': str(getattr(tweet, 'text', ''))[:500], 'author': handle,
                                   'source_url': f'https://x.com/{handle}/status/{tweet_id}',
                                   'links': links, 'license_status': 'needs_review', 'kind': 'social_link'})
            await asyncio.to_thread(repo.record_discovery, f'x:{handle}', now.isoformat(), candidates)
        return True
    except Exception as exc:
        code = str(exc) if isinstance(exc, DiscoveryError) else type(exc).__name__
        for handle in X_HANDLES:
            await asyncio.to_thread(repo.record_failure, f'x:{handle}', code)
        return False
