#!/usr/bin/env python3
"""Import pinned open-license icon sets into the UI library icon catalog.

Every icon is re-enumerated from an official upstream checkout pinned to a
reviewed revision; nothing is copied from 21st.dev or any other aggregator.
Static SVG icons are sanitized (no scripts, handlers or external references)
and hashed so the Go catalog and the frontend build can verify integrity
against the archived rights evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "mcp-go/internal/uicatalog/data"
UPSTREAMS = Path("/tmp/ui-upstreams-b2")

NAME_RULE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")
BLOCKED_TAGS = {"script", "foreignobject", "iframe", "embed", "object", "audio", "video", "canvas", "image", "use"}
HANDLER = re.compile(r"^on", re.I)
UNSAFE_REF = re.compile(r"javascript:|data:(?!image/)|vbscript:", re.I)
EXTERNAL_HREF = re.compile(r"^(?:https?:)?//", re.I)

ICON_SETS: dict[str, dict] = {
    "tabler": {
        "repository": "tabler/tabler-icons",
        "checkout": "tabler-icons",
        "revision": "55f87a73f45cf1d9eaf16d7da705065483a9e4f9",
        "license_source": "LICENSE",
        "license_sha256": "b740a1d46122672da62833e97f7e7c8a13fa85cbc7445b584b297cc00dde93db",
        "license": "MIT",
        "provider": "Tabler Icons",
        "author": "Paweł Kuna and contributors",
        "format": "svg",
    },
    "lucide": {
        "repository": "lucide-icons/lucide",
        "checkout": "lucide",
        "revision": "076b52527f0c5fe4cc1cd2472ef716fc332ccf0e",
        "license_source": "LICENSE",
        "license_sha256": "b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57",
        "license": "ISC",
        "provider": "Lucide",
        "author": "Lucide Icons and contributors",
        "format": "svg",
        "license_note": "ISC; some icons are derived from the Feather project (MIT).",
    },
    "hugeicons": {
        "repository": "hugeicons/hugeicons",
        "checkout": "hugeicons",
        "revision": "3e93f5d38c3ffb38319b1b13b128ad4bd45291c1",
        "license_source": "LICENSE.md",
        "license_sha256": "1658d8213209df7b9b86dfc05d724ede48d00dbc27abc15976ec7adec9601cde",
        "license": "MIT",
        "provider": "Hugeicons Free",
        "author": "Hugeicons",
        "format": "svg",
        "scope": "Only packages/core-free-icons members; Pro icons are excluded.",
    },
    "phosphor": {
        "repository": "phosphor-icons/core",
        "checkout": "phosphor",
        "revision": "2b75f3ad12b420c9504ef05df8d2564a28f8500e",
        "license_source": "LICENSE",
        "license_sha256": "b5b1f1da112d18ea2147decfd48ddc1bf2b5aeb6c265381579340e95b15a2bb2",
        "license": "MIT",
        "provider": "Phosphor Icons",
        "author": "Phosphor Icons",
        "format": "svg",
    },
    "material-icons": {
        "repository": "google/material-design-icons",
        "checkout": "material-icons-sp",
        "revision": "40a7a292a79d9394157e1ea24f83d52d5e17c556",
        "license_source": "LICENSE",
        "license_sha256": "58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd",
        "license": "Apache-2.0",
        "provider": "Material Icons",
        "author": "Google",
        "format": "svg",
    },
    "heroicons": {
        "repository": "tailwindlabs/heroicons",
        "checkout": "heroicons",
        "revision": "616b7a4dbbf3d011760af8066262cd5c6b3868f3",
        "license_source": "LICENSE",
        "license_sha256": "60e0b68c0f35c078eef3a5d29419d0b03ff84ec1df9c3f9d6e39a519a5ae7985",
        "license": "MIT",
        "provider": "Heroicons",
        "author": "Tailwind Labs",
        "format": "svg",
    },
    "heroicons-animated": {
        "repository": "heroicons-animated/heroicons-animated",
        "checkout": "heroicons-animated",
        "revision": "ba066ec2c2838e2e5af924db874a136715c57d3d",
        "license_source": "LICENSE",
        "license_sha256": "523f3bb472b7b76b6137becbf45c4d6019cdfbe7a1eef0807e480f7d1cf7ed40",
        "license": "MIT",
        "provider": "Heroicons Animated",
        "author": "Aniket Pawar",
        "format": "tsx",
        "dependencies": {"motion": "^12"},
    },
    "animateicons": {
        "repository": "Avijit07x/animateicons",
        "checkout": "animateicons",
        "revision": "c0a9333abe71f685e8973cd42b29c39d4718eb35",
        "license_source": "LICENSE",
        "license_sha256": "a8716f1e7c79c0575b30f5b686ea663a4530872ea6dee668fc2a7900ee88f1ac",
        "license": "MIT",
        "provider": "AnimateIcons",
        "author": "Avijit Dey",
        "format": "tsx",
        "dependencies": {"motion": "^12"},
    },
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def kebab(value: str) -> str:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"([a-zA-Z])([0-9])", r"\1-\2", value)
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


NUMBER_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
ORDINAL_WORDS = {"first": "1st", "second": "2nd", "third": "3rd"}

# Upstream ships a handful of icons under typo or legacy filenames; each entry
# was verified against the core-free vector data before mapping.
HUGEICONS_RENAMES = {
    "axis-three-d": "axis-3d.svg",
    "file-axis-three-d": "file-axis-3d.svg",
    "image-flip-horizontal": "image-flip -horizontal.svg",
    "mp-301": "mp-3-01.svg",
    "rotate-three-d": "rotate-3d.svg",
    "scale-three-d": "scale-3d.svg",
    "twenty-four-hours-clock": "24-hours-clock.svg",
}


def hugeicons_file(repo: Path, base: str) -> Path | None:
    if base in HUGEICONS_RENAMES:
        candidate = repo / "icons" / HUGEICONS_RENAMES[base]
        return candidate if candidate.is_file() else None
    parts = base.split("-")
    letters = ["-".join(p) if p in ("az", "za") else p for p in parts]
    candidates = [
        base,
        "-".join(NUMBER_WORDS.get(p, p) for p in parts),
        "-".join(letters),
        "-".join(ORDINAL_WORDS.get(p, p) for p in parts),
        re.sub(r"(\d)-x-(\d)", r"\1x\2", base),
        "-".join(NUMBER_WORDS.get(p, p) for p in letters),
        "-".join(ORDINAL_WORDS.get(p, NUMBER_WORDS.get(p, p)) for p in parts),
    ]
    for candidate in candidates:
        path = repo / "icons" / f"{candidate}.svg"
        if path.is_file():
            return path
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value)
    for candidate in candidates:
        hits = [f for f in (repo / "icons").glob("*.svg") if norm(f.stem) == norm(candidate)]
        if len(hits) == 1:
            return hits[0]
    return None


def checked_checkout(path: Path, source: dict) -> None:
    revision = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    if revision != source["revision"]:
        raise ValueError(f"checkout {source['repository']} at reviewed revision {source['revision']}")
    license_raw = (path / source["license_source"]).read_bytes()
    if sha(license_raw) != source["license_sha256"]:
        raise ValueError(f"{source['provider']} license changed; review before importing")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def validate_svg(name: str, raw: bytes) -> None:
    """Reject active or externally-referencing SVG; icons must be self-contained."""
    if len(raw) > 64_000:
        raise ValueError(f"icon exceeds size budget: {name}")
    head = raw[:512].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError(f"icon carries a DTD: {name}")
    try:
        root = ET.fromstring(raw.decode("utf-8"))
    except (ET.ParseError, UnicodeDecodeError) as error:
        raise ValueError(f"icon is not well-formed SVG: {name}: {error}") from error
    if local_name(root.tag) != "svg":
        raise ValueError(f"icon root is not <svg>: {name}")
    for element in root.iter():
        tag = local_name(element.tag)
        if tag in BLOCKED_TAGS:
            raise ValueError(f"icon uses blocked <{tag}>: {name}")
        for attr, value in element.attrib.items():
            attr_name = local_name(attr)
            if HANDLER.match(attr_name):
                raise ValueError(f"icon carries event handler {attr_name}: {name}")
            if UNSAFE_REF.search(value.strip()):
                raise ValueError(f"icon carries unsafe reference: {name}")
            if attr_name in {"href", "src"} and EXTERNAL_HREF.match(value.strip()):
                raise ValueError(f"icon references external resource: {name}")


def store(provider: str, name: str, raw: bytes) -> dict[str, str]:
    relative = f"sources/{provider}/{name}"
    target = DATA / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return relative


def store_license(provider: str, raw: bytes) -> None:
    target = DATA / f"licenses/{provider}/LICENSE"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def word_aliases(name: str, style: str, category: str, extra: list[str]) -> list[str]:
    words = [word for word in re.split(r"[-_]+", name) if word]
    aliases = list(dict.fromkeys([name, name.replace("-", " "), *words, style, category, *extra]))
    return [alias for alias in aliases if alias]


def enumerate_set(provider_id: str, source: dict, repo: Path) -> list[dict]:
    """Yield icon entries {name, style, category, aliases, repo_file, target}."""
    entries: list[dict] = []

    def add(name: str, style: str, category: str, repo_file: Path, target: str, extra: list[str] | None = None) -> None:
        if not NAME_RULE.match(name):
            raise ValueError(f"invalid icon name {name!r} in {provider_id}")
        entries.append({
            "name": name, "style": style, "category": category or "other",
            "aliases": word_aliases(name, style, category, extra or []),
            "repo_file": repo_file, "target": target,
        })

    if provider_id == "tabler":
        for style_dir, style, suffix in [("outline", "outline", ""), ("filled", "filled", "-filled")]:
            for path in sorted((repo / "icons" / style_dir).glob("*.svg")):
                add(path.stem + suffix, style, "interface", path, f"{style_dir}/{path.name}")
    elif provider_id == "lucide":
        for path in sorted((repo / "icons").glob("*.svg")):
            meta_path = path.with_suffix(".json")
            tags: list[str] = []
            category = "interface"
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                tags = [str(tag) for tag in meta.get("tags", [])][:8]
                categories = meta.get("categories", [])
                if categories:
                    category = str(categories[0])
            add(path.stem, "outline", category, path, path.name, tags)
    elif provider_id == "hugeicons":
        free = sorted((repo / "packages/core-free-icons/src").glob("*Icon.ts"))
        missing: list[str] = []
        for path in free:
            name = kebab(path.stem.removesuffix("Icon"))
            svg = hugeicons_file(repo, name)
            if svg is None:
                missing.append(name)
                continue
            add(name, "stroke", "interface", svg, f"{name}.svg")
        if missing:
            raise ValueError(f"hugeicons free icons without upstream SVG: {missing[:8]} ({len(missing)} total)")
    elif provider_id == "phosphor":
        for path in sorted((repo / "raw/regular").glob("*.svg")):
            add(path.stem, "regular", "interface", path, path.name)
    elif provider_id == "material-icons":
        for path in sorted(repo.glob("src/*/*/materialiconsoutlined/24px.svg")):
            category = path.relative_to(repo).parts[1]
            add(path.relative_to(repo).parts[2], "outlined", category, path, f"{category}/{path.relative_to(repo).parts[2]}.svg")
    elif provider_id == "heroicons":
        for style, suffix in [("outline", ""), ("solid", "-solid")]:
            for path in sorted((repo / f"optimized/24/{style}").glob("*.svg")):
                add(path.stem + suffix, style, "interface", path, f"{style}/{path.name}")
    elif provider_id == "heroicons-animated":
        for path in sorted((repo / "packages/react/src/icons").glob("*.tsx")):
            add(path.stem, "animated", "interface", path, path.name)
    elif provider_id == "animateicons":
        for library in ["lucide", "huge"]:
            for path in sorted((repo / "icons" / library).glob("*.tsx")):
                name = path.stem.removesuffix("-icon")
                suffix = "" if library == "lucide" else "-huge"
                add(name + suffix, "animated", "interface", path, f"{library}/{path.name}")
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"no enumerator for {provider_id}")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sets", nargs="*", help="provider IDs to import (default: all configured)")
    args = parser.parse_args()
    selected = args.sets or list(ICON_SETS)
    for provider_id in selected:
        if provider_id not in ICON_SETS:
            raise ValueError(f"unknown icon set {provider_id}")

    catalog_path = DATA / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    icons_path = DATA / "icons.json"
    icons_doc = json.loads(icons_path.read_text(encoding="utf-8")) if icons_path.exists() else {"version": 1, "sets": []}
    upstreams_path = DATA / "upstreams.json"
    upstreams = json.loads(upstreams_path.read_text(encoding="utf-8"))

    sets = {entry["provider_id"]: entry for entry in icons_doc["sets"]}
    now = datetime.now(timezone.utc).isoformat()
    total = 0
    for provider_id in selected:
        source = ICON_SETS[provider_id]
        repo = UPSTREAMS / source["checkout"]
        checked_checkout(repo, source)
        store_license(provider_id, (repo / source["license_source"]).read_bytes())
        entries = enumerate_set(provider_id, source, repo)
        seen: set[str] = set()
        icons: list[dict] = []
        for entry in entries:
            icon_id = f"{provider_id}:{entry['name']}"
            if icon_id in seen:
                raise ValueError(f"duplicate icon id {icon_id}")
            seen.add(icon_id)
            raw = entry["repo_file"].read_bytes()
            if source["format"] == "svg":
                validate_svg(entry["target"], raw)
            relative = store(provider_id, entry["target"], raw)
            icons.append({
                "id": icon_id,
                "name": entry["name"],
                "display": {"zh": entry["name"], "en": entry["name"]},
                "style": entry["style"],
                "category": entry["category"],
                "aliases": entry["aliases"],
                "file": relative,
                "sha256": sha(raw),
            })
        previous = sets.get(provider_id, {})
        sets[provider_id] = {
            "provider": source["provider"],
            "provider_id": provider_id,
            "author": source["author"],
            "license": source["license"],
            "license_url": f"/ui-library/licenses/{provider_id}/LICENSE",
            "license_note": source.get("license_note", ""),
            "scope_note": source.get("scope", ""),
            "repository": source["repository"],
            "revision": source["revision"],
            "source_url": f"https://github.com/{source['repository']}/tree/{source['revision']}",
            "format": source["format"],
            "dependencies": source.get("dependencies", {}),
            "added_at": previous.get("added_at", now),
            "rights_evidence_url": f"/ui-library/assets/{provider_id}/evidence/{source['revision']}/manifest.json",
            "icons": icons,
        }
        upstreams[provider_id] = {
            "repository": source["repository"],
            "revision": source["revision"],
            "license_source": source["license_source"],
        }
        total += len(icons)
        print(json.dumps({"provider": provider_id, "icons": len(icons)}), flush=True)

    icons_doc["sets"] = [sets[key] for key in sorted(sets)]
    icons_path.write_text(json.dumps(icons_doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    upstreams_path.write_text(json.dumps(upstreams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    catalog["icon_count"] = sum(len(entry["icons"]) for entry in icons_doc["sets"])
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sets": len(icons_doc["sets"]), "icon_count": catalog["icon_count"], "imported": total}))


if __name__ == "__main__":
    main()
