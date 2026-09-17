#!/usr/bin/env python3
"""Batch-import reviewed demos from the pinned visx and Base UI repositories.

visx exposes one self-contained ``Example.tsx`` per sandbox (plus a per-sandbox
``sandbox-styles.css``); Base UI exposes tailwind demos under
``docs/src/app/(docs)/react/components/<component>/demos/<demo>/tailwind``.
Both repositories are MIT licensed and pinned by commit. The same evidence,
hashing, offline-closure and real-browser gates as earlier batches apply:
demos bundling live external media (unsplash/wikimedia ``src=``) are rejected;
a small set of files with inert attribution anchors or example.com form
defaults is human-reviewed and recorded per item.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from import_batch_registry_sources import zh_title
from ui_import_common import (
    ROOT, Reject, append_unique_file, apply_additions, checked_checkout, detect_export,
    external_versions, make_item, node_modules_packages, previous_items,
    resolve_closure, store, store_license,
)

FRONTEND_MODULES = ROOT / "frontend" / "node_modules"

SOURCES = {
    "visx": {
        "repository": "airbnb/visx",
        "revision": "485c0359664ee8e612992defb16e1f035ed40b23",
        "license_source": "LICENSE",
        "license_sha256": "8c766533b7d4200b4dfb1a1afff396e3665460d21d7b4c34d059efcb5a332c84",
        "provider": "visx",
        "sandbox_root": "packages/visx-demo/src/sandboxes",
        # Original repo stylesheet shared by every sandbox (template folder);
        # supplies the mount element baseline while each sandbox's own
        # sandbox-styles.css rides along as closure CSS.
        "shared_css": "packages/visx-demo/src/sandboxes/template/sandbox-styles.css",
        "props": {"width": 600, "height": 400},
        # Human-reviewed: inert attribution anchors to bl.ocks.org originals;
        # anchors never auto-fetch and the preview CSP blocks navigation.
        "reviewed_allow_files": {
            "packages/visx-demo/src/sandboxes/visx-chord/Example.tsx",
            "packages/visx-demo/src/sandboxes/visx-drag-i/Example.tsx",
            "packages/visx-demo/src/sandboxes/visx-drag-ii/Example.tsx",
            "packages/visx-demo/src/sandboxes/visx-zoom-i/Example.tsx",
        },
        "demo_base": "https://visx.airbnb.tech/",
    },
    "base-ui": {
        "repository": "mui/base-ui",
        "revision": "ca182273cc0013bacd443e4ab03d4bd4f8cc1f35",
        "license_source": "LICENSE",
        "license_sha256": "07fc1b39d69d14bc7d40482a628f47226258eb01265db68ae684944b916beb2a",
        "provider": "Base UI",
        "components_root": "docs/src/app/(docs)/react/components",
        # Original docs layout stylesheet; demos only use Tailwind default
        # theme classes (docs/src/css/index.css states this explicitly).
        "shared_css": "docs/src/app/(docs)/layout.css",
        # Human-reviewed: example.com form default/placeholder text values and
        # inert GitHub/site-root anchors; nothing is fetched on import.
        "reviewed_allow_files": {
            "docs/src/app/(docs)/react/components/form/demos/hero/tailwind/index.tsx",
            "docs/src/app/(docs)/react/components/navigation-menu/demos/hero/tailwind/index.tsx",
            "docs/src/app/(docs)/react/components/navigation-menu/demos/nested-inline/tailwind/index.tsx",
        },
        "demo_base": "https://base-ui.com/react/components/",
    },
}


def installed_versions() -> dict[str, str]:
    """Exact dependency versions the offline preview sandbox provides."""
    versions: dict[str, str] = {}
    if not FRONTEND_MODULES.is_dir():
        return versions
    for entry in FRONTEND_MODULES.iterdir():
        if entry.name.startswith("."):
            continue
        candidates = [entry] if not entry.name.startswith("@") else list(entry.iterdir())
        for candidate in candidates:
            package_path = candidate / "package.json"
            if not package_path.is_file():
                continue
            try:
                package = json.loads(package_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            name, version = package.get("name"), package.get("version")
            if name and version:
                versions[name] = version
    return versions


def visx_candidates(root: Path, sandbox_root: str) -> list[tuple[str, str, str | None]]:
    """(slug, entry, optional per-sandbox css) for every pinned visx demo."""
    base = root / sandbox_root
    pairs: list[tuple[str, str, str | None]] = []
    for directory in sorted(base.glob("visx-*")):
        entry = directory / "Example.tsx"
        if not entry.is_file():
            continue
        slug = directory.name[len("visx-"):]
        css = directory / "sandbox-styles.css"
        pairs.append((slug, entry.relative_to(root).as_posix(),
                      css.relative_to(root).as_posix() if css.is_file() else None))
    return pairs


def base_ui_candidates(root: Path, components_root: str) -> list[tuple[str, str]]:
    """(slug, entry) for every tailwind demo in the pinned Base UI docs."""
    base = root / components_root
    pairs: list[tuple[str, str]] = []
    for entry in sorted(base.glob("*/demos/*/tailwind/index.tsx")):
        relative = entry.relative_to(base).as_posix()
        component, demo = relative.split("/")[0], relative.split("/")[2]
        pairs.append((f"{component}-{demo}", entry.relative_to(root).as_posix()))
    return pairs


def import_provider(provider_id: str, upstreams: Path, previous: dict,
                    sandbox_versions: dict[str, str], only: set[str] | None,
                    report: dict) -> list[dict]:
    source = SOURCES[provider_id]
    root = (upstreams / provider_id).resolve()
    checked_checkout(root, source)
    notice = store_license(provider_id, (root / source["license_source"]).read_bytes())
    shared_css = store(provider_id, source["shared_css"], (root / source["shared_css"]).read_bytes())
    fallback_versions = external_versions(root)
    allowed = set(source.get("reviewed_allow_files", ()))
    if provider_id == "visx":
        candidates = visx_candidates(root, source["sandbox_root"])
    else:
        candidates = [(slug, entry, None) for slug, entry in
                      base_ui_candidates(root, source["components_root"])]
    additions = []
    stats = report.setdefault(provider_id, {"imported": 0, "rejected": {}})
    for slug, entry, extra_css in candidates:
        if only and slug not in only:
            continue
        try:
            closure, packages = resolve_closure(
                root, [entry], "", available_packages=set(sandbox_versions))
            export_name = detect_export((root / entry).read_text(encoding="utf-8"), slug)
            files = []
            for closure_path in closure:
                raw = (root / closure_path).read_bytes()
                if closure_path in allowed:
                    stats["rejected"].setdefault("reviewed-exception", []).append(
                        f"{slug}:{closure_path}")
                files.append(store(provider_id, closure_path, raw,
                                   validate_media=closure_path not in allowed))
            if extra_css:
                append_unique_file(files, store(provider_id, extra_css, (root / extra_css).read_bytes()))
            append_unique_file(files, shared_css)
            declared = {dep: sandbox_versions.get(dep) or fallback_versions.get(dep, "latest")
                        for dep in packages}
            title_en = slug.replace("-", " ").title()
            demo_url = source["demo_base"]
            if provider_id == "base-ui":
                demo_url = f"{source['demo_base']}{slug.rsplit('-', 1)[0]}"
            item = make_item(
                provider_id, source, slug, title_en, zh_title(slug, title_en), entry,
                files, notice, source["shared_css"], declared, previous,
                category="component", demo_url=demo_url, export_name=export_name,
                props=source.get("props"))
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
    sandbox_versions = installed_versions()
    previous = previous_items()
    only = set(args.only) if args.only else None
    report: dict = {}
    additions = []
    for provider_id in args.providers:
        additions += import_provider(provider_id, upstreams, previous,
                                     sandbox_versions, only, report)
    if not args.dry_run:
        apply_additions(additions, {pid: SOURCES[pid] for pid in args.providers})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Imported {len(additions)} candidates from {len(args.providers)} providers.")


if __name__ == "__main__":
    main()
