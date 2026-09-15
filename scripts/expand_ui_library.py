#!/usr/bin/env python3
"""Import the reviewed MIT expansion; never fetch, execute or invent upstream UI."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'mcp-go/internal/uicatalog/data'
REVISIONS = {'hyperui': 'ae5038979b77320793360a46b85e7c71a73beda6', 'motion': '92586e62a951eb9b6bfd1cc7c8a4e6e2ab6ba17d'}
HYPER = [
    ('marketing/buttons/1', '圆角行动按钮', 'Rounded action buttons', 'button 按钮 圆角'),
    ('marketing/buttons/2', '箭头行动按钮', 'Arrow action buttons', 'button outline 按钮 描边'),
    ('marketing/buttons/3', '图标行动按钮', 'Icon action buttons', 'button icon 按钮 图标'),
    ('application/loaders/1', '旋转加载指示器', 'Spinner loader', 'spinner loading loader 加载 旋转'),
    ('application/loaders/2', '居中加载提示', 'Centered loading status', 'loading loader centered 加载 居中'),
    ('application/loaders/3', '行内加载提示', 'Inline loading status', 'loading loader inline 加载 行内'),
    ('application/badges/1', '状态徽章', 'Status badges', 'badge status 徽章 状态 标签'),
    ('application/badges/2', '图标徽章', 'Icon badges', 'badge icon 徽章 图标 标签'),
    ('application/inputs/1', '表单输入框', 'Form inputs', 'input form 输入框 表单'),
    ('application/inputs/2', '图标输入框', 'Inputs with icons', 'input helper form 输入框 表单'),
    ('application/checkboxes/1', '复选框', 'Checkboxes', 'checkbox form 复选框 表单'),
    ('application/toggles/1', '切换开关', 'Toggle switches', 'toggle switch 开关 切换'),
    ('application/radio-groups/1', '单选选项组', 'Radio group', 'radio selection 单选 选择'),
    ('application/progress-bars/1', '进度条', 'Progress bars', 'progress 进度条 进度'),
    ('application/steps/1', '步骤导航', 'Step navigation', 'step navigation 步骤 导航'),
    ('application/tabs/1', '标签页导航', 'Tab navigation', 'tab navigation 标签页 导航'),
    ('application/breadcrumbs/1', '面包屑导航', 'Breadcrumb navigation', 'breadcrumb navigation 面包屑 导航'),
    ('application/pagination/1', '分页导航', 'Pagination', 'pagination navigation 分页 导航'),
    ('application/accordions/1', '折叠内容面板', 'Accordion panels', 'accordion disclosure 折叠 面板'),
    ('marketing/faqs/1', '常见问题折叠列表', 'FAQ accordion', 'faq accordion 常见问题 折叠'),
    ('application/stats/1', '数据统计卡片', 'Statistics cards', 'stats metric card 数据 统计 卡片'),
    ('marketing/pricing/1', '价格方案卡片', 'Pricing cards', 'pricing plan card 价格 方案 卡片'),
    ('application/toasts/1', '消息提示卡片', 'Toast notification', 'toast notification 提示 消息 卡片'),
    ('marketing/announcements/1', '公告提示条', 'Announcement banner', 'announcement banner 公告 提示 横幅'),
]
MOTION = [
    ('text-shimmer/text-shimmer-basic', 'TextShimmerBasic', '文字流光', 'Shimmer text', 'text shimmer 文字 流光', 'text'),
    ('text-shimmer/text-shimmer-color', 'TextShimmerColor', '彩色文字流光', 'Colored shimmer text', 'text shimmer color 文字 流光 彩色', 'text'),
    ('text-shimmer-wave/text-shimmer-wave-basic', 'TextShimmerWaveBasic', '波浪文字流光', 'Wave shimmer text', 'text shimmer wave 文字 波浪 流光', 'text'),
    ('text-loop/text-loop-basic', 'TextLoopBasic', '循环切换文字', 'Looping text', 'text loop 文字 循环 切换', 'text'),
    ('spinning-text/spinning-text-basic', 'SpinningTextBasic', '环绕旋转文字', 'Spinning text', 'text spinning circle 文字 旋转 环绕', 'text'),
    ('text-roll/text-roll-basic', 'TextRollBasic', '翻滚文字入场', 'Rolling text reveal', 'text roll reveal 文字 翻滚 入场', 'text'),
    ('border-trail/border-trail-card-1', 'BorderTrailCard1', '流光边框卡片', 'Border trail card', 'border trail card 流光 边框 卡片', 'component'),
    ('glow-effect/glow-effect-button', 'GlowEffectButton', '彩光按钮', 'Glowing button', 'glow button 彩光 发光 按钮', 'component'),
    ('magnetic/magnetic-basic', 'MagneticBasic', '磁吸按钮', 'Magnetic button', 'magnetic button hover 磁吸 按钮 悬停', 'component'),
    ('animated-background/segmented-control', 'SegmentedControl', '滑动分段选择器', 'Animated segmented control', 'segmented control slide 分段 选择器 滑动', 'component'),
    ('disclosure/disclosure-basic', 'DisclosureBasic', '展开收起动效', 'Animated disclosure', 'disclosure accordion 折叠 展开 收起', 'component'),
    ('text-scramble/text-scramble-basic', 'TextScrambleBasic', '字符扰动揭示', 'Scrambled text reveal', 'text scramble reveal 文字 字符 扰动 解码', 'text'),
]


def original(repo: Path, revision: str, path: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(repo), 'show', f'{revision}:{path}'])


def store_file(kind: str, provider: str, path: str, content: bytes) -> dict:
    relative = f'{kind}/{provider}/{path}'
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {'name': path, 'path': relative, 'sha256': hashlib.sha256(content).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstreams', required=True, type=Path)
    args = parser.parse_args()
    catalog = json.loads((DEST / 'catalog.json').read_text(encoding='utf-8'))
    previous = {item['id']: item for item in catalog['items']}
    locks = json.loads((DEST / 'upstreams.json').read_text())
    added_at = datetime.now(timezone.utc).isoformat()
    for item in catalog['items']:
        item.setdefault('added_at', '2026-09-10T14:23:22.405698+00:00')
    additions = []
    for provider, folder, repository, label, author, licence in [
        ('hyperui', 'hyperui', 'markmead/hyperui', 'HyperUI', 'Mark Mead', 'LICENSE'),
        ('motion', 'motion-primitives', 'ibelick/motion-primitives', 'Motion Primitives', 'ibelick', 'LICENCE.md'),
    ]:
        repo = args.upstreams / folder
        revision = REVISIONS[provider]
        assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == revision
        notice = original(repo, revision, licence)
        assert b'MIT License' in notice and b'Permission is hereby granted' in notice
        license_file = store_file('licenses', provider, 'LICENSE', notice)
        locks[provider] = {'repository': repository, 'revision': revision, 'license_source': licence}
        specs = HYPER if provider == 'hyperui' else MOTION
        for spec in specs:
            slug, zh, en, aliases = (spec[0], spec[1], spec[2], spec[3]) if provider == 'hyperui' else (spec[0], spec[2], spec[3], spec[4])
            path = f'public/examples/{slug}.html' if provider == 'hyperui' else f'app/docs/{slug}.tsx'
            item_id = provider + '-' + slug.replace('/', '-')
            files: dict[str, bytes] = {}
            def collect(path: str) -> None:
                if path in files:
                    return
                content = original(repo, revision, path)
                files[path] = content
                if provider == 'motion':
                    for dependency in re.findall(r'''from\s*['"]([^'"]+)['"]''', content.decode()):
                        if dependency.startswith('@/'):
                            collect(dependency[2:] + ('' if Path(dependency).suffix else '.ts' if dependency == '@/lib/utils' else '.tsx'))
                        elif dependency not in ('react', 'motion/react', 'lucide-react', 'clsx', 'tailwind-merge'):
                            raise ValueError(f'Unreviewed import: {dependency}')
            collect(path)
            assets = []
            if provider == 'hyperui':
                html = files[path].decode()
                if re.search(r'<(?:img|iframe|video|audio)\b|(?:src|href)=["\']https?:', html, re.I):
                    raise ValueError(f'Unreviewed external asset: {path}')
                collect('public/component.js')
                css = original(repo, revision, 'public/component.css')
                # Upstream's optional Google font is not downloaded or redistributed.
                css = re.sub(rb'@import\s*(?:url\([^;]+\)|"https?[^;]+)\s*;', b'', css)
                asset = store_file('assets', provider, 'public/component.css', css)
                asset.update(license='MIT', license_url='/ui-library/licenses/hyperui/LICENSE')
                assets.append(asset)
            category = 'component' if provider == 'hyperui' else spec[5]
            notes = {'zh': '保留原版代码与 MIT 许可。', 'en': 'Preserve the original source and MIT notice.'}
            if provider == 'hyperui':
                notes['zh'] += '将附带的 component.css 和 component.js 放到网站根路径；打包样式仅移除了远程字体导入，预览使用系统字体。HTML 可嵌入任意框架，链接和提交仅用于演示。'
                notes['en'] += 'Serve the supplied component.css and component.js at the site root. Bundled CSS only removes the remote font import; previews use system fonts. HTML works with any framework; links and submissions are demo-only.'
            else:
                notes['zh'] += '保留 components/core 与 lib/utils 路径并配置 @ 别名；使用 Tailwind CSS。Motion 固定为支持 React 19 的兼容版本；亮色背景展示原示例。'
                notes['en'] += 'Keep components/core and lib/utils with the @ alias and Tailwind CSS. Motion is pinned to a React 19-compatible version; previews show the original example on a light background.'
            additions.append({'id': item_id, 'name': {'zh': zh, 'en': en}, 'description': {'zh': f'{label} 原版{zh}，含可运行预览、源码及许可。', 'en': f'Original {en} from {label}, with runnable preview, source and license.'},
                'provider': label, 'provider_id': provider, 'author': author, 'license': 'MIT', 'license_url': f'/ui-library/licenses/{provider}/LICENSE',
                'source_url': f'https://github.com/{repository}/blob/{revision}/{path}', 'revision': revision,
                'demo_url': 'https://www.hyperui.dev/components/' + slug.rsplit('/', 1)[0] if provider == 'hyperui' else 'https://motion-primitives.com/docs/' + slug.split('/')[0],
                'category': category, 'frameworks': ['html'] if provider == 'hyperui' else ['react'],
                'aliases': (aliases + ' ui component template 组件 素材 模板 ' + ('html tailwind 界面' if provider == 'hyperui' else 'motion animation 动效')).split(),
                'files': [store_file('sources', provider, file, content) for file, content in files.items()],
                'notices': [license_file], 'assets': assets, 'dependencies': {'tailwindcss': '4.3.3'} if provider == 'hyperui' else {'react': '19.2.0', 'motion': '11.18.2', 'lucide-react': '0.400.0', 'tailwindcss': '4.3.3', 'clsx': '2.1.1', 'tailwind-merge': '3.3.1'},
                'export_name': '' if provider == 'hyperui' else spec[1], 'props': {}, 'notes': notes,
                'preview_url': f'/ui-library/previews/{item_id}.html', 'poster_url': f'/ui-library/posters/{item_id}.png', 'clip_url': f'/ui-library/clips/{item_id}.webm',
                'added_at': previous.get(item_id, {}).get('added_at', added_at)})
    ids = {item['id'] for item in additions}
    for item in additions:
        if previous.get(item['id'], {}).get('revision') == item['revision'] and previous[item['id']].get('rights_evidence_url'):
            item['rights_evidence_url'] = previous[item['id']]['rights_evidence_url']
    catalog['items'] = [item for item in catalog['items'] if item['id'] not in ids] + additions
    (DEST / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (DEST / 'upstreams.json').write_text(json.dumps(locks, indent=2) + '\n', encoding='utf-8')
    print(f'Imported {len(additions)} reviewed components; catalog contains {len(catalog["items"])}.')


if __name__ == '__main__':
    main()
