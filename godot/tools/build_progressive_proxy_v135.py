"""One ultra-low temporary proxy, with exact late meshes and full core collisions.

Only proxy-03 is writable. Existing partitions, candidate07, and full carriers
stay frozen. --build emits one hierarchy-selected candidate, not parameter trials.
"""
from pathlib import Path
import argparse
import copy
import gzip
import json
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from PIL import Image, ImageDraw

import build_progressive_scenes_v135 as base

OUT = base.SCOPE / "proxy-03"
PREVIOUS = base.SCOPE / "proxy-02"
PREVIOUS_SHA = "7fde5df9fa7230ce112ce412d9763198ad2b6bc881da73cd58624193633a4210"
DUMP_SHA = "299c7df0b3b67f6e18a31ed20268c222f61b04118f9e7d316cac3c17cac7b16a"
CORE07 = base.ROOT / "artifacts/startup-v135/build/candidate-07/mode5/index-lite.pck"
CORE07_SHA = "78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5"
CAMERA_PATH = base.ROOT / "artifacts/startup-v128/independent/runtime/ready-ao-01.json"
CAMERA_SHA = "8d1e4e73f3e0975df23371e781744fdf177a3130c49677a13065a9f0e49984be"
ROAD = np.array([[20.78,6.85],[12.46,2.52],[5.31,-4.41],[-5.99,-10.45],[0.83,-16.79],
                 [8.34,-23.55],[11.43,-35.45],[25.39,-53.62],[32.64,-60.03],[31.33,-83.32],
                 [25.73,-126.46],[-6.4,-189.41]], dtype=np.float64)
FORK = np.array([[-39,-4],[-5.99,-10.45]], dtype=np.float64)
BRIDGE = np.array([[13.4,-38],[24.7,-38]], dtype=np.float64)


def write(path, data):
    base.require(path.resolve().is_relative_to(OUT.resolve()), "Only new proxy-03 artifacts")
    base.write(path, data)


def json_write(path, data):
    write(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())


def buffer(path, value):
    data = value.tobytes() if isinstance(value, np.ndarray) else value
    write(path, data)
    return {"path": path.as_posix(), "bytes": len(data), "sha256": base.sha(data)}


def distances(points, polyline):
    best = np.full(len(points), np.inf)
    for a, b in zip(polyline[:-1], polyline[1:]):
        edge = b - a
        t = np.clip(((points - a) @ edge) / np.dot(edge, edge), 0, 1)
        best = np.minimum(best, np.linalg.norm(points - (a + t[:, None] * edge), axis=1))
    return best


def protect_terrain(positions, triangles):
    """Keep entire original triangles intersecting enlarged path/Boss/bridge areas."""
    xz = positions[triangles][:, :, [0, 2]].astype(np.float64)
    centres = xz.mean(axis=1)
    radius = np.linalg.norm(xz - centres[:, None, :], axis=2).max(axis=1)
    # Max actual road half-width 3.10 plus a 1.10-unit contact/transition collar.
    return ((distances(centres, ROAD) <= 4.20 + radius)
            | (distances(centres, FORK) <= 4.20 + radius)
            | (distances(centres, BRIDGE) <= 3.20 + radius)
            | (np.linalg.norm(centres - [5.0, -12.0], axis=1) <= 6.20 + radius))


def component_partition(positions, triangles, classes=None):
    """Exact XYZ-bit connectivity, with explicit AO/material-semantic partitions.

    This graph is ONLY used to isolate simplification jobs. It never welds the
    stored render attributes or changes any collision face.
    """
    keys = positions.astype("<f4", copy=False).view("<u4")
    if classes is not None:
        base.require(np.all(classes[triangles] == classes[triangles[:, :1]]), "No mixed-semantic original triangle")
        keys = np.column_stack((keys, classes.astype(np.uint32)))
    _, inv = np.unique(keys, axis=0, return_inverse=True)
    tri = inv[triangles]
    edges = coo_matrix((np.ones(tri.size, dtype=np.uint8),
                       (tri.ravel(), np.roll(tri, 1, axis=1).ravel())), shape=(inv.max()+1, inv.max()+1)).tocsr()
    _, labels = connected_components(edges, directed=False)
    assigned = labels[tri[:, 0]]
    base.require(np.all(labels[tri] == assigned[:, None]), "Every source triangle belongs to one component")
    order = np.argsort(assigned, kind="stable")
    split = np.flatnonzero(np.diff(assigned[order])) + 1
    pieces = np.split(order, split)
    pieces.sort(key=lambda p: int(p[0]))
    return pieces, inv


def boundary(triangles, position_ids):
    tri = position_ids[triangles]
    edges = np.sort(np.concatenate((tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]])), axis=1)
    unique, count = np.unique(edges, axis=0, return_counts=True)
    return unique[count == 1]


def project(positions, camera):
    transform = np.asarray(camera["globalTransform"], dtype=np.float64)
    local = (positions - transform[3]) @ np.linalg.inv(transform[:3].T).T
    base.require(np.all(-local[:, 2] > camera["near"]), "No near-plane crossing")
    return local[:, :2] / -local[:, 2, None]


def mask_at(xy, triangles, origin, span, size=64):
    points = (xy[triangles] - origin) / np.maximum(span, 1e-10) * (size - 3) + 1
    image = Image.new("1", (size, size))
    draw = ImageDraw.Draw(image)
    for tri in points:
        draw.polygon([tuple(p) for p in tri], fill=1)
    return np.asarray(image, dtype=bool)


def select_piece(positions, xy, position_ids, original, alternatives, terrain=False, protected=False):
    """Select once from one hierarchy; bounded fidelity fallback, no re-generation."""
    unique = np.unique(original)
    source = positions[unique]
    lower, upper = source.min(0), source.max(0)
    span = upper - lower
    edge = boundary(original, position_ids)
    origin, high = xy[unique].min(0), xy[unique].max(0)
    reference = mask_at(xy, original, origin, high - origin)
    ref_count = max(1, int(reference.sum()))
    chosen, level = original, -1
    chosen_screen = {"lostFraction": 0.0, "addedFraction": 0.0, "extentRatios": [1.0]*3,
                     "boundaryEdgesExact": True, "minYDifference": 0.0, "zeroAreaProxyTriangles": 0}
    if not protected:
        for item, candidate in sorted(alternatives, key=lambda pair: len(pair[1])):
            if not len(candidate) or len(candidate) >= len(original):
                continue
            selected = positions[np.unique(candidate)]
            lo, hi = selected.min(0), selected.max(0)
            ratio = np.where(span > 1e-5, (hi - lo) / np.maximum(span, 1e-5), 1.0)
            if np.any(ratio < (0.98 if terrain else 0.90)):
                continue
            if abs(float(lo[1] - lower[1])) > (0.03 if terrain else max(0.02, float(span[1])*0.03)):
                continue
            if not np.array_equal(edge, boundary(candidate, position_ids)):
                continue
            corners = positions[candidate].astype(np.float64)
            area = np.linalg.norm(np.cross(corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]), axis=1)
            # Stock simplification can retain a few exactly collinear border
            # triangles. These rasterize no area and never become colliders.
            # Reject tiny nonzero slivers, but do not reject an entire large
            # wall because its unchanged locked boundary has these zero faces.
            zero_count = int(np.count_nonzero(area == 0))
            if np.any((area > 0) & (area < 1e-10)) or zero_count > max(2, len(candidate)//100):
                continue
            actual = mask_at(xy, candidate, origin, high-origin)
            lost = int((reference & ~actual).sum()) / ref_count
            added = int((~reference & actual).sum()) / ref_count
            if lost > (0.008 if terrain else 0.08) or added > (0.008 if terrain else 0.08):
                continue
            chosen, level = candidate, int(item["level"])
            chosen_screen = {"lostFraction": lost, "addedFraction": added, "extentRatios": ratio.tolist(),
                             "boundaryEdgesExact": True, "minYDifference": float(lo[1]-lower[1]),
                             "zeroAreaProxyTriangles": zero_count}
            break
    return chosen, {"selectedLevel": level, "beforeTriangles": len(original), "afterTriangles": len(chosen),
                    "boundaryEdges": len(edge), "protected": protected, **chosen_screen}


def prepare_pieces(row, camera, reuse=False):
    group = row["group"]
    positions = np.frombuffer(base.read_buffer(row["channels"]["0"]), dtype="<f4").reshape(-1, 3)
    indices = np.frombuffer(base.read_buffer(row["buffers"]["index_data"]), dtype=f"<u{row['indexStride']}").reshape(-1, 3)
    if group == "detail":
        colours = np.frombuffer(base.read_buffer(row["channels"]["3"]), dtype="<f4").reshape(-1, 4)
        uv = np.frombuffer(base.read_buffer(row["channels"]["4"]), dtype="<f4").reshape(-1, 2)
        classes = ((np.arange(len(positions)) < row["originalAoPrefix"]).astype(np.int32)
                   + 2*(colours[:,0] > .5) + 4*(colours[:,3] < .5) + 8*(uv[:,0] < 0))
        groups, position_ids = component_partition(positions, indices, classes)
        protected = np.zeros(len(indices), dtype=bool)
    else:
        protected = protect_terrain(positions, indices)
        sub = np.flatnonzero(~protected)
        components, position_ids = component_partition(positions, indices[sub])
        groups = [np.flatnonzero(protected)] + [sub[p] for p in components]
    pieces, flattened = [], []
    offset = 0
    for n, selected in enumerate(groups):
        original = indices[selected]
        count = original.size
        pieces.append({"id": n, "offset": offset, "count": count,
                       "protected": bool(np.all(protected[selected])), "sourceTriangleCount": len(selected)})
        flattened.append(original)
        offset += count
    all_indices = np.concatenate(flattened).astype("<i4")
    base.require(len(all_indices) == len(indices), "All original triangles assigned once")
    path = OUT / "partition" / (group + "-pieces.bin")
    info = {"path": path.as_posix(), "bytes": all_indices.nbytes, "sha256": base.sha(all_indices.tobytes())}
    if reuse:
        base.require(base.pinned(path,info["sha256"]) == all_indices.tobytes(), "Reuse exact original piece partition")
    else:
        buffer(path,all_indices)
    spec = {"entry": "assets/baked/v77/" + group + ".scn", "mesh": row["mesh"],
            "source_raw_sha256": row["sourceRawSurfacesSha256"], "pieces": pieces,
            "piece_indices": info}
    return spec, {"row": row, "positions": positions, "indices": indices, "position_ids": position_ids,
                  "xy": project(positions, camera), "groups": groups, "protected": protected}


def build(reuse_lods=False):
    destination = OUT / "final" if reuse_lods else OUT
    base.require(not destination.exists(), "One fresh selected output; never overwrite old variants")
    previous = json.loads(base.pinned(PREVIOUS / "manifest.json", PREVIOUS_SHA))
    dump = json.loads(base.pinned(PREVIOUS / "dump/native-proof.json", DUMP_SHA))
    camera = json.loads(base.pinned(CAMERA_PATH, CAMERA_SHA))["camera"]
    core07 = base.pinned(CORE07, CORE07_SHA)
    pack07 = base.read_pack(CORE07, verify=True)
    packed07 = {r["path"]: core07[r["offset"]:r["offset"]+r["bytes"]] for r in pack07["entries"]}
    for label in ("terrain-core", "detail-core"):
        old = previous["resources"][label]
        base.require(base.sha(packed07[old["entry"]]) == old["encodings"]["mode5"]["sha256"], "Actual candidate07 uses frozen proxy02")
    native, shipping = base.sources()
    specs, state = {}, {}
    for row in dump["groups"]:
        specs[row["group"]], state[row["group"]] = prepare_pieces(row, camera, reuse_lods)
        print("PROXY03_PARTITION", row["group"], len(specs[row["group"]]["pieces"]), "pieces", flush=True)
    base.GD = Path(__file__).with_suffix(".gd")
    if reuse_lods:
        base.require(json.loads((OUT / "partition/specs.json").read_bytes()) == specs, "Same exact hierarchy inputs; no parameter re-generation")
        generated = json.loads((OUT / "lods/native-proof.json").read_bytes())
        base.require(generated["status"] == "PASS" and generated["packSha256"] == base.NATIVE_SHA, "Only validated existing hierarchy")
    else:
        json_write(OUT / "partition/specs.json", specs)
        generated = base.native_run("piece_lods", native, OUT / "lods", specs)
    parameters, assembly = [], {}
    previous_request = json.loads((PREVIOUS / "assembly/request.json").read_bytes())
    originals = {row["group"]: row for row in previous_request["groups"]}
    for generated_row in generated["groups"]:
        group = generated_row["group"]
        current = state[group]
        lods = np.frombuffer(base.read_buffer(generated_row["indices"]), dtype="<i4")
        chosen, reports = [], []
        for part, response, selection in zip(specs[group]["pieces"], generated_row["pieces"], current["groups"]):
            base.require(part["id"] == response["id"], "Piece output ordering exact")
            alternatives = [(level, lods[level["offset"]:level["offset"]+level["count"]].reshape(-1, 3)) for level in response["levels"]]
            original = current["indices"][selection]
            for _, candidate in alternatives:
                base.require(np.all(np.isin(candidate, original)), "No LOD crosses piece/semantic boundary")
            result, report = select_piece(current["positions"], current["xy"], current["position_ids"], original,
                                          alternatives, terrain=group == "terrain", protected=part["protected"])
            reports.append({"id": part["id"], **report})
            chosen.append(result)
        corners = np.concatenate(chosen).astype("<i4").ravel()
        row = dict(current["row"])
        row["lodIndices"] = buffer(destination / "buffers" / (group + "-source-indices.bin"), corners)
        payloads, selected, _, channels, prefix = base.selected_proxy_buffers(row)
        spec = copy.deepcopy(originals[group])
        for key in ("core_output", "group", "sha256", "lod_index"):
            spec.pop(key, None)
        spec.update(vertex_count=len(selected), index_count=len(corners), expected_channels=channels, proxy_ao_prefix=prefix, buffers={})
        for key, payload in payloads.items():
            spec["buffers"][key] = buffer(destination / "buffers" / (group + "-" + key + ".bin"), payload)
        assembly[group] = spec
        coverage = base.projected_coverage(current["positions"], current["indices"].ravel(), corners, camera)
        # A whole-frame topology screen supplements per-piece/contact guards.
        base.require(coverage["lostFraction"] <= .025 and coverage["addedFraction"] <= .025, "Whole-frame gross coverage retained")
        protected_faces = current["indices"][current["protected"]].astype("<i4")
        params = {"group": group, "mesh": row["mesh"], "originalVertices": int(row["sourceVertices"]),
                  "proxyVertices": len(selected), "originalTriangles": int(row["sourceIndices"])//3,
                  "proxyTriangles": len(corners)//3, "proxyRawRenderBufferBytes": sum(map(len,payloads.values())),
                  "originalAoPrefix": int(row["originalAoPrefix"]), "proxyAoPrefix": prefix,
                  "pieceCount": len(reports), "simplifiedPieces": sum(r["selectedLevel"] >= 0 for r in reports),
                  "allPiecesPresent": True, "allPieceBoundaryEdgesExact": True,
                  "protectedTriangles": len(protected_faces), "protectedTriangleIndexSha256": base.sha(protected_faces.tobytes()),
                  "protectedTriangleCornerBytesSha256": base.sha(current["positions"][protected_faces].tobytes()),
                  "coverage": coverage, "screeningPassed": True, "allSelectedOriginalRawBytesExact": True,
                  "originalVertexOrderRetained": True, "fullNonAoSuffixRetained": False,
                  "pieceProof": (destination / (group + "-pieces.json")).as_posix(),
                  "zeroAreaProxyTriangles": sum(r["zeroAreaProxyTriangles"] for r in reports)}
        if group == "detail":
            params["aoTriangles"] = int(np.all(corners.reshape(-1,3) < row["originalAoPrefix"],axis=1).sum())
            params["nonAoTriangles"] = len(corners)//3 - params["aoTriangles"]
        json_write(destination / (group + "-pieces.json"), {"pieces": reports, "selectionPolicy": "Coarsest passing member of one generated hierarchy"})
        parameters.append(params)
        print(json.dumps(params), flush=True)
    json_write(destination / "parameters.json", {"rows": parameters, "terrainProtection": {"roadAndForkHalfWidth": 4.2,
                "bridgeHalfWidth": 3.2, "bossCentre": [5,-12], "bossRadius": 6.2, "wholeOriginalTrianglesRetained": True}})
    assembled = base.native_run("proxy_assemble", native, destination / "assembly", assembly)
    old_proof = json.loads(base.pinned(Path(previous["nativeProof"]), previous["nativeProofSha256"]))
    old_rows = {r["group"]: r for r in old_proof["groups"]}
    for row in assembled["groups"]:
        base.require(row["meshOnlyRestoredExact"] and row["collisionInstancesUnchangedDuringUpgrade"], "Exact final mesh/collision contract")
        base.require(row["expectedCoreSnapshot"] == old_rows[row["group"]]["expectedCoreSnapshot"] == row["restoredSnapshot"],
                     "Final candidate07 root geometry and metadata unchanged")
    resources = {"world-visuals": copy.deepcopy(previous["resources"]["world-visuals"])}
    for info in resources["world-visuals"]["encodings"].values():
        base.pinned(Path(info["path"]), info["sha256"])
    for label, saved, entry in (
        ("terrain-core", "core/terrain.scn", "assets/baked/v77/terrain.scn"),
        ("detail-core", "core/detail.scn", "assets/baked/v77/detail.scn"),
        ("bootstrap-visuals-measurement-only", "bootstrap-visuals.scn", None),
    ):
        raw = base.logical((destination / "assembly/saved" / saved).read_bytes())
        print("PROXY03_ENCODE", label, len(raw), flush=True)
        stock = base._pack(raw, 1048576, 19)
        filtered, filters = base.encode(raw)
        base.require(base.logical(stock) == base.logical(filtered) == raw, "Both resource encodings exact")
        formats = {}
        for kind, data in (("native", stock), ("mode5", filtered)):
            info = buffer(destination / kind / (label + ".scn"), data)
            info["gzip6Bytes"] = len(gzip.compress(data, compresslevel=6, mtime=0))
            formats[kind] = info
        resources[label] = {"entry": entry, "encodings": formats, "decodedBytes": len(raw),
                            "decodedSha256": base.sha(raw), "filters": filters}
    manifest = {key: copy.deepcopy(previous[key]) for key in ("schema", "sourceShippingPackSha256", "sourceNativePackSha256",
        "basePartitionManifest", "basePartitionManifestSha256", "sceneSpec", "coreMarker")}
    manifest.update(status="OFFLINE_EXACT_FINAL_RESTORE_PROXY_VISUAL_QA_PENDING", resources=resources, parameters=parameters,
                    candidate07CoreSha256=CORE07_SHA, previousProxyManifestSha256=PREVIOUS_SHA,
                    allOriginalColliderBytesExact=True, meshOnlyRestoredExact=True, preserveLiveMaterialsAndWeather=True,
                    sourceGdcEdits=False, fullCarrierReusedByteExact=True, finalCandidate07RootGeometryExact=True,
                    nativeProof=(destination / "assembly/native-proof.json").as_posix(),
                    nativeProofSha256=base.sha((destination / "assembly/native-proof.json").read_bytes()),
                    nativeLodProof=(OUT / "lods/native-proof.json").as_posix(),
                    limits=["Temporary topology/normal interpolation/appearance changes; main must accept actual boot screenshot.",
                            "Raw original selected attribute records are exact; initial triangle corners/topology are intentionally lower detail.",
                            "Full collisions and CPU full-query support must remain; never query the proxy for final procedural placement.",
                            "Per-piece silhouettes/AABB/boundary checks are not a shaded render or a guarantee of zero interior visual error.",
                            "No engine, script, shadow policy, texture, water, PCK or original/balanced change."])
    manifest["measurements"] = {"oldVisualOnlyGzip6Bytes": 2325904,
        "visualOnlyGzip6Bytes": resources["bootstrap-visuals-measurement-only"]["encodings"]["mode5"]["gzip6Bytes"],
        "oldCorePairGzip6Bytes": 5066110,
        "corePairGzip6Bytes": sum(resources[k]["encodings"]["mode5"]["gzip6Bytes"] for k in ("terrain-core", "detail-core")),
        "notWholePackOrWebTiming": True}
    for path, pin in ((CORE07,CORE07_SHA),(base.SHIP,base.SHIP_SHA),(base.NATIVE,base.NATIVE_SHA),(PREVIOUS / "manifest.json",PREVIOUS_SHA)):
        base.pinned(path,pin)
    json_write(OUT / "manifest.json", manifest)
    print(json.dumps(manifest["measurements"]), flush=True)
    print("PROXY03_READY", OUT / "manifest.json", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--build", action="store_true")
    modes.add_argument("--finalize-existing-lods", action="store_true")
    args = parser.parse_args()
    build(args.finalize_existing_lods)
