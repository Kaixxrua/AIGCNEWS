"""Shared helpers for pinned upstream UI source imports.

Every catalog entry must keep byte-for-byte original sources, a pinned revision,
archived license evidence, and a self-contained offline preview. These helpers
enforce the same rules as the first reviewed importers.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
import posixpath
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "mcp-go/internal/uicatalog/data"

# Reject bundled external URLs, site-root static assets, and embeds that require
# real media files. Dynamic src={...}/href={...} bindings and inert href="#" anchors
# stay allowed: the preview CSP blocks any actual request.
# Strict rule: any hard-coded external URL string, site-root asset reference,
# or media embed makes the source unreviewed. Dynamic bindings (``src={value}``)
# and inert ``href="#"`` anchors stay allowed. Sources may declare a small set of
# human-reviewed metadata files (e.g. site config with attribution URLs) via
# ``reviewed_allow_files``; every exception is recorded in the import report.
MEDIA = re.compile(
    r"""["'`({]\s*https?://|\{["']https?://|(?:src|href)\s*=\s*["']/(?!/)"""
    r"""|<\s*(?:video|audio|iframe)\b""",
    re.I,
)
# W3C namespace identifiers never trigger network requests; allow them in inline SVG.
MEDIA_ALLOW = re.compile(r'''https?://(?:www\.w3\.org/(?:2000/svg|1999/xlink|2000/xmlns/)|schemas\.microsoft\.com/)''', re.I)


def has_external_media(text: str) -> bool:
    return bool(MEDIA.search(MEDIA_ALLOW.sub("", text)))
ALL_IMPORTS = re.compile(r'''(?:from\s+|import\s*\()["']([^"']+)["']''')
SIDE_EFFECT_IMPORT = re.compile(r'''^\s*import\s*["']([^"']+)["']''', re.M)

# Packages provided by the preview sandbox (frontend/node_modules). Components
# needing anything else are rejected so previews never reach the network.
def node_modules_packages(frontend_root: Path | None = None) -> set[str]:
    root = frontend_root or (ROOT / "frontend" / "node_modules")
    names: set[str] = set()
    if not root.is_dir():
        return names
    for entry in root.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.name.startswith("@") and entry.is_dir():
            for scoped in entry.iterdir():
                if (scoped / "package.json").exists():
                    names.add(f"{entry.name}/{scoped.name}")
        elif (entry / "package.json").exists():
            names.add(entry.name)
    return names


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_source(path: str, raw: bytes) -> None:
    if len(raw) > 256_000:
        raise ValueError(f"source exceeds catalog file budget: {path}")
    if not path.endswith((".css", ".json", ".md", ".mdx")):
        text = raw.decode("utf-8")
        if has_external_media(text):
            raise ValueError(f"unreviewed external media or URL: {path}")


def validate_closure_file(path: str, raw: bytes, allowed: set[str]) -> None:
    """Validate one closure file; ``allowed`` lists human-reviewed exceptions."""
    if path in allowed:
        if len(raw) > 256_000:
            raise ValueError(f"source exceeds catalog file budget: {path}")
        return
    validate_source(path, raw)


def store(provider: str, name: str, raw: bytes, *, validate_media: bool = True) -> dict[str, str]:
    if validate_media:
        validate_source(name, raw)
    elif len(raw) > 256_000:
        raise ValueError(f"source exceeds catalog file budget: {name}")
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


def append_unique_file(files: list[dict], entry: dict) -> None:
    """Append a stored file unless an entry with the same path is present.

    Closures may already include a provider's shared/theme stylesheet; listing
    the same path twice makes wire delivery counts diverge from the manifest.
    """
    if any(existing["path"] == entry["path"] for existing in files):
        return
    files.append(entry)


def checked_checkout(path: Path, source: dict) -> None:
    revision = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    if revision != source["revision"]:
        raise ValueError(f"checkout {source['repository']} at reviewed revision {source['revision']}, found {revision}")
    license_raw = (path / source["license_source"]).read_bytes()
    if sha(license_raw) != source["license_sha256"]:
        raise ValueError(f"{source['provider']} license changed; review before importing")


BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
TEMPLATE_LITERAL = re.compile(r"`(?:[^`\\]|\\.)*`", re.S)
LINE_COMMENT = re.compile(r"(^|[\s;{},()=<>&|!?:+\-*/~^])//[^\n]*", re.M)


def imports_of(text: str) -> list[str]:
    """Static import specifiers; ignores comments and template-literal text.

    Code samples, regexes and transform helpers routinely contain strings like
    ``from './x'`` that are not real imports. Static specifiers never live in
    comments or template literals, so both are blanked before scanning.
    """
    cleaned = LINE_COMMENT.sub(r"\1", TEMPLATE_LITERAL.sub("``", BLOCK_COMMENT.sub("", text)))
    return ALL_IMPORTS.findall(cleaned) + SIDE_EFFECT_IMPORT.findall(cleaned)


# Imports that the offline preview replaces with local stubs (see
# frontend/scripts/original-react-previews.mjs). They never hit node_modules.
PREVIEW_STUBS = ("next/image", "next/link", "next/navigation", "next/font", "next/script", "next/dynamic")


def detect_export(text: str, slug: str) -> str:
    """Pick the mountable component export from an original entry source."""
    if re.search(r"export\s+default\b", text):
        return "default"
    names = re.findall(r"export\s+(?:async\s+)?(?:function|const|class)\s+([A-Z]\w*)", text)
    for body in re.findall(r"export\s*\{([^}]*)\}", text):
        for part in body.split(","):
            match = re.search(r"(?:\bas\s+)?([A-Z]\w*)$", part.strip())
            if match:
                names.append(match.group(1))
    names = list(dict.fromkeys(names))
    if not names:
        raise Reject("no component export found")
    pascal = "".join(piece.capitalize() for piece in re.split(r"[^a-zA-Z0-9]+", slug) if piece)
    if pascal in names:
        return pascal
    for name in names:
        if name.lower().startswith(pascal.lower()) or (pascal and pascal.lower().startswith(name.lower())):
            return name
    return names[0]


def package_name(specifier: str) -> str:
    if specifier.startswith("@"):
        return "/".join(specifier.split("/")[:2])
    return specifier.split("/")[0]


def resolve_repo_path(base: str, specifier: str) -> list[str]:
    target = posixpath.normpath((Path(base) / specifier).as_posix() if base else specifier)
    return [
        target, target + ".tsx", target + ".ts", target + ".jsx", target + ".js",
        target + ".css", target + ".json",
        target + "/index.tsx", target + "/index.ts", target + "/index.jsx", target + "/index.js",
    ]


class Reject(Exception):
    """A candidate component that cannot be imported with a reason."""


def resolve_closure(root: Path, entries: list[str], alias_root: str, *,
                    available_packages: set[str], max_files: int = 32,
                    alias_rules: list[tuple[str, str]] | None = None,
                    package_dirs: dict[str, str] | None = None) -> tuple[list[str], dict[str, str]]:
    """Collect a component's repo-relative file closure and npm dependencies.

    alias_root maps ``@/x`` imports to ``<alias_root>/x`` inside the checkout.
    alias_rules holds ordered (prefix, target) overrides applied after the
    ``@/`` marker is stripped, e.g. ("components/ui/", "src/ui/").
    package_dirs maps workspace package names (e.g. "@uitripled/utils") to a
    repo-relative source directory so monorepo-internal packages resolve to
    pinned files instead of the npm registry.
    Raises Reject with a human-readable reason when the closure cannot be
    satisfied offline.
    """
    pending = list(entries)
    resolved: list[str] = []
    packages: dict[str, str] = {}
    while pending:
        relative = pending.pop(0)
        if relative in resolved:
            continue
        file_path = root / relative
        if not file_path.is_file():
            raise Reject(f"missing file {relative}")
        resolved.append(relative)
        if len(resolved) > max_files:
            raise Reject(f"closure exceeds {max_files} files")
        if not relative.endswith((".ts", ".tsx", ".js", ".jsx")):
            continue
        text = file_path.read_text(encoding="utf-8")
        for specifier in imports_of(text):
            if "${" in specifier:
                # Template-literal placeholder picked up from inside a string
                # (e.g. a code-transform helper), never a real static path.
                continue
            if specifier.startswith(("@/components/ui/8bit/", "@/")):
                if specifier.startswith("@/"):
                    body = specifier[2:]
                    rule = next((rule for rule in (alias_rules or []) if body.startswith(rule[0])), None)
                    target = rule[1] + body[len(rule[0]):] if rule else (alias_root + "/" + body if alias_root else body)
                    candidates = resolve_repo_path("", target)
                else:
                    candidates = []
            elif specifier.startswith("."):
                base = Path(relative).parent.as_posix()
                candidates = resolve_repo_path(base, specifier)
            elif specifier.startswith(PREVIEW_STUBS) or specifier == "next":
                continue
            else:
                name = package_name(specifier)
                workspace_dir = (package_dirs or {}).get(name)
                if workspace_dir:
                    rest = specifier[len(name):].lstrip("/")
                    candidates = resolve_repo_path("", workspace_dir + ("/" + rest if rest else "/index"))
                    match = next((candidate for candidate in candidates if (root / candidate).is_file()), None)
                    if not match:
                        raise Reject(f"unresolved workspace import {specifier} from {relative}")
                    pending.append(match)
                    continue
                if name not in ("react", "react-dom"):
                    if name not in available_packages:
                        raise Reject(f"npm package not available offline: {name}")
                    packages[name] = "sandbox"
                continue
            match = next((candidate for candidate in candidates if (root / candidate).is_file()), None)
            if candidates and not match and not specifier.endswith((".css", ".json")):
                raise Reject(f"unresolved import {specifier} from {relative}")
            if match:
                pending.append(match)
    return resolved, packages


def external_versions(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for package_path in [path / "package.json", *path.glob("packages/*/package.json"), *path.glob("apps/*/package.json")]:
        if not package_path.is_file():
            continue
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        result.update(package.get("dependencies", {}))
        result.update(package.get("devDependencies", {}))
    return result


def make_item(provider_id: str, source: dict, slug: str, title_en: str, title_zh: str,
              entry_path: str, files: list[dict[str, str]], notice: dict[str, str],
              css_name: str, dependencies: dict[str, str], previous: dict, *,
              category: str = "component", extra_aliases: list[str] | None = None,
              demo_url: str = "", preview_preset: str | None = None,
              export_name: str = "default", props: dict | None = None,
              preview_alias_rules: list[list[str]] | None = None,
              preview_root: str | None = None,
              preview_package_dirs: dict[str, str] | None = None) -> dict:
    item_id = f"{provider_id}-{slug}"
    item = {
        "id": item_id,
        "name": {"zh": title_zh, "en": title_en},
        "description": {"zh": f"{source['provider']} 官方原版{title_zh}。", "en": f"Original {title_en} from {source['provider']}."},
        "notes": {"zh": "固定官方提交与许可；预览不访问外部网络。", "en": "Pinned official source and license; the preview makes no external requests."},
        "provider": source["provider"], "provider_id": provider_id, "author": f"{source['provider']} contributors",
        "license": source.get("license", "MIT"), "license_url": f"/ui-library/licenses/{provider_id}/LICENSE",
        "revision": source["revision"],
        "source_url": f"https://github.com/{source['repository']}/blob/{source['revision']}/{entry_path}",
        "demo_url": demo_url or f"https://github.com/{source['repository']}/tree/{source['revision']}",
        "category": category, "kind": "component", "frameworks": ["react"],
        "aliases": list(dict.fromkeys([slug, title_en.lower(), provider_id, "react", "tailwind", *(extra_aliases or []), "组件", "素材"])),
        "files": files, "notices": [notice], "assets": [], "dependencies": dependencies,
        "export_name": export_name, "props": props or {}, "preview_adapter": "original-react-v1",
        "preview_css": css_name,
        "preview_url": f"/ui-library/previews/{item_id}.html",
        "poster_url": f"/ui-library/posters/{item_id}.png", "clip_url": "",
        "added_at": previous.get(item_id, {}).get("added_at", datetime.now(timezone.utc).isoformat()),
        "rights_evidence_url": f"/ui-library/assets/{provider_id}/evidence/{source['revision']}/manifest.json",
    }
    if preview_preset:
        item["preview_preset"] = preview_preset
    if preview_root is None:
        preview_root = source.get("alias_root") or None
    if preview_root:
        item["preview_root"] = preview_root
    if preview_alias_rules:
        item["preview_alias_rules"] = preview_alias_rules
    if preview_package_dirs:
        item["preview_package_dirs"] = preview_package_dirs
    return item


def apply_additions(additions: list[dict], locks_update: dict[str, dict]) -> None:
    catalog_path = DATA / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in additions}
    catalog["items"] = [item for item in catalog["items"] if item["id"] not in ids] + additions
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    locks_path = DATA / "upstreams.json"
    locks = json.loads(locks_path.read_text(encoding="utf-8"))
    for provider, source in locks_update.items():
        locks[provider] = {key: source[key] for key in ("repository", "revision", "license_source")}
    locks_path.write_text(json.dumps(locks, indent=2) + "\n", encoding="utf-8")
    removed = gc_orphans(list(locks_update))
    if removed:
        print(f"gc: removed {removed} unreferenced source files")


def gc_orphans(providers: list[str] | None = None) -> int:
    """Delete stored source files no catalog item references (import reject leftovers)."""
    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    referenced = set()
    for item in catalog["items"]:
        for file in item.get("files", []):
            referenced.add(file["path"])
        if item.get("preview_preset"):
            referenced.add(item["preview_preset"])
    roots = [DATA / "sources" / provider for provider in providers] if providers else [DATA / "sources"]
    removed = 0
    for root in roots:
        if not root.exists():
            continue
        for file in sorted(root.rglob("*")):
            if file.is_file() and file.relative_to(DATA).as_posix() not in referenced:
                file.unlink()
                removed += 1
    return removed


def previous_items() -> dict:
    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    return {item["id"]: item for item in catalog["items"]}
