"""Select cached wheels without changing the index-provided requirement hashes."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

try:
    from packaging.requirements import Requirement
    from packaging.tags import sys_tags
    from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
except ModuleNotFoundError:
    # The pinned Python image has pip before application dependencies are installed.
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename


def cached_requirements(text: str, wheelhouse: Path, *, supported_tags: set[str] | None = None) -> str:
    supported = supported_tags if supported_tags is not None else {str(tag) for tag in sys_tags()}
    available = defaultdict(list)
    for wheel in wheelhouse.glob("*.whl"):
        if wheel.is_symlink() or not wheel.is_file():
            continue
        try:
            name, version, _, tags = parse_wheel_filename(wheel.name)
        except InvalidWheelFilename:
            continue
        if supported.intersection(str(tag) for tag in tags):
            available[canonicalize_name(name)].append(version)

    selected = []
    pending = []
    for line in text.splitlines(keepends=True):
        if not pending and (not line.strip() or line.lstrip().startswith("#")):
            continue
        pending.append(line)
        if line.rstrip().endswith("\\"):
            continue
        block = "".join(pending)
        pending = []
        logical = block.replace("\\\r\n", " ").replace("\\\n", " ")
        requirement, separator, _ = logical.partition("--hash=")
        if not separator:
            raise ValueError("expected requirements with index-provided hashes")
        parsed = Requirement(requirement.strip())
        if parsed.url or (parsed.marker and not parsed.marker.evaluate()):
            continue
        if any(parsed.specifier.contains(version, prereleases=True)
               for version in available[canonicalize_name(parsed.name)]):
            selected.append(block if block.endswith("\n") else block + "\n")
    if pending:
        raise ValueError("unterminated requirement continuation")
    return "".join(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", type=Path)
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(cached_requirements(args.requirements.read_text(), args.wheelhouse))


if __name__ == "__main__":
    main()
