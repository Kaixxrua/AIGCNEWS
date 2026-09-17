#!/usr/bin/env python3
"""Import reviewed, media-free components from pinned open-source UI repositories."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "mcp-go/internal/uicatalog/data"
MEDIA = re.compile(r'''["'`(]https?://|<\s*(?:img|video|audio|iframe)\b|\b(?:src|href)\s*=''', re.I)
IMPORT = re.compile(r'''(?:from\s+|import\s*\()["'](@/[^"']+)["']''')
ALL_IMPORTS = re.compile(r'''(?:from\s+|import\s*\()["']([^"']+)["']''')

SOURCES = {
    "agent-elements": {
        "repository": "21st-dev/agent-elements",
        "revision": "b04b36cb6381a1dd1a0e86cc7c90564ddcd56d37",
        "license_source": "LICENSE",
        "license_sha256": "8bc26817d6b5c323f8cb5e5da77182fe0db8a5ad0e0b563903f9382bba06dc9a",
        "provider": "Agent Elements",
    },
    "smoothui": {
        "repository": "educlopez/smoothui",
        "revision": "1d61c51eedfac615c26ac1d06d394552d0653ad0",
        "license_source": "LICENSE",
        "license_sha256": "9877f4310c0549e5ce26affe52ba97c4e60325472bdcdd308a92fccd90f119cc",
        "provider": "SmoothUI",
    },
    "kibo": {
        "repository": "shadcnblocks/kibo",
        "revision": "3d63cdb15b79d972e3dc38a10997987672f9b263",
        "license_source": "license.md",
        "license_sha256": "1fe9198b595ddadef7e2d99e3e1698c036db61c81e91c7b42df90d59f563b2ba",
        "provider": "Kibo UI",
    },
    "diceui": {
        "repository": "sadmann7/diceui",
        "revision": "f1077626690c386a915d6bade62cd24046fa1c0f",
        "license_source": "LICENSE",
        "license_sha256": "798456e9f649d796bad55d80f9ee50a71eb2d16920300a66a8221b70123e40db",
        "provider": "Dice UI",
    },
    "ai-elements": {
        "repository": "vercel/ai-elements",
        "revision": "6a9d5b1822ffb10bba4bd97175f01edd7d8651cd",
        "license_source": "LICENSE",
        "license_sha256": "b4f9adb7c568904834d0dd6cc98d16c390d21ca32fc17ae7a267715269bd5529",
        "provider": "AI Elements",
        "license": "Apache-2.0",
    },
}

AGENT_SPECS = [
    ("text-shimmer", "流光文字", "TextShimmer", {"children": "Thinking through the details…"}),
    ("error-message", "错误提示", "ErrorMessage", {"title": "Something went wrong", "message": "Please try again in a moment."}),
    ("suggestions", "提示建议", "Suggestions", {"items": [{"id": "one", "label": "Summarize this"}, {"id": "two", "label": "Show an example"}]}),
]

SMOOTH_SPECS = [
    ("per-character-rise", "逐字上升", "default", {"children": "Create with clarity"}),
    ("micro-scale-fade", "微缩淡入", "default", {"children": "Subtle motion"}),
    ("soft-blur-in", "柔焦淡入", "default", {"children": "A softer entrance"}),
    ("stagger-from-edges", "两侧交错入场", "default", {"children": "Meet in the middle"}),
    ("kinetic-center-build", "居中逐词构建", "default", {"phrases": ["Design with purpose", "Build with confidence"]}),
    ("shared-axis-x", "横轴文字切换", "default", {"phrases": ["Plan", "Create", "Deliver"]}),
]

KIBO_SPECS = [
    ("rating", "交互评分", "apps/docs/examples/rating.tsx"),
    ("relative-time", "多时区时间", "apps/docs/examples/relative-time.tsx"),
]

DICE_SPECS = [
    ("circular-progress", "环形进度", "circular-progress-demo.tsx"),
    ("angle-slider", "角度滑杆", "angle-slider-demo.tsx"),
    ("rating", "分级评分", "rating-demo.tsx"),
    ("timeline", "时间线", "timeline-demo.tsx"),
    ("gauge", "仪表盘", "gauge-demo.tsx"),
]

AI_SPECS = [
    ("shimmer", "AI 流光文字"),
    ("suggestion", "AI 建议选项"),
    ("plan", "AI 计划卡片"),
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def checked_checkout(path: Path, source: dict[str, str]) -> None:
    revision = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    if revision != source["revision"]:
        raise ValueError(f"checkout {source['repository']} at reviewed revision {source['revision']}")
    license_raw = (path / source["license_source"]).read_bytes()
    if sha(license_raw) != source["license_sha256"]:
        raise ValueError(f"{source['provider']} license changed; review before importing")


def validate(path: str, raw: bytes) -> None:
    if len(raw) > 256_000:
        raise ValueError(f"source exceeds catalog file budget: {path}")
    if MEDIA.search(raw.decode("utf-8")):
        raise ValueError(f"unreviewed external media or URL: {path}")


def store(provider: str, name: str, raw: bytes, *, validate_media: bool = True) -> dict[str, str]:
    if validate_media:
        validate(name, raw)
    relative = f"sources/{provider}/{name}"
    target = DATA / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {"name": name, "path": relative, "sha256": sha(raw)}


def store_license(provider: str, raw: bytes) -> dict[str, str]:
    relative = f"licenses/{provider}/LICENSE"
    target = DATA / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {"name": "LICENSE", "path": relative, "sha256": sha(raw)}


def base_item(provider_id: str, slug: str, zh: str, source_path: str, files: list[dict[str, str]],
              notice: dict[str, str], css_name: str, dependencies: dict[str, str], previous: dict) -> dict:
    source = SOURCES[provider_id]
    item_id = f"{provider_id}-{slug}"
    en = slug.replace("-", " ").title()
    return {
        "id": item_id,
        "name": {"zh": zh, "en": en},
        "description": {"zh": f"{source['provider']} 官方原版{zh}。", "en": f"Original {en} from {source['provider']}."},
        "notes": {"zh": "固定官方提交与许可；预览不访问外部网络。", "en": "Pinned official source and license; the preview makes no external requests."},
        "provider": source["provider"], "provider_id": provider_id, "author": f"{source['provider']} contributors",
        "license": source.get("license", "MIT"), "license_url": f"/ui-library/licenses/{provider_id}/LICENSE",
        "revision": source["revision"],
        "source_url": f"https://github.com/{source['repository']}/blob/{source['revision']}/{source_path}",
        "demo_url": f"https://github.com/{source['repository']}/tree/{source['revision']}",
        "category": "component", "kind": "component", "frameworks": ["react"],
        "aliases": [slug, en.lower(), provider_id, "react", "tailwind", zh, "组件", "素材"],
        "files": files, "notices": [notice], "assets": [], "dependencies": dependencies,
        "export_name": "default", "props": {}, "preview_adapter": "original-react-v1",
        "preview_css": css_name, "preview_url": f"/ui-library/previews/{item_id}.html",
        "poster_url": f"/ui-library/posters/{item_id}.png", "clip_url": "",
        "added_at": previous.get(item_id, {}).get("added_at", datetime.now(timezone.utc).isoformat()),
        "rights_evidence_url": f"/ui-library/assets/{provider_id}/evidence/{source['revision']}/manifest.json",
    }


def external_versions(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for package_path in [path / "package.json", *path.glob("packages/*/package.json")]:
        package = json.loads(package_path.read_text())
        result.update(package.get("dependencies", {}))
        result.update(package.get("devDependencies", {}))
    return result


def import_agent(path: Path, previous: dict) -> list[dict]:
    provider = "agent-elements"
    source = SOURCES[provider]
    notice = store_license(provider, (path / source["license_source"]).read_bytes())
    versions = external_versions(path)
    additions = []
    for slug, zh, export_name, props in AGENT_SPECS:
        payload = json.loads((path / f"public/r/{slug}.json").read_text())
        files = []
        for entry in payload["files"]:
            file = store(provider, entry["path"], entry["content"].encode())
            file["name"] = entry.get("target", entry["path"])
            files.append(file)
        deps = {name: versions.get(name, "latest") for name in payload.get("dependencies", [])}
        item = base_item(provider, slug, zh, payload["files"][0]["path"], files, notice, "components/agent-elements/agent-ui.css", deps, previous)
        item.update({"export_name": export_name, "props": props, "demo_url": f"https://agent-elements.21st.dev/components/{slug}"})
        additions.append(item)
    return additions


def import_smooth(path: Path, previous: dict) -> list[dict]:
    provider = "smoothui"
    source = SOURCES[provider]
    notice = store_license(provider, (path / source["license_source"]).read_bytes())
    css_path = "apps/docs/app/global.css"
    css = store(provider, css_path, (path / css_path).read_bytes())
    additions = []
    for slug, zh, export_name, props in SMOOTH_SPECS:
        source_path = f"packages/smoothui/components/{slug}/index.tsx"
        component = store(provider, source_path, (path / source_path).read_bytes())
        package = json.loads((path / f"packages/smoothui/components/{slug}/package.json").read_text())
        deps = {name: version for name, version in package.get("dependencies", {}).items() if not name.startswith("@repo/") and name not in {"react", "react-dom"}}
        item = base_item(provider, slug, zh, source_path, [component, css], notice, css_path, deps, previous)
        item.update({"export_name": export_name, "props": props, "demo_url": f"https://smoothui.dev/doc/{slug}"})
        additions.append(item)
    return additions


def import_kibo(path: Path, previous: dict) -> list[dict]:
    provider = "kibo"
    source = SOURCES[provider]
    notice = store_license(provider, (path / source["license_source"]).read_bytes())
    css_path = "apps/docs/app/global.css"
    css = store(provider, css_path, (path / css_path).read_bytes())
    utils_path = "packages/shadcn-ui/lib/utils.ts"
    utils = store(provider, utils_path, (path / utils_path).read_bytes())
    additions = []
    for slug, zh, demo_path in KIBO_SPECS:
        package_path = f"packages/{slug}/index.tsx"
        demo = store(provider, demo_path, (path / demo_path).read_bytes())
        component = store(provider, package_path, (path / package_path).read_bytes())
        package = json.loads((path / f"packages/{slug}/package.json").read_text())
        deps = {name: version for name, version in package.get("dependencies", {}).items() if not name.startswith("@repo/") and name not in {"react", "react-dom"}}
        item = base_item(provider, slug, zh, demo_path, [demo, component, utils, css], notice, css_path, deps, previous)
        item.update({"preview_root": "packages/shadcn-ui", "demo_url": f"https://www.kibo-ui.com/components/{slug}"})
        additions.append(item)
    return additions


def resolve_dice_files(path: Path, demo_path: str) -> list[str]:
    pending = [demo_path]
    resolved: list[str] = []
    while pending:
        relative = pending.pop(0)
        if relative in resolved:
            continue
        resolved.append(relative)
        text = (path / relative).read_text()
        for imported in IMPORT.findall(text):
            target = "docs/" + imported.removeprefix("@/")
            candidates = [target, target + ".tsx", target + ".ts", target + "/index.tsx", target + "/index.ts"]
            match = next((candidate for candidate in candidates if (path / candidate).is_file()), None)
            if not match:
                raise ValueError(f"missing Dice UI import {imported} from {relative}")
            pending.append(match)
    return resolved


def import_dice(path: Path, previous: dict) -> list[dict]:
    provider = "diceui"
    source = SOURCES[provider]
    notice = store_license(provider, (path / source["license_source"]).read_bytes())
    css_source = "docs/styles/globals.css"
    css_name = "styles/globals.css"
    css = store(provider, css_name, (path / css_source).read_bytes())
    index = {entry["name"]: entry for entry in json.loads((path / "docs/public/r/index.json").read_text())}
    additions = []
    for slug, zh, demo_name in DICE_SPECS:
        demo_path = f"docs/registry/bases/base/examples/{demo_name}"
        source_paths = resolve_dice_files(path, demo_path)
        files = [store(provider, source_path.removeprefix("docs/"), (path / source_path).read_bytes()) for source_path in source_paths]
        files.append(css)
        deps = {name: "latest" for name in index[slug].get("dependencies", [])}
        item = base_item(provider, slug, zh, demo_path, files, notice, css_name, deps, previous)
        item.update({"demo_url": f"https://www.diceui.com/docs/components/{slug}"})
        additions.append(item)
    return additions


def resolve_ai_files(path: Path, demo_path: str) -> list[str]:
    pending = [demo_path]
    resolved: list[str] = []
    while pending:
        relative = pending.pop(0)
        if relative in resolved:
            continue
        resolved.append(relative)
        for imported in ALL_IMPORTS.findall((path / relative).read_text()):
            candidates: list[str] = []
            if imported.startswith("@repo/elements/"):
                candidates.append("packages/elements/src/" + imported.removeprefix("@repo/elements/") + ".tsx")
            elif imported.startswith("@repo/shadcn-ui/"):
                target = "packages/shadcn-ui/" + imported.removeprefix("@repo/shadcn-ui/")
                candidates.extend([target, target + ".tsx", target + ".ts", target + "/index.tsx", target + "/index.ts"])
            elif imported.startswith("."):
                target = (Path(relative).parent / imported).as_posix()
                candidates.extend([target, target + ".tsx", target + ".ts", target + "/index.tsx", target + "/index.ts"])
            match = next((candidate for candidate in candidates if (path / candidate).is_file()), None)
            if candidates and not match:
                raise ValueError(f"missing AI Elements import {imported} from {relative}")
            if match:
                pending.append(match)
    return resolved


def import_ai(path: Path, previous: dict) -> list[dict]:
    provider = "ai-elements"
    source = SOURCES[provider]
    notice = store_license(provider, (path / source["license_source"]).read_bytes())
    css_path = "apps/docs/app/global.css"
    css = store(provider, css_path, (path / css_path).read_bytes())
    versions = external_versions(path)
    additions = []
    for slug, zh in AI_SPECS:
        demo_path = f"packages/examples/src/{slug}.tsx"
        source_paths = resolve_ai_files(path, demo_path)
        files = [store(provider, source_path, (path / source_path).read_bytes()) for source_path in source_paths]
        files.append(css)
        imports = {name for source_path in source_paths for name in ALL_IMPORTS.findall((path / source_path).read_text())}
        packages = {name.split("/")[0] if not name.startswith("@") else "/".join(name.split("/")[:2]) for name in imports if not name.startswith((".", "@repo/"))}
        deps = {name: versions.get(name, "latest") for name in packages if name not in {"react", "react-dom"}}
        item = base_item(provider, slug, zh, demo_path, files, notice, css_path, deps, previous)
        item.update({"demo_url": f"https://ai-sdk.dev/elements/components/{slug}"})
        additions.append(item)
    return additions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstreams", required=True, type=Path, help="directory containing agent-elements, smoothui, kibo and diceui checkouts")
    args = parser.parse_args()
    upstreams = args.upstreams.resolve()
    for provider, source in SOURCES.items():
        checked_checkout(upstreams / provider, source)

    catalog_path = DATA / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    previous = {item["id"]: item for item in catalog["items"]}
    additions = (
        import_agent(upstreams / "agent-elements", previous)
        + import_smooth(upstreams / "smoothui", previous)
        + import_kibo(upstreams / "kibo", previous)
        + import_dice(upstreams / "diceui", previous)
        + import_ai(upstreams / "ai-elements", previous)
    )
    ids = {item["id"] for item in additions}
    catalog["items"] = [item for item in catalog["items"] if item["id"] not in ids] + additions
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")

    locks_path = DATA / "upstreams.json"
    locks = json.loads(locks_path.read_text())
    for provider, source in SOURCES.items():
        locks[provider] = {key: source[key] for key in ("repository", "revision", "license_source")}
    locks_path.write_text(json.dumps(locks, indent=2) + "\n")
    print(f"Imported {len(additions)} reviewed components from {len(SOURCES)} pinned repositories.")


if __name__ == "__main__":
    main()
