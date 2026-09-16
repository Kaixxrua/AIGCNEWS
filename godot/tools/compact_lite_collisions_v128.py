"""Frozen-v127 collision-storage experiment; no scene saving or render edits.

One guarded 1/4096-unit face-storage candidate plus an exact indexed-codec
benchmark. Outputs only NEW artifacts/startup-v128/collisions children. The
terrain hash changes: retain its far-sward metadata binding on integration.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time

import numpy as np
import zstandard as zstd

from build_web_quality import write_pack
from inspect_web_pack import read_pack
from repack_web_cache import _unpack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v128/collisions"
BASE = ROOT / "artifacts/v127/index-lite.pck"
BASE_SHA = "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"
GODOT = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe"
TARGETS = {
    "assets/baked/v77/terrain.scn": 552000,
    "assets/baked/v77/detail.scn": 425853,
    "assets/baked/v77/riverbank.scn": 28152,
}
STEP = 1.0 / 4096


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def scoped(path):
    resolved = Path(path).resolve()
    require(SCOPE.resolve() == SCOPE and resolved.is_relative_to(SCOPE) and resolved != SCOPE,
            "Output must stay in the collision artifact scope")
    return resolved


def write_new(path, data):
    path = scoped(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(data)
    require(path.read_bytes() == data, "Artifact readback")
    return path


def write_json(path, value):
    return write_new(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def stage(output, label):
    for number in range(1, 10):
        path = scoped(output / f"{label}-{number:02d}")
        if not path.exists():
            path.mkdir(parents=True)
            return path
    raise ValueError("Bounded native-stage retry limit")


def run_engine(output, files=(), codecs=(), label="inspect"):
    directory = stage(output, label)
    project = directory / "sandbox"
    write_new(project / "project.godot", b'config_version=5\n[application]\nconfig/name="OfflineCollisionV128"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[shader_globals]\nmeadow_clock={"type":"float","value":0.0}\nmeadow_night={"type":"float","value":0.0}\n')
    request_path = write_json(directory / "request.json", dict(
        output=str(directory), allowed_root=str(SCOPE), reference_pack=str(BASE), files=list(files), codecs=list(codecs)))
    environment = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        isolated = project / key.lower()
        isolated.mkdir()
        environment[key] = str(isolated)
    command = [str(GODOT), "--headless", "--path", str(project), "--script", str(Path(__file__).with_suffix(".gd")),
               "--log-file", str(directory / "engine.log"), "--", "--request", str(request_path)]
    print(f"NATIVE {label}: {directory.name}", flush=True)
    started = time.perf_counter()
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=120, env=environment,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    log = process.stdout + process.stderr
    write_new(directory / "process.log", log.encode())
    require(process.returncode == 0 and "COLLISION_V128_OFFLINE: PASS" in log and "ERROR:" not in log,
            f"Native inspection failed: {directory / 'process.log'}\n{log[-4000:]}")
    result = json.loads((directory / "inspection.json").read_text())
    require(result["failures"] == 0, "Native validation failed")
    result["stageSeconds"] = time.perf_counter() - started
    return result


def unique_corners(data):
    require(len(data) > 0 and len(data) % 36 == 0, "Complete float32 triangles required")
    values = np.frombuffer(data, dtype="<f4").reshape(-1, 3)
    require(np.isfinite(values).all(), "Finite collision coordinates required")
    keys = np.frombuffer(data, dtype="V12")
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    order = np.argsort(first)
    remap = np.empty(len(order), dtype=np.uint32)
    remap[order] = np.arange(len(order), dtype=np.uint32)
    indices = remap[inverse].astype("<u4")
    vertices = values[first[order]].copy()
    require(vertices[indices].tobytes() == data, "All exact indexed corner bits roundtrip")
    return vertices, indices


def indexed_codec(data):
    vertices, indices = unique_corners(data)
    raw = vertices.tobytes() + indices.tobytes()
    frame = zstd.ZstdCompressor(level=19).compress(raw)
    blob = struct.pack("<4sIII", b"CLI1", len(indices), len(vertices), len(raw)) + frame
    require(zstd.ZstdDecompressor().decompress(blob[16:]) == raw, "Indexed codec frame roundtrip")
    return blob, dict(corners=len(indices), uniqueVertices=len(vertices), rawFaceBytes=len(data),
                      indexedRawBytes=len(raw), codecBytes=len(blob), rawFaceZstd19Bytes=len(zstd.ZstdCompressor(level=19).compress(data)),
                      exactAllCornerBits=True)


def triangle_metrics(original, candidate):
    a = original.astype(np.float64).reshape(-1, 3, 3)
    b = candidate.astype(np.float64).reshape(-1, 3, 3)
    an = np.cross(a[:, 1] - a[:, 0], a[:, 2] - a[:, 0])
    bn = np.cross(b[:, 1] - b[:, 0], b[:, 2] - b[:, 0])
    aa = np.linalg.norm(an, axis=1)
    ba = np.linalg.norm(bn, axis=1)
    nonzero = aa > 0
    ratio = np.divide(ba, aa, out=np.ones_like(aa), where=nonzero)
    cosine = np.divide(np.einsum("ij,ij->i", an, bn), aa * ba,
                       out=np.ones_like(aa), where=nonzero & (ba > 0))
    angles = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    changed = np.any(a != b, axis=(1, 2))
    bad = ((nonzero & ((ba == 0) | (ratio < 0.999) | (ratio > 1.001) | (angles > 0.1)))
           | (~nonzero & changed))
    return bad, dict(originalDegenerateTriangles=int((~nonzero).sum()),
                     newDegenerateTriangles=int((nonzero & (ba == 0)).sum()),
                     windingReversals=int((nonzero & (cosine <= 0)).sum()),
                     maxNormalDegrees=float(angles[nonzero].max(initial=0)),
                     minAreaRatio=float(ratio.min(initial=1)), maxAreaRatio=float(ratio.max(initial=1)))


def quantize_faces(data):
    vertices, indices = unique_corners(data)
    quantized = (np.rint(vertices.astype(np.float64) / STEP) * STEP).astype("<f4")
    # Retain exact signed zero and all originally grid-aligned bit patterns.
    same = vertices == quantized
    quantized[same] = vertices[same]
    original = vertices[indices]
    reverted = np.zeros(len(vertices), dtype=bool)
    for iteration in range(16):
        candidate = quantized[indices]
        bad, metrics = triangle_metrics(original, candidate)
        if not bad.any():
            break
        restore = np.unique(indices.reshape(-1, 3)[bad])
        quantized[restore] = vertices[restore]
        reverted[restore] = True
    else:
        raise ValueError("Conservative triangle guard did not converge in 16 passes")
    difference = candidate.astype(np.float64) - original.astype(np.float64)
    max_axis = float(np.abs(difference).max(initial=0))
    require(max_axis <= STEP / 2, "Grid error bound")
    require(not bad.any(), "No degenerate, reversed or excessive-normal/area-change triangles")
    result = candidate.tobytes()
    return result, dict(stepUnits=STEP, maxAxisErrorUnits=max_axis,
                        maxPositionErrorUnits=float(np.linalg.norm(difference, axis=1).max(initial=0)),
                        changedCorners=int(np.any(candidate.view("<u4") != original.view("<u4"), axis=1).sum()),
                        uniqueVertices=len(vertices), revertedUniqueVertices=int(reverted.sum()),
                        guardPasses=iteration + 1, triangles=len(indices) // 3, cornerOrderPreserved=True,
                        **metrics)


def patch_faces(raw, before, after):
    require(len(before) == len(after) and len(before) % 36 == 0, "Same-length complete face array")
    start = raw.find(before)
    require(start >= 8 and raw.find(before, start + 1) == -1, "Exactly one pinned face-byte span")
    require(raw[start - 8:start] == struct.pack("<II", 35, len(before) // 12),
            "Godot4.7.2 PackedVector3Array type/count guard")
    result = raw[:start] + after + raw[start + len(before):]
    require(len(result) == len(raw) and result[:start] == raw[:start]
            and result[start + len(before):] == raw[start + len(before):], "Only face span changed")
    return result, start


def patch_container(blob, original, candidate, start, size):
    """Keep block layout AND every nonintersecting compressed block byte-exact."""
    magic, mode, block_size, raw_size = struct.unpack_from("<4sIII", blob)
    require(magic == b"RSCC" and mode == 2 and raw_size == len(candidate) == len(original), "Pinned RSCC layout")
    count = raw_size // block_size + 1
    sizes = struct.unpack_from(f"<{count}I", blob, 16)
    cursor = 16 + 4 * count
    frames, touched = [], []
    compressor = zstd.ZstdCompressor(level=19)
    for index, length in enumerate(sizes):
        frame = blob[cursor:cursor + length]
        cursor += length
        low, high = index * block_size, min((index + 1) * block_size, raw_size)
        if low < start + size and high > start:
            if candidate[low:high] != original[low:high]:
                encoded = compressor.compress(candidate[low:high])
                frames.append(encoded)
                touched.append(index)
            else:
                frames.append(frame)
        else:
            require(candidate[low:high] == original[low:high], "No decoded changes outside collision blocks")
            frames.append(frame)
    require(cursor == len(blob) - 4, "RSCC exact block extent")
    result = blob[:16] + struct.pack(f"<{count}I", *(len(frame) for frame in frames)) + b"".join(frames) + blob[-4:]
    require(_unpack(result) == candidate, "Patched RSCC exact roundtrip")
    return result, dict(blockBytes=block_size, blocks=count, rewrittenBlocks=len(touched),
                        untouchedCompressedBlocksExact=True, zstdLevelForChangedBlocks=19)


def prepare(output):
    source = BASE.read_bytes()
    require(sha(source) == BASE_SHA, "Only frozen actual v127 lite pack allowed")
    inventory = read_pack(BASE, verify=True)
    require(len(inventory["entries"]) == 184, "Pinned full-scene resource inventory")
    output = scoped(output)
    require(not output.exists(), "Fresh output required")
    output.mkdir(parents=True)
    originals, files = {}, []
    for entry in inventory["entries"]:
        name = entry["path"]
        if name not in TARGETS:
            continue
        blob = source[entry["offset"]:entry["offset"] + entry["bytes"]]
        originals[name] = blob
        path = write_new(output / "originals" / Path(name).name, blob)
        files.append(dict(resource=name, path=str(path), sha256=sha(blob)))
    require(set(originals) == set(TARGETS), "All and only three cache scenes")
    native = run_engine(output, files)
    write_json(output / "original-inspection.json", native)
    return source, inventory, originals, native


def build(output, resume=False):
    output = scoped(output)
    if resume:
        source = BASE.read_bytes()
        require(sha(source) == BASE_SHA, "Frozen v127 source hash")
        inventory = read_pack(BASE, verify=True)
        originals = {name: (output / "originals" / Path(name).name).read_bytes() for name in TARGETS}
        native = json.loads((output / "original-inspection.json").read_text())
        for entry in inventory["entries"]:
            if entry["path"] in originals:
                require(originals[entry["path"]] == source[entry["offset"]:entry["offset"] + entry["bytes"]], "Pinned resumed scene")
    else:
        source, inventory, originals, native = prepare(output)
    records, files, codecs, replacements = [], [], [], {}
    for name, count in TARGETS.items():
        scene = native["scenes"][name]
        require(len(scene["collisions"]) == 1, "One pinned collision per cache")
        node, record = next(iter(scene["collisions"].items()))
        before = Path(record["path"]).read_bytes()
        require(record["corners"] == count and record["bytes"] == len(before) == count * 12
                and sha(before) == record["sha256"], "Native corner dump count/hash")
        stem = Path(name).stem
        codec, codec_stats = indexed_codec(before)
        codec_path = write_new(output / "indexed-prototype" / f"{stem}.cli1", codec)
        codecs.append(dict(path=str(codec_path), corners=count, facesSha256=sha(before)))
        after, geometry_stats = quantize_faces(before)
        face_path = write_new(output / "quantized-faces" / f"{stem}.bin", after)
        raw = _unpack(originals[name])
        candidate_raw, start = patch_faces(raw, before, after)
        candidate, container_stats = patch_container(originals[name], raw, candidate_raw, start, len(before))
        path = write_new(output / "candidate-scenes" / f"{stem}.scn", candidate)
        files.append(dict(resource=name, path=str(path), sha256=sha(candidate)))
        replacements[name] = candidate
        row = dict(resource=name, node=node, corners=count, rawFaceBytes=len(before),
                   beforeSceneBytes=len(originals[name]), afterSceneBytes=len(candidate), savedSceneBytes=len(originals[name]) - len(candidate),
                   beforeDecodedSha256=sha(raw), afterDecodedSha256=sha(candidate_raw),
                   beforeSceneSha256=sha(originals[name]), afterSceneSha256=sha(candidate),
                   patch=dict(offset=start, bytes=len(before), beforeFacesPath=record["path"], beforeFacesSha256=sha(before),
                              afterFacesPath=str(face_path), afterFacesSha256=sha(after), prefixType=35, count=count,
                              allOtherDecodedResourceBytesExact=True),
                   indexedPrototype=codec_stats, quantization=geometry_stats, container=container_stats)
        records.append(row)
        print(json.dumps({"scene": stem, "corners": count, "faceRawBytes": len(before), "unique": codec_stats["uniqueVertices"],
                          "exactCodecBytes": len(codec), "sceneBytesSaved": row["savedSceneBytes"],
                          "maxPositionErrorUnits": geometry_stats["maxPositionErrorUnits"]}), flush=True)
    write_json(output / "collision-patches.json", dict(baseSha256=BASE_SHA, records=records))
    after_native = run_engine(output, files, codecs, "verify")
    proofs = {}
    for name in TARGETS:
        before_scene, after_scene = native["scenes"][name], after_native["scenes"][name]
        require(before_scene["tree"] == after_scene["tree"] and before_scene["bundle"] == after_scene["bundle"],
                f"All node/property/ref/material/render bytes exact: {name}")
        require(before_scene["collisions"].keys() == after_scene["collisions"].keys(), "Collision node paths exact")
        row = next(row for row in records if row["resource"] == name)
        for node, before_shape in before_scene["collisions"].items():
            after_shape = after_scene["collisions"][node]
            require(before_shape["properties"] == after_shape["properties"] and before_shape["corners"] == after_shape["corners"], "All collision constraints exact")
            require(after_shape["sha256"] == row["patch"]["afterFacesSha256"], "Native quantized corner bytes exact")
        proofs[name] = dict(allOtherNodePropertiesAndBundleExact=True, collisionConstraintsExact=True,
                            nativeCornerBytesMatch=True, renderMeshesMaterialsScriptsUnchanged=True)
    destination = output / "index-lite-collision-candidate.pck"
    write_pack(BASE, inventory, destination, replacements)
    packed = destination.read_bytes()
    after_inventory = read_pack(destination, verify=True)
    require([e["path"] for e in inventory["entries"]] == [e["path"] for e in after_inventory["entries"]], "Every resource and resource order preserved")
    exact = 0
    for old, new in zip(inventory["entries"], after_inventory["entries"]):
        a = source[old["offset"]:old["offset"] + old["bytes"]]
        b = packed[new["offset"]:new["offset"] + new["bytes"]]
        if old["path"] not in TARGETS:
            require(a == b, "Untargeted PCK entry byte-exact")
            exact += 1
    compressed = gzip.compress(packed, compresslevel=6, mtime=0)
    write_new(destination.with_suffix(".pck.gz"), compressed)
    before_gzip = len(gzip.compress(source, compresslevel=6, mtime=0))
    require(BASE.read_bytes() == source, "Frozen original PCK remains exact")
    report = dict(basePack=str(BASE), baseSha256=BASE_SHA, candidatePack=str(destination), candidateSha256=sha(packed),
                  beforeRawBytes=len(source), afterRawBytes=len(packed), beforeGzip6Bytes=before_gzip, afterGzip6Bytes=len(compressed),
                  rawSavedBytes=len(source) - len(packed), gzip6SavedBytes=before_gzip - len(compressed),
                  entries=184, untouchedEntriesExact=exact, changedEntries=3, collisions=records, nativeProofs=proofs,
                  nativeIndexedPrototypeTiming=after_native["codecs"], nativeOriginalInspectionSeconds=native["stageSeconds"],
                  nativeVerificationAndCodecSeconds=after_native["stageSeconds"], quantizedRuntimeExtraDecodeOperations=0,
                  exactIndexedPrototypeIntegrated=False, readyToStage=False,
                  integrationRequirement="Keep far-sward terrain_sha256 provenance aligned after the final terrain merge. Its runtime SHA check is conditional on the .gd source existing; v127 contains .gdc/.gd.remap only. Do not overwrite main render candidate with this standalone scene.",
                  limit="Offline headless isolated cache validation, not Web startup/walking or first-load performance proof.")
    write_json(output / "proof.json", report)
    print(json.dumps({key: report[key] for key in ("candidatePack", "afterRawBytes", "afterGzip6Bytes", "rawSavedBytes", "gzip6SavedBytes", "untouchedEntriesExact", "readyToStage")}), flush=True)
    return report


def summarize(output):
    """One transfer check at the existing preparer's Brotli quality; no staging."""
    import brotli

    output = scoped(output)
    report = json.loads((output / "proof.json").read_text())
    source = BASE.read_bytes()
    candidate = scoped(report["candidatePack"]).read_bytes()
    require(sha(source) == BASE_SHA and sha(candidate) == report["candidateSha256"], "Pinned comparison packs")
    before_br = brotli.compress(source, quality=6)
    after_br = brotli.compress(candidate, quality=6)
    published_br = BASE.with_suffix(".pck.br").read_bytes()
    require(brotli.decompress(published_br) == source, "Actual v127 Brotli decodes to pinned PCK")
    write_new(output / "index-lite-collision-candidate.pck.br", after_br)
    rows = []
    for row in report["collisions"]:
        name = Path(row["resource"]).name
        original = (output / "originals" / name).read_bytes()
        transformed = (output / "candidate-scenes" / name).read_bytes()
        require(sha(original) == row["beforeSceneSha256"] and sha(transformed) == row["afterSceneSha256"], "Pinned scene comparison")
        _, _, block, raw_size = struct.unpack_from("<4sIII", original)
        count = raw_size // block + 1
        sizes = struct.unpack_from(f"<{count}I", original, 16)
        low, high = row["patch"]["offset"], row["patch"]["offset"] + row["patch"]["bytes"]
        interior = sum(length for i, length in enumerate(sizes) if low <= i * block and min((i + 1) * block, raw_size) <= high)
        intersecting = sum(length for i, length in enumerate(sizes) if i * block < high and (i + 1) * block > low)
        codec = row["indexedPrototype"]
        rows.append(dict(resource=row["resource"], collisionOnlyBlockStoredBytes=interior,
                         collisionPlusBoundaryBlocksStoredBytes=intersecting,
                         boundaryWarning="Boundary blocks also hold noncollision bytes; these sums are not independently attributable transport savings.",
                         beforeSceneGzip6Bytes=len(gzip.compress(original, compresslevel=6, mtime=0)),
                         afterSceneGzip6Bytes=len(gzip.compress(transformed, compresslevel=6, mtime=0)),
                         exactCodec=codec,
                         decoderArrays=dict(compressedBytes=codec["codecBytes"], expandedIndexedBytes=codec["indexedRawBytes"],
                                            vertexTableBytes=codec["uniqueVertices"] * 12, indexArrayBytes=codec["corners"] * 4,
                                            finalFacesBytes=codec["rawFaceBytes"],
                                            excludes="PCK/cache, transient slices/copies, allocator and normal physics BVH memory")))
    result = dict(baseSha256=BASE_SHA, candidateSha256=report["candidateSha256"],
                  beforeActualBrotliBytes=len(published_br), beforeSameSettingsBrotliBytes=len(before_br),
                  afterBrotli6Bytes=len(after_br), brotli6SavedBytes=len(before_br) - len(after_br),
                  gzip6SavedBytes=report["gzip6SavedBytes"],
                  collisions=rows,
                  exactIndexedCodecBytes=sum(row["indexedPrototype"]["codecBytes"] for row in report["collisions"]),
                  standaloneOriginalFacesZstd19Bytes=sum(row["indexedPrototype"]["rawFaceZstd19Bytes"] for row in report["collisions"]),
                  indexedDecodeNativeUsec=sum(row["decodeUsec"] for row in report["nativeIndexedPrototypeTiming"]),
                  normalShapeBuildNativeUsec=sum(row["setFacesUsec"] for row in report["nativeIndexedPrototypeTiming"]),
                  newDegenerateTriangles=0, windingReversals=0,
                  maxLocalPositionErrorUnits=max(row["quantization"]["maxPositionErrorUnits"] for row in report["collisions"]),
                  recommendForIntegration=False,
                  conclusion="No several-MB gain demonstrated. Stock-form quantization has negligible gzip benefit; indexed prototype still requires resource-load integration and does not justify extra decoding for its measured codec-only gain.",
                  terrainBindingClarification="meadow_far_sward.gd:25-27 checks terrain SHA only when SOURCE_PATH .gd exists. Actual v127 contains .gdc and .gd.remap, not .gd; metadata mismatch is not proof of a Web cache rebuild. Preserve/rebind provenance for source-bearing builds.",
                  timingCaveat="One isolated desktop headless measurement, not Web/20Mbps/80ms. No new full scene, browser, service, engine build or staging.")
    write_json(output / "feasibility.json", result)
    print(json.dumps({key: result[key] for key in ("beforeActualBrotliBytes", "beforeSameSettingsBrotliBytes", "afterBrotli6Bytes", "brotli6SavedBytes", "gzip6SavedBytes", "exactIndexedCodecBytes", "indexedDecodeNativeUsec", "recommendForIntegration")}), flush=True)
    return result


def self_test():
    import unittest

    class CollisionTests(unittest.TestCase):
        def test_indexed_all_corner_bits_and_order(self):
            points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [-0., 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
            vertices, indices = unique_corners(points.tobytes())
            self.assertEqual(len(vertices), 4)
            self.assertEqual(vertices[indices].tobytes(), points.tobytes())
            self.assertEqual(indexed_codec(points.tobytes())[0][:4], b"CLI1")

        def test_quantization_corner_order_bounds_and_degenerate_guard(self):
            points = np.array([[.00101, 0, 0], [1, 0, 0], [0, 1, 0], [2, 0, 0], [2.000001, 0, 0], [2, .000001, 0]], dtype="<f4")
            after, proof = quantize_faces(points.tobytes())
            self.assertEqual(len(after), points.nbytes)
            self.assertLessEqual(proof["maxAxisErrorUnits"], STEP / 2)
            self.assertEqual(proof["newDegenerateTriangles"], 0)
            self.assertEqual(after[36:], points.tobytes()[36:])

        def test_span_guard_and_every_outside_byte(self):
            before = np.arange(9, dtype="<f4").tobytes()
            after = bytes(len(before))
            raw = b"header!" + struct.pack("<II", 35, 3) + before + b"suffix"
            result, start = patch_faces(raw, before, after)
            self.assertEqual(result[:start], raw[:start])
            self.assertEqual(result[start + len(before):], b"suffix")
            for invalid in (before, raw + before, raw.replace(struct.pack("<II", 35, 3), bytes(8))):
                with self.assertRaises(ValueError):
                    patch_faces(invalid, before, after)

        def test_container_preserves_noncollision_frames(self):
            from repack_web_cache import _pack
            raw = bytes(range(256)) * 48
            changed = raw[:5000] + b"changed" + raw[5007:]
            original = _pack(raw, 4096, 3)
            result, proof = patch_container(original, raw, changed, 5000, 7)
            self.assertEqual(_unpack(result), changed)
            self.assertEqual(proof["rewrittenBlocks"], 1)

        def test_scope_and_invalid_coordinate_input(self):
            for path in (ROOT, SCOPE, ROOT / "godot/assets/new.scn"):
                with self.assertRaises(ValueError):
                    scoped(path)
            for data in (b"", bytes(12), np.full(9, np.nan, dtype="<f4").tobytes()):
                with self.assertRaises(ValueError):
                    unique_corners(data)

    return unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CollisionTests)).wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SCOPE / "candidate-01")
    parser.add_argument("--resume", action="store_true", help="Reuse a verified original inspection; never overwrite artifacts")
    parser.add_argument("--summarize", action="store_true", help="Measure the one existing candidate, no new profile")
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        raise SystemExit(0 if self_test() else 1)
    if arguments.summarize:
        summarize(arguments.output)
    else:
        build(arguments.output, arguments.resume)
