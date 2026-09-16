"""Read-only independent proof of actual leaf-LOD candidate-02.

No builder, native process, browser or service is invoked. Native dump/reload
artifacts are rehashed and bound to the actual PCK's decoded scene resources.
"""
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from inspect_web_pack import read_pack
from test_dense_scene_containers_v126 import decode_rscc


ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "artifacts/startup-v128/leaf-lod/candidate-02"
BASE = ROOT / "artifacts/v127/index-lite.pck"
BASE_SHA = "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"
PACK_SHA = "48840869e6638addbb399b3226accae060a0e41f330b40bab611f367bec4648c"
TARGETS = {"assets/baked/v77/detail.scn": {"PropGroundStitches", "CreepingMeadowAndLedgeGrowth", "LivingMeadowUnderstory"},
           "assets/baked/v77/foothill.scn": {"CastleFoothillWoodland"},
           "assets/baked/v77/riverbank.scn": {"RootedRiparianCover"}}
CHANNELS = {"0": 12, "1": 12, "2": 16, "3": 16, "4": 8, "5": 8}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def without_comments(source):
    # Keep quoted res:// includes; a naive // regex silently deletes them.
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                  lambda match: match[0] if match[0].startswith('"') else "", source, flags=re.S)


def record(row):
    path = Path(row["path"]).resolve(strict=True)
    require(path.is_relative_to(CASE.resolve()) and path.stat().st_size <= 128 * 1024 * 1024, "Bounded local dump")
    data = path.read_bytes()
    require(len(data) == row["bytes"] and sha(data) == row["sha256"], "Native buffer hash/size")
    return data


def contents(path, expected_sha):
    blob = path.read_bytes()
    require(sha(blob) == expected_sha, "Actual PCK SHA")
    directory = read_pack(path)
    return blob, {r["path"]: blob[r["offset"]:r["offset"] + r["bytes"]] for r in directory["entries"]}


def recognize(position, color, triangles):
    """Independent authored-block grammar, not the builder's result/counts."""
    alpha = np.rint(color[:, 3] * 255).astype(np.int16)
    corner_alpha = alpha[triangles]
    strip_pattern = np.array([0, 85, 0, 0, 85, 85, 85, 170, 85, 85, 170, 170, 170, 255, 170])
    fan_pattern = np.array([0, 255, 166, 166, 255, 166, 166, 255, 166, 166, 255, 166, 166, 255, 166, 166, 255, 0])
    groups = {}
    joins = []
    for kind, width, pattern in (("blade", 5, strip_pattern), ("oval", 6, fan_pattern)):
        starts = np.flatnonzero(np.all(np.abs(corner_alpha - pattern[:3]) <= 1, axis=1))
        starts = starts[starts + width <= len(triangles)]
        if not len(starts):
            continue
        blocks = triangles[starts[:, None] + np.arange(width)].reshape(-1, width * 3)
        matches = np.all(np.abs(alpha[blocks] - pattern) <= 1, axis=1)
        for start, block in zip(starts[matches], blocks[matches]):
            p = position[block]
            if kind == "blade":
                if not all(np.array_equal(p[a], p[b]) for a, b in ((2, 3), (1, 4), (7, 10), (8, 9))):
                    continue
                centres = [(p[a] + p[b]) / 2 for a, b in ((1, 5), (6, 8), (7, 11), (12, 14))]
                gap = max(np.linalg.norm(centres[0] - centres[1]), np.linalg.norm(centres[2] - centres[3]))
                if gap >= 0.008:
                    continue
                joins.append(float(gap))
                new = block[[0, 13, 2]][None, :]
            else:
                if not all(np.array_equal(p[j * 3 + 2], p[((j + 1) % 6) * 3]) for j in range(6)):
                    continue
                if not all(np.array_equal(p[1], p[j * 3 + 1]) for j in range(1, 6)):
                    continue
                ring = block[[0, 3, 9, 15]]
                new = np.stack((ring, np.full(4, block[1]), np.roll(ring, -1)), axis=1)
            require(int(start) not in groups, "Ambiguous authored primitive")
            groups[int(start)] = (kind, width, new, block)
    rebuilt, selected_groups, unmatched = [], [], 0
    cursor = 0
    while cursor < len(triangles):
        group = groups.get(cursor)
        if group is None:
            rebuilt.append(triangles[cursor:cursor + 1])
            unmatched += 1
            cursor += 1
        else:
            selected_groups.append(group)
            rebuilt.append(group[2])
            cursor += group[1]
    result = np.concatenate(rebuilt).astype(np.uint32)
    return result, selected_groups, {"maxRecognizedStripCenterGapM": max(joins, default=0), "unmatchedTriangles": unmatched}


def area_vectors(position, triangles):
    p = position[triangles].astype(np.float64)
    return np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])


def group_metrics(position, groups):
    result = {}
    for kind, width in (("blade", 5), ("oval", 6)):
        chosen = [g for g in groups if g[0] == kind]
        if not chosen:
            result[kind] = {"plants": 0}
            continue
        old_indices = np.stack([g[3] for g in chosen]).reshape(len(chosen), width, 3)
        new_indices = np.stack([g[2] for g in chosen])
        old_vectors = area_vectors(position, old_indices.reshape(-1, 3)).reshape(len(chosen), width, 3)
        new_vectors = area_vectors(position, new_indices.reshape(-1, 3)).reshape(len(chosen), -1, 3)
        old_area = np.linalg.norm(old_vectors, axis=2).sum(axis=1)
        new_area = np.linalg.norm(new_vectors, axis=2).sum(axis=1)
        valid = old_area > 1e-15
        ratio = new_area[valid] / old_area[valid]
        newly_empty = int(np.count_nonzero(valid & (new_area <= 1e-15)))
        dot = (new_vectors.sum(axis=1) * old_vectors.sum(axis=1)).sum(axis=1)
        result[kind] = {"plants": len(chosen), "newlyZeroAreaPlants": newly_empty,
                        "beforeZeroAreaTriangles": int(np.count_nonzero(np.linalg.norm(old_vectors, axis=2) <= 1e-15)),
                        "afterZeroAreaTriangles": int(np.count_nonzero(np.linalg.norm(new_vectors, axis=2) <= 1e-15)),
                        "aggregateOrientationReversedPlants": int(np.count_nonzero(dot < -1e-15)),
                        "surfaceAreaRatio": {"min": float(ratio.min()), "median": float(np.median(ratio)),
                                             "max": float(ratio.max()), "sumRatio": float(new_area.sum() / old_area.sum())}}
    return result


def audit():
    base_blob, base = contents(BASE, BASE_SHA)
    blob, final = contents(CASE / "index-lite.pck", PACK_SHA)
    require(len(base) == len(final) == 184 and list(base) == list(final), "184 exact inventory names/order")
    changed = {p for p in base if base[p] != final[p]}
    require(changed <= TARGETS.keys(), "No resource change outside three allowed leaf containers")
    proof = json.loads((CASE / "proof.json").read_text())
    require(proof["sourceSha256"] == BASE_SHA and proof["candidateSha256"] == PACK_SHA and proof["aggressiveBlades"] is True, "Leaf proof pins")
    before = json.loads((CASE / "before.json").read_text())
    after = json.loads((CASE / "after.json").read_text())
    require(before["failures"] == after["failures"] == 0 and before["files"].keys() == after["files"].keys() == TARGETS.keys(), "Native dump/reload evidence")
    findings, rows = [], []
    for resource, labels in TARGETS.items():
        before_file, after_file = before["files"][resource], after["files"][resource]
        source = Path(before_file["path"]).read_bytes()
        assembled = Path(after_file["path"]).read_bytes()
        require(source == base[resource] and sha(source) == before_file["sha256"], "Before dump bound to actual base PCK")
        require(sha(assembled) == after_file["sha256"] and decode_rscc(final[resource])[0] == decode_rscc(assembled)[0],
                "Reloaded native scene bound to decoded actual candidate PCK")
        a, b = before_file["snapshot"], after_file["snapshot"]
        require(all(a[k] == b[k] for k in ("tree", "bundle", "packed_properties")), "Nodes, metadata, materials or collision changed")
        require(a["meshes"].keys() == b["meshes"].keys(), "Mesh set changed")
        for label in a["meshes"]:
            old_mesh, new_mesh = a["meshes"][label], b["meshes"][label]
            if label not in labels:
                require(old_mesh == new_mesh, "Untargeted rock/riverbank mesh exact")
                continue
            require(old_mesh["properties"] == new_mesh["properties"], "Target mesh properties exact")
            require(len(old_mesh["surfaces"]) == len(new_mesh["surfaces"]) == 1, "Single surface")
            sa, sb = old_mesh["surfaces"][0], new_mesh["surfaces"][0]
            require({k: v for k, v in sa["fixed"].items() if k != "index_count"} ==
                    {k: v for k, v in sb["fixed"].items() if k != "index_count"}, "Format/AABB/UV scale/material exact")
            require(sa["format"] == sb["format"], "No encoding format changes")
            old_raw = {key: record(row) for key, row in sa["raw_buffers"].items()}
            new_raw = {key: record(row) for key, row in sb["raw_buffers"].items()}
            indices = np.frombuffer(old_raw["index_data"], dtype=f'<u{sa["index_stride"]}').astype(np.uint32).reshape(-1, 3)
            position = np.frombuffer(record(sa["decoded"]["0"]), dtype="<f4").reshape(-1, 3)
            color = np.frombuffer(record(sa["decoded"]["3"]), dtype="<f4").reshape(-1, 4)
            require(np.isfinite(position).all() and np.isfinite(color).all() and indices.max() < len(position), "Finite/in-bounds source")
            expected, groups, metrics = recognize(position, color, indices)
            ids = np.unique(expected)
            require(len(ids) == sb["vertex_count"] and expected.size == sb["index_count"], "Independent triangle/vertex selection counts")
            final_indices = np.frombuffer(new_raw["index_data"], dtype=f'<u{sb["index_stride"]}').astype(np.uint32).reshape(-1, 3)
            require(final_indices.max() < len(ids) and np.array_equal(ids[final_indices], expected), "Every output triangle/corner order exact")
            require(sb["index_stride"] == (2 if len(ids) <= 65536 else 4), "Native index-width transition valid")
            count, vs, ns, ats = (sa[k] for k in ("vertex_count", "vertex_stride", "normal_tangent_stride", "attribute_stride"))
            split = count * vs
            selected = (np.frombuffer(old_raw["vertex_data"][:split], dtype=np.uint8).reshape(count, vs)[ids].tobytes()
                        + np.frombuffer(old_raw["vertex_data"][split:], dtype=np.uint8).reshape(count, ns)[ids].tobytes())
            require(selected == new_raw["vertex_data"], "Selected raw positions/normal/tangent bytes exact")
            require(np.frombuffer(old_raw["attribute_data"], dtype=np.uint8).reshape(count, ats)[ids].tobytes() == new_raw["attribute_data"],
                    "Selected raw color/alpha/UV bytes exact")
            for channel, stride in CHANNELS.items():
                old_channel, new_channel = record(sa["decoded"][channel]), record(sb["decoded"][channel])
                require(np.frombuffer(old_channel, dtype=np.uint8).reshape(count, stride)[ids].tobytes() == new_channel,
                        "Actual native decoded selected channel bytes exact: " + channel)
            counts = {"blades": sum(g[0] == "blade" for g in groups), "ovals": sum(g[0] == "oval" for g in groups),
                      "unmatchedTriangles": metrics["unmatchedTriangles"], "beforeTriangles": len(indices), "afterTriangles": len(expected),
                      "recognizedPlants": len(groups), "beforeVertices": count, "afterVertices": len(ids)}
            require(all(proof["meshes"][label][k] == value for k, value in counts.items()), "Declared recognizer counts")
            roots = [g[3][[0, 2]] if g[0] == "blade" else g[3][[0]] for g in groups]
            require(not roots or np.isin(np.concatenate(roots), ids).all(), "Every recognized root corner retained")
            topology = group_metrics(position, groups)
            for kind, value in topology.items():
                if value.get("newlyZeroAreaPlants", 0) or value.get("aggregateOrientationReversedPlants", 0):
                    findings.append({"mesh": label, "kind": kind, "geometry": value})
            rows.append({"resource": resource, "mesh": label, **counts, **metrics, "indexStrideBefore": sa["index_stride"],
                         "indexStrideAfter": sb["index_stride"], "selectedSixDecodedChannelsByteExact": True,
                         "rootsAndUnmatchedTrianglesExact": True, "plantGeometry": topology})
    # Prove the actual target shader graph, not a statement about COLOR.a.
    roots = set()
    def shaders(value):
        if isinstance(value, list):
            if len(value) == 3 and value[0] == "Shader":
                roots.add(value[1].removeprefix("res://"))
            else:
                for item in value:
                    shaders(item)
        elif isinstance(value, dict):
            for item in value.values():
                shaders(item)
    for resource, labels in TARGETS.items():
        for label in labels:
            shaders(before["files"][resource]["snapshot"]["tree"][label])
    require(roots == {"shaders/meadow_leaves.gdshader"}, "Only the reviewed leaf shader")
    pending, shader_pins = list(roots), {}
    while pending:
        p = pending.pop()
        if p in shader_pins:
            continue
        require(p in final and final[p] == base[p], "Shader graph exact")
        source = without_comments(final[p].decode())
        require(not re.search(r"\bVERTEX_ID\b", source), "No vertex-ID-dependent material on remapped vertices")
        shader_pins[p] = sha(final[p])
        for target in re.findall(r'#include\s+"res://([^"]+)"', source):
            pending.append(target)
    require(BASE.read_bytes() == base_blob and (CASE / "index-lite.pck").read_bytes() == blob, "Inputs unchanged")
    exact_textures = [p for p in base if p.endswith(".ctex")]
    require(len(exact_textures) == 32 and all(base[p] == final[p] for p in exact_textures), "All atlas/texture alpha payloads exact")
    return {"schemaVersion": 1, "status": "PASS_STRUCTURAL_SELECTION_PENDING_VISUAL" if not findings else "TOPOLOGY_FINDINGS_REVIEW_REQUIRED",
            "baseSha256": BASE_SHA, "packSha256": PACK_SHA, "bytes": len(blob), "entries": 184,
            "byteExactEntries": 184 - len(changed), "changedContainers": sorted(changed), "meshes": rows,
            "all32TexturesByteExact": True, "allScriptsShadersSettingsTerrainWaterEntriesByteExact": True,
            "snapshotNodesMaterialsRootMetadataCollidersExact": True, "untargetedRockMeshesExact": True,
            "actualNativeDumpReloadChannelsBoundToPack": True, "targetShaderGraph": shader_pins,
            "findings": findings, "proofSha256": sha((CASE / "proof.json").read_bytes()),
            "beforeDumpSha256": sha((CASE / "before.json").read_bytes()), "afterDumpSha256": sha((CASE / "after.json").read_bytes()),
            "builderSha256": sha((ROOT / "godot/tools/build_lite_leaves_v128.py").read_bytes()),
            "inspectorSha256": sha((ROOT / "godot/tools/compact_lite_meshes.gd").read_bytes()),
            "checkerSha256": sha(Path(__file__).read_bytes()), "newNativeRuns": 0, "builds": 0, "browserActions": 0,
            "limits": ["Shape/topology is intentionally lossy; selected vertex byte equality does not mean pixel or wind interpolation equality.",
                       "Area ratios are summed geometric triangle area, not projected screen coverage or a visual pass.",
                       "COLOR.a drives vertex wind and material interpolation; this opaque leaf shader does not write ALPHA.",
                       "This rechecks existing inert native artifacts and actual PCK composition. No independent full-scene native or GPU run here."]}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
