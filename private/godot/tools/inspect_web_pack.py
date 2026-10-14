"""Read-only inventory of a standalone, unencrypted Godot PCK v2/v3/v4.

Directory layout follows Godot core/io/file_access_pack.cpp. No extraction or
rewriting; bounds and per-entry MD5 are checked before reporting payload size.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct


def read_pack(path: Path, verify=True):
    length = path.stat().st_size
    with path.open("rb") as stream:
        def number(fmt):
            size = struct.calcsize(fmt)
            data = stream.read(size)
            if len(data) != size:
                raise ValueError("Truncated pack")
            return struct.unpack(fmt, data)[0]

        if stream.read(4) != b"GDPC":
            raise ValueError("Expected a standalone Godot PCK")
        version = number("<I")
        engine = [number("<I") for _ in range(3)]
        flags = number("<I")
        if version not in (2, 3, 4) or flags & ~2:
            raise ValueError("Unsupported pack version, encryption, or sparse bundle")
        base = number("<Q")
        if version >= 3:
            directory = number("<Q")
            if not 40 <= directory < length:
                raise ValueError("Invalid directory offset")
            stream.seek(directory)
        else:
            stream.seek(64, 1)
        count = number("<I")
        if count > 1_000_000:
            raise ValueError("Implausible entry count")
        entries = []
        for _ in range(count):
            name_size = number("<I")
            if not 0 < name_size <= 32768:
                raise ValueError("Invalid path length")
            name = stream.read(name_size).rstrip(b"\0").decode("utf-8")
            offset, size = number("<Q") + base, number("<Q")
            digest = stream.read(16).hex()
            entry_flags = number("<I")
            if entry_flags or offset < base or offset + size > length:
                raise ValueError(f"Unsupported or out-of-bounds entry: {name}")
            entries.append(dict(path=name, offset=offset, bytes=size, md5=digest))
        if len({entry["path"] for entry in entries}) != len(entries):
            raise ValueError("Duplicate resource paths")
        if verify:
            for entry in entries:
                stream.seek(entry["offset"])
                digest = hashlib.md5(stream.read(entry["bytes"])).hexdigest()
                if digest != entry["md5"]:
                    raise ValueError(f"Checksum mismatch: {entry['path']}")
    return dict(version=version, engine=engine, bytes=length, entries=entries)


def summarize(pack):
    groups = defaultdict(lambda: dict(count=0, bytes=0))
    for entry in pack["entries"]:
        suffix = Path(entry["path"]).suffix
        groups[suffix]["count"] += 1
        groups[suffix]["bytes"] += entry["bytes"]
    return dict(version=pack["version"], engine=pack["engine"], bytes=pack["bytes"],
                fileCount=len(pack["entries"]), groups=dict(groups),
                largest=sorted(pack["entries"], key=lambda x: x["bytes"], reverse=True)[:25])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--all", action="store_true", help="Include every entry")
    args = parser.parse_args()
    pack = read_pack(args.pack)
    print(json.dumps(pack if args.all else summarize(pack), indent=2))
