"""Try bounded stronger lossless RSCC packing, preserving every decoded byte.

No mesh simplification or scene saving. Terrain is excluded so far-sward's
terrain SHA binding and AO signatures stay exact. This optimizes transfer bytes,
not shader compilation. Only NEW artifacts below startup-v126/dense-scenes.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

from build_web_quality import write_pack
from inspect_web_pack import read_pack
from repack_web_cache import CACHE_ENTRIES, _pack, _unpack


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v126/dense-scenes"
BASE_SHA = "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"
PROFILES = ((262144, 19), (1048576, 19), (1048576, 22))


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def size(blob):
    return {"bytes": len(blob), "gzipBytes": len(gzip.compress(blob, compresslevel=9, mtime=0)), "sha256": sha(blob)}


def build(source, output):
    source = source.resolve(strict=True)
    output = output.resolve()
    if output.exists() or not output.is_relative_to(SCOPE) or output == SCOPE or SCOPE.resolve() != SCOPE:
        raise ValueError("Use a NEW child of the owned dense-scenes directory")
    before_pack = source.read_bytes()
    if sha(before_pack) != BASE_SHA:
        raise ValueError("Only the frozen v125 combined pack is eligible")
    inventory = read_pack(source)
    before_entries = {row["path"]: before_pack[row["offset"]:row["offset"] + row["bytes"]]
                      for row in inventory["entries"]}
    if len(before_entries) != 184 or not CACHE_ENTRIES.issubset(before_entries):
        raise ValueError("Unexpected source inventory")
    output.mkdir(parents=True)
    replacements, records = {}, []
    for name in sorted(CACHE_ENTRIES):
        before = before_entries[name]
        raw = _unpack(before)
        best, best_size = before, size(before)
        trials = []
        for block, level in PROFILES:
            started = time.perf_counter()
            candidate = _pack(raw, block, level)
            encode_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            decoded = _unpack(candidate)
            decode_ms = (time.perf_counter() - started) * 1000
            if decoded != raw:
                raise ValueError("Lossless RSCC roundtrip mismatch")
            candidate_size = size(candidate)
            trials.append({"blockBytes": block, "zstdLevel": level, **candidate_size,
                           "encodeMs": round(encode_ms, 2), "pythonDecodeMs": round(decode_ms, 2)})
            if candidate_size["gzipBytes"] < best_size["gzipBytes"]:
                best, best_size = candidate, candidate_size
        record = {"path": name, "before": size(before), "after": best_size,
                  "decodedSha256": sha(raw), "decodedBytes": len(raw), "decodedBytesExact": True,
                  "trials": trials}
        if best != before:
            path = output / Path(name).name
            path.write_bytes(best)
            record["file"] = str(path)
            replacements[name] = best
        records.append(record)
        print(json.dumps({"entry": name, "beforeGzip": record["before"]["gzipBytes"],
                          "afterGzip": best_size["gzipBytes"]}), flush=True)
    destination = output / "index-lite.pck"
    write_pack(source, inventory, destination, replacements)
    after_blob = destination.read_bytes()
    after_inventory = read_pack(destination)
    after_entries = {row["path"]: after_blob[row["offset"]:row["offset"] + row["bytes"]]
                     for row in after_inventory["entries"]}
    if before_entries.keys() != after_entries.keys():
        raise ValueError("Resource inventory changed")
    for name, blob in before_entries.items():
        actual = after_entries[name]
        if actual != replacements.get(name, blob):
            raise ValueError(f"Unexpected resource mutation: {name}")
        if name in replacements and _unpack(blob) != _unpack(actual):
            raise ValueError(f"Decoded resource mutation: {name}")
    if source.read_bytes() != before_pack:
        raise ValueError("Source pack changed during build")
    proof = {"schemaVersion": 1, "profile": "lossless-scene-containers-v126", "source": str(source),
             "sourceSha256": BASE_SHA, "before": size(before_pack), "after": size(after_blob),
             "entries": 184, "changedContainers": len(replacements),
             "unchangedEntries": 184 - len(replacements), "allDecodedResourcesExact": True,
             "terrainWaterScriptsShadersTexturesExact": True, "changes": records,
             "note": "Offline packing and Python decode timings; not a Web/Godot startup benchmark or visual acceptance."}
    (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    manifest = {"sourceSha256": BASE_SHA, "replacements": [
        {"path": row["path"], "file": row["file"], "beforeSha256": row["before"]["sha256"],
         "afterSha256": row["after"]["sha256"], "decodedSha256": row["decodedSha256"]}
        for row in records if "file" in row]}
    (output / "pack-replacements.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in proof.items() if key != "changes"}, indent=2))
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)
