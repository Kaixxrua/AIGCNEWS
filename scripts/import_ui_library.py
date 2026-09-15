#!/usr/bin/env python3
"""Import reviewed, licensed upstream sources without rewriting their visuals.

Clone the four repositories listed in docs/ui-library.md into --upstreams first.
The resulting catalog and sources are shared by the website and the Go MCP server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "mcp-go/internal/uicatalog/data"
PROVIDERS = {
    "paper": ("shaders", "paper-design/shaders", "Paper Shaders", "Paper Design", "Apache-2.0", ["LICENSE", "NOTICE"]),
    "threeui": ("threeui", "MengTo/threeui", "ThreeUI", "Meng To / ThreeUI", "MIT", ["LICENSE", "ASSET-LICENSES.md", "FONT-LICENSES.md", "THIRD_PARTY_NOTICES.md"]),
    "inspira": ("inspira-ui", "unovue/inspira-ui", "Inspira UI", "Inspira UI contributors", "MIT", ["LICENSE"]),
    "uilayouts": ("uilayouts", "ui-layouts/uilayouts", "UI Layouts", "Naymur / UI Layouts", "MIT", ["LICENSE"]),
}
REVISIONS = {
    "paper": "7002061d8389781a45e479584deeca0cf538474e",
    "threeui": "68802d5428071ada5c20db8094b1649e6bb770ed",
    "inspira": "6da457c849e01c2543d5b2593651f989f9ea2b52",
    "uilayouts": "88d827d7ec342917ca06f6894e5add65fabbe5d8",
}
PAPER = [
    ("mesh-gradient", "MeshGradient", "流动网格渐变", "gradient aurora 渐变 极光"),
    ("liquid-metal", "LiquidMetal", "液态金属", "liquid metal chrome 液态 金属 铬"),
    ("grain-gradient", "GrainGradient", "颗粒渐变", "grain noise texture 噪点 颗粒 纹理"),
    ("dot-orbit", "DotOrbit", "轨道光点", "dots orbit particles 粒子 轨道 光点"),
    ("god-rays", "GodRays", "体积光束", "light rays beams 光束 体积光"),
    ("waves", "Waves", "流动波纹", "waves ripple 波浪 波纹 涟漪"),
    ("warp", "Warp", "空间扭曲", "warp distortion tunnel 扭曲 隧道"),
    ("voronoi", "Voronoi", "细胞光场", "voronoi cells organic 细胞 有机"),
    ("swirl", "Swirl", "流体旋涡", "swirl vortex fluid 旋涡 流体"),
    ("spiral", "Spiral", "螺旋光场", "spiral vortex 螺旋 旋涡"),
    ("smoke-ring", "SmokeRing", "烟雾光环", "smoke ring orb 烟雾 光环 圆环"),
    ("neuro-noise", "NeuroNoise", "神经噪声", "neural noise organic 神经 噪声"),
    ("metaballs", "Metaballs", "融合液滴", "metaballs blob liquid 融合 液滴 球体"),
    ("water", "Water", "水面折射", "water refraction ripple 水面 折射 波纹"),
    ("color-panels", "ColorPanels", "流动彩色面板", "color panels glass 色彩 面板 玻璃"),
    ("perlin-noise", "PerlinNoise", "柏林噪声", "perlin noise clouds 柏林 噪声 云雾"),
    ("pulsing-border", "PulsingBorder", "脉冲边框", "pulsing border glow 脉冲 边框 发光"),
    ("gem-smoke", "GemSmoke", "宝石烟雾", "gem smoke iridescent 宝石 烟雾 虹彩"),
]
THREE = [
    ("liquid-form", "LiquidFormBackground", "液态形体", "liquid metal 3d raymarch 液态 金属 三维", "shader"),
    ("stream-convergence", "StreamConvergenceBackground", "汇聚光流", "stream convergence flow 汇聚 光流", "shader"),
    ("ribbon-field", "RibbonFieldBackground", "交互丝带", "ribbon pointer flow 丝带 鼠标 交互", "shader"),
    ("bell-field", "BellFieldBackground", "共振光场", "bell resonance ember 共振 光场 火星", "shader"),
    ("condensation", "CondensationBackground", "凝结水滴", "condensation glass droplets 玻璃 水滴 凝结", "background"),
    ("typography-vortex", "TypographyVortexCanvas", "文字旋涡", "typography text vortex 文字 排版 旋涡", "text"),
]
VUE = [
    ("bg-silk", "SilkBackground", "丝绸流光", "silk fabric flow 丝绸 流光"),
    ("bg-particle-whirlpool", "ParticleWhirlpoolBg", "交互粒子旋涡", "particles whirlpool vortex 3d 粒子 旋涡 三维 交互"),
    ("bg-bubbles", "BubblesBg", "立体气泡", "bubbles spheres 3d 气泡 球体 三维"),
    ("bg-neural", "NeuralBg", "神经网络光场", "neural network 神经 网络 光场"),
]


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def collect(repo: Path, revision: str, path: str, files: dict[str, bytes]) -> None:
    path = path.replace("\\", "/")
    if path in files:
        return
    content = git(repo, "show", f"{revision}:{path}")
    files[path] = content
    for spec in re.findall(r'(?:from\s*|import\s*)[\"\']([^\"\']+)[\"\']', content.decode()):
        if not spec.startswith("."):
            continue
        base = (repo / path).parent / spec.split("?")[0]
        options = [base, *(Path(str(base) + ext) for ext in (".ts", ".tsx", ".js", ".vue"))]
        if base.suffix == ".js":
            options.extend([base.with_suffix(".ts"), base.with_suffix(".tsx")])
        match = next((item for item in options if item.is_file()), None)
        if not match:
            raise ValueError(f"Unresolved upstream relative import: {path} -> {spec}")
        collect(repo, revision, match.resolve().relative_to(repo.resolve()).as_posix(), files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstreams", type=Path, required=True)
    args = parser.parse_args()
    prior = json.loads((DEST / 'catalog.json').read_text(encoding='utf-8'))['items'] if (DEST / 'catalog.json').exists() else []
    first_added = {item['id']: item.get('added_at') for item in prior}
    imported_at = datetime.now(timezone.utc).isoformat()
    specs = []
    for slug, component, zh, aliases in PAPER:
        specs.append(dict(provider="paper", slug=slug, component=component + "Example", category="shader", zh=zh,
            en=re.sub(r"(?<!^)(?=[A-Z])", " ", component), aliases=aliases,
            path=f"docs/registry/{slug}-example.tsx", extra=[f"packages/shaders/src/shaders/{slug}.ts"],
            demo=f"https://shaders.paper.design/{slug}", dependencies={"react": "19.2.0", "@paper-design/shaders-react": "0.0.80"}))
    for slug, component, zh, aliases, category in THREE:
        specs.append(dict(provider="threeui", slug=slug, component=component, category=category, zh=zh,
            en=slug.replace("-", " ").title(), aliases=aliases, path=f"src/shaders/{slug}/{component}.tsx",
            extra=["src/shaders/community.css"], demo=f"https://threeui.com/{'text-animation' if category == 'text' else 'backgrounds'}/{slug}", dependencies={"react": "19.2.0"}))
    for slug, component, zh, aliases in VUE:
        docs_slug = {"bg-silk": "silk-background", "bg-neural": "neural-background", "bg-bubbles": "bubbles-bg", "bg-particle-whirlpool": "particle-whirlpool-bg"}[slug]
        specs.append(dict(provider="inspira", slug=slug, component="default", category="shader", zh=zh,
            en=re.sub(r"(?<!^)(?=[A-Z])", " ", component), aliases=aliases,
            path=f"app/components/inspira/ui/{slug}/{component}.vue",
            extra=["app/components/inspira/ui/shader-toy/ShaderToy.vue"] if slug == "bg-silk" else [],
            demo=f"https://inspira-ui.com/docs/components/backgrounds/{docs_slug}", dependencies={"vue": "^3.5.0", ("three" if slug in ("bg-particle-whirlpool", "bg-bubbles") else "ogl"): ("0.180.0" if slug in ("bg-particle-whirlpool", "bg-bubbles") else "1.0.11"), "clsx": "2.1.1", "tailwind-merge": "3.3.1"}))
    for slug, component, zh, aliases, category, props in [
        ("text-randomized", "RandomizedTextEffect", "字符解码", "text scramble reveal 文字 字符 解码", "text", {"text": "Production ready code"}),
        ("spotlight", "Spotlight", "鼠标聚光灯", "spotlight mouse cursor hover 鼠标 悬停 聚光灯", "component", {}),
    ]:
        specs.append(dict(provider="uilayouts", slug=slug, component=component, category=category, zh=zh,
            en=slug.replace("-", " ").title(), aliases=aliases, props=props,
            path=f"apps/ui-layout/components/ui/{slug}.tsx", extra=["apps/ui-layout/lib/utils.ts"] if slug == "spotlight" else [],
            demo=f"https://www.ui-layouts.com/components/{'spotlight-cards' if slug == 'spotlight' else 'randomized-text-effect'}", dependencies={"react": "19.2.0", "clsx": "2.1.1", "tailwind-merge": "3.3.1"}))
    catalog = []
    locks = json.loads((DEST / 'upstreams.json').read_text()) if (DEST / 'upstreams.json').exists() else {}
    for spec in specs:
        key = spec["provider"]
        folder, repository, provider, author, license_id, notices = PROVIDERS[key]
        repo = args.upstreams / folder
        revision = git(repo, "rev-parse", "HEAD").decode().strip()
        if revision != REVISIONS[key]:
            raise ValueError(f"{repository}: checkout reviewed revision {REVISIONS[key]} before importing")
        locks[key] = {"repository": repository, "revision": revision}
        files: dict[str, bytes] = {}
        for path in [spec["path"], *spec["extra"]]:
            collect(repo, revision, path, files)
        source_files = []
        for path, content in files.items():
            target = DEST / "sources" / key / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            source_files.append({"name": path, "path": f"sources/{key}/{path}", "sha256": hashlib.sha256(content).hexdigest()})
        for notice in notices:
            target = DEST / "licenses" / key / notice
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git(repo, "show", f"{revision}:{notice}"))
        item_id = f"{key}-{spec['slug']}"
        assets = []
        if key == "threeui":
            font_path = "src/shaders/fonts/fragment-mono.woff2"
            font = git(repo, "show", f"{revision}:{font_path}")
            target = DEST / "assets" / key / font_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(font)
            assets.append({"name": font_path, "path": f"assets/{key}/{font_path}", "sha256": hashlib.sha256(font).hexdigest(), "license": "OFL-1.1", "license_url": "/ui-library/licenses/threeui/FONT-LICENSES.md"})
        zh_note, en_note = "保留原作者的视觉效果与交互。", "Preserve the original visuals and interactions."
        if key == "paper":
            zh_note += "入口组件使用锁定版本的 Paper 包；附带着色器源码可用于查看与定制。"
            en_note += " The entry component uses the pinned Paper package; shader implementation files are supplied for inspection and customization."
        if key == "inspira":
            zh_note += "普通 Vue 项目需提供 cn 工具；使用 Tailwind 样式与列出的渲染依赖。"
            en_note += " For plain Vue, provide the cn utility, Tailwind styles and the listed rendering dependencies."
            if spec["slug"] == "bg-silk":
                zh_note += "显式导入 ShaderToy 和 useTemplateRef。"
                en_note += " Import ShaderToy and useTemplateRef explicitly."
        catalog.append({"id": item_id, "name": {"zh": spec["zh"], "en": spec["en"]},
            "added_at": first_added.get(item_id) or imported_at,
            "description": {"zh": f"{provider} 原版{spec['zh']}，支持实际运行预览与源码复制。", "en": f"Original {spec['en']} from {provider}, with a live preview and reusable source."},
            "provider": provider, "provider_id": key, "author": "Giorgi Azmaipharashvili / Inspira UI" if spec["slug"] == "bg-silk" else author, "license": license_id,
            "source_url": f"https://github.com/{repository}/blob/{revision}/{spec['path']}",
            "demo_url": spec["demo"], "revision": revision, "category": spec["category"],
            "frameworks": ["vue", "nuxt"] if key == "inspira" else ["react"],
            "aliases": (spec["aliases"] + " ui component components template templates 组件 素材 模板 " + {"shader": "shader shaders webgl effect animation 着色器 动效 背景 background", "background": "background 背景", "text": "text typography 文字 文本 排版", "component": "interaction interactive 交互"}[spec["category"]]).split(), "files": source_files, "dependencies": spec["dependencies"],
            "export_name": spec["component"], "props": spec.get("props", {}), "assets": assets,
            "preview_url": f"/ui-library/previews/{item_id}.html", "poster_url": f"/ui-library/posters/{item_id}.png",
            "clip_url": f"/ui-library/clips/{item_id}.webm",
            "notes": {"zh": zh_note, "en": en_note},
            "license_url": f"/ui-library/licenses/{key}/{notices[0]}",
            "notices": [{"name": f"licenses/{key}/{notice}", "path": f"licenses/{key}/{notice}", "sha256": hashlib.sha256((DEST / "licenses" / key / notice).read_bytes()).hexdigest()} for notice in notices]})
    featured = ["threeui-liquid-form", "paper-gem-smoke", "inspira-bg-particle-whirlpool", "paper-liquid-metal", "paper-mesh-gradient", "inspira-bg-silk", "threeui-typography-vortex", "paper-pulsing-border", "paper-warp", "paper-god-rays", "threeui-bell-field", "inspira-bg-bubbles"]
    catalog.sort(key=lambda item: featured.index(item["id"]) if item["id"] in featured else len(featured))
    imported_ids = {item['id'] for item in catalog}
    previous = {item['id']: item for item in prior}
    for item in catalog:
        if previous.get(item['id'], {}).get('revision') == item['revision'] and previous[item['id']].get('rights_evidence_url'):
            item['rights_evidence_url'] = previous[item['id']]['rights_evidence_url']
    catalog.extend(item for item in prior if item['id'] not in imported_ids)
    (DEST / "catalog.json").write_text(json.dumps({"version": 1, "items": catalog}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DEST / "upstreams.json").write_text(json.dumps(locks, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(catalog)} original components from {len(locks)} pinned upstreams.")


if __name__ == "__main__":
    main()
