#!/usr/bin/env python3
"""Import a reviewed, media-free BundUI batch from a pinned checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "mcp-go/internal/uicatalog/data"
PROVIDER = "bundui"
REPOSITORY = "bundui/components"
REVISION = "c07468613dfe7db776f1749a0921a1e5e7bd33d5"
LICENSE_SOURCE = "LICENCE.md"
LICENSE_SHA256 = "933435f572112da637d0944fbfc500c0c19a4fb9df1da2c2e0387966f273fa31"

# Registry name, Chinese title, category, exported symbol, preview props.
SPECS = [
    ("animated-gradient-text", "渐变流光文字", "text", "default", {"text": "Build something memorable"}),
    ("count-animation", "数字递增动画", "text", "default", {"number": 12840, "prefix": "+"}),
    ("text-morph-animation", "文字融合切换", "text", "default", {"texts": ["Design", "Build", "Ship"]}),
    ("magnetic-button", "磁吸按钮", "component", "default", {"children": "Explore"}),
    ("ripple-effect", "点击涟漪", "component", "RippleEffect", {"children": "Press me", "className": "bg-black px-6 py-3 text-white"}),
    ("meteor-shower", "流星雨背景", "background", "default", {"children": "Meteor shower", "className": "h-full w-full"}),
    ("snowfall", "飘雪背景", "background", "default", {"children": "Snowfall", "className": "h-full w-full"}),
    ("fireworks", "烟花背景", "background", "default", {"children": "Fireworks", "className": "h-full w-full"}),
    ("geometric", "几何动态背景", "background", "default", {"children": "Geometric", "className": "h-full w-full"}),
    ("wavy", "波浪动态背景", "background", "default", {"children": "Wavy", "className": "h-full w-full"}),
]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def store(relative: str, raw: bytes) -> dict[str, str]:
    target = DATA / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {"name": relative.removeprefix(f"sources/{PROVIDER}/"), "path": relative, "sha256": digest(raw)}


def validate_source(path: str, raw: bytes) -> None:
    text = raw.decode("utf-8")
    if len(raw) > 256_000:
        raise ValueError(f"source exceeds catalog file budget: {path}")
    if re.search(r"https?://|<\s*(?:img|video|audio|iframe)\b|\b(?:src|href)=", text, re.I):
        raise ValueError(f"unreviewed external media or URL: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    head = (upstream / ".git/refs/heads/main").read_text().strip() if (upstream / ".git/refs/heads/main").exists() else ""
    if head != REVISION:
        import subprocess
        head = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if head != REVISION:
        raise ValueError(f"checkout {REPOSITORY} at reviewed revision {REVISION}")

    license_raw = (upstream / LICENSE_SOURCE).read_bytes()
    if digest(license_raw) != LICENSE_SHA256 or b"MIT License" not in license_raw:
        raise ValueError("BundUI license changed; review before importing")
    license_file = store(f"licenses/{PROVIDER}/LICENSE", license_raw)
    css_raw = (upstream / "app/globals.css").read_bytes()
    validate_source("app/globals.css", css_raw)
    css_file = store(f"sources/{PROVIDER}/app/globals.css", css_raw)

    catalog_path = DATA / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    previous = {item["id"]: item for item in catalog["items"]}
    added_at = datetime.now(timezone.utc).isoformat()
    additions = []
    package = json.loads((upstream / "package.json").read_text(encoding="utf-8"))
    versions = {**package.get("dependencies", {}), **package.get("devDependencies", {})}

    for slug, zh, category, export_name, props in SPECS:
        payload = json.loads((upstream / f"public/r/{slug}.json").read_text(encoding="utf-8"))
        files = []
        for entry in payload["files"]:
            path = entry["path"]
            raw = entry["content"].encode()
            validate_source(path, raw)
            files.append(store(f"sources/{PROVIDER}/{path}", raw))
        files.append(css_file)
        dependencies = {name: versions.get(name, "latest") for name in payload.get("dependencies", [])}
        item_id = f"bundui-{slug}"
        en = payload.get("title") or slug.replace("-", " ").title()
        additions.append({
            "id": item_id,
            "name": {"zh": zh, "en": en},
            "description": {"zh": f"BundUI 原版{zh}，来自官方 MIT 仓库。", "en": f"Original {en} from the official MIT-licensed BundUI repository."},
            "notes": {"zh": "保留官方源码与许可；预览不访问外部网络。", "en": "Preserve the official source and license; the preview makes no external requests."},
            "provider": "BundUI", "provider_id": PROVIDER, "author": "BundUI contributors",
            "license": "MIT", "license_url": f"/ui-library/licenses/{PROVIDER}/LICENSE",
            "revision": REVISION,
            "source_url": f"https://github.com/{REPOSITORY}/blob/{REVISION}/{payload['files'][0]['path']}",
            "demo_url": f"https://bundui.io/docs/{slug}", "category": category,
            "kind": "component", "frameworks": ["react"],
            "aliases": list(dict.fromkeys([slug, en.lower(), "bundui", "react", "tailwind", "motion", category, zh, "组件", "素材"])),
            "files": files, "notices": [license_file], "assets": [], "dependencies": dependencies,
            "export_name": export_name, "props": props, "preview_adapter": "original-react-v1",
            "preview_css": "app/globals.css", "preview_fill": category == "background",
            "preview_url": f"/ui-library/previews/{item_id}.html", "poster_url": f"/ui-library/posters/{item_id}.png",
            "clip_url": "", "added_at": previous.get(item_id, {}).get("added_at", added_at),
            "rights_evidence_url": f"/ui-library/assets/{PROVIDER}/evidence/{REVISION}/manifest.json",
        })

    ids = {item["id"] for item in additions}
    catalog["items"] = [item for item in catalog["items"] if item["id"] not in ids] + additions
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    locks_path = DATA / "upstreams.json"
    locks = json.loads(locks_path.read_text())
    locks[PROVIDER] = {"repository": REPOSITORY, "revision": REVISION, "license_source": LICENSE_SOURCE}
    locks_path.write_text(json.dumps(locks, indent=2) + "\n")
    print(f"Imported {len(additions)} reviewed BundUI components at {REVISION}.")


if __name__ == "__main__":
    main()
