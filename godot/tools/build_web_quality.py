"""Build two NEW Web packs; source PCK, imports and original artwork stay intact.

Original: byte-identical resources except losslessly repacked RSCC containers.
Balanced: additionally re-encode only five opaque material CTEX mip chains using
WebP quality 88. Dimensions, mip count, alpha, geometry and shaders are retained.
"""
import argparse
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from inspect_web_pack import read_pack
from repack_web_cache import repack_entry


MATERIALS = (
    "meadow-sward-v60.png-", "ochre-trail-v39.png-",
    "limestone-fractured-v61.png-", "riverbank-limestone-v68.png-",
    "bridge-oak-v39.png-",
)
CACHES = {f"assets/baked/v77/{name}.scn" for name in ("detail", "brush", "foothill", "riverbank")}
CACHES.add("assets/baked/v113/far-sward.scn")


def compress_material(blob, quality=88):
    if blob[:4] != b"GST2" or struct.unpack_from("<I", blob, 4)[0] != 1:
        raise ValueError("Unsupported CTEX header")
    kind, width, height, mips, image_format = struct.unpack_from("<IHHII", blob, 36)
    if kind != 2 or image_format not in (4, 5) or mips > 16:
        raise ValueError("Expected a WebP RGB(A) CTEX")
    result, offset, levels = bytearray(blob[:52]), 52, []
    for level in range(mips + 1):
        size = struct.unpack_from("<I", blob, offset)[0]
        offset += 4
        source = blob[offset:offset + size]
        offset += size
        original = Image.open(io.BytesIO(source)).convert("RGBA")
        if original.size != (max(1, width >> level), max(1, height >> level)):
            raise ValueError("Unexpected mip dimensions")
        before = np.asarray(original)
        if not np.all(before[:, :, 3] == 255):
            raise ValueError("Balanced whitelist must remain fully opaque")
        buffer = io.BytesIO()
        original.convert("RGB").save(buffer, "WEBP", quality=quality, method=6)
        encoded = buffer.getvalue()
        # Retain original mip when tiny/lossless payload is already smaller.
        if len(encoded) >= len(source):
            encoded = source
        decoded = Image.open(io.BytesIO(encoded)).convert("RGBA")
        after = np.asarray(decoded)
        if decoded.size != original.size or not np.array_equal(before[:, :, 3], after[:, :, 3]):
            raise ValueError("Compression changed dimensions/alpha")
        difference = before[:, :, :3].astype(np.float32) - after[:, :, :3]
        mse = float(np.mean(difference * difference))
        psnr = 99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse)
        levels.append(dict(level=level, size=list(original.size), bytes=len(encoded),
                           psnr=round(psnr, 3), mae=round(float(np.mean(np.abs(difference))), 3)))
        result.extend(struct.pack("<I", len(encoded)))
        result.extend(encoded)
    if offset != len(blob):
        raise ValueError("Unexpected CTEX trailing data")
    # A diagnostic guard, not proof that the whole scene still looks good.
    if levels[0]["psnr"] < 28:
        raise ValueError(f"Material quality below conservative guard: {levels[0]}")
    return bytes(result), levels


def write_pack(source, inventory, destination, replacements):
    destination = destination.resolve()
    if destination.exists() or destination == source.resolve():
        raise ValueError(f"Refusing to overwrite an existing file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".building")
    with source.open("rb") as reader, temporary.open("xb") as writer:
        header = bytearray(reader.read(112))
        if inventory["version"] != 4:
            raise ValueError("Writer only supports observed standalone PCK v4")
        struct.pack_into("<Q", header, 24, 112)
        writer.write(header)
        entries = []
        for entry in inventory["entries"]:
            writer.write(b"\0" * (-writer.tell() % 16))
            reader.seek(entry["offset"])
            blob = replacements.get(entry["path"])
            if blob is None:
                blob = reader.read(entry["bytes"])
            entries.append((entry["path"], writer.tell() - 112, len(blob), hashlib.md5(blob).digest()))
            writer.write(blob)
        writer.write(b"\0" * (-writer.tell() % 16))
        directory = writer.tell()
        writer.write(struct.pack("<I", len(entries)))
        for path, offset, size, digest in entries:
            name = path.encode("utf-8")
            name += b"\0" * (-len(name) % 4)
            writer.write(struct.pack("<I", len(name)) + name)
            writer.write(struct.pack("<QQ", offset, size) + digest + struct.pack("<I", 0))
        writer.seek(32)
        writer.write(struct.pack("<Q", directory))
    read_pack(temporary)  # Bounds + complete MD5 verification before publication.
    temporary.rename(destination)


def build(source, directory):
    inventory = read_pack(source)
    original, balanced, changes = {}, {}, []
    with source.open("rb") as reader:
        for entry in inventory["entries"]:
            name = entry["path"]
            is_material = name.startswith(".godot/imported/") and name.endswith(".ctex") and any(
                Path(name).name.startswith(prefix) for prefix in MATERIALS)
            if name not in CACHES and not is_material:
                continue
            reader.seek(entry["offset"])
            blob = reader.read(entry["bytes"])
            if name in CACHES:
                candidate = repack_entry(name, blob)
                # Smaller inner Zstd is not necessarily smaller HTTP payload:
                # the original 4KiB blocks can contain compressible repetition.
                # Reject any rewrite that regresses the supported gzip fallback.
                transport_wins = len(gzip.compress(candidate, compresslevel=6, mtime=0)) < len(gzip.compress(blob, compresslevel=6, mtime=0))
                if len(candidate) < len(blob) and transport_wins:
                    original[name] = balanced[name] = candidate
                    changes.append(dict(path=name, kind="lossless-rscc", before=len(blob), after=len(candidate)))
            else:
                try:
                    candidate, levels = compress_material(blob)
                except ValueError as error:
                    raise ValueError(f"{name}: {error}") from error
                balanced[name] = candidate
                changes.append(dict(path=name, kind="opaque-webp-q88", before=len(blob),
                                    after=len(candidate), levels=levels))
    if len([row for row in changes if row["kind"] == "opaque-webp-q88"]) != len(MATERIALS):
        raise ValueError("Incomplete balanced material whitelist")
    write_pack(source, inventory, directory / "index.pck", original)
    write_pack(source, inventory, directory / "index-balanced.pck", balanced)
    report = dict(source=str(source.resolve()), sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  sourceBytes=source.stat().st_size, originalBytes=(directory / "index.pck").stat().st_size,
                  balancedBytes=(directory / "index-balanced.pck").stat().st_size, changes=changes)
    (directory / "quality-build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = build(args.source, args.directory)
    print(json.dumps({key: value for key, value in result.items() if key != "changes"}, indent=2))
