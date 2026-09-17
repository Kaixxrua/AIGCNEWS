#!/usr/bin/env python3
"""Create a tiny integrity-valid UI catalog for clean-checkout CI builds."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVISION = "1" * 40


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return digest(content)


def materialize(data: Path) -> None:
    source = b"export const CiFixture = () => null\nexport default CiFixture\n"
    large_source = source + (b"// synthetic palette fixture padding\n" * 2000)
    license_text = b"CI-only synthetic fixture. Not a production catalog entry.\n"
    resource_a = b"fixture-resource-a\n"
    resource_b = b"fixture-resource-b\n"
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    source_path = "sources/ci/fixture.ts"
    large_source_path = "sources/ci/theme-presets.ts"
    license_path = "licenses/ci/LICENSE"
    evidence_dir = data / "assets" / "ci" / "evidence" / REVISION
    source_hash = write(data / source_path, source)
    large_source_hash = write(data / large_source_path, large_source)
    license_hash = write(data / license_path, license_text)
    resource_a_hash = write(evidence_dir / "resource-a.txt", resource_a)
    resource_b_hash = write(evidence_dir / "resource-b.txt", resource_b)
    screenshot_hash = write(evidence_dir / "screenshot.png", png)

    icon_svgs = {}
    for icon_name in ("check", "menu"):
        icon_path = f"sources/ci/icons/{icon_name}.svg"
        icon_svgs[icon_name] = (
            icon_path,
            write(
                data / icon_path,
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/></svg>\n'.encode(),
            ),
        )
    evidence = {
        "revision": REVISION,
        "license": "MIT",
        "captured_at": "2026-09-16T00:00:00Z",
        "license_grants": ["commercial-use", "redistribution"],
        "source_files": {
            source_path: source_hash,
            large_source_path: large_source_hash,
            **{icon_path: icon_hash for icon_path, icon_hash in icon_svgs.values()},
        },
        "resources": [
            {"name": "resource-a.txt", "sha256": resource_a_hash},
            {"name": "resource-b.txt", "sha256": resource_b_hash},
        ],
        "screenshot": "screenshot.png",
        "screenshot_sha256": screenshot_hash,
    }
    write(
        evidence_dir / "manifest.json",
        (json.dumps(evidence, sort_keys=True) + "\n").encode(),
    )

    def item(
        item_id: str, *, source_file: dict[str, str] | None = None
    ) -> dict[str, object]:
        write(data / "posters" / f"{item_id}.png", png)
        return {
            "rights_evidence_url": f"/ui-library/assets/ci/evidence/{REVISION}/manifest.json",
            "id": item_id,
            "added_at": "2026-09-16T00:00:00Z",
            "name": {"zh": "CI 构建素材", "en": "CI build fixture"},
            "description": {
                "zh": "仅用于干净检出构建。",
                "en": "Clean-checkout build fixture.",
            },
            "notes": {
                "zh": "保留合成夹具的测试语义，不进入生产。",
                "en": "Preserve fixture semantics; never ship to production.",
            },
            "provider": "CI",
            "provider_id": "ci",
            "author": "AIGCNEWS",
            "license": "MIT",
            "license_url": "/ui-library/licenses/ci/LICENSE",
            "revision": REVISION,
            "source_url": "https://example.invalid/ci-fixture",
            "demo_url": "https://example.invalid/ci-fixture",
            "category": "component",
            "frameworks": ["vue"],
            "aliases": ["fixture", "构建"],
            "files": [
                source_file
                or {"name": "fixture.ts", "path": source_path, "sha256": source_hash}
            ],
            "notices": [
                {"name": "LICENSE", "path": license_path, "sha256": license_hash}
            ],
            "assets": [],
            "props": {},
            "dependencies": {},
            "export_name": "CiFixture",
            "preview_url": f"/ui-library/previews/{item_id}.html",
            "poster_url": f"/ui-library/posters/{item_id}.png",
            "clip_url": "",
        }

    items = []
    for index in range(42):
        theme = item(f"ci-theme-{index + 1:02d}")
        theme.update(
            {
                "name": {"zh": f"CI 配色 {index + 1}", "en": f"CI palette {index + 1}"},
                "category": "theme",
                "kind": "theme",
                "subcategory": "color-theme",
                "frameworks": ["css"],
                "aliases": ["palette", "配色"],
                "theme": {
                    "light": {"primary": f"hsl({index} 60% 50%)"},
                    "dark": {"primary": f"hsl({index} 60% 70%)"},
                },
            }
        )
        items.append(theme)
    dashboard = item("shadcn-dashboard-01")
    dashboard.update(
        {
            "name": {"zh": "CI 仪表盘", "en": "CI dashboard"},
            "category": "dashboard",
            "kind": "template",
            "aliases": ["shadcn"],
        }
    )
    items.append(dashboard)
    tweakcn = item(
        "tweakcn-claude",
        source_file={
            "name": "utils/theme-presets.ts",
            "path": large_source_path,
            "sha256": large_source_hash,
        },
    )
    tweakcn.update({"name": {"zh": "CI 大文件", "en": "CI large source"}})
    items.append(tweakcn)
    write(
        data / "catalog.json",
        (
            json.dumps({"version": 1, "items": items}, ensure_ascii=False) + "\n"
        ).encode(),
    )
    write(data / "upstreams.json", b"{}\n")
    icon_set = {
        "provider": "CI",
        "provider_id": "ci",
        "author": "AIGCNEWS",
        "license": "MIT",
        "license_url": "/ui-library/licenses/ci/LICENSE",
        "license_note": "",
        "scope_note": "",
        "repository": "ci/fixture",
        "revision": REVISION,
        "source_url": "https://example.invalid/ci-fixture",
        "format": "svg",
        "dependencies": {},
        "added_at": "2026-09-16T00:00:00Z",
        "rights_evidence_url": f"/ui-library/assets/ci/evidence/{REVISION}/manifest.json",
        "icons": [
            {
                "id": f"ci:{icon_name}",
                "name": icon_name,
                "display": {"zh": icon_name, "en": icon_name},
                "style": "outline",
                "category": "interface",
                "aliases": [icon_name],
                "file": icon_path,
                "sha256": icon_hash,
            }
            for icon_name, (icon_path, icon_hash) in icon_svgs.items()
        ],
    }
    write(
        data / "icons.json",
        (json.dumps({"version": 1, "sets": [icon_set]}, ensure_ascii=False) + "\n").encode(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-copy", action="store_true")
    args = parser.parse_args()
    data = ROOT / "mcp-go" / "internal" / "uicatalog" / "data"
    if data.exists():
        shutil.rmtree(data)
    materialize(data)
    preview_root = ROOT / "frontend" / ".ui-previews" / "previews"
    if preview_root.exists():
        shutil.rmtree(preview_root)
    for item_id in [
        *(f"ci-theme-{index + 1:02d}" for index in range(42)),
        "shadcn-dashboard-01",
        "tweakcn-claude",
    ]:
        write(
            preview_root / f"{item_id}.html",
            b"<!doctype html><title>CI fixture</title>\n",
        )
    if args.frontend_copy:
        target = ROOT / "frontend" / ".ui-library-data"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(data, target)


if __name__ == "__main__":
    main()
