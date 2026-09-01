"""Classify a release candidate into a deterministic offline gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LEVELS = {"green": 0, "yellow": 1, "red": 2}


def classify_gate(manifest: dict[str, Any], *, source_dirty: bool = False, source_matches: bool = True, digest_matches: bool = True) -> str:
    if source_dirty or not source_matches or not digest_matches:
        return "reject"
    risk = manifest.get("risk")
    if risk not in LEVELS:
        return "reject"
    return {"green": "automatic", "yellow": "manual", "red": "blocked"}[risk]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--source-dirty", action="store_true")
    parser.add_argument("--source-mismatch", action="store_true")
    parser.add_argument("--digest-mismatch", action="store_true")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(classify_gate(manifest, source_dirty=args.source_dirty, source_matches=not args.source_mismatch, digest_matches=not args.digest_mismatch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
