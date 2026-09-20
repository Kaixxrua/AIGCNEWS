from __future__ import annotations

import hashlib
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[2] / "scripts/release"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("preserve_contact_quality", SCRIPTS / "preserve_contact_quality.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def pack(version: int) -> bytes:
    entries = {quality.GOVERNOR: b"extends Node\n" + b"# old adaptive governor\n" * 20,
               "camp_presentation/art.png": b"unchanged artwork"}
    directory = bytearray(struct.pack("<I", len(entries)))
    header = bytearray(96)
    struct.pack_into("<4sIIIIIQ", header, 0, b"GDPC", version, 4, 7, 2, 0, 0)
    if version >= 3:
        struct.pack_into("<Q", header, 32, 96 + sum(map(len, entries.values())) if version == 4 else 96)
    start = 100 + sum(4 + len(name.encode()) + 1 + 36 for name in entries)
    if version == 4:
        start = 96
    payload = bytearray()
    for name, content in entries.items():
        encoded = name.encode() + b"\0"
        directory += struct.pack("<I", len(encoded)) + encoded
        directory += struct.pack("<QQ", start + len(payload), len(content))
        directory += hashlib.md5(content).digest() + struct.pack("<I", 0)
        payload += content
    return bytes(header + payload + directory if version == 4 else header + directory + payload)


@pytest.mark.parametrize("version", [2, 3, 4])
def test_disables_only_governor_and_preserves_payload_layout(version):
    original = pack(version)
    result = quality.replace_entries(original, {quality.GOVERNOR: quality.DISABLED})
    assert len(result) == len(original)
    before, after = quality.pack_entries(original), quality.pack_entries(result)
    assert before == after
    for name, (offset, size, _) in after.items():
        if name == quality.GOVERNOR:
            assert result[offset:offset + size].rstrip() == quality.DISABLED.rstrip()
        else:
            assert result[offset:offset + size] == original[offset:offset + size]


def test_rejects_corrupt_art_instead_of_repacking_it():
    damaged = pack(4).replace(b"unchanged artwork", b"corrupted artwork")
    with pytest.raises(quality.StageError, match="checksum"):
        quality.replace_entries(damaged, {quality.GOVERNOR: quality.DISABLED})


def test_rejects_missing_governor_and_oversized_replacement():
    with pytest.raises(quality.StageError, match="missing"):
        quality.replace_entries(pack(4), {"missing.gd": quality.DISABLED})
    with pytest.raises(quality.StageError, match="size"):
        quality.replace_entries(pack(4), {quality.GOVERNOR: b"x" * 10000})


@pytest.mark.parametrize("blob", [b"", b"GDPC", pack(4)[:100], pack(4)[:150]])
def test_rejects_truncated_packs(blob):
    with pytest.raises(quality.StageError):
        quality.replace_entries(blob, {quality.GOVERNOR: quality.DISABLED})
