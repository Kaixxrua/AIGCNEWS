"""Fail-closed adapter for static HTML referred by X and hosted in opted-in GitHub repos."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from adapter import Hold, blob_sha, sha

_REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
_PATH = re.compile(r'[A-Za-z0-9_./-]+\.html')
_MIT_MARKERS = (
    'permission is hereby granted, free of charge',
    'to deal in the software without restriction',
    'including without limitation the rights',
    'use, copy, modify, merge, publish, distribute, sublicense, and/or sell',
    'subject to the following conditions',
    'copyright notice and this permission notice shall be included',
    'the software is provided "as is"',
    'authors or copyright holders be liable for any claim, damages or other liability',
)
_BLOCKED_CSS = re.compile(r'@import|url\s*\(|expression\s*\(|behavior\s*:|-moz-binding', re.I)


def provider_id(payload: dict) -> str:
    config_id = payload.get('discovery_source_config_id')
    if not isinstance(config_id, int) or config_id <= 0:
        raise Hold('unapproved_x_source_config')
    return f'xgithub-{config_id}'


def checked_payload(payload: dict) -> tuple[str, str, str]:
    repository = str(payload.get('repo', ''))
    path = str(payload.get('path', ''))
    revision = str(payload.get('source_revision', ''))
    if (payload.get('kind') != 'x_github_html' or payload.get('auto_publish_eligible') is not True
            or not _REPOSITORY.fullmatch(repository) or not _PATH.fullmatch(path)
            or '..' in Path(path).parts or not re.fullmatch(r'[0-9a-f]{40}', revision)):
        raise Hold('invalid_x_github_candidate')
    return repository, path, revision


def license_path(payload: dict) -> str:
    roots = [
        str(entry.get('path', '')) for entry in payload.get('license_files', [])
        if re.fullmatch(r'(?i:licen[cs]e)(?:\.(?:md|txt))?', str(entry.get('path', '')))
    ]
    if len(roots) != 1:
        raise Hold('single_root_license_required')
    return roots[0]


def validate_mit_license(payload: dict, raw: bytes, path: str) -> None:
    expected = next((entry.get('sha') for entry in payload.get('license_files', []) if entry.get('path') == path), None)
    if expected != blob_sha(raw) or len(raw) > 128_000:
        raise Hold('license_blob_mismatch')
    text = raw.decode('utf-8').lower()
    if not all(marker in text for marker in _MIT_MARKERS):
        raise Hold('unsupported_or_modified_license')
    if re.search(r'non[- ]commercial|no commercial|not for commercial|additional restriction', text):
        raise Hold('restricted_license')


def _safe_css(value: str) -> None:
    if _BLOCKED_CSS.search(value):
        raise Hold('unreviewed_css_resource')


class StaticHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.body = False
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        lowered = tag.lower()
        if lowered == 'body':
            self.body = True
        if lowered == 'style':
            self.in_style = True
        if lowered in {'script', 'iframe', 'object', 'embed', 'video', 'audio', 'canvas', 'foreignobject', 'base'}:
            raise Hold('active_or_embedded_content')
        for key, value in attrs.items():
            key, value = key.lower(), value or ''
            if key.startswith('on') or key in {'srcdoc', 'formaction', 'action'}:
                raise Hold('active_attribute')
            if key == 'style':
                _safe_css(value)
            if key in {'src', 'href', 'xlink:href', 'poster', 'srcset'}:
                if lowered == 'a' and key == 'href' and value.startswith('#'):
                    continue
                raise Hold('external_resource_or_link')
        if lowered == 'meta' and 'http-equiv' in attrs:
            raise Hold('active_meta')

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag.lower() == 'style':
            self.in_style = False

    def handle_data(self, value):
        if self.in_style:
            _safe_css(value)


def validate_static_html(raw: bytes, expected_blob: str) -> str:
    if len(raw) > 160_000 or blob_sha(raw) != expected_blob:
        raise Hold('source_blob_mismatch_or_size')
    text = raw.decode('utf-8')
    parser = StaticHTML()
    parser.feed(text)
    parser.close()
    if not parser.body or not re.search(r'</body>', text, re.I):
        raise Hold('missing_body')
    return sha(re.sub(r'\s+', ' ', re.search(r'<body[^>]*>([\s\S]*?)</body>', text, re.I)[1]).encode())


def make_item(data: Path, payload: dict, raw: bytes, license_raw: bytes, added_at: str) -> dict:
    repository, path, revision = checked_payload(payload)
    provider = provider_id(payload)
    slug = re.sub(r'[^a-z0-9]+', '-', f'{repository}-{path}'.lower()).strip('-')[:180]
    item_id = f'x-{slug}'
    source_path = f'sources/{provider}/{path}'
    notice_path = f'licenses/{provider}/LICENSE'
    source = data / source_path
    notice = data / notice_path
    source.parent.mkdir(parents=True, exist_ok=True)
    notice.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(raw)
    notice.write_bytes(license_raw)
    title = Path(path).stem.replace('-', ' ').replace('_', ' ').strip().title() or repository
    return {
        'id': item_id, 'name': {'zh': title, 'en': title},
        'description': {'zh': f'由 X 发现的 {repository} 原版静态 UI，含源码与 MIT 许可。',
                        'en': f'Original static UI from {repository}, discovered via X with source and MIT license.'},
        'provider': repository, 'provider_id': provider, 'author': repository.split('/')[0],
        'license': 'MIT', 'license_url': f'/ui-library/{notice_path}',
        'source_url': payload['source_url'], 'revision': revision,
        'demo_url': payload.get('x_source_url', payload['source_url']),
        'category': 'component', 'frameworks': ['html'],
        'aliases': [title.lower(), 'html', 'css', 'ui', 'component', '组件', '素材'],
        'files': [{'name': path, 'path': source_path, 'sha256': sha(raw)}],
        'notices': [{'name': 'LICENSE', 'path': notice_path, 'sha256': sha(license_raw)}],
        'dependencies': {}, 'export_name': '', 'props': {}, 'assets': [],
        'notes': {'zh': '保留原版 HTML/CSS 和 MIT 许可；自动发布不允许脚本或外部资源。',
                  'en': 'Preserve the original HTML/CSS and MIT notice; automated publication forbids scripts and external resources.'},
        'preview_kind': 'html', 'preview_url': f'/ui-library/previews/{item_id}.html',
        'poster_url': f'/ui-library/posters/{item_id}.png', 'clip_url': '',
        'added_at': added_at, 'subcategory': 'other', 'kind': 'component', 'styles': [],
        'rights_evidence_url': f'/ui-library/assets/{provider}/evidence/{revision}/manifest.json',
    }
