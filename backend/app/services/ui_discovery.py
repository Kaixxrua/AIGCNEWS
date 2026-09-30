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
from backend.app.services.outbound_target_policy import OutboundTargetPolicyError, normalize_http_url, pin_http_target

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
# The tympanus.net RSS now answers automated clients with a Cloudflare challenge;
# challenges are never solved. Codrops publishes each demo as a repository of the
# codrops GitHub organization, so newly created repositories are link-only
# candidates (Codrops demos forbid redistribution as-is and may carry
# third-party images; they are never published into the catalog).
CODROPS_REPOS = 'https://api.github.com/orgs/codrops/repos?sort=created&direction=desc&per_page=30'
MAX_BYTES = 12 * 1024 * 1024


class DiscoveryError(Exception):
    """Only stable, non-secret error codes cross into stored diagnostics."""


async def read_upstream(client: httpx.AsyncClient, url: str, token: str = '') -> bytes:
    host = urlsplit(url).hostname
    if urlsplit(url).scheme != 'https' or host != 'api.github.com':
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


async def read_configured_feed(client: httpx.AsyncClient, url: str) -> bytes:
    """Fetch an administrator-configured feed through the shared SSRF-safe pinned target policy."""
    if urlsplit(url).scheme != 'https':
        raise DiscoveryError('unsafe_feed_target')
    try:
        target = await asyncio.to_thread(
            pin_http_target, url, allowed_ports={443}, reject_mixed=True,
        )
    except OutboundTargetPolicyError as exc:
        raise DiscoveryError('unsafe_feed_target') from exc
    headers = {'User-Agent': 'AIGCNEWS-UI-Discovery/1.0', 'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml'}
    async with client.stream(
        'GET', target.request_url, headers={**headers, **target.headers},
        extensions=target.extensions, follow_redirects=False,
    ) as response:
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


def feed_candidates(raw: bytes, feed_url: str) -> list[dict[str, Any]]:
    head = raw[:2048].lstrip().lower()
    if head.startswith(b'<html') or head.startswith(b'<!doctype html'):
        # Bot challenges and error pages are HTML, not feeds; report, never bypass.
        raise DiscoveryError('feed_returned_html')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise DiscoveryError('unsafe_feed_xml')
    root = ElementTree.fromstring(raw)
    result = []
    entries = list(root.findall('./channel/item'))
    if not entries:
        entries = list(root.findall('.//{http://www.w3.org/2005/Atom}entry'))
    feed_host = urlsplit(feed_url).hostname
    for item in entries:
        url = item.findtext('link', '')
        if not url:
            link = item.find('{http://www.w3.org/2005/Atom}link')
            url = str(link.get('href', '')) if link is not None else ''
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname:
            continue
        if feed_host == 'tympanus.net' and parsed.hostname != feed_host:
            continue
        title = item.findtext('title', '') or item.findtext('{http://www.w3.org/2005/Atom}title', '')
        published_at = (
            item.findtext('pubDate', '')
            or item.findtext('{http://www.w3.org/2005/Atom}published', '')
            or item.findtext('{http://www.w3.org/2005/Atom}updated', '')
        )
        result.append({'id': url, 'revision': hashlib.sha256(ElementTree.tostring(item)).hexdigest(),
                       'title': title, 'source_url': url, 'published_at': published_at,
                       'license_status': 'needs_review', 'kind': 'article_link'})
    if not result:
        raise DiscoveryError('empty_or_invalid_feed')
    return result


def codrops_candidates(raw: bytes) -> list[dict[str, Any]]:
    result = []
    for repository in json.loads(raw):
        name = str(repository.get('name', ''))
        url = str(repository.get('html_url', ''))
        if repository.get('fork') or repository.get('archived') or url != f'https://github.com/codrops/{name}':
            continue
        homepage = str(repository.get('homepage') or '')
        link = {'id': url, 'title': name, 'source_url': url, 'repo': f'codrops/{name}',
                'description': str(repository.get('description') or '')[:500],
                'demo_url': homepage if urlsplit(homepage).scheme == 'https' else '',
                'published_at': str(repository.get('created_at') or ''),
                'license_status': 'needs_review', 'kind': 'article_link'}
        link['revision'] = hashlib.sha256(json.dumps(
            [link['source_url'], link['description'], link['demo_url']]).encode()).hexdigest()
        result.append(link)
    if not result:
        raise DiscoveryError('source_layout_changed_or_empty')
    return result


async def discover_web(repo: PostgresUiLibraryRepository, *, token: str = '', proxy: str = '',
                       client: httpx.AsyncClient | None = None) -> bool:
    if client is None:
        async with httpx.AsyncClient(timeout=30, trust_env=False, proxy=proxy or None) as owned:
            return await discover_web(repo, token=token, client=owned)
    succeeded = True
    configured = await asyncio.to_thread(repo.list_source_configs, enabled_only=True)
    sources: list[RepositorySource | dict[str, Any] | None] = [*SOURCES, None, *configured]
    for source in sources:
        custom = isinstance(source, dict)
        if custom:
            source_id = f"custom:{source['id']}"
        else:
            source_id = source.id if source else 'codrops'
        try:
            async with asyncio.timeout(90):
                if custom and source['kind'] == 'feed':
                    feed_url = normalize_http_url(source['feed_url'], allowed_ports={443})
                    raw = await read_configured_feed(client, feed_url)
                    candidates = feed_candidates(raw, feed_url)
                    revision = hashlib.sha256(raw).hexdigest()
                elif source:
                    repository = source['repository'] if custom else source.repo
                    paths = tuple(source['path_patterns']) if custom else source.paths
                    repository_source = RepositorySource(source_id, repository, paths)
                    commit = json.loads(await read_upstream(client, f'https://api.github.com/repos/{repository}/commits/HEAD', token))
                    commit_sha = commit['sha']
                    raw = await read_upstream(client, f'https://api.github.com/repos/{repository}/git/trees/{commit_sha}?recursive=1', token)
                    tree = json.loads(raw)
                    tree['commit_sha'] = commit_sha
                    candidates = tree_candidates(repository_source, tree)
                    revision = tree.get('commit_sha', tree['sha'])
                else:
                    raw = await read_upstream(client, CODROPS_REPOS, token)
                    candidates = codrops_candidates(raw)
                    revision = hashlib.sha256(json.dumps([c['id'] for c in candidates]).encode()).hexdigest()
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
        publish_sources = {
            str(source['repository']).lower(): source
            for source in await asyncio.to_thread(repo.list_source_configs, enabled_only=True)
            if source['kind'] == 'github' and source.get('x_auto_publish')
        }
        resolved = {
            repository: await asyncio.to_thread(repo.source_candidates, f"custom:{config['id']}")
            for repository, config in publish_sources.items()
        }
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
                linked_repositories = set()
                for link in links:
                    parsed = urlsplit(link)
                    if parsed.hostname not in {'github.com', 'www.github.com'}:
                        continue
                    parts = [part for part in parsed.path.split('/') if part]
                    if len(parts) >= 2:
                        linked_repositories.add(f'{parts[0]}/{parts[1]}'.removesuffix('.git').lower())
                for repository in linked_repositories:
                    config = publish_sources.get(repository)
                    for item in resolved.get(repository, []):
                        promoted = dict(item)
                        promoted.update({
                            'id': f"x:{tweet_id}:{item['id']}", 'kind': 'x_github_html',
                            'x_tweet_id': tweet_id, 'x_author': handle,
                            'x_source_url': f'https://x.com/{handle}/status/{tweet_id}',
                            'discovery_source_config_id': config['id'],
                            'auto_publish_eligible': True,
                        })
                        candidates.append(promoted)
            await asyncio.to_thread(repo.record_discovery, f'x:{handle}', now.isoformat(), candidates)
        return True
    except Exception as exc:
        code = str(exc) if isinstance(exc, DiscoveryError) else type(exc).__name__
        for handle in X_HANDLES:
            await asyncio.to_thread(repo.record_failure, f'x:{handle}', code)
        return False
