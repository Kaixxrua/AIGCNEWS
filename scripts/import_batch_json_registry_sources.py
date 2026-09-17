#!/usr/bin/env python3
"""Batch-import reviewed demo compositions from JSON-registry pinned repositories.

systaliko ships public/r/*-demo.json entries whose files live in the checkout at
registry/demo/**; uitripled ships packages/registry/public/r/*-shadcnui.json
entries whose files live under packages/components/react-shadcn. Both are
resolved to repo-local file closures with the same media, package and size
rules as the registry batch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from import_batch_registry_sources import zh_title
from ui_import_common import (
    append_unique_file,
    DATA, Reject, apply_additions, checked_checkout, detect_export,
    external_versions, make_item, node_modules_packages, previous_items,
    resolve_closure, sha, store, store_license,
)

UITRIPLED_PACKAGE = "packages/components/react-shadcn"
UITRIPLED_REGISTRY_PREFIX = "@uitripled/react-shadcn/"

SOURCES = {
    "systaliko": {
        "repository": "YoucefBnm/Systaliko-UI",
        "revision": "ed82dae1ed03605ceea1415f92a45399eb76b111",
        "license_source": "LICENSE",
        "license_sha256": "6c8a6adc04a00f3d9e96e295429066953dc02e7646fe634ec2484d33aefef29d",
        "provider": "Systaliko UI",
        "checkout": "systaliko",
        "alias_root": "",
        "css": "app/globals.css",
        "registry_glob": "public/r/*-demo.json",
        "entry_root": "",
        "category": "block",
    },
    "uitripled": {
        "repository": "moumen-soliman/uitripled",
        "revision": "05d18376db775072ed61d0cab8ea184f8f527429",
        "license_source": "LICENSE.md",
        "license_sha256": "25cd04751092a150079ad36e3eba68789e5dbcb62e713f2281df1e508461b927",
        "provider": "uiTripled",
        "checkout": "uitripled",
        "alias_root": f"{UITRIPLED_PACKAGE}/src",
        "alias_rules": [("components/ui/", f"{UITRIPLED_PACKAGE}/src/ui/")],
        "package_dirs": {"@uitripled/utils": "packages/utils/src"},
        "css": "apps/docs/app/globals.css",
        "css_name": "globals.css",
        "registry_glob": f"{UITRIPLED_PACKAGE.replace('components/react-shadcn', 'registry')}/public/r/*-shadcnui.json",
        "entry_root": UITRIPLED_PACKAGE,
        "category": "block",
    },
}


def registry_items(source: dict, root: Path) -> list[dict]:
    items = []
    for path in sorted(root.glob(source["registry_glob"])):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if entry.get("name"):
            items.append(entry)
    return items


def import_provider(provider_id: str, upstreams: Path, previous: dict, available: set[str],
                    only: set[str] | None, report: dict) -> list[dict]:
    source = SOURCES[provider_id]
    root = (upstreams / source.get("checkout", provider_id)).resolve()
    checked_checkout(root, source)
    notice = store_license(provider_id, (root / source["license_source"]).read_bytes())
    css_file = store(provider_id, source.get("css_name", source["css"]), (root / source["css"]).read_bytes())
    versions = external_versions(root)
    entry_root = source["entry_root"]
    # Sources with workspace package_dirs resolve closures against the repo
    # root so monorepo-internal packages stay pinned repo-relative files.
    repo_closure = bool(source.get("package_dirs"))
    package_root = root if repo_closure else (root / entry_root if entry_root else root)
    additions = []
    stats = report.setdefault(provider_id, {"imported": 0, "rejected": {}})
    for entry in registry_items(source, root):
        name = entry["name"]
        if only and name not in only:
            continue
        slug = name
        item_id = f"{provider_id}-{slug}"
        try:
            files_meta = entry.get("files", [])
            if not files_meta:
                raise Reject("registry item has no files")
            entries = []
            for meta in files_meta:
                path = meta.get("path", "")
                if not path.endswith((".tsx", ".ts", ".jsx", ".js")):
                    continue
                if path.startswith(UITRIPLED_REGISTRY_PREFIX):
                    path = path[len(UITRIPLED_REGISTRY_PREFIX):]
                if repo_closure and entry_root:
                    path = f"{entry_root}/{path}"
                if entry_root and not repo_closure and not (package_root / path).is_file() and (root / path).is_file():
                    # systaliko demo paths are repo-relative already.
                    entries.append(path)
                    continue
                if not (package_root / path).is_file():
                    raise Reject(f"missing file {path}")
                entries.append(path)
            if not entries:
                raise Reject("no component source file")
            closure, packages = resolve_closure(
                package_root, entries, source["alias_root"],
                available_packages=available,
                alias_rules=[tuple(rule) for rule in source.get("alias_rules", [])],
                package_dirs=source.get("package_dirs"))
            entry_path = next((p for p in closure if p.endswith((".tsx", ".jsx"))) or closure[0], closure[0])
            repo_prefix = "" if repo_closure else (f"{entry_root}/" if entry_root else "")
            files = []
            for relative in closure:
                raw = (package_root / relative).read_bytes()
                files.append(store(provider_id, relative, raw))
            append_unique_file(files, css_file)
            declared = {dep: versions.get(dep, "latest") for dep in entry.get("dependencies", []) or []}
            declared.update({dep: versions.get(dep, "latest") for dep in packages})
            title_en = (entry.get("title") or slug.replace("-", " ").title()).removesuffix(" Demo")
            export_source = (package_root / entry_path).read_text(encoding="utf-8")
            category = "block" if entry.get("type") in ("registry:block", "registry:page") else "component"
            item = make_item(
                provider_id, source, slug, title_en, zh_title(slug, title_en), repo_prefix + entry_path,
                files, notice, css_file["name"], declared, previous,
                category=category,
                export_name=detect_export(export_source, slug),
                preview_root=source["alias_root"] or None,
                preview_alias_rules=[list(rule) for rule in source.get("alias_rules", [])] or None,
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
