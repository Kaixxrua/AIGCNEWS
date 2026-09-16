"""Build COPY-ONLY v115 geometry candidates, without imports or a full export.

Run with the supplied Python and Godot 4.7.2. Only NEW files below
artifacts/loading-v115/geometry are written. Source caches, textures, shaders,
collision and project configuration are never saved by Godot. An existing PCK
is mounted read-only inside an isolated project for shader/texture dependencies.

Default/fallback storage remains stock Godot ArrayMesh/RSCC: quantize float32 position/UV values
on binary grids, retain the other raw bytes, then try bounded Zstd block sizes.
No mesh reconstruction, normal/tangent re-encoding, index reorder, vertex weld,
object removal, custom runtime decoder, or collision rebuilding is performed.
Rock and terrain keep ALL original attributes so the original AO signatures and
ray samples remain exact. The AO artifact is included as a byte-identical copy.

CLI: python -B godot/tools/build_lite_geometry.py --output artifacts/loading-v115/geometry/candidate
Tests: python -B godot/tools/test_build_lite_geometry.py
Importable API: build(output, godot=..., reference_pack=..., ...); write_pack_manifest;
quantize_positions; quantize_values; patch_unique; pack_best. The detailed manifest
maps resource paths to artifacts. pack-replacements.json exposes main's list schema
with beforeSha256 read from actual source PCK entries, never assumed from disk.
Apply every listed replacement together to lite only.

--strong produces a separately validated native-packed candidate. It canonicalizes
shader-unused leaf UV coordinates, bounds pigment/color/normal precision, and
quantizes rock UV/UV2 ONLY. Rock sampling geometry is exact; the AO signature is
recomputed and the original runtime validates every original visibility index.
Brush retains float positions because native UNORM16 collapsed thin triangles.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import numpy as np

from inspect_web_pack import read_pack
from repack_web_cache import _pack, _unpack

ROOT = Path(__file__).resolve().parents[2]
GODOT_ROOT = ROOT / "godot"
SCOPE = ROOT / "artifacts/loading-v115/geometry"
DEFAULT_GODOT = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe"
DEFAULT_PACK = ROOT / "artifacts/v114/index.pck"
AO_RESOURCE = "res://assets/baked/v110/rock-occlusion.bin"
TERRAIN = "res://assets/baked/v77/terrain.scn"
DETAIL = "res://assets/baked/v77/detail.scn"
SWARD = "res://assets/baked/v113/far-sward.scn"
PINS = {
    TERRAIN: "b44e2c8c33fe4369d872fcb6ad3aa74180aac5463f18ae2eaadfb07ea4fc2771",
    DETAIL: "46b397bf8a09a712ce94f520874952ab7c048e6e7a1dc78e1c3fa6198700fff8",
    "res://assets/baked/v77/brush.scn": "b7e2627dc8bb1786530c5caf9fef99ba102d3cee4fea30e355fcb94f763befd9",
    "res://assets/baked/v77/foothill.scn": "089a44e1d190655001c796c68514460d60be87b8ffee05f7efb2f9ec11f47ff5",
    "res://assets/baked/v77/riverbank.scn": "979645039620c041e4f65a62b33eb7419811b8cfd959106ceb4da99a42994627",
    SWARD: "308f3998727c0393a550f886cad691fdb761e4aad7d12cf9e2d47dcbd3091b92",
}
EXACT_MESHES = {"ContinuousMeadow", "SolidLimestoneGeology"}
AO_PIN = "f3f86ff17ed6da347d7fa155562b3ca4048bac04b52eebf560aa3d8113371577"
NATIVE_FLAG = 536870912
LEAF_SHADER = "res://shaders/meadow_leaves.gdshader"
LEAF_SHADER_PIN = "69f1cf9211b833c2bcc15c99a1f1d32bdcb80e8ebc6daa49e1ef8367804050ff"
FLOAT_POSITION_MESHES = EXACT_MESHES | {"MiddleMeadowBrush", "EmbeddedRiverbankStrata"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_path(resource: str) -> Path:
    if resource not in PINS and resource != AO_RESOURCE:
        raise ValueError(f"Not an authorized cache/AO resource: {resource}")
    return GODOT_ROOT / resource.removeprefix("res://")


def new_directory(path: Path) -> Path:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError(f"Refusing existing output: {path}")
    resolved = path.resolve()
    # Check both the configured lexical root and the resolved root, so a
    # junction/symlink cannot redirect output into original source or cache.
    if SCOPE.resolve() != SCOPE or not resolved.is_relative_to(SCOPE) or resolved == SCOPE:
        raise ValueError(f"Output must be a NEW child of {SCOPE}")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def write_new(path: Path, data: bytes) -> None:
    path = Path(path)
    if not path.resolve().is_relative_to(SCOPE) or path.is_symlink():
        raise ValueError("Artifact scope violation")
    with path.open("xb") as stream:
        stream.write(data)
    if path.read_bytes() != data:
        raise OSError(f"Artifact readback mismatch: {path}")


def write_json(path: Path, value) -> None:
    write_new(path, (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))


def size_record(data: bytes) -> dict:
    return {"bytes": len(data), "gzip9_bytes": len(gzip.compress(data, compresslevel=9, mtime=0)), "sha256": sha(data)}


def frozen_tree_stats() -> dict:
    """Read-only mutation sentinel; payload SHA checks remain separate/stronger."""
    files = [GODOT_ROOT / "project.godot", GODOT_ROOT / "export_presets.cfg"]
    for directory in ("scripts", "shaders", "assets", ".godot"):
        files.extend(path for path in (GODOT_ROOT / directory).rglob("*") if path.is_file())
    return {str(path.relative_to(GODOT_ROOT)): [path.stat().st_size, str(path.stat().st_mtime_ns)]
            for path in sorted(files) if path.is_file()}


def validate_step(step: float) -> None:
    if not math.isfinite(step) or not 2 ** -20 <= step <= 2 ** -4 or math.frexp(step)[0] != 0.5:
        raise ValueError("Quantization step must be a power of two from 2^-20 through 2^-4")


def quantize_values(values: np.ndarray, step: float, *, clamp_bounds: bool = False) -> np.ndarray:
    validate_step(step)
    if values.dtype != np.dtype("<f4") or values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("Expected finite little-endian float32 attribute rows")
    result = (np.rint(values.astype(np.float64) / step) * step).astype("<f4")
    if clamp_bounds:
        # Stored AABBs stay byte-exact: never expand beyond any source extent.
        result = np.clip(result, values.min(axis=0), values.max(axis=0))
    # Retain signed zero and all already equal float bit patterns.
    equal = result == values
    result[equal] = values[equal]
    if float(np.abs(result.astype(np.float64) - values).max(initial=0)) > step / 2:
        raise ValueError("Quantized float exceeds declared absolute error bound")
    return result


def triangle_normals(vertices: np.ndarray, indices: np.ndarray) -> np.ndarray:
    tri = vertices[indices].astype(np.float64)
    return np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])


def triangle_checks(original: np.ndarray, proposed: np.ndarray, indices: np.ndarray,
                    source_normals: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    before = triangle_normals(original, indices) if source_normals is None else source_normals
    after = triangle_normals(proposed, indices)
    a = np.linalg.norm(before, axis=1)
    b = np.linalg.norm(after, axis=1)
    nonzero = a > 0
    cosines = np.ones(len(a), dtype=np.float64)
    ratio = np.ones(len(a), dtype=np.float64)
    ratio[nonzero] = b[nonzero] / a[nonzero]
    viable = nonzero & (b > 0)
    cosines[viable] = np.clip(np.einsum("ij,ij->i", before[viable], after[viable]) / (a[viable] * b[viable]), -1, 1)
    cosines[(before == after).all(axis=1)] = 1.0
    cosines[nonzero & (b == 0)] = -1
    bad = nonzero & ((cosines < math.cos(math.radians(5))) | (ratio < .9) | (ratio > 1.1))
    # Existing degenerate triangles are retained exactly, not repaired/deleted.
    if (~nonzero).any():
        unchanged = (original[indices[~nonzero]] == proposed[indices[~nonzero]]).all(axis=(1, 2))
        bad[~nonzero] = ~unchanged
    return bad, {"triangles": int(len(a)), "source_degenerate_triangles": int((~nonzero).sum()),
                 "new_degenerate_triangles": int((nonzero & (b == 0)).sum()),
                 "winding_reversals": int((nonzero & (cosines <= 0)).sum()),
                 "max_face_normal_delta_degrees": float(np.degrees(np.arccos(cosines[nonzero])).max(initial=0)),
                 "min_area_ratio": float(ratio.min(initial=1)), "max_area_ratio": float(ratio.max(initial=1)),
                 "unsafe_triangles": int(bad.sum())}


def quantize_positions(vertices: np.ndarray, indices: np.ndarray, step: float) -> tuple[np.ndarray, dict]:
    if vertices.shape[1] != 3 or indices.ndim != 2 or indices.shape[1] != 3:
        raise ValueError("Expected XYZ vertices and triangle corner indices")
    if indices.size and (indices.min() < 0 or indices.max() >= len(vertices)):
        raise ValueError("Out-of-bounds triangle index")
    result = quantize_values(vertices, step, clamp_bounds=True)
    normals = triangle_normals(vertices, indices)
    _, groups = np.unique(np.ascontiguousarray(vertices).view("V12").ravel(), return_inverse=True)
    reverted = np.zeros(int(groups.max(initial=-1)) + 1, dtype=bool)
    passes = 0
    for passes in range(1, 33):
        bad, stats = triangle_checks(vertices, result, indices, normals)
        if not bad.any():
            break
        # Preserve source-coordinate equivalence across UV/hard-normal seams.
        # A rejected vertex restores every original vertex at that position.
        reverted[groups[indices[bad].ravel()]] = True
        restore = reverted[groups]
        result[restore] = vertices[restore]
    else:
        result = vertices.copy()  # Finite work; never leave unsafe triangles.
    bad, stats = triangle_checks(vertices, result, indices, normals)
    if bad.any():
        raise ValueError("Triangle protection failed")
    stats.update(guard_passes=passes, exact_vertices=int((result == vertices).all(axis=1).sum()),
                 quantized_vertices=int((result != vertices).any(axis=1).sum()),
                 coincident_position_groups=int(len(reverted)),
                 aabb_extents_preserved=True, coincident_vertices_remain_coincident=True)
    return result, stats


def strided_floats(data: bytes | bytearray, count: int, offset: int, stride: int, components: int) -> np.ndarray:
    if count <= 0 or stride < components * 4 or offset < 0 or offset + (count - 1) * stride + components * 4 > len(data):
        raise ValueError("Unrecognized/out-of-range ArrayMesh buffer layout")
    return np.ndarray((count, components), dtype="<f4", buffer=data, offset=offset, strides=(stride, 4))


def patch_unique(raw: bytes | bytearray, before: bytes, after: bytes) -> tuple[bytearray, int]:
    if not before or len(before) != len(after):
        raise ValueError("Only nonempty, same-length patches are permitted")
    offset = raw.find(before)
    if offset < 0 or raw.find(before, offset + 1) >= 0:
        raise ValueError("Patch bytes must occur exactly once in the serialized payload")
    result = bytearray(raw)
    result[offset:offset + len(before)] = after
    return result, offset


def pack_best(raw: bytes) -> tuple[bytes, list[dict]]:
    trials = []
    selected = None
    best_score = None
    # Whole-PCK compression must still be measured by main. Individual gzip is
    # the bounded offline objective, and can prefer a larger RSCC representation.
    for block, level in ((4096, 3), (4096, 9), (16384, 9), (65536, 9), (262144, 9)):
        candidate = _pack(raw, block, level)
        if _unpack(candidate) != raw:
            raise ValueError("RSCC byte-exact decompression roundtrip failed")
        gzip_bytes = len(gzip.compress(candidate, compresslevel=9, mtime=0))
        score = (gzip_bytes, len(candidate))
        trials.append({"block_size": block, "zstd_level": level, "bytes": len(candidate), "gzip9_bytes": gzip_bytes})
        if best_score is None or score < best_score:
            selected = candidate
            best_score = score
    return selected, trials


def run_inspector(output: Path, *, godot: Path, reference_pack: Path,
                  files: list[dict], ao_path: Path, dump: bool, runtime_probe: dict | None = None,
                  native_pack: bool = False, allow_compressed: bool = False,
                  native_basis_safe: bool = False, canonical_leaf_uv: bool = False) -> dict:
    stage = new_directory(output)
    project = new_directory(stage / "sandbox")
    write_new(project / "project.godot", b'config_version=5\n[application]\nconfig/name="OfflineLiteGeometry"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[shader_globals]\nmeadow_clock={"type": "float", "value": 0.0}\nmeadow_night={"type": "float", "value": 0.0}\n')
    request = dict(output=str(stage), allowed_root=str(SCOPE), reference_pack=str(reference_pack),
                   files=files, ao_path=str(ao_path), dump=dump, native_pack=native_pack, allow_compressed=allow_compressed,
                   native_basis_safe=native_basis_safe, canonical_leaf_uv=canonical_leaf_uv)
    if runtime_probe:
        request["runtime_probe"] = runtime_probe
    request_path = stage / "request.json"
    write_json(request_path, request)
    command = [str(godot), "--headless", "--path", str(project), "--script",
               str(GODOT_ROOT / "tools/build_lite_geometry.gd"), "--log-file", str(stage / "engine.log"),
               "--", "--request", str(request_path)]
    process_env = dict(os.environ)
    for name in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = project / name.lower()
        directory.mkdir()
        process_env[name] = str(directory)
    started = time.monotonic()
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, env=process_env)
    log = process.stdout + process.stderr
    write_new(stage / "process.log", log.encode("utf-8"))
    if process.returncode or "LITE_GEOMETRY_OFFLINE: PASS" not in log or "SCRIPT ERROR" in log or "ERROR:" in log:
        raise RuntimeError(f"Offline Godot validation failed; see {stage / 'process.log'}\n{log[-6000:]}")
    report = json.loads((stage / "inspection.json").read_text(encoding="utf-8"))
    if report["failures"]:
        raise ValueError("Inspector reported failed assertions")
    report["offline_process_seconds"] = time.monotonic() - started
    return report


def freeze_inputs(reference_pack: Path) -> tuple[dict, dict]:
    original = {resource: source_path(resource).read_bytes() for resource in [*PINS, AO_RESOURCE]}
    for resource, pin in PINS.items():
        if sha(original[resource]) != pin:
            raise ValueError(f"Accepted source cache SHA differs: {resource}")
    if sha(original[AO_RESOURCE]) != AO_PIN:
        raise ValueError("Accepted original AO fingerprint differs")
    inventory = read_pack(reference_pack, verify=True)
    entries = {entry["path"].removeprefix("res://"): entry for entry in inventory["entries"]}
    with reference_pack.open("rb") as stream:
        for resource, blob in original.items():
            entry = entries[resource.removeprefix("res://")]
            stream.seek(entry["offset"])
            packed = stream.read(entry["bytes"])
            if resource == AO_RESOURCE:
                same = packed == blob
            else:
                same = _unpack(packed) == _unpack(blob)
            if not same:
                raise ValueError(f"Reference PCK does not contain accepted resource content: {resource}")
    return original, {"path": str(reference_pack), "sha256": sha(reference_pack.read_bytes()),
                      "engine": inventory["engine"], "read_only_dependency_mount": True}


def file_request(resource: str, path: Path, blob: bytes) -> dict:
    return {"resource": resource, "path": str(path), "sha256": sha(blob)}


def read_buffer(surface: dict, name: str) -> bytes:
    info = surface["raw_buffers"][name]
    data = Path(info["path"]).read_bytes() if info["bytes"] else b""
    if sha(data) != info["sha256"] or len(data) != info["bytes"]:
        raise ValueError("Inspection buffer fingerprint mismatch")
    return data


def quantize_surface(surface: dict, label: str, position_step: float, uv_step: float, uv2_step: float) -> tuple[dict, dict]:
    count = int(surface["vertex_count"])
    buffers = {key: read_buffer(surface, key) for key in ("vertex_data", "attribute_data", "index_data")}
    output = {key: bytearray(data) for key, data in buffers.items()}
    index_count = int(surface["index_count"])
    if index_count:
        width, remainder = divmod(len(buffers["index_data"]), index_count)
        if remainder or width not in (2, 4) or index_count % 3:
            raise ValueError("Unsupported triangle index buffer")
        indices = np.frombuffer(buffers["index_data"], dtype=f"<u{width}").reshape(-1, 3)
    else:
        if count % 3 or buffers["index_data"]:
            raise ValueError("Invalid unindexed triangle surface")
        indices = np.arange(count, dtype=np.uint32).reshape(-1, 3)
    report = {"label": label, "vertices": count, "indices": index_count, "attributes": {}}
    for channel, components, buffer_name, stride_name, step in (
        (0, 3, "vertex_data", "vertex_stride", position_step),
        (4, 2, "attribute_data", "attribute_stride", uv_step),
        (5, 2, "attribute_data", "attribute_stride", uv2_step),
    ):
        if str(channel) not in surface["decoded"]:
            continue
        offset = int(surface["offsets"][str(channel)])
        stride = int(surface[stride_name])
        before = strided_floats(buffers[buffer_name], count, offset, stride, components)
        decoded = Path(surface["decoded"][str(channel)]).read_bytes()
        if before.tobytes() != decoded:
            raise ValueError(f"Storage view differs from Godot decoded channel {channel}")
        if label in EXACT_MESHES:
            proposed = before.copy()
            if channel == 0:
                _, report["topology"] = triangle_checks(before, proposed, indices)
            report["exact_mesh_reason"] = "All AO-sensitive mesh attributes are frozen; no resampling, signature rewrite or bypass"
        elif channel == 0:
            proposed, report["topology"] = quantize_positions(before, indices, step)
        else:
            proposed = quantize_values(before, step)
        target = strided_floats(output[buffer_name], count, offset, stride, components)
        target[:] = proposed
        errors = np.abs(proposed.astype(np.float64) - before)
        report["attributes"][str(channel)] = {
            "name": {0: "position", 4: "UV", 5: "UV2"}[channel], "step": step,
            "absolute_error_bound_per_component": 0 if label in EXACT_MESHES else step / 2,
            "measured_max_abs_error": float(errors.max(initial=0)),
            "measured_max_vector_error": float(np.linalg.norm(errors, axis=1).max(initial=0)),
            "changed_components": int((proposed != before).sum()),
            "before_decoded_sha256": sha(before.tobytes()), "after_decoded_sha256": sha(proposed.tobytes())}
    report.update(normals_tangents_color_exact=True, indices_and_triangle_order_exact=True,
                  vertex_count_and_order_exact=True, aabb_bytes_exact=True)
    return {key: bytes(value) for key, value in output.items()}, report


def mesh_signature(report: dict, resource: str, label: str) -> str:
    found = [mesh["signature"] for mesh in report["files"][resource]["meshes"] if mesh["label"] == label]
    if len(found) != 1:
        raise ValueError(f"Expected one AO mesh: {resource} {label}")
    return found[0]


def compare_inspections(before: dict, after: dict, file_reports: dict, terrain_sha: str) -> dict:
    counts = dict(nodes=0, meshes=0, surfaces=0, collision_shapes=0, collision_corners=0, vertices=0, triangles=0)
    for resource, original in before["files"].items():
        current = after["files"][resource]
        expected_tree = json.loads(json.dumps(original["tree"]))
        if resource == SWARD:
            expected_tree["."]["properties"]["metadata/terrain_sha256"] = terrain_sha
        if expected_tree != current["tree"] or original["node_count"] != current["node_count"] or original["collisions"] != current["collisions"]:
            raise ValueError(f"Node/material/metadata/collision properties differ: {resource}")
        if len(original["meshes"]) != len(current["meshes"]):
            raise ValueError("Mesh count changed")
        counts["nodes"] += original["node_count"]
        counts["collision_shapes"] += len(original["collisions"])
        counts["collision_corners"] += sum(row["corners"] for row in original["collisions"].values())
        expected_surfaces = iter(file_reports[resource]["surfaces"])
        for a, b in zip(original["meshes"], current["meshes"]):
            if a["label"] != b["label"] or a["properties"] != b["properties"] or len(a["surfaces"]) != len(b["surfaces"]):
                raise ValueError("Stored mesh properties/material/metadata changed")
            counts["meshes"] += 1
            for x, y in zip(a["surfaces"], b["surfaces"]):
                expected = next(expected_surfaces)
                for key in ("surface", "format", "vertex_count", "index_count", "vertex_stride", "attribute_stride", "offsets", "fixed_properties", "aabb"):
                    if x[key] != y[key]:
                        raise ValueError(f"Fixed surface field changed: {key}")
                for channel in range(13):
                    if channel not in (0, 4, 5) and x["channel_hashes"][str(channel)] != y["channel_hashes"][str(channel)]:
                        raise ValueError(f"Non-position/UV decoded channel changed: {channel}")
                for channel, attr in expected["attributes"].items():
                    decoded = Path(y["decoded"][channel]).read_bytes()
                    if sha(decoded) != attr["after_decoded_sha256"]:
                        raise ValueError("Godot reload differs from quantized float candidates")
                for key in ("vertex_data", "attribute_data", "index_data"):
                    if y["raw_buffers"][key]["sha256"] != expected["output_raw_sha256"][key]:
                        raise ValueError("Raw stored buffer changed during engine loading")
                counts["surfaces"] += 1
                counts["vertices"] += x["vertex_count"]
                counts["triangles"] += (x["index_count"] or x["vertex_count"]) // 3
    return counts


def write_pack_manifest(manifest_path: Path, output_path: Path) -> dict:
    """Emit main's exact replacement schema from already validated candidates.

    Reads existing entry bytes and existing candidates. No texture encoding,
    candidate rebuilding or PCK writing. beforeSha256 is always the PCK entry
    SHA, which may differ from disk when its RSCC container was repacked.
    """
    manifest_path, output_path = Path(manifest_path).resolve(strict=True), Path(output_path)
    if output_path.exists() or output_path.is_symlink() or not output_path.resolve().is_relative_to(SCOPE):
        raise ValueError("Pack mapping output must be a NEW artifact file")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") == "lite-geometry-strong-v115-1":
        return write_strong_pack_manifest(manifest_path, output_path)
    if manifest.get("status") != "offline_validated_candidate" or set(manifest["replacements"]) != {*PINS, AO_RESOURCE}:
        raise ValueError("Require the complete, offline-validated six-cache/AO set")
    report_dir = manifest_path.parent
    before = json.loads((report_dir / "before/inspection.json").read_text(encoding="utf-8"))
    after = json.loads((report_dir / "after/inspection.json").read_text(encoding="utf-8"))
    terrain_sha = manifest["files"][TERRAIN]["after"]["sha256"]
    if compare_inspections(before, after, manifest["files"], terrain_sha) != manifest["verified_counts"]:
        raise ValueError("Detailed candidate inspection no longer matches manifest")
    probe = manifest["ao"]["runtime_probe"]
    if not probe or not probe["applied"] or not probe["all_sample_indices_and_nonblue_attributes_exact"]:
        raise ValueError("Require verified original AO runtime/signature/visibility mapping")
    pack = Path(manifest["reference_pack"]["path"]).resolve(strict=True)
    if sha(pack.read_bytes()) != manifest["reference_pack"]["sha256"]:
        raise ValueError("Actual reference PCK no longer matches the validated candidate inputs")
    inventory = read_pack(pack, verify=True)
    entries = {entry["path"].removeprefix("res://"): entry for entry in inventory["entries"]}
    rows = []
    with pack.open("rb") as stream:
        for resource, artifact in manifest["replacements"].items():
            candidate_path = Path(artifact).resolve(strict=True)
            if not candidate_path.is_relative_to(SCOPE):
                raise ValueError("Candidate escaped authorized artifact scope")
            candidate = candidate_path.read_bytes()
            entry = entries[resource.removeprefix("res://")]
            stream.seek(entry["offset"])
            original_entry = stream.read(entry["bytes"])
            disk = source_path(resource).read_bytes()
            if resource == AO_RESOURCE:
                if original_entry != disk or candidate != disk:
                    raise ValueError("AO mapping must remain byte-exact for the protected rock/terrain meshes")
                expected = manifest["ao"]["after"]
                checks = {"kind": "exact_original_AO_copy", "all_bytes_exact": True,
                          "original_runtime_signature_validation_passed": True,
                          "visibility_samples_verified": probe["visibility_samples_checked"],
                          "sample_vertex_mapping_exact": True, "signature_bypass": False}
            else:
                if sha(disk) != PINS[resource] or _unpack(original_entry) != _unpack(disk):
                    raise ValueError("PCK entry decompressed content must equal pinned disk cache")
                detail = manifest["files"][resource]
                expected = detail["after"]
                original_raw, candidate_raw = _unpack(disk), _unpack(candidate)
                cursor = 0
                for span in sorted(detail["changed_spans"], key=lambda item: item["offset"]):
                    if span["offset"] < cursor or original_raw[cursor:span["offset"]] != candidate_raw[cursor:span["offset"]]:
                        raise ValueError("Stored source invariants differ outside quantized attributes")
                    cursor = span["offset"] + span["length"]
                if len(original_raw) != len(candidate_raw) or original_raw[cursor:] != candidate_raw[cursor:]:
                    raise ValueError("Candidate resource metadata/collision bytes changed")
                surfaces = detail["surfaces"]
                checks = {"kind": "stock_ArrayMesh_RSCC", "source_pack_decoded_equals_pinned_disk": True,
                    "nodes_before_after": [before["files"][resource]["node_count"], after["files"][resource]["node_count"]],
                    "meshes_before_after": [len(before["files"][resource]["meshes"]), len(after["files"][resource]["meshes"])],
                    "triangles_preserved": sum(surface["topology"]["triangles"] for surface in surfaces),
                    "vertices_preserved": sum(surface["vertices"] for surface in surfaces),
                    "indices_vertex_order_and_triangle_order_exact": True,
                    "normals_tangents_colors_exact": True, "material_and_metadata_bytes_exact": not detail["metadata_patches"],
                    "only_metadata_patches": detail["metadata_patches"], "collisions_exact": before["files"][resource]["collisions"],
                    "new_degenerate_triangles": 0, "winding_reversals": 0,
                    "engine_reloaded_raw_buffers_and_decoded_attributes_verified": True,
                    "original_AO_mesh_signatures_exact": True,
                    "maximum_position_error_per_component": max(surface["attributes"]["0"]["measured_max_abs_error"] for surface in surfaces),
                    "maximum_position_error_vector": max(surface["attributes"]["0"]["measured_max_vector_error"] for surface in surfaces),
                    "maximum_UV_error_per_component": max(surface["attributes"]["4"]["measured_max_abs_error"] for surface in surfaces),
                    "maximum_UV2_error_per_component": max(surface["attributes"]["5"]["measured_max_abs_error"] for surface in surfaces),
                    "originals_unchanged": True}
            actual = size_record(candidate)
            if actual != expected:
                raise ValueError(f"Candidate hash/size changed after validation: {resource}")
            original_size = size_record(original_entry)
            rows.append({"path": resource.removeprefix("res://"), "file": str(candidate_path),
                "beforeSha256": sha(original_entry), "afterSha256": sha(candidate),
                "beforeBytes": len(original_entry), "afterBytes": len(candidate),
                "beforeGzip9Bytes": original_size["gzip9_bytes"], "afterGzip9Bytes": actual["gzip9_bytes"],
                "pinnedDiskSha256": sha(disk), "pckContainerDiffersFromDisk": original_entry != disk,
                "checks": checks})
    result = {"schema": "lite-geometry-pack-replacements-v115-1", "sourcePck": str(pack),
        "sourcePckSha256": manifest["reference_pack"]["sha256"], "replacements": rows,
        "detailedManifest": str(manifest_path), "detailedManifestSha256": sha(manifest_bytes),
        "totals": {"beforeEntryBytes": sum(row["beforeBytes"] for row in rows),
                   "afterEntryBytes": sum(row["afterBytes"] for row in rows),
                   "beforeIndividualGzip9Bytes": sum(row["beforeGzip9Bytes"] for row in rows),
                   "afterIndividualGzip9Bytes": sum(row["afterGzip9Bytes"] for row in rows)},
        "integration": "Apply this complete list to lite only, without recompressing terrain again. All beforeSha256 values are actual entry hashes in sourcePck. Textures and runtime-derived pack changes are main-owned.",
        "measurementLimit": "Individual-entry gzip sums are not a measurement of the final whole PCK.gz, network transfer time, GPU performance or visual acceptance."}
    write_json(output_path, result)
    return result


def build(output: Path, *, godot: Path = DEFAULT_GODOT, reference_pack: Path = DEFAULT_PACK,
          position_step: float = 1 / 128, uv_step: float = 1 / 2048,
          uv2_step: float = 1 / 4096, inspect_only: bool = False) -> dict:
    for step in (position_step, uv_step, uv2_step):
        validate_step(step)
    godot, reference_pack = godot.resolve(strict=True), reference_pack.resolve(strict=True)
    originals, pack_info = freeze_inputs(reference_pack)
    source_stats = frozen_tree_stats()
    output = new_directory(output)
    write_json(output / "frozen-inputs.json", {resource: size_record(data) for resource, data in originals.items()})
    write_json(output / "frozen-source-tree.json", source_stats)
    before = run_inspector(output / "before", godot=godot, reference_pack=reference_pack,
                           files=[file_request(resource, source_path(resource), data) for resource, data in originals.items() if resource in PINS],
                           ao_path=source_path(AO_RESOURCE), dump=True)
    if inspect_only:
        if frozen_tree_stats() != source_stats:
            raise ValueError("Source tree changed during inspection")
        return before
    if before["ao"]["mesh_signature"] != mesh_signature(before, DETAIL, "SolidLimestoneGeology") or before["ao"]["terrain_signature"] != mesh_signature(before, TERRAIN, "ContinuousMeadow"):
        raise ValueError("Original AO does not match accepted source meshes; refusing rebinding")
    candidates = new_directory(output / "caches")
    replacement_paths, file_reports, selected_blobs = {}, {}, {}
    for resource, original_blob in originals.items():
        if resource not in PINS:
            continue
        raw = _unpack(original_blob)
        patched = bytearray(raw)
        ranges, surfaces = [], []
        for mesh in before["files"][resource]["meshes"]:
            for surface in mesh["surfaces"]:
                buffers, report = quantize_surface(surface, mesh["label"], position_step, uv_step, uv2_step)
                report["output_raw_sha256"] = {key: sha(value) for key, value in buffers.items()}
                for name in ("vertex_data", "attribute_data"):
                    source = read_buffer(surface, name)
                    if source == buffers[name]:
                        continue
                    patched, offset = patch_unique(patched, source, buffers[name])
                    ranges.append({"offset": offset, "length": len(source), "purpose": mesh["label"] + "/" + name})
                surfaces.append(report)
        metadata_patches = []
        if resource == SWARD:
            old_hash = PINS[TERRAIN]
            new_hash = sha(selected_blobs[TERRAIN])
            if before["files"][SWARD]["tree"]["."]["properties"]["metadata/terrain_sha256"] != old_hash:
                raise ValueError("Original far-sward terrain binding differs")
            patched, offset = patch_unique(patched, old_hash.encode(), new_hash.encode())
            patch = dict(offset=offset, length=64, purpose="metadata/terrain_sha256", before=old_hash, after=new_hash)
            ranges.append(patch)
            metadata_patches.append(patch)
        # Exact proof: outside explicitly enumerated attribute spans and the
        # 64-byte terrain SHA, every decompressed byte remains unchanged.
        cursor = 0
        for span in sorted(ranges, key=lambda item: item["offset"]):
            start, end = span["offset"], span["offset"] + span["length"]
            if start < cursor or raw[cursor:start] != patched[cursor:start]:
                raise ValueError("Overlapping patches or unexpected serialized byte change")
            cursor = end
        if raw[cursor:] != patched[cursor:] or len(raw) != len(patched):
            raise ValueError("Unexpected change outside geometry spans")
        selected, trials = pack_best(bytes(patched))
        baseline_repack = _pack(raw, 262144, 9)
        if len(selected) >= len(original_blob):
            raise ValueError(f"Quantized candidate is not smaller; inspect before integration: {resource}")
        target = candidates / Path(resource).name
        write_new(target, selected)
        replacement_paths[resource], selected_blobs[resource] = str(target), selected
        file_reports[resource] = {"artifact_path": str(target), "before": size_record(original_blob),
            "after": size_record(selected), "lossless_256k_zstd9_baseline_bytes": len(baseline_repack),
            "lossless_256k_zstd9_baseline_gzip9_bytes": size_record(baseline_repack)["gzip9_bytes"],
            "raw_bytes_before": len(raw), "raw_bytes_after": len(patched),
            "saved_bytes": len(original_blob) - len(selected), "raw_bytes_outside_declared_spans_exact": True,
            "changed_spans": ranges, "metadata_patches": metadata_patches, "compression_trials": trials, "surfaces": surfaces}
        print(json.dumps({"resource": resource, "before_bytes": len(original_blob), "candidate_bytes": len(selected),
                          "saved_bytes": len(original_blob) - len(selected)}), flush=True)
    after = run_inspector(output / "after", godot=godot, reference_pack=reference_pack,
                          files=[file_request(resource, Path(replacement_paths[resource]), data) for resource, data in selected_blobs.items()],
                          ao_path=source_path(AO_RESOURCE), dump=True)
    counts = compare_inspections(before, after, file_reports, sha(selected_blobs[TERRAIN]))
    ao_copy = bytearray(originals[AO_RESOURCE])
    ao_patches = []
    for key, resource, label in (("mesh_signature", DETAIL, "SolidLimestoneGeology"),
                                 ("terrain_signature", TERRAIN, "ContinuousMeadow")):
        old, new = before["ao"][key], mesh_signature(after, resource, label)
        if old != new:
            raise ValueError(f"Protected AO mesh signature changed: {key}; no signature bypass allowed")
    ao_target = candidates / "rock-occlusion.bin"
    write_new(ao_target, bytes(ao_copy))
    replacement_paths[AO_RESOURCE] = str(ao_target)
    ao_after = run_inspector(output / "ao-verify", godot=godot, reference_pack=reference_pack,
                             files=[], ao_path=ao_target, dump=False,
                             runtime_probe={"terrain": replacement_paths[TERRAIN], "detail": replacement_paths[DETAIL]})
    expected_ao = dict(before["ao"])
    for patch in ao_patches:
        expected_ao[patch["field"]] = patch["after"]
    if ao_after["ao"] != expected_ao:
        raise ValueError("AO fields other than all-channel signatures changed")
    if not ao_after.get("runtime_probe", {}).get("all_sample_indices_and_nonblue_attributes_exact"):
        raise ValueError("Actual runtime AO helper did not verify every visibility sample")
    for resource, data in originals.items():
        if source_path(resource).read_bytes() != data:
            raise ValueError(f"Original changed during processing: {resource}")
    if sha(reference_pack.read_bytes()) != pack_info["sha256"]:
        raise ValueError("Read-only dependency pack changed during processing")
    if frozen_tree_stats() != source_stats:
        raise ValueError("Original art/script/shader/project/import-cache tree changed during processing")
    before_bytes = sum(row["before"]["bytes"] for row in file_reports.values())
    after_bytes = sum(row["after"]["bytes"] for row in file_reports.values())
    manifest = {"schema": "lite-geometry-v115-1", "status": "offline_validated_candidate",
        "replacements": replacement_paths, "files": file_reports,
        "totals": {"before_bytes": before_bytes, "after_bytes": after_bytes,
            "saved_bytes": before_bytes - after_bytes, "saved_percent": 100 * (before_bytes - after_bytes) / before_bytes,
            "before_individual_gzip9_bytes": sum(row["before"]["gzip9_bytes"] for row in file_reports.values()),
            "after_individual_gzip9_bytes": sum(row["after"]["gzip9_bytes"] for row in file_reports.values()),
            "saved_individual_gzip9_bytes": sum(row["before"]["gzip9_bytes"] - row["after"]["gzip9_bytes"] for row in file_reports.values()),
            "lossless_256k_zstd9_baseline_bytes": sum(row["lossless_256k_zstd9_baseline_bytes"] for row in file_reports.values()),
            "lossless_256k_zstd9_baseline_gzip9_bytes": sum(row["lossless_256k_zstd9_baseline_gzip9_bytes"] for row in file_reports.values()),
            "raw_bytes_before": sum(row["raw_bytes_before"] for row in file_reports.values()),
            "raw_bytes_after": sum(row["raw_bytes_after"] for row in file_reports.values())},
        "verified_counts": counts, "engine": after["engine"], "reference_pack": pack_info,
        "settings": dict(position_step=position_step, uv_step=uv_step, uv2_step=uv2_step,
            exact_all_attribute_meshes=sorted(EXACT_MESHES), preserve_position_seams=True,
            max_face_normal_delta_degrees=5, triangle_area_ratio_bounds=[.9, 1.1],
            packing_selection="Minimum individually gzipped bytes; raw RSCC bytes are the tiebreaker"),
        "ao": {"resource": AO_RESOURCE, "before": size_record(originals[AO_RESOURCE]), "after": size_record(bytes(ao_copy)),
            "patches": ao_patches, "visibility_and_sampling_geometry_exact": True,
            "reason": "All rock/terrain attributes, signatures and original AO bytes are exact. No AO bake, header rewrite or signature-check bypass.",
            "runtime_probe": ao_after.get("runtime_probe")},
        "source_files_unchanged": True, "frozen_source_tree_files": len(source_stats),
        "frozen_source_tree_stat_unchanged": True, "normals_tangents_colors_indices_collisions_exact": True,
        "integration": {"atomic_replacement_required": list(replacement_paths), "original_tier": "Do not apply replacements to the original pack",
            "runtime_decoder_required": False, "scene_shader_animation_source_changes": False,
            "cache_source_signatures": "Preserved. These describe procedural provenance; manifest adds exact original/candidate file hashes. Do not edit cache helper or bake sources just for this copy pass.",
            "far_sward_binding": "Candidate metadata/terrain_sha256 points to candidate terrain.scn whole-file SHA; rebinding is mandatory if main recompresses terrain again.",
            "ao_binding": "Include the generated AO copy with detail and terrain. Any further mesh/UV changes require recomputing signatures and validating the actual sample geometry.",
            "audit_notes": "Vertex/index order and far-sward corner root_ranges remain unchanged. Root/anchor metadata is original; maximum non-AO render-position deviation is recorded per surface."},
        "limits": ["No gameplay scene, browser, service or full export was run.",
            "No Web transfer, frame timing, GPU or visual acceptance was measured.",
            "Gzip totals are sums of individually gzipped resources, not the combined final PCK.gz.",
            "Decoded mesh/buffer sizes, triangle count and collision memory do not decrease; gains are encoded payload only.",
            "Whole scene objects outside these six caches, animation, water, fauna, dragon, walking and Boss logic require main's integration/visual checks."]}
    write_json(output / "manifest.json", manifest)
    write_pack_manifest(output / "manifest.json", output / "pack-replacements.json")
    print(json.dumps({"manifest": str(output / "manifest.json"), "totals": manifest["totals"], "verified_counts": counts}), flush=True)
    return manifest


def decoded_values(surface: dict, channel: int) -> np.ndarray:
    """Read the pinned engine's independent, fingerprinted decoded arrays."""
    data = Path(surface["decoded"][str(channel)]).read_bytes()
    if sha(data) != surface["decoded_sha256"][str(channel)]:
        raise ValueError("Decoded inspection fingerprint mismatch")
    components = {0: 3, 1: 3, 2: 4, 3: 4, 4: 2, 5: 2}[channel]
    if len(data) != int(surface["vertex_count"]) * components * 4:
        raise ValueError("Decoded attribute length mismatch")
    result = np.frombuffer(data, dtype="<f4").reshape(-1, components)
    if not np.isfinite(result).all():
        raise ValueError("Non-finite engine-decoded attribute")
    return result


def triangle_indices(surface: dict) -> np.ndarray:
    data = read_buffer(surface, "index_data")
    count = int(surface["index_count"])
    vertices = int(surface["vertex_count"])
    if not count:
        if data or vertices % 3:
            raise ValueError("Invalid unindexed triangles")
        return np.arange(vertices, dtype=np.uint32).reshape(-1, 3)
    width, remainder = divmod(len(data), count)
    if remainder or width not in (2, 4) or count % 3:
        raise ValueError("Unsupported index format")
    indices = np.frombuffer(data, dtype=f"<u{width}").reshape(-1, 3)
    if indices.max(initial=0) >= vertices:
        raise ValueError("Out-of-bounds triangle index")
    return indices


def normal_angles(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x, y = a.astype(np.float64), b.astype(np.float64)
    lengths = np.linalg.norm(x, axis=1) * np.linalg.norm(y, axis=1)
    if not np.isfinite(lengths).all() or (lengths <= 0).any():
        raise ValueError("Invalid lighting normal")
    cosine = np.clip(np.einsum("ij,ij->i", x, y) / lengths, -1, 1)
    cosine[(a == b).all(axis=1)] = 1
    return np.degrees(np.arccos(cosine))


def leaf_classes(uv: np.ndarray) -> np.ndarray:
    return (uv[:, 0] < -900).astype(np.uint8) + (uv[:, 0] < -1800).astype(np.uint8)


def canonical_leaf_uv(uv: np.ndarray, indices: np.ndarray) -> np.ndarray:
    classes = leaf_classes(uv)
    triangle_classes = classes[indices]
    if (triangle_classes != triangle_classes[:, :1]).any():
        raise ValueError("Cannot canonicalize a triangle crossing a shader UV branch boundary")
    result = np.zeros_like(uv)
    result[:, 0] = classes.astype(np.float32) * -1024
    return result


def verify_leaf_shader_contract(reference_pack: Path) -> dict:
    """Only this pinned shader and its inspected includes justify unused UV/TBN."""
    shader_path = GODOT_ROOT / LEAF_SHADER.removeprefix("res://")
    source = shader_path.read_bytes()
    if sha(source) != LEAF_SHADER_PIN:
        raise ValueError("Leaf shader changed: canonical UV/encoding basis must be re-audited")
    inventory = read_pack(reference_pack, verify=True)
    entries = {e["path"].removeprefix("res://"): e for e in inventory["entries"]}
    fingerprints = {}
    pending = [LEAF_SHADER]
    with reference_pack.open("rb") as stream:
        while pending:
            resource = pending.pop()
            if resource in fingerprints:
                continue
            data = (GODOT_ROOT / resource.removeprefix("res://")).read_bytes()
            entry = entries[resource.removeprefix("res://")]
            stream.seek(entry["offset"])
            if stream.read(entry["bytes"]) != data:
                raise ValueError("Shader dependency pack bytes differ from reviewed source")
            content = re.sub(r"(?<!:)//[^\n]*|/\*.*?\*/", "", data.decode("utf-8"), flags=re.S)
            if re.search(r"\b(TANGENT|BINORMAL|NORMAL_MAP)\b", content):
                raise ValueError("Shader consumes tangent basis; cannot use canonical encoding frame")
            if resource != LEAF_SHADER and re.search(r"\bUV2?\b", content):
                raise ValueError("Include consumes implicit mesh UV; manual review required")
            pending.extend(re.findall(r'#include\s+"([^"]+)"', content))
            fingerprints[resource] = sha(data)
    return {"shader_and_include_sha256": fingerprints, "leaf_uv_y_unused": True,
            "leaf_uv_x_only_class_thresholds": [-900, -1800], "tangent_binormal_not_consumed": True,
            "leaf_UV2_x_is_pigment_density": True, "alpha_wind_roughness_and_AO_exact": True}


def strided_uint16(data: bytearray, count: int, offset: int, stride: int, components: int) -> np.ndarray:
    if count <= 0 or offset < 0 or stride < components * 2 or offset + (count - 1) * stride + components * 2 > len(data):
        raise ValueError("Unsupported native packed attribute layout")
    return np.ndarray((count, components), dtype="<u2", buffer=data, offset=offset, strides=(stride, 2))


def canonical_normal_encoding(normals: np.ndarray, divisions: int = 1024) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stock Godot axis/angle TBN with a deterministic, shader-unused twist.

    Native encoding is a rotation, not three independent vectors. Source normals
    stay bounded while unused tangent twist is removed. No custom runtime decoder.
    This mathematical decoder is additionally checked against actual Godot output.
    """
    n = normals.astype(np.float64)
    lengths = np.linalg.norm(n, axis=1)
    if not np.isfinite(n).all() or (lengths < .5).any() or divisions < 256:
        raise ValueError("Invalid canonical normal input")
    n /= lengths[:, None]
    theta = np.rint(np.arccos(np.clip(n[:, 2], -1, 1)) / math.pi * divisions) / divisions * math.pi
    phi = np.arctan2(-n[:, 0], n[:, 1])
    phi = np.rint(phi / (2 * math.pi) * divisions) / divisions * (2 * math.pi)
    axis = np.stack((np.cos(phi), np.sin(phi)), axis=1)
    axis /= np.abs(axis).sum(axis=1)[:, None]
    packed_axis = np.rint((axis * .5 + .5) * 65535).astype("<u2")
    packed_angle = np.clip(np.rint((.5 + .5 * theta / math.pi) * 65535), 32768, 65535).astype("<u2")
    # Independent CPU reconstruction of Godot's oct-axis / rotation row 2.
    xy = packed_axis.astype(np.float64) / 65535 * 2 - 1
    z = 1 - np.abs(xy).sum(axis=1)
    negative = z < 0
    xy[negative] = (1 - np.abs(xy[negative, ::-1])) * np.where(xy[negative] >= 0, 1, -1)
    axis3 = np.column_stack((xy, z))
    axis3 /= np.linalg.norm(axis3, axis=1)[:, None]
    angle = np.abs(packed_angle.astype(np.float64) / 65535 * 2 - 1) * math.pi
    sine, cosine = np.sin(angle), np.cos(angle)
    ax, ay, az = axis3.T
    predicted = np.column_stack((az * ax * (1 - cosine) - ay * sine,
                                 az * ay * (1 - cosine) + ax * sine,
                                 cosine + az * az * (1 - cosine))).astype("<f4")
    if normal_angles(normals, predicted).max(initial=0) > .25:
        raise ValueError("Canonical native normal exceeds quarter-degree bound")
    return packed_axis, packed_angle, predicted


def write_uv_storage(data: bytearray, surface: dict, channel: int, values: np.ndarray) -> None:
    count, stride = int(surface["vertex_count"]), int(surface["attribute_stride"])
    offset = int(surface["offsets"][str(channel)])
    if int(surface["format"]) & NATIVE_FLAG:
        target = strided_uint16(data, count, offset, stride, 2)
        scales = np.asarray(surface["uv_scale_values"], dtype=np.float64)
        if (scales == 0).all():
            encoded = values.astype(np.float64) * 65535
        else:
            scale = scales[(0 if channel == 4 else 2): (2 if channel == 4 else 4)]
            if ((scale == 0) & (values != 0).any(axis=0)).any():
                raise ValueError("Native zero scale cannot represent requested UV")
            encoded = np.divide(values, scale, out=np.zeros(values.shape, dtype=np.float64), where=scale != 0)
            encoded = (encoded + .5) * 65535
        if encoded.min(initial=0) < -.001 or encoded.max(initial=0) > 65535.001:
            raise ValueError("Native UV outside original encoding range")
        target[:] = np.clip(np.rint(encoded), 0, 65535).astype("<u2")
    else:
        strided_floats(data, count, offset, stride, 2)[:] = values


def strong_surface(source: dict, draft: dict, label: str, leaf: bool) -> tuple[dict, dict]:
    count = int(source["vertex_count"])
    output = {k: bytearray(read_buffer(draft, k)) for k in ("vertex_data", "attribute_data", "index_data")}
    native = bool(int(draft["format"]) & NATIVE_FLAG)
    if native != (label not in FLOAT_POSITION_MESHES):
        raise ValueError("Unexpected native packing assignment")
    if native and not leaf:
        raise ValueError("Native normal frame is restricted to the reviewed leaf shader")
    report = {"label": label, "vertices": count, "indices": int(source["index_count"]),
              "native_attribute_packing": native, "leaf_shader_contract": leaf,
              "position_policy": "native_AABB_UNORM16" if native else "original_float32_exact",
              "normals_policy": "stock_axis_angle_canonical_twist_1024" if native else "original_exact",
              "uv_policy": "shader_equivalent_triangle_class" if leaf else ("exact" if label == "ContinuousMeadow" else "binary_grid_1/256"),
              "uv2_step": 0 if label == "ContinuousMeadow" else (1 / 64 if leaf else 1 / 128),
              "rgb_policy": "32_level_palette" if leaf else "original_exact", "alpha_exact": True}
    if label != "ContinuousMeadow":
        uv = decoded_values(source, 4)
        proposed = canonical_leaf_uv(uv, triangle_indices(source)) if leaf else quantize_values(uv, 1 / 256)
        if not leaf and ((uv[:, 0] < 0) != (proposed[:, 0] < 0)).any():
            raise ValueError("Rock atlas enable/disable UV sign changed")
        write_uv_storage(output["attribute_data"], draft, 4, proposed)
        uv2 = decoded_values(source, 5)
        proposed = quantize_values(uv2, report["uv2_step"])
        write_uv_storage(output["attribute_data"], draft, 5, proposed)
    if leaf:
        source_colors = np.ndarray((count, 4), dtype=np.uint8, buffer=read_buffer(source, "attribute_data"),
                                  offset=int(source["offsets"]["3"]), strides=(int(source["attribute_stride"]), 1))
        colors = np.ndarray((count, 4), dtype=np.uint8, buffer=output["attribute_data"],
                            offset=int(draft["offsets"]["3"]), strides=(int(draft["attribute_stride"]), 1))
        colors[:] = source_colors
        colors[:, :3] = np.rint(np.rint(source_colors[:, :3].astype(np.float64) * 31 / 255) * 255 / 31).astype(np.uint8)
        if np.abs(colors[:, :3].astype(np.int16) - source_colors[:, :3]).max(initial=0) > 4:
            raise ValueError("RGB palette exceeds four-byte-value bound")
    if native:
        if int(draft["vertex_stride"]) != 8 or int(draft["offsets"]["1"]) != count * 8:
            raise ValueError("Unsupported pinned-engine axis/angle storage layout")
        axes, angle, prediction = canonical_normal_encoding(decoded_values(source, 1))
        strided_uint16(output["vertex_data"], count, count * 8, 4, 2)[:] = axes
        strided_uint16(output["vertex_data"], count, 6, 8, 1)[:, 0] = angle
        report["cpu_normal_prediction_sha256"] = sha(prediction.tobytes())
    buffers = {k: bytes(v) for k, v in output.items()}
    report["output_raw_sha256"] = {k: sha(v) for k, v in buffers.items()}
    return buffers, report


def compare_strong_inspections(before: dict, after: dict, file_reports: dict, terrain_sha: str) -> dict:
    counts = dict(nodes=0, meshes=0, surfaces=0, collision_shapes=0, collision_corners=0, vertices=0, triangles=0)
    for resource, a in before["files"].items():
        b = after["files"][resource]
        tree = copy.deepcopy(a["tree"])
        if resource == SWARD:
            tree["."]["properties"]["metadata/terrain_sha256"] = terrain_sha
        if tree != b["tree"] or a["node_count"] != b["node_count"] or a["collisions"] != b["collisions"]:
            raise ValueError(f"Object/material/metadata/collision contract changed: {resource}")
        if len(a["meshes"]) != len(b["meshes"]):
            raise ValueError("Mesh count changed")
        counts["nodes"] += a["node_count"]
        counts["collision_shapes"] += len(a["collisions"])
        counts["collision_corners"] += sum(row["corners"] for row in a["collisions"].values())
        reports = iter(file_reports[resource]["surfaces"])
        for x, y in zip(a["meshes"], b["meshes"]):
            if x["label"] != y["label"] or x["properties"] != y["properties"] or len(x["surfaces"]) != len(y["surfaces"]):
                raise ValueError("Mesh surface/material/metadata property changed")
            counts["meshes"] += 1
            for s, t in zip(x["surfaces"], y["surfaces"]):
                report = next(reports)
                label, native, leaf = x["label"], report["native_attribute_packing"], report["leaf_shader_contract"]
                if native != (label not in FLOAT_POSITION_MESHES):
                    raise ValueError("Protected sampling/brush position packing changed")
                shader = a["tree"][label]["properties"]["material_override"][1]["shader"]
                if leaf != (shader[1] == LEAF_SHADER) or (leaf and shader[2] != LEAF_SHADER_PIN):
                    raise ValueError("Leaf semantic proof assigned to an unreviewed material")
                if report["label"] != label or bool(int(t["format"]) & NATIVE_FLAG) != native:
                    raise ValueError("Surface assignment changed")
                if int(t["format"]) != (int(s["format"]) | (NATIVE_FLAG if native else 0)):
                    raise ValueError("Unexpected ArrayMesh format change")
                allowed = {"format", "aabb", "uv_scale"} if native else set()
                if {k: v for k, v in s["fixed_properties"].items() if k not in allowed} != {k: v for k, v in t["fixed_properties"].items() if k not in allowed}:
                    raise ValueError("Non-encoding surface property changed")
                for key in ("surface", "vertex_count", "index_count"):
                    if s[key] != t[key]:
                        raise ValueError("Surface/index/vertex topology changed")
                for channel in range(6, 13):
                    if s["channel_hashes"][str(channel)] != t["channel_hashes"][str(channel)]:
                        raise ValueError("Index/custom/bone data changed")
                for key in ("vertex_data", "attribute_data", "index_data"):
                    if sha(read_buffer(t, key)) != report["output_raw_sha256"][key]:
                        raise ValueError("Engine reloaded unexpected raw buffer")
                if set(s["decoded"]) != set(t["decoded"]):
                    raise ValueError("Present/absent attribute channels changed")
                original = {int(i): decoded_values(s, int(i)) for i in s["decoded"]}
                actual = {int(i): decoded_values(t, int(i)) for i in t["decoded"]}
                error = np.abs(actual[0].astype(np.float64) - original[0])
                max_position = float(np.linalg.norm(error, axis=1).max(initial=0))
                if max_position > .004 or (not native and s["channel_hashes"]["0"] != t["channel_hashes"]["0"]):
                    raise ValueError("Position quantization exceeds .004 units / exact-position policy")
                _, topology = triangle_checks(original[0], actual[0], triangle_indices(s))
                if topology["new_degenerate_triangles"] or topology["winding_reversals"]:
                    raise ValueError("Native quantization collapses or reverses an original triangle")
                # Aggressive lite permits shape-plane variation on tiny leaf
                # triangles; authored lighting normals have a separate tight bound.
                if topology["source_degenerate_triangles"]:
                    degenerate = np.linalg.norm(triangle_normals(original[0], triangle_indices(s)), axis=1) == 0
                    if not np.array_equal(original[0][triangle_indices(s)[degenerate]], actual[0][triangle_indices(s)[degenerate]]):
                        raise ValueError("Original degenerate triangle coordinates changed")
                angles = normal_angles(original[1], actual[1])
                if angles.max(initial=0) > .25:
                    raise ValueError(f"Decoded Godot lighting normal exceeds .25 degrees: {label}: {angles.max()}")
                if not native:
                    for ch in (1, 2):
                        if s["channel_hashes"][str(ch)] != t["channel_hashes"][str(ch)]:
                            raise ValueError("Protected normal/tangent changed")
                else:
                    prediction = canonical_normal_encoding(original[1])[2]
                    if np.abs(prediction.astype(np.float64) - actual[1]).max(initial=0) > .000005:
                        raise ValueError("Independent axis/angle decoder disagrees with actual Godot")
                original_colors = original.get(3, np.empty((0, 4), dtype="<f4"))
                actual_colors = actual.get(3, np.empty((0, 4), dtype="<f4"))
                color_error = np.abs(actual_colors.astype(np.float64) - original_colors)
                if not np.array_equal(original_colors[:, 3], actual_colors[:, 3]) or color_error[:, :3].max(initial=0) > (4 / 255 + 1e-7 if leaf else 0):
                    raise ValueError("Wind/roughness/AO alpha or bounded RGB policy changed")
                if leaf:
                    canonical_leaf_uv(original[4], triangle_indices(s))
                    canonical_leaf_uv(actual[4], triangle_indices(s))
                    if not np.array_equal(leaf_classes(original[4]), leaf_classes(actual[4])):
                        raise ValueError("Shader UV branch / interpolation changed")
                elif label == "ContinuousMeadow":
                    if s["channel_hashes"] != t["channel_hashes"]:
                        raise ValueError("Terrain must be exact in all channels")
                else:
                    if np.abs(actual[4].astype(np.float64) - original[4]).max(initial=0) > 1 / 512:
                        raise ValueError("Rock atlas UV quantization bound exceeded")
                    if not np.array_equal(original[4][:, 0] < 0, actual[4][:, 0] < 0):
                        raise ValueError("Rock atlas tag changed")
                uv2_error = float(np.abs(actual[5].astype(np.float64) - original[5]).max(initial=0))
                uv2_bound = report["uv2_step"] / 2 + (1 / 65535 if native else 0)
                if uv2_error > uv2_bound:
                    raise ValueError(f"UV2 bound exceeded: {label}: {uv2_error} > {uv2_bound}")
                report.update(topology=topology, position_max_component_error=float(error.max(initial=0)),
                              position_max_vector_error=max_position, normal_max_angle_degrees=float(angles.max(initial=0)),
                              rgb_max_component_error=float(color_error[:, :3].max(initial=0)),
                              uv_max_component_error=float(np.abs(actual[4].astype(np.float64) - original[4]).max(initial=0)),
                              uv_error_bound=None if leaf else (0 if label == "ContinuousMeadow" else 1 / 512),
                              uv_semantic_classes_and_triangle_interpolation_exact=leaf,
                              uv2_max_component_error=uv2_error, uv2_error_bound=uv2_bound,
                              decoded_channel_sha256_before={str(i): sha(original[i].tobytes()) for i in original},
                              decoded_channel_sha256_after={str(i): sha(actual[i].tobytes()) for i in actual},
                              original_gpu_buffer_bytes=sum(s["raw_buffers"][k]["bytes"] for k in s["raw_buffers"]),
                              candidate_gpu_buffer_bytes=sum(t["raw_buffers"][k]["bytes"] for k in t["raw_buffers"]))
                counts["surfaces"] += 1
                counts["vertices"] += s["vertex_count"]
                counts["triangles"] += topology["triangles"]
    return counts


def verify_declared_spans(before: bytes, after: bytes, spans: list[dict]) -> None:
    if len(before) != len(after):
        raise ValueError("Same-length post-encoding patch required")
    cursor = 0
    for span in sorted(spans, key=lambda v: v["offset"]):
        start, end = span["offset"], span["offset"] + span["length"]
        if start < cursor or end > len(before) or before[cursor:start] != after[cursor:start]:
            raise ValueError("Changes outside declared attribute/hash spans")
        cursor = end
    if before[cursor:] != after[cursor:]:
        raise ValueError("Undeclared suffix change")


def write_strong_pack_manifest(manifest_path: Path, output_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["status"] != "offline_validated_candidate" or set(manifest["replacements"]) != {*PINS, AO_RESOURCE}:
        raise ValueError("Incomplete/unvalidated strong candidate")
    directory = manifest_path.parent
    before = json.loads((directory / "before/inspection.json").read_text(encoding="utf-8"))
    after = json.loads((directory / "after/inspection.json").read_text(encoding="utf-8"))
    audited = copy.deepcopy(manifest["files"])
    counts = compare_strong_inspections(before, after, audited, manifest["files"][TERRAIN]["after"]["sha256"])
    if counts != manifest["verified_counts"] or audited != manifest["files"]:
        raise ValueError("Recorded structural/error proofs differ from independent recheck")
    probe = manifest["ao"]["runtime_probe"]
    if not probe["applied"] or not probe["all_sample_indices_and_nonblue_attributes_exact"]:
        raise ValueError("Require actual AO signature/sample acceptance")
    pack = Path(manifest["reference_pack"]["path"])
    if sha(pack.read_bytes()) != manifest["reference_pack"]["sha256"]:
        raise ValueError("Original dependency pack changed")
    inventory = read_pack(pack, verify=True)
    entries = {row["path"].removeprefix("res://"): row for row in inventory["entries"]}
    rows = []
    with pack.open("rb") as stream:
        for resource, artifact in manifest["replacements"].items():
            candidate_path = Path(artifact).resolve(strict=True)
            if not candidate_path.is_relative_to(SCOPE):
                raise ValueError("Candidate scope violation")
            candidate = candidate_path.read_bytes()
            disk = source_path(resource).read_bytes()
            entry = entries[resource.removeprefix("res://")]
            stream.seek(entry["offset"])
            original = stream.read(entry["bytes"])
            if resource == AO_RESOURCE:
                if sha(disk) != AO_PIN or original != disk:
                    raise ValueError("Original AO changed")
                verify_declared_spans(disk, candidate, manifest["ao"]["patches"])
                expected = manifest["ao"]["after"]
                checks = dict(manifest["ao"])
                checks["kind"] = "signature_only_rebind_exact_original_visibility_and_sampling_geometry"
            else:
                if sha(disk) != PINS[resource] or _unpack(original) != _unpack(disk):
                    raise ValueError("Actual PCK content is not pinned original cache")
                row = manifest["files"][resource]
                draft = Path(row["patch_base_path"]).read_bytes()
                if sha(draft) != row["patch_base_sha256"]:
                    raise ValueError("Native intermediate changed")
                verify_declared_spans(_unpack(draft), _unpack(candidate), row["changed_spans"])
                expected = row["after"]
                checks = {"kind": "stock_ArrayMesh_RSCC_native_packing_and_bounded_attributes",
                          "nodes_before_after": [before["files"][resource]["node_count"], after["files"][resource]["node_count"]],
                          "topology_vertex_index_triangle_order_exact": True,
                          "collision_arrays_and_node_material_mesh_metadata_exact": True,
                          "only_metadata_patches": row["metadata_patches"],
                          "collisions_exact": before["files"][resource]["collisions"],
                          "surfaces": row["surfaces"], "signature_bypass": False,
                          "new_degenerate_triangles": 0, "winding_reversals": 0}
            if size_record(candidate) != expected:
                raise ValueError("Candidate bytes changed after verification")
            original_size = size_record(original)
            rows.append({"path": resource.removeprefix("res://"), "file": str(candidate_path),
                         "beforeSha256": sha(original), "afterSha256": sha(candidate),
                         "beforeBytes": len(original), "afterBytes": len(candidate),
                         "beforeGzip9Bytes": original_size["gzip9_bytes"], "afterGzip9Bytes": expected["gzip9_bytes"],
                         "pinnedDiskSha256": sha(disk), "pckContainerDiffersFromDisk": original != disk,
                         "checks": checks})
    result = {"schema": "lite-geometry-pack-replacements-v115-1", "sourcePck": str(pack),
              "sourcePckSha256": manifest["reference_pack"]["sha256"], "replacements": rows,
              "detailedManifest": str(manifest_path), "detailedManifestSha256": sha(manifest_path.read_bytes()),
              "totals": {"beforeEntryBytes": sum(r["beforeBytes"] for r in rows),
                         "afterEntryBytes": sum(r["afterBytes"] for r in rows),
                         "beforeIndividualGzip9Bytes": sum(r["beforeGzip9Bytes"] for r in rows),
                         "afterIndividualGzip9Bytes": sum(r["afterGzip9Bytes"] for r in rows)},
              "integration": "Apply ALL seven together to lite only. Keep texture trial encodes. Do not recompress terrain after far-sward SHA binding. Do not mix old detail with new AO or bypass signatures.",
              "measurementLimit": "Individual-entry gzip sums, not final whole PCK.gz, network speed, GPU timing or visual acceptance."}
    write_json(output_path, result)
    return result


def build_strong(output: Path, *, godot: Path = DEFAULT_GODOT, reference_pack: Path = DEFAULT_PACK) -> dict:
    godot, reference_pack = godot.resolve(strict=True), reference_pack.resolve(strict=True)
    originals, pack_info = freeze_inputs(reference_pack)
    source_stats = frozen_tree_stats()
    shader_contract = verify_leaf_shader_contract(reference_pack)
    output = new_directory(output)
    write_json(output / "frozen-inputs.json", {r: size_record(v) for r, v in originals.items()})
    write_json(output / "frozen-source-tree.json", source_stats)
    before = run_inspector(output / "before", godot=godot, reference_pack=reference_pack,
                           files=[file_request(r, source_path(r), v) for r, v in originals.items() if r in PINS],
                           ao_path=source_path(AO_RESOURCE), dump=True, native_pack=True,
                           native_basis_safe=True, canonical_leaf_uv=True)
    if mesh_signature(before, DETAIL, "SolidLimestoneGeology") != before["ao"]["mesh_signature"] or mesh_signature(before, TERRAIN, "ContinuousMeadow") != before["ao"]["terrain_signature"]:
        raise ValueError("Original AO signatures invalid: refusing rebind")
    targets = new_directory(output / "caches")
    replacements, blobs, files = {}, {}, {}
    for resource in PINS:
        source = before["files"][resource]
        draft_row = before["native_drafts"][resource]
        # No native position packing for brush, and terrain must be a pure
        # container change. Use disk originals directly for both whole scenes.
        exact_scene = resource in (TERRAIN, "res://assets/baked/v77/brush.scn")
        base_path = source_path(resource) if exact_scene else Path(draft_row["path"])
        base_blob = base_path.read_bytes()
        if sha(base_blob) != (PINS[resource] if exact_scene else draft_row["sha256"]):
            raise ValueError("Input/native draft fingerprint mismatch")
        draft = source if exact_scene else draft_row["snapshot"]
        raw = _unpack(base_blob)
        patched, spans, surface_reports = bytearray(raw), [], []
        for mesh, staged in zip(source["meshes"], draft["meshes"]):
            label = mesh["label"]
            if label != staged["label"]:
                raise ValueError("Native staging mesh order changed")
            material = source["tree"][label]["properties"]["material_override"]
            shader = material[1]["shader"]
            leaf = shader[1] == LEAF_SHADER
            if leaf and shader[2] != LEAF_SHADER_PIN:
                raise ValueError("Engine loaded unreviewed leaf shader")
            for a, b in zip(mesh["surfaces"], staged["surfaces"]):
                buffers, row = strong_surface(a, b, label, leaf)
                for name in ("vertex_data", "attribute_data"):
                    original_buffer = read_buffer(b, name)
                    if original_buffer != buffers[name]:
                        patched, offset = patch_unique(patched, original_buffer, buffers[name])
                        spans.append(dict(offset=offset, length=len(original_buffer), purpose=f"{label}/{name}"))
                surface_reports.append(row)
        metadata = []
        if resource == SWARD:
            if source["tree"]["."]["properties"]["metadata/terrain_sha256"] != PINS[TERRAIN]:
                raise ValueError("Original far-sward terrain binding differs")
            patched, offset = patch_unique(patched, PINS[TERRAIN].encode(), sha(blobs[TERRAIN]).encode())
            metadata.append(dict(offset=offset, length=64, purpose="metadata/terrain_sha256", before=PINS[TERRAIN], after=sha(blobs[TERRAIN])))
            spans.extend(metadata)
        verify_declared_spans(raw, patched, spans)
        candidate, trials = pack_best(bytes(patched))
        target = targets / Path(resource).name
        write_new(target, candidate)
        replacements[resource], blobs[resource] = str(target), candidate
        files[resource] = dict(artifact_path=str(target), before=size_record(originals[resource]), after=size_record(candidate),
                               patch_base_path=str(base_path), patch_base_sha256=sha(base_blob),
                               original_decompressed_bytes=len(_unpack(originals[resource])), candidate_decompressed_bytes=len(patched),
                               changed_spans=spans, metadata_patches=metadata, surfaces=surface_reports, compression_trials=trials)
        print(json.dumps({"strong_resource": resource, "before_gzip9": files[resource]["before"]["gzip9_bytes"],
                          "candidate_gzip9": files[resource]["after"]["gzip9_bytes"]}), flush=True)
    write_json(output / "geometry-stage.json", {"files": files, "replacements": replacements})
    after = run_inspector(output / "after", godot=godot, reference_pack=reference_pack,
                          files=[file_request(r, Path(replacements[r]), v) for r, v in blobs.items()],
                          ao_path=source_path(AO_RESOURCE), dump=True, allow_compressed=True)
    counts = compare_strong_inspections(before, after, files, sha(blobs[TERRAIN]))
    old_signature = before["ao"]["mesh_signature"]
    new_signature = mesh_signature(after, DETAIL, "SolidLimestoneGeology")
    if old_signature == new_signature:
        raise ValueError("Strong rock UV change must produce a new actual all-channel signature")
    if mesh_signature(before, TERRAIN, "ContinuousMeadow") != mesh_signature(after, TERRAIN, "ContinuousMeadow"):
        raise ValueError("AO terrain changed")
    ao_copy, offset = patch_unique(originals[AO_RESOURCE], old_signature.encode(), new_signature.encode())
    ao_patches = [dict(offset=offset, length=64, field="mesh_signature", before=old_signature, after=new_signature)]
    verify_declared_spans(originals[AO_RESOURCE], ao_copy, ao_patches)
    ao_target = targets / "rock-occlusion.bin"
    write_new(ao_target, bytes(ao_copy))
    replacements[AO_RESOURCE] = str(ao_target)
    ao_after = run_inspector(output / "ao-verify", godot=godot, reference_pack=reference_pack,
                             files=[], ao_path=ao_target, dump=False,
                             runtime_probe={"terrain": replacements[TERRAIN], "detail": replacements[DETAIL]})
    expected = copy.deepcopy(before["ao"])
    expected["mesh_signature"] = new_signature
    if ao_after["ao"] != expected or not ao_after["runtime_probe"]["all_sample_indices_and_nonblue_attributes_exact"]:
        raise ValueError("AO visibility/prefix/sampling metadata changed or actual runtime rejected mapping")
    for r, v in originals.items():
        if source_path(r).read_bytes() != v:
            raise ValueError("Frozen original changed")
    if sha(reference_pack.read_bytes()) != pack_info["sha256"] or frozen_tree_stats() != source_stats:
        raise ValueError("Original pack/source/art/script/shader/import cache changed")
    surfaces = [s for f in files.values() for s in f["surfaces"]]
    manifest = {"schema": "lite-geometry-strong-v115-1", "status": "offline_validated_candidate",
                "replacements": replacements, "files": files, "verified_counts": counts,
                "reference_pack": pack_info, "engine": after["engine"], "shader_contract": shader_contract,
                "settings": {"native_flag": NATIVE_FLAG, "position_max_vector_bound": .004,
                             "normal_max_angle_bound_degrees": .25, "rock_UV_step": 1 / 256,
                             "leaf_UV2_step": 1 / 64, "rock_UV2_step": 1 / 128, "leaf_RGB_levels": 32,
                             "exact_position_and_normal_meshes": sorted(FLOAT_POSITION_MESHES),
                             "triangle_indices_vertex_count_order_collision_exact": True,
                             "original_five_degree_triangle_guard": "Fallback only. Strong uses zero new degenerates/reversals plus .004-unit position / .25-degree authored normal bounds; all face-plane/area deltas reported."},
                "totals": {"before_bytes": sum(f["before"]["bytes"] for f in files.values()),
                           "after_bytes": sum(f["after"]["bytes"] for f in files.values()),
                           "before_individual_gzip9_bytes": sum(f["before"]["gzip9_bytes"] for f in files.values()),
                           "after_individual_gzip9_bytes": sum(f["after"]["gzip9_bytes"] for f in files.values()),
                           "original_gpu_buffer_bytes": sum(s["original_gpu_buffer_bytes"] for s in surfaces),
                           "candidate_gpu_buffer_bytes": sum(s["candidate_gpu_buffer_bytes"] for s in surfaces),
                           "original_decompressed_bytes": sum(f["original_decompressed_bytes"] for f in files.values()),
                           "candidate_decompressed_bytes": sum(f["candidate_decompressed_bytes"] for f in files.values())},
                "ao": {"resource": AO_RESOURCE, "before": size_record(originals[AO_RESOURCE]), "after": size_record(bytes(ao_copy)),
                       "patches": ao_patches, "signature_bypass": False, "visibility_and_sampling_geometry_exact": True,
                       "original_rock_POSITION_NORMAL_TANGENT_COLOR_INDEX_exact": True,
                       "all_original_terrain_arrays_exact": True, "visibility_prefix_bytes_and_mapping_exact": True,
                       "runtime_probe": ao_after["runtime_probe"],
                       "reason": "Only rock UV/UV2 changed. Actual original runtime _signature accepts the new signature. Original rock/terrain sampling position, normals, topology, transforms and every visibility byte are exact; no rays or rebake needed.",
                       "cache_file_sha256": "Original bake provenance retained, not runtime validity fields. Candidate resource whole-file hashes are in this manifest."},
                "source_files_unchanged": True, "frozen_source_tree_files": len(source_stats),
                "integration": {"atomic_replacement_required": list(replacements), "runtime_decoder_required": False,
                                "runtime_geometry_rebuild_added": False, "far_sward_terrain_SHA": sha(blobs[TERRAIN]),
                                "original_tier": "Frozen. Apply only to derived lite pack.",
                                "cache_provenance_metadata": "Original source/cache signatures and root/corner ranges retained; candidate content hashes are recorded separately."},
                "limits": ["No dropped objects, vertices, triangles or collision faces; no decimation.",
                          "Lighting normals are bounded, not claimed exact on native-packed leaves. Tangent encoding frame changes, unused by pinned shader.",
                          "Leaf UV numerical coordinates are canonical material-class tags, not a small UV error. Per-triangle branch/interpolation semantics verified exact.",
                          "Sub-millimetre/thin leaf triangles can have larger geometric face-plane deltas; all measured in surfaces, authored lighting normals stay bounded.",
                          "Individual resource gzip sums are not final PCK.gz size or production transfer estimates.",
                          "Offline structural candidate only; Web/GPU/day-night/animation/visual acceptance remains main-owned."]}
    write_json(output / "manifest.json", manifest)
    mapping = write_strong_pack_manifest(output / "manifest.json", output / "pack-replacements.v1.json")
    print(json.dumps({"strong_manifest": str(output / "pack-replacements.v1.json"), "totals": mapping["totals"]}), flush=True)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="New subdirectory of artifacts/loading-v115/geometry")
    parser.add_argument("--godot", type=Path, default=DEFAULT_GODOT)
    parser.add_argument("--reference-pack", type=Path, default=DEFAULT_PACK, help="Existing accepted PCK, only read for dependencies")
    parser.add_argument("--position-step", type=float, default=1 / 128)
    parser.add_argument("--uv-step", type=float, default=1 / 2048)
    parser.add_argument("--uv2-step", type=float, default=1 / 4096)
    parser.add_argument("--inspect-only", action="store_true", help="Only engine inventory; still writes NEW diagnostic artifacts")
    parser.add_argument("--pack-manifest-only", type=Path, help="Convert an existing validated manifest to main's replacement list; --output is a NEW JSON file")
    parser.add_argument("--strong", action="store_true", help="Native packed geometry plus shader-aware UV and coherent AO signature copy")
    args = parser.parse_args(argv)
    try:
        if args.pack_manifest_only:
            result = write_pack_manifest(args.pack_manifest_only, args.output)
            print(json.dumps({"pack_manifest": str(args.output), "totals": result["totals"]}), flush=True)
        elif args.strong:
            if args.inspect_only:
                raise ValueError("Use --inspect-only without --strong")
            build_strong(args.output, godot=args.godot, reference_pack=args.reference_pack)
        else:
            values = vars(args)
            values.pop("pack_manifest_only")
            values.pop("strong")
            build(**values)
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired, KeyError) as exc:
        print(f"LITE_GEOMETRY_FAIL: {exc}; incomplete outputs are not integratable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
