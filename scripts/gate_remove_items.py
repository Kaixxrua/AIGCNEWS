#!/usr/bin/env python3
"""Remove catalog items that failed a quality gate, then gc orphaned sources.

Usage: gate_remove_items.py <id> [<id> ...]
Records nothing fancy: deletion is the signal; the gate log records the reason.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ui_import_common import DATA, gc_orphans


def main() -> None:
    ids = set(sys.argv[1:])
    if not ids:
        raise SystemExit("no ids given")
    catalog_path = DATA / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    before = len(catalog["items"])
    removed = [item for item in catalog["items"] if item["id"] in ids]
    catalog["items"] = [item for item in catalog["items"] if item["id"] not in ids]
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    providers = set()
    for item in removed:
        providers.add(item.get("provider_id", ""))
        for key in ("poster_url", "preview_url", "clip_url"):
            url = item.get(key) or ""
            if not url:
                continue
            name = url.rsplit("/", 1)[-1]
            folder = {"poster_url": "posters", "preview_url": "previews", "clip_url": "clips"}[key]
            target = DATA / folder / name
            if target.exists():
                target.unlink()
    orphans = gc_orphans(sorted(p for p in providers if p))
    print(f"removed {before - len(catalog['items'])} items, {orphans} orphaned sources gc'd")


if __name__ == "__main__":
    main()
