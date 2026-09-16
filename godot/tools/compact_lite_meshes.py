"""One lossless, full-storage-key mesh compaction candidate from frozen v125.

Only six allowlisted leaf meshes in four scenes. No welding by position, LOD,
triangle removal/reorder, normal recomputation, attribute re-encoding or texture
work. Native Godot dumps and reloads raw _surfaces; Python verifies every decoded
triangle corner byte. Writes only NEW children of artifacts/startup-v126/mesh-compact.
Run --self-test first. --resume resumes an interrupted build, never an existing PCK.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import numpy as np

from inspect_web_pack import read_pack
from build_web_quality import write_pack
from repack_web_cache import _unpack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v126/mesh-compact"
BASE = ROOT / "artifacts/v125/index-lite.pck"
BASE_SHA = "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"
GODOT = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe"
TARGETS = {
    "assets/baked/v77/detail.scn": ["PropGroundStitches", "CreepingMeadowAndLedgeGrowth", "LivingMeadowUnderstory"],
    "assets/baked/v77/brush.scn": ["MiddleMeadowBrush"],
    "assets/baked/v77/foothill.scn": ["CastleFoothillWoodland"],
    "assets/baked/v77/riverbank.scn": ["RootedRiparianCover"],
}
CHANNEL_WIDTHS = {"0": 12, "1": 12, "2": 16, "3": 16, "4": 8, "5": 8}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def scoped(path):
    path = Path(path).resolve()
    require(SCOPE.resolve() == SCOPE and path.is_relative_to(SCOPE) and path != SCOPE,
            "Output must stay in a child of the authorized mesh-compact directory")
    return path


def write_new(path, data):
    path = scoped(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    require(path.read_bytes() == data, "Artifact readback mismatch")


def write_json(path, value):
    write_new(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def read_record(record):
    data = Path(record["path"]).read_bytes()
    require(len(data) == record["bytes"] and sha(data) == record["sha256"], "Dump fingerprint mismatch")
    return data


def without_comments(text):
    return re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/',
                  lambda match: match.group(1) or "", text, flags=re.S)


def shader_proof(entries, roots=None):
    """Scan actual target-material shader roots and their complete packed include graph."""
    hashes = {}
    pending = list(roots) if roots is not None else [p for p in entries if p.endswith((".gdshader", ".gdshaderinc"))]
    while pending:
        path = pending.pop()
        if path in hashes:
            continue
        require(path in entries and path.endswith((".gdshader", ".gdshaderinc")), "Unknown shader root/include")
        data = entries[path]
        source = without_comments(data.decode("utf-8"))
        require(not re.search(r"\bVERTEX_ID\b", source), f"Vertex-ID dependent shader rejected: {path}")
        require("##" not in source, f"Token-pasting requires manual review: {path}")
        for include in re.findall(r'#include\s+"([^"]+)"', source):
            target = include.removeprefix("res://") if include.startswith("res://") else str(PurePosixPath(path).parent / include)
            require(".." not in PurePosixPath(target).parts and target in entries,
                    f"Unknown shader include: {path}: {include}")
            require(target.endswith(".gdshaderinc"), "Unreviewed include resource type")
            pending.append(target)
        hashes[path] = sha(data)
    require(hashes, "No packed shaders found")
    return {"targetShaderRoots": sorted(roots or []), "targetShadersAndAllIncludes": hashes, "vertexIdAbsent": True}


def target_shader_roots(before):
    roots = set()
    def visit(value):
        if isinstance(value, list):
            if len(value) == 3 and value[0] == "Shader" and isinstance(value[1], str):
                require(value[1].startswith("res://"), "Unknown target shader path")
                roots.add(value[1].removeprefix("res://"))
            else:
                for child in value:
                    visit(child)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
    for path, labels in TARGETS.items():
        snapshot = before["files"][path]["snapshot"]
        for label in labels:
            visit(snapshot["tree"][label])
            visit(snapshot["meshes"][label])
    require(roots, "Target meshes must have auditable shader materials")
    return roots


def compact_buffers(vertex, attributes, indices, count, vertex_stride, normal_stride, attribute_stride, index_stride):
    require(count > 0 and vertex_stride > 0 and normal_stride > 0 and attribute_stride > 0, "Invalid vertex layout")
    require(len(vertex) == count * (vertex_stride + normal_stride), "Vertex/normal-tangent partition size mismatch")
    require(len(attributes) == count * attribute_stride, "Attribute partition size mismatch")
    require(index_stride in (2, 4) and len(indices) > 0 and len(indices) % (index_stride * 3) == 0,
            "Only indexed triangle surfaces are authorized")
    require(index_stride == (2 if count <= 65536 else 4), "Godot index format mismatch")
    corners = np.frombuffer(indices, dtype=f"<u{index_stride}")
    require(corners.max() < count, "Index out of bounds")
    split = count * vertex_stride
    positions = np.frombuffer(vertex[:split], dtype=np.uint8).reshape(count, vertex_stride)
    normals = np.frombuffer(vertex[split:], dtype=np.uint8).reshape(count, normal_stride)
    attrs = np.frombuffer(attributes, dtype=np.uint8).reshape(count, attribute_stride)
    keys = np.concatenate((positions, normals, attrs), axis=1)
    width = keys.shape[1]
    _, first, inverse = np.unique(keys.view(f"V{width}").ravel(), return_index=True, return_inverse=True)
    order = np.argsort(first)
    representatives = first[order]
    stable_ids = np.empty(len(first), dtype=np.uint32)
    stable_ids[order] = np.arange(len(first), dtype=np.uint32)
    mapping = stable_ids[inverse]
    unique_count = len(first)
    skipped_boundary = count > 65536 >= unique_count
    # Do not silently switch from GL_UNSIGNED_INT to GL_UNSIGNED_SHORT.
    if skipped_boundary:
        representatives = np.arange(count)
        mapping = np.arange(count, dtype=np.uint32)
    new_count = len(representatives)
    remapped = mapping[corners]
    require(np.array_equal(keys[corners], keys[representatives][remapped]), "Raw triangle-corner bytes changed")
    new_vertex = positions[representatives].tobytes() + normals[representatives].tobytes()
    new_attributes = attrs[representatives].tobytes()
    new_indices = remapped.astype(f"<u{index_stride}").tobytes()
    return {"vertex_data": new_vertex, "attribute_data": new_attributes, "index_data": new_indices}, {
        "beforeVertices": count, "uniqueStorageKeys": unique_count, "afterVertices": new_count,
        "removedDuplicateVertices": count - new_count, "indexCount": len(corners), "triangleCount": len(corners) // 3,
        "beforeBufferBytes": len(vertex) + len(attributes) + len(indices),
        "afterBufferBytes": len(new_vertex) + len(new_attributes) + len(new_indices),
        "jointKeyBytes": width, "indexStride": index_stride, "indexWidthBoundaryKeptOriginal": skipped_boundary,
        "rawCornerSha256": sha(keys[corners].tobytes()), "rawCornerBytesExact": True,
        "firstOccurrenceVertexOrder": True}, mapping


def new_stage(output, name):
    for number in range(1, 10):
        stage = scoped(output / f"{name}-{number:02d}")
        if not stage.exists():
            stage.mkdir(parents=True)
            return stage
    raise ValueError("Bounded stage retry limit reached")


def run_engine(output, files, assemble=False):
    stage = new_stage(output, "assemble" if assemble else "inspect")
    project = stage / "sandbox"
    write_new(project / "project.godot", b'config_version=5\n[application]\nconfig/name="OfflineMeshCompact"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[shader_globals]\nmeadow_clock={"type":"float","value":0.0}\nmeadow_night={"type":"float","value":0.0}\n')
    request = dict(output=str(stage), allowed_root=str(SCOPE), reference_pack=str(BASE), files=files, assemble=assemble)
    request_path = stage / "request.json"
    write_json(request_path, request)
    environment = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = project / key.lower()
        directory.mkdir()
        environment[key] = str(directory)
    command = [str(GODOT), "--headless", "--path", str(project), "--script", str(Path(__file__).with_suffix(".gd")),
               "--log-file", str(stage / "engine.log"), "--", "--request", str(request_path)]
    print(f"NATIVE {'ASSEMBLE/RELOAD' if assemble else 'DUMP'} {stage.name}", flush=True)
    started = time.monotonic()
    try:
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=240, env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as error:
        write_new(stage / "timeout.txt", str(error).encode())
        raise
    log = process.stdout + process.stderr
    write_new(stage / "process.log", log.encode())
    require(process.returncode == 0 and "MESH_COMPACT_OFFLINE: PASS" in log and "ERROR:" not in log,
            f"Native stage failed: {stage / 'process.log'}\n{log[-5000:]}")
    report = json.loads((stage / "inspection.json").read_text())
    require(report["failures"] == 0, "Native validation reported failures")
    report["stageSeconds"] = time.monotonic() - started
    return report


def compare_scenes(before, after, changes):
    proofs = {}
    for path, targets in TARGETS.items():
        a, b = before["files"][path]["snapshot"], after["files"][path]["snapshot"]
        for key in ("tree", "bundle", "packed_properties"):
            require(a[key] == b[key], f"Scene nodes/collisions/order/materials/metadata changed: {path}: {key}")
        require(a["meshes"].keys() == b["meshes"].keys(), "Mesh set changed")
        for label, mesh_a in a["meshes"].items():
            mesh_b = b["meshes"][label]
            require(mesh_a["properties"] == mesh_b["properties"], "Mesh properties changed")
            require(len(mesh_a["surfaces"]) == len(mesh_b["surfaces"]), "Surface count changed")
            if label not in targets:
                require(mesh_a == mesh_b, f"Excluded rock mesh changed: {path}:{label}")
                continue
            sa, sb = mesh_a["surfaces"][0], mesh_b["surfaces"][0]
            require(sa["fixed"] == sb["fixed"], f"Surface format/AABB/UV scale/material/metadata changed: {label}")
            require(sa["index_count"] == sb["index_count"] and sa["index_stride"] == sb["index_stride"], "Index count/width changed")
            change = changes[path][label]
            require(sb["vertex_count"] == change["vertex_count"], "Unexpected reloaded vertex count")
            for key, buffer in change["buffers"].items():
                require(sb["raw_buffers"][key]["sha256"] == buffer["sha256"], "Godot changed requested storage bytes")
            ia = np.frombuffer(read_record(sa["raw_buffers"]["index_data"]), dtype=f'<u{sa["index_stride"]}')
            ib = np.frombuffer(read_record(sb["raw_buffers"]["index_data"]), dtype=f'<u{sb["index_stride"]}')
            channels = {}
            for channel, stride in CHANNEL_WIDTHS.items():
                decoded_a, decoded_b = read_record(sa["decoded"][channel]), read_record(sb["decoded"][channel])
                require(len(decoded_a) == sa["vertex_count"] * stride and len(decoded_b) == sb["vertex_count"] * stride,
                        "Unexpected native decoded channel size")
                ca = np.frombuffer(decoded_a, dtype=np.uint8).reshape(-1, stride)[ia]
                cb = np.frombuffer(decoded_b, dtype=np.uint8).reshape(-1, stride)[ib]
                require(np.array_equal(ca, cb), f"Decoded triangle corner differs: {label}, channel {channel}")
                channels[channel] = dict(bytes=ca.size, sha256=sha(ca.tobytes()), byteExact=True)
            proofs[f"{path}:{label}"] = {"decodedTriangleCornerChannels": channels, "allCornersExact": True,
                                         "surfaceFixedPropertiesExact": True, "indexCountAndWidthExact": True}
    require(len(proofs) == 6, "Exactly six target meshes must be verified")
    return proofs


def build(output, resume=False):
    output = scoped(output)
    require(not (output / "index-lite.pck").exists(), "Only one candidate, never overwrite a pack")
    require(resume or not output.exists(), "Use a fresh directory (or --resume after interruption)")
    output.mkdir(parents=True, exist_ok=resume)
    base_bytes = BASE.read_bytes()
    require(sha(base_bytes) == BASE_SHA, "Frozen v125 base changed")
    inventory = read_pack(BASE)
    entries = {e["path"]: base_bytes[e["offset"]:e["offset"] + e["bytes"]] for e in inventory["entries"]}
    sources = []
    for path, targets in TARGETS.items():
        copy = output / "original" / Path(path).name
        if not copy.exists():
            write_new(copy, entries[path])
        require(copy.read_bytes() == entries[path], "Original extraction differs from frozen PCK")
        sources.append(dict(resource=path, targets=targets, path=str(copy), sha256=sha(entries[path])))
    before_cache = output / "before.json"
    before = json.loads(before_cache.read_text()) if before_cache.exists() else run_engine(output, sources)
    if not before_cache.exists():
        write_json(before_cache, before)
    shader_checks = shader_proof(entries, target_shader_roots(before))
    changes, statistics = {}, {}
    buffers_dir = new_stage(output, "buffers")
    for path, targets in TARGETS.items():
        changes[path] = {}
        for label in targets:
            mesh = before["files"][path]["snapshot"]["meshes"][label]
            require(len(mesh["surfaces"]) == 1, "Exactly one surface per target")
            surface = mesh["surfaces"][0]
            data = {key: read_record(surface["raw_buffers"][key]) for key in ("vertex_data", "attribute_data", "index_data")}
            result, stats, mapping = compact_buffers(data["vertex_data"], data["attribute_data"], data["index_data"],
                surface["vertex_count"], surface["vertex_stride"], surface["normal_tangent_stride"],
                surface["attribute_stride"], surface["index_stride"])
            records = {}
            for key, value in result.items():
                file = buffers_dir / f"{label}-{key}.bin"
                write_new(file, value)
                records[key] = dict(path=str(file), bytes=len(value), sha256=sha(value))
            write_new(buffers_dir / f"{label}-old-to-new.bin", mapping.astype("<u4").tobytes())
            changes[path][label] = dict(vertex_count=stats["afterVertices"], buffers=records)
            statistics[f"{path}:{label}"] = stats
            print(f"COMPACT {label}: {stats['beforeVertices']} -> {stats['afterVertices']} vertices; "
                  f"{stats['triangleCount']} triangles unchanged", flush=True)
    assembly_sources = [{**source, "replacements": changes[source["resource"]]} for source in sources]
    after = run_engine(output, assembly_sources, assemble=True)
    proofs = compare_scenes(before, after, changes)
    write_json(output / "after.json", after)
    replacements, replacement_rows = {}, []
    for path in TARGETS:
        file = Path(after["files"][path]["path"])
        blob = file.read_bytes()
        replacements[path] = blob
        original = entries[path]
        replacement_rows.append(dict(path=path, file=str(file), beforeSha256=sha(original), afterSha256=sha(blob),
            before=len(original), after=len(blob), beforeResourceRawBytes=len(_unpack(original)),
            afterResourceRawBytes=len(_unpack(blob)), beforeGzip6=len(gzip.compress(original, compresslevel=6, mtime=0)),
            afterGzip6=len(gzip.compress(blob, compresslevel=6, mtime=0))))
    # A separate full-scene candidate, leaving all180 other PCK entries exact.
    candidate = output / "index-lite.pck"
    write_pack(BASE, inventory, candidate, replacements)
    candidate_bytes = candidate.read_bytes()
    result_inventory = read_pack(candidate)
    require([r["path"] for r in inventory["entries"]] == [r["path"] for r in result_inventory["entries"]], "Pack resource order changed")
    exact_rows = []
    for entry in result_inventory["entries"]:
        path = entry["path"]
        actual = candidate_bytes[entry["offset"]:entry["offset"] + entry["bytes"]]
        require(actual == replacements.get(path, entries[path]), f"Unscoped PCK resource change: {path}")
        exact_rows.append(dict(path=path, beforeSha256=sha(entries[path]), afterSha256=sha(actual), byteExact=actual == entries[path]))
    packed = gzip.compress(candidate_bytes, compresslevel=6, mtime=0)
    write_new(candidate.with_suffix(".pck.gz"), packed)
    require(gzip.decompress(packed) == candidate_bytes and sha(BASE.read_bytes()) == BASE_SHA, "Gzip/input check failed")
    base_gzip = len(gzip.compress(base_bytes, compresslevel=6, mtime=0))
    saving = (base_gzip - len(packed)) / base_gzip
    report = dict(schemaVersion=1, source=str(BASE), sourceSha256=BASE_SHA, engine=str(GODOT),
        engineSha256=sha(GODOT.read_bytes()), sourceBytes=len(base_bytes), candidateBytes=len(candidate_bytes),
        sourceGzip6Bytes=base_gzip, candidateGzip6Bytes=len(packed), gzipSavingPercent=saving * 100,
        candidateSha256=sha(candidate_bytes), candidateGzipSha256=sha(packed), targets=TARGETS,
        meshStatistics=statistics, decodedCornerProof=proofs, shaders=shader_checks,
        entries=exact_rows, replacements=replacement_rows, untouchedEntryCount=sum(r["byteExact"] for r in exact_rows),
        inputsUnchanged=True, trianglesObjectsMaterialsCollisionsPreserved=True, recommendForIntegration=saving >= .05,
        stopDecision="One candidate complete; below5% gzip saving: stop, no more trials" if saving < .05 else "One candidate complete; main owns integration",
        visualPerformanceAcceptance="Not tested here; exact native decoded corners are structural proof only",
        integration="Apply these mesh scenes before any scene-container recompression; never overwrite them with pre-compaction scenes. New PCK hash needs main contract mapping.")
    write_json(output / "manifest.json", report)
    write_json(output / "pack-replacements.json", {"sourcePckSha256": BASE_SHA,
        "recommendForIntegration": saving >= .05, "replacements": replacement_rows})
    print(json.dumps({k: report[k] for k in ("sourceBytes", "candidateBytes", "sourceGzip6Bytes", "candidateGzip6Bytes", "gzipSavingPercent", "candidateSha256", "stopDecision")}, indent=2), flush=True)
    return report


def self_test():
    import unittest
    class CompactionTests(unittest.TestCase):
        def test_complete_key_and_stable_corner_order(self):
            n = 6
            positions = bytes([1, 1, 1, 1, 1, 2])
            normals = bytes([3, 3, 4, 3, 3, 3])
            attrs = bytes([5, 5, 5, 6, 5, 5])
            corners = np.array([4, 3, 2, 1, 0, 5], dtype="<u2").tobytes()
            data, report, mapping = compact_buffers(positions + normals, attrs, corners, n, 1, 1, 1, 2)
            self.assertEqual(report["afterVertices"], 4)
            self.assertEqual(mapping.tolist(), [0, 0, 1, 2, 0, 3])
            self.assertEqual(np.frombuffer(data["index_data"], dtype="<u2").tolist(), [0, 2, 1, 0, 0, 3])
            self.assertEqual(data["vertex_data"], bytes([1, 1, 1, 2, 3, 4, 3, 3]))
        def test_signed_zero_and_every_attribute_byte_distinguish_vertices(self):
            positions = np.array([0.0, -0.0, 0.0], dtype="<f4").tobytes()
            attrs = bytes([0, 0, 1])
            _, report, _ = compact_buffers(positions + b"aaa", attrs, np.array([0, 1, 2], dtype="<u2").tobytes(), 3, 4, 1, 1, 2)
            self.assertEqual(report["afterVertices"], 3)
        def test_index_width_boundary_keeps_original(self):
            n = 65537
            _, report, _ = compact_buffers(b"a" * n + b"b" * n, b"c" * n, np.array([0, 1, n - 1], dtype="<u4").tobytes(), n, 1, 1, 1, 4)
            self.assertTrue(report["indexWidthBoundaryKeptOriginal"])
            self.assertEqual(report["afterVertices"], n)
        def test_bad_layout_and_index_rejected(self):
            for indices in (b"", np.array([0, 1, 3], dtype="<u2").tobytes()):
                with self.assertRaises(ValueError):
                    compact_buffers(b"aaabbb", b"ccc", indices, 3, 1, 1, 1, 2)
        def test_packed_shader_include_vertex_id_rejected(self):
            files = {"shaders/a.gdshader": b'#include "res://shaders/b.gdshaderinc"\nvoid vertex(){}',
                     "shaders/b.gdshaderinc": b"// VERTEX_ID is not used\n"}
            self.assertTrue(shader_proof(files)["vertexIdAbsent"])
            files["shaders/b.gdshaderinc"] = b"float id = float(VERTEX_ID);"
            with self.assertRaises(ValueError):
                shader_proof(files)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompactionTests))
    return result.wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SCOPE / "candidate-01")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(0 if self_test() else 1)
    build(args.output, args.resume)
