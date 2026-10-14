"""Read-only, pinned dense-scenes candidate proof; no builder/native execution.

Independently parses RSCC block tables and compares decoded bytes. Only the
existing read-only PCK directory/MD5 reader and standard zstandard codec are reused.
Run: E:/Anaconda3/python.exe -B godot/tools/test_dense_scene_containers_v126.py
"""
import gzip
import hashlib
import json
from pathlib import Path
import struct

import zstandard as zstd

from inspect_web_pack import read_pack


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts/v125/index-lite.pck"
CANDIDATE = ROOT / "artifacts/startup-v126/dense-scenes/candidate-01/index-lite.pck"
SOURCE_SHA = "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"
CANDIDATE_SHA = "1486269c29086c476a18550d6b2baf59be970cb1ca7a323899f9c4a2f945210c"
ALLOWED = frozenset({"assets/baked/v113/far-sward.scn", "assets/baked/v77/brush.scn",
                     "assets/baked/v77/detail.scn", "assets/baked/v77/foothill.scn",
                     "assets/baked/v77/riverbank.scn"})
MAX_BLOCK = 1024 * 1024
MAX_RAW = 128 * 1024 * 1024  # Bounded to these five reviewed resources.


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def metrics(blob):
    return {"bytes": len(blob), "gzipBytes": len(gzip.compress(blob, compresslevel=9, mtime=0)),
            "sha256": sha(blob)}


def decode_rscc(blob):
    require(len(blob) >= 24 and blob[:4] == blob[-4:] == b"RSCC", "RSCC magic/trailer mismatch")
    mode, block_bytes, raw_bytes = struct.unpack_from("<III", blob, 4)
    require(mode == 2, "Expected Godot MODE_ZSTD=2")
    require(4096 <= block_bytes <= MAX_BLOCK and 0 < raw_bytes <= MAX_RAW, "Unbounded resource")
    block_count = raw_bytes // block_bytes + 1  # Same table convention as Godot, including empty tail.
    table_end = 16 + 4 * block_count
    require(table_end <= len(blob) - 4, "Truncated RSCC block table")
    lengths = struct.unpack_from(f"<{block_count}I", blob, 16)
    require(table_end + sum(lengths) == len(blob) - 4, "Compressed block extents disagree with trailer")
    chunks, cursor, windows = [], table_end, []
    decoder = zstd.ZstdDecompressor()
    for index, compressed_bytes in enumerate(lengths):
        expected = block_bytes if index < block_count - 1 else raw_bytes % block_bytes
        frame = blob[cursor:cursor + compressed_bytes]
        cursor += compressed_bytes
        if frame:
            parameters = zstd.get_frame_parameters(frame)
            require(parameters.dict_id == 0, "Unexpected external Zstd dictionary")
            require(parameters.content_size == expected, "Frame content size differs from RSCC block")
            require(parameters.window_size <= block_bytes, "Frame window exceeds bounded block")
            windows.append(parameters.window_size)
            chunk = decoder.decompress(frame, max_output_size=max(expected, 1), allow_extra_data=False)
        else:
            require(expected == 0, "Missing nonempty frame")
            chunk = b""
        require(len(chunk) == expected, "Decoded block size mismatch")
        chunks.append(chunk)
    raw = b"".join(chunks)
    require(len(raw) == raw_bytes, "Decoded resource length mismatch")
    return raw, {"mode": mode, "blockBytes": block_bytes, "blockCount": block_count,
                 "decodedBytes": raw_bytes, "decodedSha256": sha(raw),
                 "tailBytes": raw_bytes % block_bytes,
                 "maxCompressedBlockBytes": max(lengths), "maxWindowBytes": max(windows, default=0)}


def audit():
    source_blob, candidate_blob = SOURCE.read_bytes(), CANDIDATE.read_bytes()
    require(sha(source_blob) == SOURCE_SHA and sha(candidate_blob) == CANDIDATE_SHA, "Pack pin mismatch")
    original, candidate = read_pack(SOURCE), read_pack(CANDIDATE)  # Checks every directory MD5 and bound.
    require(original["version"] == candidate["version"] and original["engine"] == candidate["engine"],
            "PCK/engine format changed")
    require(len(original["entries"]) == len(candidate["entries"]) == 184, "Inventory size changed")
    require([r["path"] for r in original["entries"]] == [r["path"] for r in candidate["entries"]],
            "Inventory order/names changed")
    def contents(pack, blob):
        return {row["path"]: blob[row["offset"]:row["offset"] + row["bytes"]] for row in pack["entries"]}
    before, after = contents(original, source_blob), contents(candidate, candidate_blob)
    changed = {name for name in before if before[name] != after[name]}
    require(changed == ALLOWED, "Change set differs from explicit five-container allowlist")
    proof_path, manifest_path = CANDIDATE.with_name("proof.json"), CANDIDATE.with_name("pack-replacements.json")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(proof["schemaVersion"] == 1 and proof["profile"] == "lossless-scene-containers-v126", "Proof schema")
    require(proof["sourceSha256"] == manifest["sourceSha256"] == SOURCE_SHA, "Manifest source pin")
    require(Path(proof["source"]).resolve() == SOURCE.resolve(), "Unexpected source path")
    records = {row["path"]: row for row in proof["changes"]}
    replacements = {row["path"]: row for row in manifest["replacements"]}
    require(len(records) == len(proof["changes"]) == len(replacements) == len(manifest["replacements"]) == 5,
            "Duplicate/missing proof records")
    require(records.keys() == replacements.keys() == ALLOWED, "Manifest change set")
    details = []
    for name in sorted(changed):
        raw_before, before_info = decode_rscc(before[name])
        raw_after, after_info = decode_rscc(after[name])
        require(raw_before == raw_after, f"Decoded byte mismatch: {name}")
        row, replacement = records[name], replacements[name]
        before_size, after_size = metrics(before[name]), metrics(after[name])
        require(row["before"] == before_size and row["after"] == after_size, f"Container size/hash proof: {name}")
        require(row["decodedBytes"] == len(raw_before) and row["decodedBytesExact"] is True and
                row["decodedSha256"] == replacement["decodedSha256"] == sha(raw_before), f"Decoded proof: {name}")
        require(replacement["beforeSha256"] == sha(before[name]) and replacement["afterSha256"] == sha(after[name]),
                f"Replacement pin: {name}")
        file = Path(replacement["file"]).resolve(strict=True)
        require(file.is_relative_to(CANDIDATE.parent.resolve()) and file == Path(row["file"]).resolve(),
                f"Unscoped replacement payload: {name}")
        require(file.read_bytes() == after[name], f"Replacement file != actual PCK bytes: {name}")
        selected = [trial for trial in row["trials"] if trial["sha256"] == sha(after[name])]
        require(len(selected) == 1 and selected[0]["blockBytes"] == after_info["blockBytes"], "Selected trial")
        require(after_size["gzipBytes"] == min([before_size["gzipBytes"]] +
                                               [trial["gzipBytes"] for trial in row["trials"]]), "Selected gzip winner")
        details.append({"path": name, "before": before_size, "after": after_size,
                        "beforeContainer": before_info, "afterContainer": after_info,
                        "decodedBytesExact": True, "replacementFileExact": True})
    before_size, after_size = metrics(source_blob), metrics(candidate_blob)
    require(proof["before"] == before_size and proof["after"] == after_size, "Whole-pack byte/gzip/hash proof")
    require(proof["entries"] == 184 and proof["changedContainers"] == 5 and proof["unchangedEntries"] == 179,
            "Proof counts differ from actual pack")
    require(proof["allDecodedResourcesExact"] is True and proof["terrainWaterScriptsShadersTexturesExact"] is True,
            "Proof claims inconsistent")
    require(SOURCE.read_bytes() == source_blob and CANDIDATE.read_bytes() == candidate_blob, "Input changed during audit")
    terrain = [name for name in before if "terrain" in name.lower()]
    require(terrain and all(before[name] == after[name] for name in terrain), "Terrain identity")
    return {"schemaVersion": 1, "status": "PASS_EXACT_LOSSLESS_CONTAINER_PROOF",
            "source": str(SOURCE), "candidate": str(CANDIDATE), "before": before_size, "after": after_size,
            "entries": 184, "allEntryMd5Checked": True, "unchangedEntries": 179, "changedContainers": 5,
            "decodedResourcesExact": True, "decodedMeshTriangleAlphaMetadataExact": True,
            "terrainEntries": terrain, "terrainExact": True, "details": details,
            "rawBytesSaved": before_size["bytes"] - after_size["bytes"],
            "gzip9BytesSaved": before_size["gzipBytes"] - after_size["gzipBytes"],
            "gzipPolicy": "Offline Python gzip.compress(level=9, mtime=0), same codec/settings on both packs; not server transfer proof",
            "proofSha256": sha(proof_path.read_bytes()), "manifestSha256": sha(manifest_path.read_bytes()),
            "checkerSha256": sha(Path(__file__).read_bytes()), "zstandardVersion": zstd.__version__,
            "nativeRuns": 0, "builds": 0, "browserActions": 0,
            "startupPerformanceAccepted": False, "nativeCompatibilityExecuted": False,
            "limit": "Byte/format identity only. No Python decode timings are reported as Godot/Web startup or memory performance."}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
