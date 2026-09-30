#!/usr/bin/env python3
"""Batch-import reviewed components from directory-convention pinned repositories.

Unlike registry-driven sources these repositories expose their demo/component
files through plain directory conventions (examples/, docs demos, block kits,
shader folders). Candidates are enumerated by glob, expanded to a repo-local
file closure, and rejected automatically when they require external media,
unavailable npm packages, or oversize sources. The real-browser gate drops
candidates that mount but render nothing.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from import_batch_registry_sources import zh_title
from ui_import_common import (
    Reject,
    append_unique_file,
    apply_additions,
    checked_checkout,
    detect_export,
    external_versions,
    make_item,
    node_modules_packages,
    previous_items,
    resolve_closure,
    store,
    store_license,
)

UILAYOUTS_APP = "apps/ui-layout"

SOURCES = {
    "fancy": {
        "repository": "danielpetho/fancy",
        "revision": "f9f62c61207b2dd3210476dd98af3c9a5be24094",
        "license_source": "LICENSE",
        "license_sha256": "39b0d9c112b4e80383da88660cbaa64972f741e80205c14fa1b779ff1989cc09",
        "provider": "Fancy Components",
        "alias_root": "src",
        "css": "src/app/globals.css",
        "glob": "src/fancy/examples/**/*.tsx",
        "slug": "filename",
        "category_from_dir": {"background": "background", "blocks": "block", "text": "text"},
        "demo_base": "https://www.fancycomponents.dev/docs/components/",
    },
    "jolly": {
        "repository": "jolbol1/jolly-ui",
        "revision": "aac97a84f8e0c2071a5e255c2f6ec190e238c1c2",
        "license_source": "LICENSE",
        "license_sha256": "7a423cdb2273725e3a7120b557a15034a1be9619b3170b046ffe0ff9ddc7d37b",
        "provider": "Jolly UI",
        "checkout": "jolly-ui",
        "alias_root": "src",
        "css": "src/app/globals.css",
        "glob": "src/registry/new-york/example/**/*.tsx",
        "slug": "filename",
        # Human-reviewed: inert demo anchor targets (href="https://adobe.com/" etc.)
        # and site-root nav hrefs; anchors never auto-fetch and preview CSP blocks
        # navigation. table-sortable.tsx stays rejected (live fetch to swapi.py4e.com).
        "reviewed_allow_files": {
            "src/registry/new-york/example/breadcrumbs/breadcrumbs-demo.tsx",
            "src/registry/new-york/example/breadcrumbs/breadcrumbs-disabled.tsx",
            "src/registry/new-york/example/breadcrumbs/breadcrumbs-dropdown.tsx",
            "src/registry/new-york/example/breadcrumbs/breadcrumbs-ellipsis.tsx",
            "src/registry/new-york/example/breadcrumbs/breadcrumbs-separator.tsx",
            "src/registry/new-york/example/combobox/combobox-links.tsx",
            "src/registry/new-york/example/grid-list/grid-list-links.tsx",
            "src/registry/new-york/example/link/link-demo.tsx",
            "src/registry/new-york/example/link/link-variants.tsx",
            "src/registry/new-york/example/list-box/list-box-links.tsx",
            "src/registry/new-york/example/list-box/list-box-links-replace.tsx",
            "src/registry/new-york/example/menu/menu-links.tsx",
            "src/registry/new-york/example/select/select-links.tsx",
            "src/registry/new-york/example/tag-group/tag-group-links.tsx",
        },
        "demo_base": "https://jollyui.dev/docs/components/",
    },
    "motion-primitives": {
        "repository": "ibelick/motion-primitives",
        "revision": "43a31886f505c0cd0f11887683cfb9ff36431f9c",
        "license_source": "LICENCE.md",
        "license_sha256": "f668f5ef3635eb906f10b1eea9a32e449eb6e1a183ab6879ef6d56c0980dd2f3",
        "provider": "Motion Primitives",
        "alias_root": "",
        "css": "app/globals.css",
        "glob": "app/docs/**/*.tsx",
        "slug": "filename",
        "category_from_dir": {"text-effect": "text", "text-loop": "text"},
        "demo_base": "https://motion-primitives.com/docs/",
    },
    "animata": {
        "repository": "codse/animata",
        "revision": "36674e4e9cfdc0f237693d8b736a2bf41065ca1d",
        "license_source": "LICENSE.md",
        "license_sha256": "ff78804659cbc28380d087cae79c494f243f8ef22b1e2ac5ec119b5de9314f05",
        "provider": "Animata",
        "alias_root": "",
        "css": "styles/globals.css",
        "glob": "animata/**/*.tsx",
        "exclude": [r"\.stories\.tsx$"],
        "slug": "filename",
        "category_from_dir": {"background": "background", "text": "text"},
        "demo_base": "https://animata.design/docs/",
    },
    "tailark": {
        "repository": "tailark/blocks",
        "revision": "8139698115c1341bfd2e3e286c04bb4d8146f472",
        "license_source": "LICENCE.md",
        "license_sha256": "9ceb2565db4149b699df9fb53b16963f59675f5308de1143679639b2c561410c",
        "provider": "Tailark",
        "alias_root": "",
        "css": "app/globals.css",
        "glob": "registry/bases/base/*/blocks/**/*.tsx",
        "slug": "tailark_block",
        "category": "block",
        "demo_base": "https://tailark.com/",
    },
    "threeui": {
        "repository": "MengTo/threeui",
        "revision": "68802d5428071ada5c20db8094b1649e6bb770ed",
        "license_source": "LICENSE",
        "license_sha256": "b2a071ba22fefd803f4e9d1f5c777dd79c62d191695586a1a73fd4d0ebd051c6",
        "provider": "ThreeUI",
        "alias_root": "",
        "css": "src/styles.css",
        "glob": "src/shaders/**/*.tsx",
        "slug": "parent_dir",
        "category": "shader",
        "demo_base": "https://threeui.com/",
    },
    "ui-layouts": {
        "repository": "UI-Layouts/ui-layouts",
        "revision": "88d827d7ec342917ca06f6894e5add65fabbe5d8",
        "license_source": "LICENSE",
        "license_sha256": "25d698c61ceea4d42107ef85ef37d4449f1169ca24c7ee288db434688071e1e3",
        "provider": "UI Layouts",
        "alias_root": UILAYOUTS_APP,
        "package_dirs": {
            "@repo/ui": "packages/ui/src",
            "@repo/blocks": "packages/blocks/src",
            "@repo/shadcn": "packages/shadcn/src",
        },
        "css": f"{UILAYOUTS_APP}/app/globals.css",
        "glob": f"{UILAYOUTS_APP}/components/ui/*.tsx",
        "slug": "filename",
        # Human-reviewed: lib/utils.ts carries inert site-config attribution URLs
        # (same class as registry sources' lib/site.ts); nothing is fetched on import.
        "reviewed_allow_files": {"apps/ui-layout/lib/utils.ts"},
        "demo_base": "https://www.ui-layouts.com/components/",
    },
    # Added 2026-09-30 for the scheduled refresh (scripts/ui_publication/refresh.py).
    "neobrutalism": {
        "repository": "ekmas/neobrutalism-components",
        "revision": "3306a802724874a85f93079702b2795370a279d4",
        "license_source": "LICENSE",
        "license_sha256": "a77140948a68fafb5e0077a287502104203b7ccb11255b311101ec8fe85fa250",
        "provider": "Neobrutalism components",
        "checkout": "neobrutalism-components",
        "alias_root": "src",
        "css": "src/styling/globals.css",
        # Official docs examples compose the primitives with real content; bare
        # registry primitives render empty without children.
        "glob": "src/examples/ui/**/*.tsx",
        "slug": "dir_file",
        "slug_base": "src/examples/ui",
        "demo_base": "https://www.neobrutalism.dev/docs/",
    },
    "syntaxui": {
        "repository": "SyntaxUI/syntaxui",
        "revision": "322491934c9e25e3fe3db593197ead09c7544bd3",
        "license_source": "LICENSE",
        "license_sha256": "ce899f42fe57d66a394e52c8113c047bc87f651199df6fb44ef3297f2cd02e37",
        "provider": "SyntaxUI",
        "alias_root": "src",
        "css": "src/styles/tailwind.css",
        "glob": "src/showcase/**/*.tsx",
        # Background* patterns embed Hero Patterns SVGs (CC BY 4.0, third party),
        # which the repository's MIT grant does not cover.
        "exclude": [r"/effects/Background(Bricks|Cross|Dots|Plus|XO)\.tsx$", r"/playground/"],
        "slug": "filename",
        "category_from_dir": {
            "effects": "background", "gradients": "background", "text": "text",
            "text-drop": "text", "text-ticker": "text", "banner": "block", "features": "block",
            "footer": "block", "logo-cloud": "block", "pricing": "block", "testimonial": "block",
        },
        "demo_base": "https://www.syntaxui.com/",
    },
    # Tremor Labs relicensed the former Tremor Blocks catalog as MIT in 2025.
    # Icons come from @remixicon/react, pinned at 4.8.0 in frontend/package.json:
    # 4.9.0 moved to the non-OSI "Remix Icon License 1.0".
    "tremor-blocks": {
        "repository": "tremorlabs/tremor-blocks",
        "revision": "b319e8d3d3678a4f60f4802f7e85bc1abc52d598",
        "license_source": "LICENSE.md",
        "license_sha256": "3546b8d22c1657e8f6d36ae83e8721f894946337d9966e1d84fbfcdfa1c9ae0b",
        "provider": "Tremor Blocks",
        "alias_root": "src",
        "css": "src/app/global.css",
        "glob": "src/content/components/*/*.tsx",
        "slug": "filename",
        "category": "block",
        "demo_base": "https://blocks.tremor.so/blocks/",
    },
    "launch-ui": {
        "repository": "launch-ui/launch-ui",
        "revision": "b0d4d5bce91d13523450416ce1797109076b2787",
        "license_source": "LICENSE.md",
        "license_sha256": "dbc6555e70ebd80b5e0e6793ae3e1f03b2b3d3716e27bd10f36525066d649669",
        "provider": "Launch UI",
        "alias_root": "",
        "css": "app/globals.css",
        "glob": "components/sections/*/*.tsx",
        "slug": "dir_file",
        "slug_base": "components/sections",
        "category": "block",
        # Human-reviewed: site config holds inert attribution/nav URLs (ogImage is
        # metadata, never rendered) and the FAQ links the free Figma kit via an
        # anchor; preview CSP blocks navigation and nothing is fetched.
        "reviewed_allow_files": {"config/site.ts", "components/sections/faq/default.tsx"},
        "demo_base": "https://www.launchuicomponents.com/",
    },
}


def candidates(source: dict, root: Path) -> list[tuple[str, str]]:
    """(slug, repo-relative entry path) pairs from the source's convention."""
    excludes = [re.compile(pattern) for pattern in source.get("exclude", [])]
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for path in sorted(root.glob(source["glob"])):
        relative = path.relative_to(root).as_posix()
        if any(pattern.search(relative) for pattern in excludes):
            continue
        mode = source["slug"]
        if mode == "filename":
            slug = path.stem
        elif mode == "parent_dir":
            slug = path.parent.name if path.stem.lower() == "index" else path.stem
        elif mode == "dir_file":
            # <base>/<component>/<variant>.tsx -> component-variant; index -> component
            if path.parent == root / source["slug_base"]:
                slug = path.stem
            else:
                slug = path.parent.name if path.stem.lower() == "index" else f"{path.parent.name}-{path.stem}"
        elif mode == "tailark_block":
            parts = relative.split("/")
            # registry/bases/base/<kit>/blocks/<category>/<variant>[.tsx|/index.tsx]
            kit, category = parts[4], parts[6]
            variant = parts[7] if path.stem.lower() == "index" else path.stem
            slug = f"{kit}-{category}-{variant}"
        else:
            raise ValueError(f"unknown slug mode {mode}")
        slug = slug.lower().replace("_", "-")
        if slug in seen:
            # keep ids unique when different folders reuse a demo filename
            parent = path.parent.name.lower().replace("_", "-")
            slug = f"{parent}-{slug}"
            if slug in seen:
                continue
        seen.add(slug)
        pairs.append((slug, relative))
    return pairs


def import_provider(provider_id: str, upstreams: Path, previous: dict, available: set[str],
                    only: set[str] | None, report: dict) -> list[dict]:
    source = SOURCES[provider_id]
    root = (upstreams / source.get("checkout", provider_id)).resolve()
    checked_checkout(root, source)
    notice = store_license(provider_id, (root / source["license_source"]).read_bytes())
    css_file = store(provider_id, source["css"], (root / source["css"]).read_bytes())
    versions = external_versions(root)
    additions = []
    stats = report.setdefault(provider_id, {"imported": 0, "rejected": {}})
    for slug, relative in candidates(source, root):
        if only and slug not in only:
            continue
        try:
            closure, packages = resolve_closure(
                root, [relative], source["alias_root"],
                available_packages=available,
                alias_rules=[tuple(rule) for rule in source.get("alias_rules", [])],
                package_dirs=source.get("package_dirs"))
            entry_path = next((p for p in closure if p.endswith((".tsx", ".jsx"))), relative)
            export_name = detect_export((root / entry_path).read_text(encoding="utf-8"), slug)
            allowed = set(source.get("reviewed_allow_files", ()))
            files = []
            for closure_path in closure:
                raw = (root / closure_path).read_bytes()
                if closure_path in allowed:
                    stats["rejected"].setdefault("reviewed-exception", []).append(
                        f"{slug}:{closure_path}")
                files.append(store(provider_id, closure_path, raw,
                                   validate_media=closure_path not in allowed))
            append_unique_file(files, css_file)
            declared = {dep: versions.get(dep, "latest") for dep in packages}
            title_en = slug.replace("-", " ").title()
            category = source.get("category")
            if not category:
                segment = relative.split("/")[-2] if "/" in relative else ""
                category = source.get("category_from_dir", {}).get(segment, "component")
            item = make_item(
                provider_id, source, slug, title_en, zh_title(slug, title_en), entry_path,
                files, notice, source["css"], declared, previous,
                category=category,
                demo_url=source["demo_base"],
                export_name=export_name,
                preview_root=source["alias_root"] or None,
                preview_package_dirs=source.get("package_dirs"))
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
    parser.add_argument("--only", nargs="*", default=None, help="limit to specific slugs")
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
