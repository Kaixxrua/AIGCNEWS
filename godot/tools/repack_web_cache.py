"""Lossless RSCC transport repack; never load/resave Godot resources.

PCK processor: repack_entry(entry_name, blob) enforces CACHE_ENTRIES.
repack_bytes(blob) is the path-agnostic codec; its caller must apply that allowlist.
CLI: INPUT [--dry-run | --output NEW_COPY]. Default: dry-run.
Tests: E:/Anaconda3/python.exe -B godot/tools/repack_web_cache.py --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import zstandard as zstd

BLOCK_SIZE = 262144
LEVEL = 9
MAGIC = b"RSCC"
MODE_ZSTD = 2
HEADER = struct.Struct("<4sIII")
MAX_RAW_BYTES = 512 * 1024 * 1024
GODOT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ENTRIES = frozenset({
    "assets/baked/v77/detail.scn",
    "assets/baked/v77/brush.scn",
    "assets/baked/v77/foothill.scn",
    "assets/baked/v77/riverbank.scn",
    "assets/baked/v113/far-sward.scn",
})


def _entry_name(name: str) -> str:
    name = name.removeprefix("res://")
    if name not in CACHE_ENTRIES:
        raise ValueError(f"Entry outside five-cache allowlist (terrain excluded): {name}")
    return name


def _unpack(blob: bytes) -> bytes:
    if len(blob) < 24 or blob[:4] != MAGIC or blob[-4:] != MAGIC:
        raise ValueError("Invalid RSCC header/trailer")
    _, mode, block_size, raw_size = HEADER.unpack_from(blob)
    if mode != MODE_ZSTD or not 4096 <= block_size <= 1048576:
        raise ValueError("Unsupported RSCC codec/block size")
    if raw_size > MAX_RAW_BYTES:
        raise ValueError("RSCC uncompressed size exceeds safety limit")
    # Godot includes a final empty block when the size is an exact multiple.
    count = raw_size // block_size + 1
    cursor = HEADER.size + count * 4
    end = len(blob) - 4
    if cursor > end:
        raise ValueError("Truncated RSCC block table")
    sizes = struct.unpack_from(f"<{count}I", blob, HEADER.size)
    chunks = []
    decoder = zstd.ZstdDecompressor()
    for index, size in enumerate(sizes):
        expected = min(block_size, raw_size - index * block_size)
        if cursor + size > end or (expected and not size):
            raise ValueError("Truncated/empty RSCC block")
        frame = blob[cursor:cursor + size]
        cursor += size
        try:
            if frame:
                declared = zstd.frame_content_size(frame)
                if declared not in (expected, zstd.CONTENTSIZE_UNKNOWN):
                    raise ValueError("ZSTD frame size disagrees with RSCC table")
                decoded = decoder.decompress(
                    frame, max_output_size=max(expected, 1), allow_extra_data=False
                )
            else:
                decoded = b""
        except zstd.ZstdError as exc:
            raise ValueError(f"Invalid ZSTD block {index}: {exc}") from exc
        if len(decoded) != expected:
            raise ValueError("Decompressed RSCC block length mismatch")
        chunks.append(decoded)
    if cursor != end:
        raise ValueError("Unexpected data before RSCC trailer")
    raw = b"".join(chunks)
    if len(raw) != raw_size:
        raise ValueError("Decompressed RSCC total length mismatch")
    return raw


def _pack(raw: bytes, block_size: int = BLOCK_SIZE, level: int = LEVEL) -> bytes:
    compressor = zstd.ZstdCompressor(level=level)
    chunks = [compressor.compress(raw[i:i + block_size])
              for i in range(0, len(raw) + 1, block_size)]
    table = struct.pack(f"<{len(chunks)}I", *(len(chunk) for chunk in chunks))
    return (HEADER.pack(MAGIC, MODE_ZSTD, block_size, len(raw))
            + table + b"".join(chunks) + MAGIC)


def repack_bytes(blob: bytes) -> bytes:
    """Return 256KiB/level-9 RSCC, verified against every original payload byte.

    No metadata/indices/resource offsets are parsed, edited or regenerated.
    This function performs no filesystem I/O and cannot identify an entry path.
    """
    raw = _unpack(blob)
    result = _pack(raw)
    if _unpack(result) != raw:
        raise ValueError("Lossless roundtrip verification failed")
    return result


def repack_entry(entry_name: str, blob: bytes) -> bytes:
    """Recommended PCK entry point: reject terrain and all unrelated entries."""
    _entry_name(entry_name)
    return repack_bytes(blob)


def _output_path(source: Path, output: Path) -> Path:
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists (including symlinks); refusing overwrite")
    output = output.resolve()
    if output == source.resolve():
        raise ValueError("Output must not be the input")
    if output.is_relative_to((GODOT_ROOT / "assets").resolve()):
        raise ValueError("Writing anywhere in godot/assets is forbidden")
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; refusing overwrite")
    if not output.parent.is_dir():
        raise ValueError("Output parent must already exist")
    return output


def _self_test() -> bool:
    import unittest

    class RepackTests(unittest.TestCase):
        def test_roundtrip_boundaries_and_idempotence(self):
            for length in (0, 1, 4096, BLOCK_SIZE, BLOCK_SIZE + 17):
                raw = (bytes(range(256)) * (length // 256 + 1))[:length]
                before = _pack(raw, 4096, 3)
                after = repack_bytes(before)
                self.assertEqual(_unpack(after), raw)
                self.assertEqual(repack_bytes(after), after)

        def test_invalid_container_fails_closed(self):
            valid = _pack(b"source payload" * 100, 4096, 3)
            bad_codec = bytearray(valid)
            struct.pack_into("<I", bad_codec, 4, 0)
            bad_size = bytearray(valid)
            struct.pack_into("<I", bad_size, 16, len(valid))
            for broken in (b"", valid[:-1], b"XXXX" + valid[4:],
                           valid[:-4] + b"extra" + MAGIC, bytes(bad_codec), bytes(bad_size)):
                with self.assertRaises(ValueError):
                    repack_bytes(broken)

        def test_scope_and_output_guards(self):
            for forbidden in ("assets/baked/v77/terrain.scn", "other.scn",
                              "assets/baked/v77/../v77/detail.scn"):
                with self.assertRaises(ValueError):
                    repack_entry(forbidden, b"")
            source = GODOT_ROOT / "assets/baked/v77/detail.scn"
            for output in (source, Path(__file__), GODOT_ROOT / "assets/new-copy.scn"):
                with self.assertRaises(ValueError):
                    _output_path(source, output)

        def test_current_five_caches_in_memory(self):
            saved = 0
            terrain = GODOT_ROOT / "assets/baked/v77/terrain.scn"
            terrain_hash = hashlib.sha256(terrain.read_bytes()).digest()
            for entry in sorted(CACHE_ENTRIES):
                source = GODOT_ROOT / entry
                original = source.read_bytes()
                candidate = repack_entry("res://" + entry, original)
                self.assertEqual(_unpack(candidate), _unpack(original))
                self.assertEqual(source.read_bytes(), original)
                saved += len(original) - len(candidate)
                print(json.dumps({"entry": entry, "before": len(original),
                                  "after": len(candidate), "saved": len(original) - len(candidate),
                                  "raw_equal": True, "source_unchanged": True}), flush=True)
            self.assertEqual(hashlib.sha256(terrain.read_bytes()).digest(), terrain_hash)
            print(f"CACHE_REPACK_TEST_TOTAL saved_bytes={saved}; no files written", flush=True)

    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RepackTests)
    ).wasSuccessful()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="One of the five canonical project caches")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output", type=Path, help="Explicit NEW copy outside godot/assets")
    mode.add_argument("--dry-run", action="store_true", help="Memory only (also the default)")
    parser.add_argument("--self-test", action="store_true", help="Unittests plus current-cache memory roundtrips")
    args = parser.parse_args(argv)
    if args.self_test:
        if args.input or args.output or args.dry_run:
            parser.error("--self-test must be used alone")
        return 0 if _self_test() else 1
    if args.input is None:
        parser.error("INPUT is required unless --self-test is selected")
    try:
        source = args.input.resolve(strict=True)
        inputs = {(GODOT_ROOT / name).resolve(): name for name in CACHE_ENTRIES}
        if source not in inputs:
            raise ValueError("CLI input must be one of the five canonical non-terrain caches")
        output = _output_path(source, args.output) if args.output else None
        original = source.read_bytes()
        result = repack_entry(inputs[source], original)
        if source.read_bytes() != original:
            raise ValueError("Input changed during repack; refusing output")
        if output is not None:
            with output.open("xb") as file:  # Exclusive creation closes overwrite races.
                file.write(result)
            if output.read_bytes() != result:
                raise OSError("Output readback mismatch; discard this candidate")
        print(json.dumps({"entry": inputs[source], "input_bytes": len(original),
                          "output_bytes": len(result), "saved_bytes": len(original) - len(result),
                          "sha256": hashlib.sha256(result).hexdigest(), "raw_equal": True,
                          "mode": "copy" if output else "dry-run", "output": str(output) if output else None}))
        return 0
    except (OSError, ValueError, zstd.ZstdError) as exc:
        print(f"CACHE_REPACK_FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
