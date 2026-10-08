"""Reviewed HTML examples: keep complete source documents and pin exact excerpts.

Only the documented examples are mounted, never the documentation application.
The source document, its byte range and hash remain available for attribution
and reproduction. Framework directives, inline handlers and media are held.
"""
from __future__ import annotations

import html
import json
import posixpath
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import ui_import_common as common
from import_batch_registry_sources import zh_title
from ui_import_common import MEDIA_ALLOW, Reject, checked_checkout, make_item, sha, store, store_license

SOURCES = {
    "basecoat": {
        "repository": "hunvreus/basecoat",
        "revision": "6953a4adbe63cb5ba25e2bda30d7b76202d4f2b4",
        "license_source": "LICENSE.md",
        "license_sha256": "160a6cea26ff1931297957499ab739e94c4bc79ecea18b490c9f533fa76ace78",
        "provider": "Basecoat",
        "glob": "site/src/docs/components/*.mdx",
        "format": "preview",
        "css": "src/css/basecoat.css",
        "scripts": ["src/js/basecoat.js", *[
            f"src/js/{name}.js" for name in (
                "accordion", "popover", "combobox", "command", "drawer",
                "dropdown-menu", "range", "select", "sidebar", "tabs", "toast")]],
        # Charts require a separate Chart.js demo initializer; the theme switcher
        # requires the docs app. They are not standalone examples.
        "exclude": [r"^(chart|theme-switcher)-", r"-rtl(?:-|$)",
                    # These original popovers open outside a 390px viewport.
                    r"^(button-group-popover|popover-basic|popover-sides)$"],
        "demo_base": "https://basecoatui.com/components/",
        "tailwind": 4,
        "icon_lock": "site/package-lock.json",
        "icon_version": "1.21.0",
        "icon_notice": "lucide-static-1.21.0-LICENSE",
        "icon_notice_sha256": "b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57",
    },
    "sailboatui": {
        "repository": "sailboatui/sailboatui",
        "revision": "8d0970f39193d8e852bf338298665556aa3163c8",
        "license_source": "LICENSE",
        "license_sha256": "2c7bff4e41907ac0892951b11bed424330065df88e6e96b2217c7e4828d33ff9",
        "provider": "Sailboat UI",
        "glob": "content/docs/**/*.html",
        "format": "hugo",
        "css": "assets/css/tailwind.css",
        "scripts": [],
        "demo_base": "https://sailboatui.com/docs/",
        "tailwind": 3,
        "icon_notice": "heroicons-2.2.0-LICENSE",
        "icon_notice_sha256": "60e0b68c0f35c078eef3a5d29419d0b03ff84ec1df9c3f9d6e39a519a5ae7985",
        # The trusted compiler mirrors this theme instead of executing upstream
        # CommonJS. A changed configuration must be reviewed before refreshing.
        "config": "tailwind.config.js",
        "config_sha256": "4403d455a289e227397915e221c4075da442fa720f24bbacccfe8d1f069029b5",
    },
}

PATTERNS = {
    "preview": re.compile(r'<Preview\b([^>]*)>([\s\S]*?)</Preview>'),
    "hugo": re.compile(r'\{\{<\s*code\b([^>]*?)>\}\}([\s\S]*?)\{\{<\s*/code\s*>\}\}'),
}
CSS_IMPORT = re.compile(r'@import\s+[\"\']([^\"\']+)[\"\']\s*;')
CSS_URL = re.compile(r'url\(\s*[\"\']?((?:[^()\"\']|\([^)]*\))+)', re.I)
TAGS = set(('a abbr article aside b blockquote br button caption circle clipPath code col colgroup '
            'dd defs del details div dl dt ellipse em fieldset figcaption figure footer form g '
            'h1 h2 h3 h4 h5 h6 header hr i input kbd label legend li line linearGradient main '
            'mark menu nav ol optgroup option output p path polygon polyline pre progress radialGradient '
            'rect s section select small span stop strong sub summary sup svg symbol table tbody '
            'td text textarea th thead time title tr tspan u ul use').lower().split())


class FragmentGate(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag not in TAGS:
            raise Reject("unsupported HTML element: " + tag)
        for name, value in attrs:
            value = (value or '').strip()
            if name.startswith(('on', 'x-', 'v-', 'hx-', 'wire:', '@', ':')):
                raise Reject("inline handler or framework directive")
            if name in {'src', 'srcset', 'poster', 'background', 'data'}:
                raise Reject("unreviewed media attribute")
            if name in {'href', 'xlink:href', 'action', 'formaction'} and value and not value.startswith('#'):
                raise Reject("nonlocal navigation or resource")
            if name == 'style' and re.search(r'url\s*\(|@import|\\', value, re.I):
                raise Reject("unreviewed inline CSS resource")

    handle_startendtag = handle_starttag


def excerpts(raw: bytes, mode: str):
    text = raw.decode('utf-8')
    for match in PATTERNS[mode].finditer(text):
        attrs, markup = match.groups()
        if mode == 'hugo':
            title = re.search(r'ctitle="([^"]+)"', attrs)
            title = title[1] if title else 'Default'
            wrapper = 'w-full'
        else:
            headings = re.findall(r'^#{2,3}\s+(.+)$', text[:match.start()], re.M)
            title = headings[-1] if headings else 'Default'
            classes = re.search(r'\bclass="([^"]*)"', attrs)
            # Matches ReallySimpleDocs 1.0.12 Preview.astro from the upstream
            # lockfile: a plain div with the given class, otherwise w-fit.
            wrapper = classes[1] if classes else 'w-fit'
        start = len(text[:match.start(2)].encode('utf-8'))
        fragment = markup.encode('utf-8')
        yield html.unescape(title), markup, {
            'start': start, 'end': start + len(fragment), 'sha256': sha(fragment),
            'wrapper_class': html.unescape(wrapper),
        }


def read_local(root: Path, name: str) -> bytes:
    path = root / name
    if (not path.resolve().is_relative_to(root.resolve())
            or any(part.startswith(('.', '_')) for part in Path(name).parts)):
        raise Reject("source path outside catalog boundary")
    raw = path.read_bytes()
    if len(raw) > 256_000:
        raise Reject("source exceeds catalog file budget")
    return raw


def stylesheets(root: Path, entry: str, found=None) -> dict[str, bytes]:
    found = {} if found is None else found
    if entry in found:
        return found
    raw = read_local(root, entry)
    text = raw.decode('utf-8')
    if '\\' in text:
        raise Reject("escaped CSS requires review")
    for url in CSS_URL.findall(text):
        if not url.startswith(('data:image/svg+xml;', '#')):
            raise Reject("external CSS resource")
    found[entry] = raw
    for specifier in CSS_IMPORT.findall(text):
        if not specifier.startswith('.'):
            raise Reject("nonlocal CSS import")
        child = posixpath.normpath(posixpath.join(posixpath.dirname(entry), specifier))
        stylesheets(root, child, found)
    if re.search(r'@import\b', CSS_IMPORT.sub('', text)):
        raise Reject("unsupported CSS import")
    return found


def import_provider(provider_id, upstreams, previous, available, only, report):
    source = SOURCES[provider_id]
    root = upstreams / provider_id
    checked_checkout(root, source)
    if source.get('icon_lock'):
        with (root / source['icon_lock']).open() as stream:
            icon = json.load(stream)['packages']['node_modules/lucide-static']
        if icon['version'] != source['icon_version']:
            raise Reject('Icon package changed; license review required')
    icon_raw = (Path(__file__).parent / 'ui_publication/notices' / source['icon_notice']).read_bytes()
    if sha(icon_raw) != source['icon_notice_sha256']:
        raise Reject('Icon notice integrity failure')
    shared = stylesheets(root, source['css'])
    if source.get('config'):
        config = read_local(root, source['config'])
        if sha(config) != source['config_sha256']:
            raise Reject("Tailwind configuration changed; review required")
        shared[source['config']] = config
        if '@tailwindcss/forms' not in available:
            raise Reject("Tailwind forms plugin unavailable offline")
    for name in source['scripts']:
        raw = read_local(root, name)
        if re.search(r'\b(?:import|fetch|XMLHttpRequest|WebSocket|eval)\b|https?://',
                     MEDIA_ALLOW.sub('', raw.decode('utf-8'))):
            raise Reject("runtime script requires review")
        shared[name] = raw
    notice = store_license(provider_id, (root / source['license_source']).read_bytes())
    icon_path = f"licenses/{provider_id}/{source['icon_notice']}"
    (common.DATA / icon_path).write_bytes(icon_raw)
    icon_notice = {'name': source['icon_notice'], 'path': icon_path, 'sha256': sha(icon_raw)}
    shared_files = [store(provider_id, name, raw, validate_media=False) for name, raw in shared.items()]
    stats = report.setdefault(provider_id, {'imported': 0, 'rejected': {}})
    additions = []
    for path in sorted(root.glob(source['glob'])):
        relative = path.relative_to(root).as_posix()
        raw = read_local(root, relative)
        seen = Counter()
        for title, markup, selection in excerpts(raw, source['format']):
            suffix = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') or 'example'
            slug = path.stem + '-' + suffix
            seen[slug] += 1
            if seen[slug] > 1:
                slug += '-' + str(seen[slug])
            if only and slug not in only:
                continue
            if any(re.search(pattern, slug) for pattern in source.get('exclude', [])):
                stats['rejected'].setdefault('reviewed exclusion', []).append(slug)
                continue
            try:
                FragmentGate().feed(markup)
                title_en = path.stem.replace('-', ' ').title() + ' · ' + title
                # A directly copyable example is an unmodified byte excerpt of
                # the archived document, not a rewritten/generated component.
                example = store(provider_id, f'examples/{slug}.html', markup.encode('utf-8'))
                example['name'] = 'example.html'
                document = store(provider_id, relative, raw, validate_media=False)
                files = [example, document, *shared_files]
                section = path.parent.name if source['format'] == 'hugo' else ''
                dependencies = {'tailwindcss': '^' + str(source['tailwind'])}
                if source['tailwind'] == 3:
                    dependencies['@tailwindcss/forms'] = '0.5.11'
                item = make_item(provider_id, source, slug, title_en, zh_title(slug, title_en),
                                 relative, files, notice, source['css'],
                                 dependencies, previous,
                                 demo_url=source['demo_base'] + (section + '/' if section else '') + path.stem + '/')
                selection['path'] = document['path']
                item.update(preview_adapter='original-html-v1', preview_fragment=selection,
                            preview_tailwind=source['tailwind'], preview_scripts=source['scripts'],
                            frameworks=['html', 'tailwind'])
                item['notices'].append(icon_notice)
                item['aliases'] = [value for value in item['aliases'] if value != 'react'] + ['html']
                item['notes'] = {
                    'zh': 'example.html 是文档中未经改写的 HTML 示例；同时保留完整原始文档、样式和脚本。预览使用系统字体，不加载外部图片。',
                    'en': 'example.html is an unmodified HTML excerpt; full original documents, styles and scripts are also preserved. System fonts; no external images.',
                }
                additions.append(item)
                stats['imported'] += 1
            except (Reject, ValueError) as error:
                stats['rejected'].setdefault(str(error).split(':')[0], []).append(slug)
    return additions
