#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.project_catalog_evidence import (  # noqa: E402
    verify_project_catalog_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify project-catalog evidence without changing runtime state."
    )
    parser.add_argument("artifact")
    parser.add_argument("--release-id")
    parser.add_argument("--revision")
    parser.add_argument("--image-digest")
    parser.add_argument("--topology-file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
        if not isinstance(artifact, dict):
            raise ValueError("artifact must be an object")
        topology_sha256 = None
        if args.topology_file:
            import hashlib

            topology_sha256 = hashlib.sha256(
                Path(args.topology_file).read_bytes()
            ).hexdigest()
        result = verify_project_catalog_evidence(
            artifact,
            release_id=args.release_id,
            revision=args.revision,
            image_digest=args.image_digest,
            topology_sha256=topology_sha256,
            now=datetime.now().astimezone(),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    except Exception as error:
        print(
            json.dumps(
                {"status": "failed", "error_class": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
