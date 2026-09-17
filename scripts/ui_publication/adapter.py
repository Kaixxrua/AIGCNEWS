"""Fail-closed HyperUI importer. Policy changes require a new source review."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

REPOSITORY = 'markmead/hyperui'
LICENSE_SHA = '60e0bb845a95da072acc1ada114cf8ce325347ed9d5f802d8d7fd9b511248f98'
HELPER_SHA = '3cb42e2b9cba44f749ddaf7e1a2323480c4bf6f8a7f77e893a5bfd3b971fb4a3'
CSS_SHA = '2658bf28fd6743d1598376a1e1b2a0c6a9661020be295010d2f5850379514a45'
TRANSLATIONS = {'accordions':'折叠面板','alerts':'警告提示','avatars':'头像','badges':'徽章','breadcrumbs':'面包屑导航','buttons':'按钮','cards':'卡片','checkboxes':'复选框','dividers':'分隔线','dropdowns':'下拉菜单','inputs':'输入框','loaders':'加载动画','pagination':'分页','progress-bars':'进度条','radio-groups':'单选组','selects':'选择器','stats':'统计卡片','steps':'步骤','tables':'表格','tabs':'标签页','textareas':'文本域','toasts':'消息提示','toggles':'切换开关','announcements':'公告栏','banners':'横幅','contact':'联系表单','ctas':'行动按钮','faqs':'常见问题','footers':'页脚','forms':'表单','headers':'页头','pricing':'价格方案','sections':'内容区块','testimonials':'评价','grids':'网格','menus':'菜单','side-menu':'侧边菜单','vertical-menu':'纵向菜单'}


class Hold(ValueError):
    """Candidate requires human review; never a license approval."""


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def checked_path(value: str) -> str:
    if not re.fullmatch(r'public/examples/[a-z0-9-]+/[a-z0-9-]+/[0-9]+\.html', value):
        raise Hold('unsupported_source_path')
    return value


class SafeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body = False
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'body':
            self.body = True
        if tag in {'img','image','iframe','object','embed','video','audio','canvas','foreignobject','base','style'}:
            raise Hold('unreviewed_media_or_embedded_content')
        if tag == 'script':
            if attrs.get('src') != '/component.js' or attrs.get('type', '') not in ('', 'text/javascript'):
                raise Hold('unreviewed_script')
            self.in_script = True
        for key, value in attrs.items():
            value = value or ''
            if key.startswith('on') or key in {'srcdoc','formaction','action','style'}:
                raise Hold('unreviewed_active_attribute')
            if key in {'src','href','xlink:href','poster','srcset'}:
                if (tag, key, value) in {('script','src','/component.js'), ('link','href','/component.css')}:
                    continue
                if tag == 'a' and key == 'href' and (value.startswith('#') or value == '/'):
                    continue
                raise Hold('unreviewed_resource_or_link')
        if tag == 'meta' and 'http-equiv' in attrs:
            raise Hold('unreviewed_meta')

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

    def handle_data(self, value):
        if self.in_script and value.strip():
            raise Hold('inline_script')


def validate_source(raw: bytes, expected_blob: str) -> str:
    if len(raw) > 120_000 or blob_sha(raw) != expected_blob:
        raise Hold('source_blob_mismatch_or_size')
    text = raw.decode('utf-8')
    parser = SafeHTML()
    parser.feed(text)
    parser.close()
    if not parser.body or not re.search(r'</body>', text, re.I):
        raise Hold('missing_body')
    if re.search(r'\b(?:facebook|instagram|twitter|youtube|paypal|mastercard|visa|apple|google|nike|adidas|spotify|tiktok)\b', text, re.I):
        raise Hold('brand_content_needs_review')
    return sha(re.sub(r'\s+', ' ', re.search(r'<body[^>]*>([\s\S]*?)</body>', text, re.I)[1]).encode())


def validate_license(payload: dict, license_raw: bytes, helper: bytes) -> None:
    if payload['repo'] != REPOSITORY or not re.fullmatch('[0-9a-f]{40}', payload['source_revision']):
        raise Hold('unapproved_repository_or_revision')
    if sha(license_raw) != LICENSE_SHA or sha(helper) != HELPER_SHA:
        raise Hold('license_or_helper_changed')
    licenses = payload.get('license_files', [])
    expected = {'LICENSE': blob_sha(license_raw), '.agents/skills/frontend-design/LICENSE.txt': 'f433b1a53f5b830a205fd2df78e2b34974656c7b'}
    # The separate design-skill license applies only to .agents, which is never imported.
    if {entry['path']: entry['sha'] for entry in licenses} != expected:
        raise Hold('license_scope_changed')


def write_json(path: Path, data: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def make_item(data: Path, template: dict, payload: dict, raw: bytes, added_at: str) -> dict:
    path = checked_path(payload['path'])
    slug = path.removeprefix('public/examples/').removesuffix('.html')
    category, variant = slug.split('/')[-2:]
    # Unknown categories need an editorial mapping instead of invented descriptions.
    if category not in TRANSLATIONS:
        raise Hold('unmapped_category')
    item = copy.deepcopy(template)
    # A new candidate has never inherited another work's visual review.
    for field in ('editorial', 'theme', 'preview_width', 'styles', 'subcategory', 'kind'):
        item.pop(field, None)
    fine_category = {'announcements': 'badges', 'alerts': 'badges', 'breadcrumbs': 'navigation', 'pagination': 'navigation', 'headers': 'navigation', 'menus': 'navigation', 'selects': 'inputs', 'textareas': 'inputs', 'radio-groups': 'checkboxes', 'faqs': 'faq', 'footers': 'footer', 'ctas': 'hero', 'stats': 'tables'}.get(category, category)
    item.update(subcategory=fine_category, kind='block' if fine_category in ('hero', 'pricing', 'features', 'testimonials', 'faq', 'footer') else 'component', styles=[])
    item_id = 'hyperui-' + slug.replace('/', '-')
    zh, en = f'{TRANSLATIONS[category]} · {variant}', f'{category.replace("-", " ").title()} · {variant}'
    item.update(id=item_id, name={'zh': zh, 'en': en},
                description={'zh': f'HyperUI 原版{zh}，含源码、预览与 MIT 许可。', 'en': f'Original HyperUI {en}, with source, preview and MIT notice.'},
                revision=payload['source_revision'], source_url=payload['source_url'],
                demo_url='https://www.hyperui.dev/components/' + slug.rsplit('/', 1)[0],
                aliases=[category, en, TRANSLATIONS[category], 'html', 'tailwind', 'component', '组件', '素材', '模板'],
                added_at=added_at, clip_url=f'/ui-library/clips/{item_id}-{payload["source_revision"][:12]}.mp4',
                preview_kind='html', preview_url=f'/ui-library/previews/{item_id}.html',
                poster_url=f'/ui-library/posters/{item_id}-{payload["source_revision"][:12]}.webp',
                rights_evidence_url=f'/ui-library/assets/hyperui/evidence/{payload["source_revision"]}/manifest.json')
    relative = 'sources/hyperui/' + path
    target = data / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    item['files'] = [{'name': path, 'path': relative, 'sha256': sha(raw)}, template['files'][1]]
    return item
