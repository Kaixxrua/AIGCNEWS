"""Pinned v134 offline scene partition; no live scripts, exports, or staging.

First run --inventory. --build writes native and mode-5 core/deferred scenes
and a per-entry integration manifest inside artifacts/startup-v135/scenes.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import struct
import subprocess
import time

from inspect_web_pack import read_pack
from repack_web_cache import _pack, _unpack
from build_filtered_scene_pack_v128 import encode, decode

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v135/scenes"
SHIP = ROOT / "artifacts/v134/index-lite.pck"
NATIVE = ROOT / "artifacts/startup-v128/combined-01/native-audit-twin.pck"
SHIP_SHA = "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3"
NATIVE_SHA = "83caf8ac1126ccacea3a2146109d234193a3de60a887cff2d383e4cfb21c6ce6"
ENGINE = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64.exe"
ENGINE_SHA = "ab1824f85bfd8e0e4128182c000c4003a3e042245b2967848d089b2a04b22424"
GD = Path(__file__).with_suffix(".gd")
GROUPS = {
    "detail": {"entry": "assets/baked/v77/detail.scn", "deferred": ["LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"]},
    "foothill": {"entry": "assets/baked/v77/foothill.scn", "deferred": ["CastleFoothillWoodland"]},
    "riverbank": {"entry": "assets/baked/v77/riverbank.scn", "deferred": ["RootedRiparianCover"]},
    "brush": {"entry": "assets/baked/v77/brush.scn", "deferred": ["MiddleMeadowBrush"]},
    "crown-edge": {"entry": "assets/baked/lite-v128/crown-edge-controller.scn", "deferred": ["CrownToTurfFringe", "CrownTransitionBranchlets"]},
    "far-sward": {"entry": "assets/baked/v113/far-sward.scn", "deferred": ["DistantMeadowSward"], "replace_root": True},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def pinned(path, expected):
    data = path.read_bytes()
    require(sha(data) == expected, f"Pin mismatch: {path}")
    return data


def write(path, data):
    path = path.resolve()
    require(path.is_relative_to(SCOPE.resolve()) and not path.exists(), f"New scoped artifact only: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def json_write(path, value):
    write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def normalized_hash(value):
    """Hash the decoded fingerprint tree, not serialized SCN resource IDs.

    Snapshot scalars are typed Godot var_to_bytes SHA256 values. Dictionaries
    use sorted UTF-8 JSON keys; only transport scene_file_path and generated
    internal Resource paths/scene IDs are excluded by the GD snapshot.
    """
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def entries(path, pin):
    blob = pinned(path, pin)
    pack = read_pack(path, verify=True)
    require(pack["version"] == 4 and len(pack["entries"]) == 185, "Pinned 185-entry v4 pack")
    return {e["path"]: blob[e["offset"]:e["offset"] + e["bytes"]] for e in pack["entries"]}


def logical(blob):
    if blob[:4] != b"RSCC":
        return blob
    mode = struct.unpack_from("<I", blob, 4)[0]
    require(mode in (2, 5), "Only known codecs")
    return decode(blob) if mode == 5 else _unpack(blob)


def sources():
    native = entries(NATIVE, NATIVE_SHA)
    shipping = entries(SHIP, SHIP_SHA)
    require(list(native) == list(shipping), "Identical source entry ordering")
    for name in native:
        require(native[name] == shipping[name] or logical(native[name]) == logical(shipping[name]), f"Input twins logically exact: {name}")
    return native, shipping


def native_run(mode, native, directory, specs=None):
    pinned(ENGINE, ENGINE_SHA)
    groups = []
    selected = dict(GROUPS if specs is None else specs)
    if mode == "inventory":
        selected["terrain"] = {"entry": "assets/baked/v77/terrain.scn", "deferred": []}
    for group, spec in selected.items():
        row = dict(spec, group=group, sha256=sha(native[spec["entry"]]))
        if mode == "partition":
            for kind in ("core", "deferred"):
                path = directory / "saved" / kind / f"{group}.scn"
                path.parent.mkdir(parents=True, exist_ok=True)
                row[f"{kind}_output"] = path.as_posix()
        if mode == "proxy_assemble":
            path = directory / "saved/core" / f"{group}.scn"
            path.parent.mkdir(parents=True, exist_ok=True)
            row["core_output"] = path.as_posix()
        groups.append(row)
    output = directory / "native-proof.json"
    request = dict(mode=mode, pack=NATIVE.as_posix(), output=output.as_posix(), groups=groups)
    if mode == "proxy_assemble":
        request["visual_output"] = (directory / "saved/world-visuals.scn").as_posix()
        request["bootstrap_visual_output"] = (directory / "saved/bootstrap-visuals.scn").as_posix()
    request_path = directory / "request.json"
    json_write(request_path, request)
    env = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = directory / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    command = [str(ENGINE), "--headless", "--path", str(directory), "--main-pack", str(NATIVE),
               "--log-file", str(directory / "engine.log"), "--script", str(GD), "--", str(request_path)]
    started = time.perf_counter()
    process = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    log = process.stdout + process.stderr
    write(directory / "process.log", log.encode())
    json_write(directory / "invocation.json", {"command": command, "returncode": process.returncode,
               "seconds": time.perf_counter() - started, "engineSha256": ENGINE_SHA, "probeSha256": sha(GD.read_bytes())})
    require(process.returncode == 0 and "ERROR:" not in log and "SCRIPT ERROR" not in log, f"Native partition probe failed: {log[-5000:]}")
    report = json.loads(output.read_bytes())
    require(report["status"] == "PASS", "All native checks PASS")
    return report


def inventory():
    native, shipping = sources()
    report = native_run("inventory", native, SCOPE / "inventory-01")
    for row in report["groups"]:
        row["sourceShippingBytes"] = len(shipping[row["entry"]])
        row["sourceShippingGzip6Bytes"] = len(gzip.compress(shipping[row["entry"]], compresslevel=6, mtime=0))
        row["deferredChildren"] = GROUPS.get(row["group"], {}).get("deferred", [])
    report["shippingPackSha256"] = SHIP_SHA
    json_write(SCOPE / "inventory.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def build():
    native, shipping = sources()
    destination = SCOPE / "candidate-02"
    require(not (destination / "manifest.json").exists() and not (destination / "mode5").exists(), "Do not overwrite completed candidate")
    native_dir = next((destination / f"native-{i:02}" for i in range(1, 5) if not (destination / f"native-{i:02}").exists()), None)
    require(native_dir is not None, "Bounded native attempts exhausted")
    report = native_run("partition", native, native_dir)
    previous_rows, previous_native = {}, {}
    previous_path = SCOPE / "candidate-01/manifest.json"
    if previous_path.exists():
        previous = json.loads(previous_path.read_bytes())
        require(previous["sourceShippingPackSha256"] == SHIP_SHA and previous["sourceNativePackSha256"] == NATIVE_SHA,
                "Reuse only parts derived from the exact same frozen input pair")
        previous_proof_path = Path(previous["nativeProof"])
        pinned(previous_proof_path, previous["nativeProofSha256"])
        previous_proof = json.loads(previous_proof_path.read_bytes())
        require(previous_proof["status"] == "PASS", "Reuse only previously validated splits")
        previous_rows = {row["group"]: row for row in previous["groups"]}
        previous_native = {row["group"]: row for row in previous_proof["groups"]}
    normalized = {}
    results = []
    for row in report["groups"]:
        require(row["reassembledExact"] and row["packedResourceMetadataExact"], "Native value and metadata parity")
        group = row["group"]
        item = {"group": group, "sourceEntry": row["sourceEntry"], "sourceShippingSha256": sha(shipping[row["sourceEntry"]]),
                "sourceNativeSha256": sha(native[row["sourceEntry"]]), "children": row["mapping"], "variants": {},
                "sceneSpec": {"resource": f"res://progressive/details/{group}.scn",
                              "parent": "MeadowEdgeGrowth" if group == "crown-edge" else ".",
                              "roots": GROUPS[group]["deferred"]}}
        normalized[group] = {"original": normalized_hash(row["originalSnapshot"]),
                             "restored": normalized_hash(row["reassembledSnapshot"]),
                             "core": normalized_hash(row["coreSnapshot"]), "allFullValuesExact": True}
        require(normalized[group]["original"] == normalized[group]["restored"], "Final normalized fingerprint exact")
        for kind in ("core", "deferred"):
            reuse_previous = kind == "deferred" and group != "far-sward" and group in previous_rows
            previous_part = previous_rows[group]["variants"][kind] if reuse_previous else None
            if reuse_previous:
                require(row["originalSnapshot"] == previous_native[group]["originalSnapshot"] == previous_native[group]["reassembledSnapshot"],
                        "Previous full deferred values pinned to the identical original, no placeholder changes")
                source_blob = pinned(Path(previous_part["encodings"]["native"]["path"]), previous_part["encodings"]["native"]["sha256"])
            else:
                source_blob = (native_dir / "saved" / kind / f"{group}.scn").read_bytes()
            raw = logical(source_blob)
            stock = source_blob if reuse_previous else _pack(raw, 1048576, 19)
            require(_unpack(stock) == raw, "Stock encoding roundtrip")
            print(f"PROGRESSIVE_ENCODE: {group}/{kind} decoded={len(raw)}", flush=True)
            started = time.perf_counter()
            if reuse_previous:
                filtered = pinned(Path(previous_part["encodings"]["mode5"]["path"]), previous_part["encodings"]["mode5"]["sha256"])
                modes = previous_part["filters"]
            else:
                filtered, modes = encode(raw)
            require(decode(filtered) == raw, "Mode-5 encoding roundtrip")
            paths = {}
            for variant, payload in (("native", stock), ("mode5", filtered)):
                path = destination / variant / kind / f"{group}.scn"
                write(path, payload)
                paths[variant] = {"path": path.as_posix(), "bytes": len(payload), "sha256": sha(payload),
                                  "gzip6Bytes": len(gzip.compress(payload, compresslevel=6, mtime=0))}
            packed_entry = row["sourceEntry"] if kind == "core" else f"progressive/details/{group}.scn"
            item["variants"][kind] = {"entry": packed_entry, "decodedBytes": len(raw), "decodedSha256": sha(raw),
                                      "encodings": paths, "filters": modes, "encodeSeconds": time.perf_counter() - started,
                                      "reusedExactPriorDeferred": reuse_previous}
        results.append(item)
        print(json.dumps({"group": group, "coreMode5Gzip6Bytes": item["variants"]["core"]["encodings"]["mode5"]["gzip6Bytes"],
                          "deferredMode5Gzip6Bytes": item["variants"]["deferred"]["encodings"]["mode5"]["gzip6Bytes"]}), flush=True)
    preserved = ["assets/baked/v77/terrain.scn", "assets/baked/v110/rock-occlusion.bin"]
    manifest = {"schema": "meadow-progressive-scenes-v135-1", "status": "PASS_OFFLINE_PARTITION_RUNTIME_INTEGRATION_REQUIRED",
                "sourceShippingPackSha256": SHIP_SHA, "sourceNativePackSha256": NATIVE_SHA, "groups": results,
                "coreAlwaysUnchanged": {name: {"sha256": sha(shipping[name]), "bytes": len(shipping[name]),
                                               "gzip6Bytes": len(gzip.compress(shipping[name], compresslevel=6, mtime=0))} for name in preserved},
                "allCollisionsInCore": True, "finalDecodedNodeResourceParity": True,
                "nativeProof": (native_dir / "native-proof.json").as_posix(),
                "nativeProofSha256": sha((native_dir / "native-proof.json").read_bytes()),
                "noNumericPrecisionOrAoChanges": True, "noPckOrLiveSourceEdits": True,
                "coreCacheVersionAndSourceSignatureRetained": True,
                "placeholderContract": {"metadata": {"progressive_placeholder": True}, "mesh": "ArrayMesh, zero surfaces",
                                        "material": "original material_override", "requiredMetadata": "all original metadata retained",
                                        "fullReplacementsHaveProgressiveMetadata": False},
                "supersedes": "candidate-01 (null meshes, no placeholder flag, FarSward root not wrapped)",
                "requiresRuntimeIntegration": ["Replace same-name placeholders at the original sibling index; clear owners as static_cache.restore does.",
                    "Do not run full mesh/root audits while placeholders contain zero surfaces.",
                    "Crown stubs retain exact cache metadata and support existing empty mesh/material duplicate operations; verify actual controller attachment in main integration.",
                    "Mount/use native scenes only with stock engine; mode-5 scenes need the matching decoder."]}
    manifest["coreReplacedMode5Gzip6Bytes"] = sum(item["variants"]["core"]["encodings"]["mode5"]["gzip6Bytes"] for item in results)
    manifest["deferredMode5Gzip6Bytes"] = sum(item["variants"]["deferred"]["encodings"]["mode5"]["gzip6Bytes"] for item in results)
    manifest["coreAllCachePayloadGzip6Bytes"] = manifest["coreReplacedMode5Gzip6Bytes"] + sum(row["gzip6Bytes"] for row in manifest["coreAlwaysUnchanged"].values())
    pinned(SHIP, SHIP_SHA)
    pinned(NATIVE, NATIVE_SHA)
    json_write(destination / "manifest.json", manifest)
    json_write(destination / "normalized-hashes.json", {"schema": "godot-typed-value-fingerprint-canonical-json-v1",
               "description": normalized_hash.__doc__, "sourceShippingPackSha256": SHIP_SHA,
               "sourceNativePackSha256": NATIVE_SHA, "nativeProofSha256": manifest["nativeProofSha256"], "groups": normalized})
    print(json.dumps({key: value for key, value in manifest.items() if key not in ("groups", "coreAlwaysUnchanged")}, indent=2), flush=True)


def read_buffer(info):
    data = pinned(Path(info["path"]), info["sha256"])
    require(len(data) == info["bytes"], "Exact buffer length")
    return data


def selected_proxy_buffers(row):
    """Select whole original records in ascending index order, no quantization."""
    import numpy as np
    count = int(row["sourceVertices"])
    corners = np.frombuffer(read_buffer(row["lodIndices"]), dtype="<i4")
    require(len(corners) > 0 and len(corners) % 3 == 0 and corners.min() >= 0 and corners.max() < count, "Bounded original LOD indices")
    selected = np.unique(corners)
    mapping = np.full(count, -1, dtype=np.int32)
    mapping[selected] = np.arange(len(selected), dtype=np.int32)
    remapped = mapping[corners]
    vertex = read_buffer(row["buffers"]["vertex_data"])
    attributes = read_buffer(row["buffers"]["attribute_data"])
    vs, ns, ats = (int(row[key]) for key in ("vertexStride", "normalStride", "attributeStride"))
    require(len(vertex) == count * (vs + ns) and len(attributes) == count * ats, "Exact raw storage partition sizes")
    positions = np.frombuffer(vertex[:count * vs], dtype=np.uint8).reshape(count, vs)
    normals = np.frombuffer(vertex[count * vs:], dtype=np.uint8).reshape(count, ns)
    attrs = np.frombuffer(attributes, dtype=np.uint8).reshape(count, ats)
    result = {"vertex_data": positions[selected].tobytes() + normals[selected].tobytes(),
              "attribute_data": attrs[selected].tobytes(),
              "index_data": remapped.astype("<u2" if len(selected) <= 65536 else "<u4").tobytes()}
    expected = {}
    for key, info in row["channels"].items():
        data = read_buffer(info)
        require(len(data) % count == 0, "Fixed decoded channel element size")
        channel = np.frombuffer(data, dtype=np.uint8).reshape(count, len(data) // count)
        expected[key] = sha(channel[selected].tobytes())
    require(np.array_equal(selected[remapped], corners), "Triangle order and all LOD corner references preserved")
    prefix = int(row["originalAoPrefix"])
    proxy_prefix = int(np.count_nonzero(selected < prefix))
    require(np.all(selected[:proxy_prefix] < prefix) and np.all(selected[proxy_prefix:] >= prefix), "Contiguous original AO membership retained")
    return result, selected, corners, expected, proxy_prefix


def projected_coverage(positions, original_indices, selected_indices, camera):
    """Coarse conservative software silhouette sample, NOT rendered visual QA."""
    import numpy as np
    from PIL import Image, ImageDraw
    width, height = 320, 200
    transform = np.asarray(camera["globalTransform"], dtype=np.float64)
    basis = transform[:3].T
    local = (positions - transform[3]) @ np.linalg.inv(basis).T
    depth = -local[:, 2]
    tangent = np.tan(np.deg2rad(float(camera["fov"])) / 2)
    require(camera["keepAspect"] == 1 and camera["projection"] == 0, "Pinned perspective vertical-FOV camera")
    require(np.all(depth > float(camera["near"])), "No unsupported near-plane crossing in coverage probe")
    xy = np.column_stack(((local[:, 0] / (depth * tangent * width / height) + 1) * width / 2,
                          (1 - local[:, 1] / (depth * tangent)) * height / 2))
    def mask(indices):
        triangles = xy[indices.reshape(-1, 3)]
        low, high = triangles.min(axis=1), triangles.max(axis=1)
        inside = (high[:, 0] >= 0) & (high[:, 1] >= 0) & (low[:, 0] < width) & (low[:, 1] < height)
        bitmap = Image.new("1", (width, height))
        draw = ImageDraw.Draw(bitmap)
        for triangle in triangles[inside]:
            draw.polygon([tuple(point) for point in triangle], fill=1)
        return np.asarray(bitmap, dtype=bool)
    before, after = mask(original_indices), mask(selected_indices)
    original_pixels = int(np.count_nonzero(before))
    lost = int(np.count_nonzero(before & ~after))
    added = int(np.count_nonzero(after & ~before))
    union = int(np.count_nonzero(before | after))
    return {"sampleSize": [width, height], "originalCoveredPixels": original_pixels,
            "lostPixels": lost, "addedPixels": added, "lostFraction": lost / max(1, original_pixels),
            "addedFraction": added / max(1, original_pixels), "intersectionOverUnion": int(np.count_nonzero(before & after)) / max(1, union),
            "method": "conservative integer triangle silhouettes; no lighting, occlusion, texture or depth acceptance",
            "notVisualAcceptance": True}


def proxy():
    import numpy as np
    native, shipping = sources()
    destination = SCOPE / "proxy-02"
    require(not destination.exists(), "One separate fresh proxy candidate; never overwrite partitions")
    base_manifest_path = SCOPE / "candidate-02/manifest.json"
    base_manifest_sha = "bc603c646147535d85e88f7a9754a4c1061d4d11bfe5f7ce011f4748fbf02ad0"
    base_manifest = json.loads(pinned(base_manifest_path, base_manifest_sha))
    specs = {"terrain": {"entry": "assets/baked/v77/terrain.scn", "mesh": "ContinuousMeadow", "lod_index": 2},
             "detail": {"entry": "assets/baked/v77/detail.scn", "mesh": "SolidLimestoneGeology", "lod_index": 1}}
    dump = native_run("proxy_dump", native, destination / "dump", specs)
    camera_path = ROOT / "artifacts/startup-v128/independent/runtime/ready-ao-01.json"
    camera = json.loads(pinned(camera_path, "8d1e4e73f3e0975df23371e781744fdf177a3130c49677a13065a9f0e49984be"))["camera"]
    parameters = []
    for row in dump["groups"]:
        group = row["group"]
        full_non_ao_suffix = group == "detail"
        if full_non_ao_suffix:
            lod = np.frombuffer(read_buffer(row["lodIndices"]), dtype="<i4").reshape(-1, 3)
            original = np.frombuffer(read_buffer(row["buffers"]["index_data"]), dtype=f"<u{int(row['indexStride'])}").reshape(-1, 3)
            prefix = int(row["originalAoPrefix"])
            require(not np.any(np.any(original < prefix, axis=1) & np.any(original >= prefix, axis=1)), "Original triangles do not cross AO boundary")
            require(not np.any(np.any(lod < prefix, axis=1) & np.any(lod >= prefix, axis=1)), "LOD does not bridge AO boundary")
            hybrid = np.concatenate((lod[np.all(lod < prefix, axis=1)], original[np.all(original >= prefix, axis=1)])).astype("<i4").tobytes()
            path = destination / "buffers/detail-hybrid-source-indices.bin"
            write(path, hybrid)
            row["lodIndices"] = {"path": path.as_posix(), "bytes": len(hybrid), "sha256": sha(hybrid)}
        data, selected, corners, expected, proxy_prefix = selected_proxy_buffers(row)
        all_positions = np.frombuffer(read_buffer(row["channels"]["0"]), dtype="<f4").reshape(-1, 3)
        original_indices = np.frombuffer(read_buffer(row["buffers"]["index_data"]), dtype=f"<u{int(row['indexStride'])}")
        actual_positions = all_positions[selected]
        coverage = projected_coverage(all_positions, original_indices, corners, camera)
        before_min, before_max = all_positions.min(axis=0), all_positions.max(axis=0)
        after_min, after_max = actual_positions.min(axis=0), actual_positions.max(axis=0)
        ratios = (after_max - after_min) / np.maximum(before_max - before_min, 0.00001)
        # These are screening limits for a temporary proxy, not an art pass.
        screened = coverage["lostFraction"] <= 0.02 and coverage["addedFraction"] <= 0.02 and bool(np.all(ratios >= 0.97))
        entry = dict(specs[group], vertex_count=len(selected), index_count=len(corners), expected_channels=expected,
                     proxy_ao_prefix=proxy_prefix, full_ao_prefix=int(row["originalAoPrefix"]), buffers={})
        for key, payload in data.items():
            path = destination / "buffers" / f"{group}-{key}.bin"
            write(path, payload)
            entry["buffers"][key] = {"path": path.as_posix(), "sha256": sha(payload), "bytes": len(payload)}
        if group == "terrain":
            path = destination / "inputs/terrain.scn"
            write(path, native[specs[group]["entry"]])
            entry["core_source"] = path.as_posix()
            entry["core_source_sha256"] = sha(native[specs[group]["entry"]])
        else:
            core = next(item for item in base_manifest["groups"] if item["group"] == "detail")["variants"]["core"]["encodings"]["native"]
            pinned(Path(core["path"]), core["sha256"])
            entry["core_source"], entry["core_source_sha256"] = core["path"], core["sha256"]
        specs[group] = entry
        parameters.append({"group": group, "mesh": row["mesh"], "selectedLevel": row["selectedLevel"],
                           "originalVertices": int(row["sourceVertices"]), "proxyVertices": len(selected),
                           "originalTriangles": int(row["sourceIndices"]) // 3, "proxyTriangles": len(corners) // 3,
                           "proxyRawRenderBufferBytes": sum(map(len, data.values())), "levels": row["levels"],
                           "coverage": coverage, "actualBoundsBefore": [before_min.tolist(), before_max.tolist()],
                           "actualBoundsAfter": [after_min.tolist(), after_max.tolist()], "extentRatios": ratios.tolist(),
                           "screeningPassed": screened, "originalAoPrefix": int(row["originalAoPrefix"]), "proxyAoPrefix": proxy_prefix,
                           "allSelectedOriginalRawBytesExact": True, "originalVertexOrderRetained": True,
                           "fullNonAoSuffixRetained": full_non_ao_suffix})
        print(json.dumps(parameters[-1]), flush=True)
    json_write(destination / "parameters.json", {"sourcePackSha256": SHIP_SHA, "rows": parameters})
    require(all(row["screeningPassed"] for row in parameters), "Proxy coarse silhouette/bounds screen rejected; no integrated candidate produced")
    assembled = native_run("proxy_assemble", native, destination / "assembly", specs)
    require(all(row["meshOnlyRestoredExact"] and row["collisionInstancesUnchangedDuringUpgrade"] for row in assembled["groups"]), "Exact mesh-only restoration with persistent collisions")
    outputs = {}
    for label, saved, packed_entry in (
        ("terrain-core", destination / "assembly/saved/core/terrain.scn", "assets/baked/v77/terrain.scn"),
        ("detail-core", destination / "assembly/saved/core/detail.scn", "assets/baked/v77/detail.scn"),
        ("world-visuals", destination / "assembly/saved/world-visuals.scn", "progressive/details/world-visuals.scn"),
        ("bootstrap-visuals-measurement-only", destination / "assembly/saved/bootstrap-visuals.scn", None),
    ):
        raw = logical(saved.read_bytes())
        stock = _pack(raw, 1048576, 19)
        print(f"PROXY_ENCODE: {label} decoded={len(raw)}", flush=True)
        filtered, modes = encode(raw)
        require(_unpack(stock) == decode(filtered) == raw, "Exact proxy/twin resource codecs")
        encodings = {}
        for variant, blob in (("native", stock), ("mode5", filtered)):
            path = destination / variant / f"{label}.scn"
            write(path, blob)
            encodings[variant] = {"path": path.as_posix(), "bytes": len(blob), "sha256": sha(blob),
                                  "gzip6Bytes": len(gzip.compress(blob, compresslevel=6, mtime=0))}
        outputs[label] = {"entry": packed_entry, "decodedSha256": sha(raw), "decodedBytes": len(raw), "encodings": encodings, "filters": modes}
    proof = {"schema": "meadow-progressive-visual-proxy-v135-1", "status": "OFFLINE_EXACT_FINAL_RESTORE_PROXY_VISUAL_QA_PENDING",
             "sourceShippingPackSha256": SHIP_SHA, "sourceNativePackSha256": NATIVE_SHA,
             "basePartitionManifest": base_manifest_path.as_posix(), "basePartitionManifestSha256": base_manifest_sha,
             "parameters": parameters, "resources": outputs, "allOriginalColliderBytesExact": True,
             "meshOnlyRestoredExact": True, "preserveLiveMaterialsAndWeather": True,
             "coreMarker": {"progressive_visual_proxy": True}, "sourceGdcEdits": False,
             "sceneSpec": {"resource": "res://progressive/details/world-visuals.scn", "parent": ".",
                           "roots": ["ContinuousMeadow", "SolidLimestoneGeology"], "meshOnly": True,
                           "restoreShaderParameters": {"SolidLimestoneGeology": {"rock_ao_vertex_count": 317556}},
                           "removeMetadata": ["progressive_visual_proxy"]},
             "nativeProof": (destination / "assembly/native-proof.json").as_posix(),
             "nativeProofSha256": sha((destination / "assembly/native-proof.json").read_bytes()),
             "limits": ["320x200 conservative software silhouettes and AABB checks are not rendered visual acceptance or a proof of no hidden holes.",
                        "Main owns explicit proxy AO/audit bypass, actual controller integration, live material/texture/weather preservation and visual QA.",
                        "Original terrain/detail colliders stay in core; late visual resource has no colliders.",
                        "Only core temporary topology changes; late full meshes/attributes/AO are exact source values."]}
    pinned(SHIP, SHIP_SHA)
    pinned(NATIVE, NATIVE_SHA)
    pinned(base_manifest_path, base_manifest_sha)
    json_write(destination / "manifest.json", proof)
    print(json.dumps({"status": proof["status"], "manifest": str(destination / "manifest.json"),
                      "corePairGzip6Bytes": sum(outputs[name]["encodings"]["mode5"]["gzip6Bytes"] for name in ("terrain-core", "detail-core")),
                      "lateVisualsGzip6Bytes": outputs["world-visuals"]["encodings"]["mode5"]["gzip6Bytes"],
                      "proxyVisualOnlyGzip6Bytes": outputs["bootstrap-visuals-measurement-only"]["encodings"]["mode5"]["gzip6Bytes"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--inventory", action="store_true")
    actions.add_argument("--build", action="store_true")
    actions.add_argument("--proxy", action="store_true")
    args = parser.parse_args()
    inventory() if args.inventory else proxy() if args.proxy else build()
