#!/usr/bin/env python3
"""Archive commit-pinned license evidence for icon sets; never overwrite an existing record."""
import argparse
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "mcp-go/internal/uicatalog/data"


def download(request):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return response.read(), {k: response.headers.get(k) for k in ["Date", "ETag", "Last-Modified", "Content-Type"]}
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("providers", nargs="*", help="provider IDs to archive (default: all icon sets)")
    args = parser.parse_args()
    icons = json.loads((DATA / "icons.json").read_text(encoding="utf-8"))
    locks = json.loads((DATA / "upstreams.json").read_text(encoding="utf-8"))
    for icon_set in icons["sets"]:
        provider = icon_set["provider_id"]
        if args.providers and provider not in args.providers:
            continue
        lock = locks[provider]
        revision = lock["revision"]
        if revision != icon_set["revision"]:
            raise ValueError(f"{provider} lock/icon revision mismatch")
        repo = lock["repository"]
        base = DATA / f"assets/{provider}/evidence/{revision}"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "manifest.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        sources = {icon["file"]: icon["sha256"] for icon in icon_set["icons"]}
        downloads = []
        names = list(dict.fromkeys([lock.get("license_source", "LICENSE"), "README.md"] + lock.get("notice_sources", [])))
        for name in names:
            url = f"https://raw.githubusercontent.com/{repo}/{revision}/{quote(name)}"
            target = base / name
            if target.exists():
                raw = target.read_bytes()
                headers = {}
            else:
                request = urllib.request.Request(url, headers={"User-Agent": "AIGCNEWS-license-archive/1.0"})
                raw, headers = download(request)
                target.write_bytes(raw)
            if name == lock.get("license_source", "LICENSE"):
                assert hashlib.sha256(raw).hexdigest() == hashlib.sha256((DATA / f"licenses/{provider}/LICENSE").read_bytes()).hexdigest(), provider + " license mismatch"
            downloads.append({"name": name, "url": url, "sha256": hashlib.sha256(raw).hexdigest(), "http_headers": headers})
        record = {
            "repository": repo,
            "revision": revision,
            "captured_at": old["captured_at"] if old else datetime.now(timezone.utc).isoformat(),
            "license": icon_set["license"],
            "license_source": lock.get("license_source", "LICENSE"),
            "license_grants": ["commercial-use", "redistribution"],
            "conditions": ["Preserve the original copyright, license and supplied notices."],
            "resources": downloads,
            "source_files": sources,
            "license_page_url": f"https://github.com/{repo}/blob/{revision}/" + lock.get("license_source", "LICENSE"),
            "screenshot": "license-page.png",
            "scope": icon_set.get("scope_note") or "Only the pinned source and separately listed licensed assets; excludes unrelated Pro products, external media, and trademark rights.",
        }
        if old:
            for name, digest in old["source_files"].items():
                assert sources.get(name, digest) == digest, "Changed historical evidence"
            record["source_files"] = {**old["source_files"], **sources}
            record["resources"] = old["resources"]
            for field in ("screenshot_sha256", "screenshot_captured_at"):
                if field in old:
                    record[field] = old[field]
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        url = "/ui-library/" + path.relative_to(DATA).as_posix()
        if icon_set["rights_evidence_url"] != url:
            icon_set["rights_evidence_url"] = url
        print(json.dumps({"provider": provider, "revision": revision, "source_files": len(sources), "license": icon_set["license"]}), flush=True)
    (DATA / "icons.json").write_text(json.dumps(icons, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
