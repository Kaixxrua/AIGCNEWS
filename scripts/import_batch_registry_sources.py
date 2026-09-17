#!/usr/bin/env python3
"""Batch-import reviewed components from five registry-style pinned repositories.

Candidates are enumerated from each repository's own registry.json, expanded to a
repo-local file closure, and rejected automatically when they require external
media, unavailable npm packages, or oversize sources.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ui_import_common import (
    append_unique_file,
    DATA, Reject, apply_additions, checked_checkout, detect_export,
    external_versions, make_item, node_modules_packages, previous_items,
    resolve_closure, sha, store, store_license,
)

def intentui_remap(relative: str) -> list[str]:
    """Registry paths reference generated files; map them to pre-blocks sources."""
    if not relative.startswith("registry/blocks/"):
        return [relative]
    rest = relative[len("registry/blocks/"):]
    name, _, tail = rest.partition("/")
    group = name.rsplit("-", 1)[0]
    candidates = [f"src/app/pre-blocks/{group}/{rest}"]
    if tail:
        candidates.append(f"src/app/pre-blocks/{group}/{tail}")
    candidates.append(f"src/app/pre-blocks/{rest}")
    return candidates


SOURCES = {
    "8bitcn": {
        "repository": "TheOrcDev/8bitcn-ui",
        "revision": "898caa5932590ab8ff70f54e3c9aff5b5baa523c",
        "license_source": "license.md",
        "license_sha256": "1f7c401e999345dc159be2023cb7587d72e044f3e736b378dff8828a7060c31e",
        "provider": "8bitcn",
        "checkout": "8bitcn",
        "alias_root": "",
        "css": "app/globals.css",
        "registry": "registry.json",
        "types": {"registry:block", "registry:component"},
        "demo_base": "https://8bitcn.com/docs/components/",
        # Reviewed 2026-09-16: site config carries only attribution metadata
        # strings (name/title/description/url); nothing loads over the network.
        "reviewed_allow_files": {"lib/site.ts"},
    },
    "hextaui": {
        "repository": "preetsuthar17/HextaUI",
        "revision": "17ae993ed321e921dd03d2c98e81a140c8e316a8",
        "license_source": "LICENSE",
        "license_sha256": "1712522c36838eacc34a3e0b567eccd8668486a5badaf369521944760ac5845b",
        "provider": "HextaUI",
        "checkout": "hexta-ui",
        "alias_root": "",
        "css": "app/globals.css",
        "registry": "registry.json",
        "types": {"registry:ui", "registry:component", "registry:block"},
        "demo_base": "https://hextaui.com/docs/ui/",
    },
    "serenity": {
        "repository": "ayushmxxn/serenity-ui",
        "revision": "73e966d45466aecda715ad05a56d3c9159b56e25",
        "license_source": "LICENSE",
        "license_sha256": "b4405e1c45dc0c9ac9931969bced7f42372303ef32bfd1c5f5f23a9dd0cd3325",
        "provider": "Serenity UI",
        "checkout": "serenity",
        "alias_root": "",
        "css": "app/globals.css",
        "registry": "registry.json",
        "types": {"registry:component"},
        "demo_base": "https://www.serenity-ui.com/components/",
    },
    "intentui": {
        "repository": "intentui/intentui",
        "revision": "2eb03e6f34e2fd65e1940177d325d0897cc11701",
        "license_source": "LICENSE",
        "license_sha256": "7dad1521d255c7394cb96536896e454f69e89667f3646787554fc9b24691fbb1",
        "provider": "Intent UI",
        "checkout": "intentui",
        "alias_root": "src",
        "css": "src/styles/app.css",
        "registry": "registry.json",
        "types": {"registry:ui", "registry:block", "registry:page"},
        "remap": intentui_remap,
        "preview_preset": "src/styles/themes/stone.css",
        "extra_closure": ["src/styles/themes/stone.css"],
        "demo_base": "https://intentui.com/docs/components/",
    },
    "shadcnspace": {
        "repository": "shadcnspace/shadcnspace",
        "revision": "6cbc9245562238a03d84f1e914e35942c800eb24",
        "license_source": "LICENSE",
        "license_sha256": "5642c9362fb1863feedf930a3d3a87b395763ebbdc62b7fc87bdfeb1d68250e7",
        "provider": "Shadcn Space",
        "checkout": "shadcnspace",
        "alias_root": "src",
        "css": "src/app/globals.css",
        "registry": "registry.json",
        "types": {"registry:block", "registry:component", "registry:ui"},
        "demo_base": "https://shadcnspace.com/blocks/",
    },
}

TITLE_ZH = {
    "accordion": "手风琴", "alert": "警告提示", "alert-dialog": "确认对话框", "aspect-ratio": "固定比例容器",
    "avatar": "头像", "badge": "徽标", "breadcrumb": "面包屑", "button": "按钮", "button-group": "按钮组",
    "calendar": "日历", "card": "卡片", "carousel": "轮播", "chart": "图表", "checkbox": "复选框",
    "collapsible": "折叠面板", "combobox": "组合框", "command": "命令面板", "context-menu": "右键菜单",
    "dialog": "对话框", "drawer": "抽屉", "dropdown-menu": "下拉菜单", "form": "表单", "hover-card": "悬停卡片",
    "input": "输入框", "input-otp": "一次性验证码输入", "label": "标签", "menubar": "菜单栏",
    "navigation-menu": "导航菜单", "pagination": "分页", "popover": "气泡浮层", "progress": "进度条",
    "radio-group": "单选组", "resizable": "可拖拽分栏", "scroll-area": "滚动区域", "select": "选择器",
    "separator": "分隔线", "sheet": "侧边面板", "skeleton": "骨架屏", "slider": "滑杆", "sonner": "通知 toast",
    "switch": "开关", "table": "表格", "tabs": "选项卡", "textarea": "多行输入", "toast": "通知",
    "toggle": "切换按钮", "toggle-group": "切换按钮组", "tooltip": "工具提示",
}


def zh_title(slug: str, title: str) -> str:
    if slug in TITLE_ZH:
        return TITLE_ZH[slug]
    for key, value in sorted(TITLE_ZH.items(), key=lambda pair: -len(pair[0])):
        if slug.startswith(key + "-"):
            return f"{value} {slug[len(key) + 1:]}"
    return title or slug.replace("-", " ")


def import_provider(provider_id: str, upstreams: Path, previous: dict, available: set[str],
                    only: set[str] | None, report: dict) -> list[dict]:
    source = SOURCES[provider_id]
    root = (upstreams / source.get("checkout", provider_id)).resolve()
    checked_checkout(root, source)
    notice = store_license(provider_id, (root / source["license_source"]).read_bytes())
    css_file = store(provider_id, source["css"], (root / source["css"]).read_bytes())
    preset_file = None
    if source.get("preview_preset"):
        preset_file = store(provider_id, source["preview_preset"], (root / source["preview_preset"]).read_bytes())
    versions = external_versions(root)
    registry = json.loads((root / source["registry"]).read_text(encoding="utf-8"))
    additions = []
    stats = report.setdefault(provider_id, {"imported": 0, "rejected": {}})
    for entry in registry.get("items", []):
        name = entry.get("name", "")
        if not name or entry.get("type") not in source["types"]:
            continue
        if only and name not in only:
            continue
        slug = name
        item_id = f"{provider_id}-{slug}"
        try:
            files_meta = entry.get("files", [])
            if not files_meta:
                raise Reject("registry item has no files")
            remap = source.get("remap")
            entries = []
            for meta in files_meta:
                path = meta.get("path", "")
                if not path.endswith((".tsx", ".ts", ".jsx", ".js")):
                    continue
                candidates = remap(path) if remap else [path]
                match = next((c for c in candidates if (root / c).is_file()), None)
                if not match:
                    raise Reject(f"missing file {path}")
                entries.append(match)
            if not entries:
                raise Reject("no component source file")
            closure, packages = resolve_closure(
                root, entries + list(source.get("extra_closure", [])), source["alias_root"],
                available_packages=available)
            entry_path = next((p for p in closure if p.endswith((".tsx", ".jsx"))) or closure[0], closure[0])
            export_name = detect_export((root / entry_path).read_text(encoding="utf-8"), slug)
            allowed = set(source.get("reviewed_allow_files", ()))
            files = []
            for relative in closure:
                raw = (root / relative).read_bytes()
                if relative in allowed:
                    stats["rejected"].setdefault("reviewed-exception", []).append(f"{slug}:{relative}")
                files.append(store(provider_id, relative, raw, validate_media=relative not in allowed))
            append_unique_file(files, css_file)
            if preset_file:
                append_unique_file(files, preset_file)
            declared = {dep: versions.get(dep, "latest") for dep in entry.get("dependencies", [])}
            declared.update({dep: versions.get(dep, "latest") for dep in packages})
            title_en = entry.get("title") or slug.replace("-", " ").title()
            category = "block" if entry.get("type") == "registry:block" else "component"
            item = make_item(
                provider_id, source, slug, title_en, zh_title(slug, title_en), entry_path,
                files, notice, source["css"], declared, previous,
                category=category,
                demo_url=source["demo_base"] + slug,
                preview_preset=source.get("preview_preset"),
                export_name=export_name)
            additions.append(item)
            stats["imported"] += 1
        except (Reject, ValueError) as error:
            reason = str(error).split(":")[0]
            stats["rejected"].setdefault(reason, []).append(slug)
    return additions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstreams", required=True, type=Path)
    parser.add_argument("--providers", nargs="*", default=list(SOURCES))
    parser.add_argument("--only", nargs="*", default=None, help="limit to specific registry names")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    upstreams = args.upstreams.resolve()
    available = node_modules_packages()
    previous = previous_items()
    only = set(args.only) if args.only else None
    report: dict = {}
    additions = []
    for provider_id in args.providers:
        additions += import_provider(provider_id, upstreams, previous, available, only, report)
    if not args.dry_run:
        apply_additions(additions, {pid: SOURCES[pid] for pid in args.providers})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Imported {len(additions)} candidates from {len(args.providers)} providers.")


if __name__ == "__main__":
    main()
