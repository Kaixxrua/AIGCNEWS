#!/usr/bin/env python3
"""Create a new pinned private release with automatic contact quality reduction disabled.

The input is verified and never edited. Fixed-size PCK entry replacements preserve
all unrelated payload bytes, offsets, artwork, scene packs and engine binaries.
Requires brotli only when building the release's compressed transport sidecars.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import struct
from pathlib import Path

from stage_private_frontend import (
    DESCRIPTOR,
    MANIFEST,
    PRIVATE_SOURCE,
    RELEASE_DIR,
    StageError,
    load_release,
    sha256,
    verify_scene,
    verify_sources,
)

GOVERNOR = "camp_presentation/camp_performance_governor.gd"
# Keep the legacy class callable; configure(false) makes its owner free it.
DISABLED = b"extends Node\n# Quality is selected by the user, never by measured FPS.\nfunc configure(_scene: Node3D) -> bool:\n\treturn false\n"


def pack_entries(blob: bytes):
    """Validate an unencrypted PCK v2-v4 and return its checked directory."""
    data = bytearray(blob)
    if len(data) < 100 or data[:4] != b"GDPC":
        raise StageError("invalid PCK header")
    version, = struct.unpack_from("<I", data, 4)
    flags, base = struct.unpack_from("<IQ", data, 20)
    if version not in (2, 3, 4) or flags & ~2:
        raise StageError("unsupported PCK format")
    cursor = struct.unpack_from("<Q", data, 32)[0] if version >= 3 else 96
    seen = set()
    entries = {}
    try:
        count, = struct.unpack_from("<I", data, cursor)
        cursor += 4
        if count > 100000:
            raise StageError("invalid PCK entry count")
        for _ in range(count):
            length, = struct.unpack_from("<I", data, cursor)
            cursor += 4
            if not 0 < length <= 32768:
                raise StageError("invalid PCK path length")
            name = bytes(data[cursor:cursor + length]).rstrip(b"\0").decode()
            cursor += length
            offset, size = struct.unpack_from("<QQ", data, cursor)
            offset += base
            checksum_at = cursor + 16
            entry_flags, = struct.unpack_from("<I", data, cursor + 32)
            cursor += 36
            if entry_flags or name in seen or offset < base or offset + size > len(data):
                raise StageError("invalid PCK entry")
            seen.add(name)
            content = bytes(data[offset:offset + size])
            if hashlib.md5(content).digest() != data[checksum_at:checksum_at + 16]:
                raise StageError("PCK entry checksum mismatch")
            entries[name] = (offset, size, checksum_at)
    except (struct.error, UnicodeError) as exc:
        raise StageError("malformed PCK directory") from exc
    return entries


def replace_entries(blob: bytes, replacements: dict[str, bytes]) -> bytes:
    entries = pack_entries(blob)
    if not set(replacements) <= entries.keys():
        raise StageError("required PCK entries missing")
    data = bytearray(blob)
    for name, replacement in replacements.items():
        offset, size, checksum_at = entries[name]
        if len(replacement) > size:
            raise StageError("replacement exceeds PCK entry size")
        replacement = replacement.ljust(size, b" ")
        data[offset:offset + size] = replacement
        data[checksum_at:checksum_at + 16] = hashlib.md5(replacement).digest()
    return bytes(data)


def build(private: Path, output: Path, release_id: str, descriptor_digest: str) -> str:
    import brotli

    descriptor = json.loads((private / DESCRIPTOR).read_text())
    pinned = load_release(private, descriptor["release_id"], descriptor_digest)
    verify_sources(private / PRIVATE_SOURCE, pinned.source_files)
    verify_scene(private / RELEASE_DIR, pinned.scene_files)
    if output.exists() or output.resolve().is_relative_to(private.resolve()):
        raise StageError("output must be a new directory outside the input release")
    scene = private / RELEASE_DIR / "camp-scene"
    packs = list(scene.glob("camp-presentation-*.pck"))
    if len(packs) != 1:
        raise StageError("expected one presentation runtime")
    runtime = packs[0]
    patched = replace_entries(runtime.read_bytes(), {GOVERNOR: DISABLED})
    old_digest = sha256(runtime)
    new_digest = hashlib.sha256(patched).hexdigest()
    renamed = {runtime.name: f"camp-presentation-{new_digest[:12]}.pck"}
    substitutions = {old_digest: new_digest, runtime.name: renamed[runtime.name]}
    changed = {renamed[runtime.name]: patched}
    for wrapper in scene.glob("camp-bootstrap-*.pck"):
        # Only bindings contain the pinned presentation hash. Equal-width pins
        # let us preserve the wrapper's settings and every other resource.
        raw = wrapper.read_bytes()
        offset, size, _ = pack_entries(raw)["camp_bootstrap/bindings.json"]
        text = raw[offset:offset + size].decode()
        if old_digest not in text or runtime.name not in text:
            raise StageError("wrapper does not pin the presentation runtime")
        text = text.replace(old_digest, new_digest).replace(runtime.name, renamed[runtime.name])
        content = replace_entries(raw, {"camp_bootstrap/bindings.json": text.encode()})
        digest = hashlib.sha256(content).hexdigest()
        name = wrapper.name.replace(sha256(wrapper)[:12], digest[:12])
        renamed[wrapper.name] = name
        substitutions[sha256(wrapper)] = digest
        substitutions[wrapper.name] = name
        changed[name] = content
    if len(changed) != 3:
        raise StageError("expected full and lite bootstrap wrappers")
    shutil.copytree(private, output)
    target = output / RELEASE_DIR / "camp-scene"
    entry = (target / "meadow-camp-entry.js").read_text()
    old_entry_digest = sha256(target / "meadow-camp-entry.js")
    for old, new in substitutions.items():
        entry = entry.replace(old, new)
    changed["meadow-camp-entry.js"] = entry.encode()
    html = (target / "index.html").read_text().replace(
        old_entry_digest[:16], hashlib.sha256(entry.encode()).hexdigest()[:16])
    changed["index.html"] = html.encode()
    for old in renamed:
        for suffix in ("", ".br", ".gz"):
            (target / (old + suffix)).unlink(missing_ok=True)
    for name, content in changed.items():
        (target / name).write_bytes(content)
        (target / (name + ".gz")).write_bytes(gzip.compress(content, mtime=0))
        (target / (name + ".br")).write_bytes(brotli.compress(content))
    manifest = json.loads((output / MANIFEST).read_text())
    manifest.update(release_id=release_id, files={
        p.relative_to(output / RELEASE_DIR).as_posix(): sha256(p)
        for p in (output / RELEASE_DIR).rglob("*") if p.is_file()
    })
    (output / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    descriptor.update(release_id=release_id, manifest_sha256=sha256(output / MANIFEST))
    (output / DESCRIPTOR).write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n")
    result = sha256(output / DESCRIPTOR)
    final = load_release(output, release_id, result)
    verify_scene(output / RELEASE_DIR, final.scene_files)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-descriptor-sha256", required=True)
    args = parser.parse_args()
    print(build(args.private_root, args.output, args.release_id, args.expected_descriptor_sha256))
