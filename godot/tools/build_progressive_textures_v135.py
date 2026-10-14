"""Offline bootstrap CTEX mip copies; no encoder, engine, subprocess or PCK writes.

The two manifests are conditional integration inputs, NOT runtime-safe packs.
Logical dimensions and every retained encoded mip stay exact. Code that reads
physical pixels or generates meshes from alpha needs a main-owned adaptation;
late texture replacement alone cannot restore geometry built from lower alpha.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import struct

from PIL import Image

from inspect_web_pack import read_pack


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v135/textures"
SOURCE = ROOT / "artifacts/v134/index-lite.pck"
SOURCE_SHA = "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3"
OBSERVED_CORE = ROOT / "artifacts/startup-v135/build/candidate-05/mode5/index-lite.pck"
CORE_SHA = "699c08aac4201b9c507d964b6a857247af6f718ebab203da085e5937de0052db"
WATER_NAME = "river-ripples-v37"
PROFILES = {"bootstrap128": 128, "bootstrap256": 256}

# These are integration blockers, not permission to change runtime/shaders here.
INITIAL_CONTRACTS = {
    "castle-dragon-turns-v57": ["dragon-physical-pixels"],
    "windmill-village-v50": ["absolute-pixel-mesh-build", "exact-alpha-derived-geometry"],
    "meadow-herbs-v73": ["absolute-pixel-mesh-build", "exact-alpha-derived-geometry"],
    "meadow-scrub-v74": ["absolute-pixel-mesh-build", "exact-alpha-derived-geometry"],
    "mountain-groves-v100": ["absolute-pixel-mesh-build", "exact-alpha-derived-geometry"],
    "castle-town-v62": ["exact-alpha-derived-geometry"],
    "mountain-massif-v106": ["exact-alpha-derived-geometry"],
    "wooded-hills-v107": ["exact-alpha-derived-geometry"],
}
PIXEL_AUDITS = {"road-lanterns-v52", "castle-town-v62", "windmill-village-v50"}
SAMPLER_RETENTION = {
    "castle-town-v62": ("initial-alpha-derived-city-foundation", ["meadow_city_builder.gd:34", "meadow_city_builder.gd:59", "meadow_settlement_lights.gd:197"]),
    "windmill-village-v50": ("initial-absolute-pixels-foundation-and-rotor-radius", ["meadow_village_builder.gd:52", "meadow_village_builder.gd:63", "meadow_village_builder.gd:104", "meadow_settlement_lights.gd:197"]),
    "mountain-massif-v106": ("initial-normalized-alpha-derived-relief", ["meadow_mountain_relief.gd:26", "meadow_mountain_relief.gd:60"]),
    "wooded-hills-v107": ("initial-normalized-alpha-derived-relief", ["meadow_mountain_relief.gd:26", "meadow_mountain_relief.gd:60"]),
    "mountain-groves-v100": ("initial-original-crops-to-alpha-derived-herb-conform", ["meadow_mountain_groves.gd:124", "meadow_herb_modules.gd:57"]),
    "meadow-herbs-v73": ("initial-original-pixel-crops-and-alpha-derived-conform", ["meadow_herb_modules.gd:36", "meadow_herb_modules.gd:57"]),
    "meadow-scrub-v74": ("initial-image-size-uv-normalization-and-alpha-derived-conform", ["meadow_scrub_modules.gd:16", "meadow_scrub_modules.gd:17", "meadow_herb_modules.gd:57"]),
    "road-lanterns-v52": ("explicit-debug-pixel-audit-retained-by-main-request-not-normal-build-read", ["meadow_road_lights.gd:42", "meadow_road_lights.gd:55"]),
    "castle-dragon-turns-v57": ("runtime-shader-original-pixels-divided-by-physical-textureSize", ["../shaders/meadow_dragon.gdshader:22", "meadow_dragon_art.gd:4", "meadow_wildlife.gd:463"]),
}
CONTRACT_NOTES = {
    "dragon-physical-pixels": {
        "evidence": ["godot/shaders/meadow_dragon.gdshader:22",
                     "godot/scripts/meadow_dragon_art.gd:4",
                     "godot/scripts/meadow_wildlife.gd:463"],
        "condition": "pose() divides original pixel offsets/body coordinates by physical textureSize. Preserve the original CTEX unless main handles initial logical-vs-physical pixel registration and restores it on full upgrade.",
    },
    "absolute-pixel-mesh-build": {
        "evidence": ["godot/scripts/meadow_village_builder.gd:52",
                     "godot/scripts/meadow_village_builder.gd:63",
                     "godot/scripts/meadow_herb_modules.gd:36",
                     "godot/scripts/meadow_herb_modules.gd:57",
                     "godot/scripts/meadow_scrub_modules.gd:16",
                     "godot/scripts/meadow_mountain_groves.gd:124"],
        "condition": "get_image() returns reduced physical pixels, but raw crops/loop bounds are original pixels. Some reads become out of bounds; scrub also normalizes original crops by the reduced Image size. Initial runtime must bypass/use exact cached construction data, not just fix final materials.",
    },
    "exact-alpha-derived-geometry": {
        "evidence": ["godot/scripts/meadow_city_builder.gd:34",
                     "godot/scripts/meadow_mountain_relief.gd:26",
                     "godot/scripts/meadow_herb_modules.gd:54"],
        "condition": "Original alpha determines mesh feet, root metadata, deformation and/or rotor radius. Scaling/clamping accesses only avoids bounds errors; it does not prove final geometry exact. Preserve exact derived data or restore exact full geometry through main's approved runtime path.",
    },
    "pixel-coordinate-audits": {
        "evidence": ["godot/scripts/meadow_road_lights.gd:55",
                     "godot/scripts/meadow_settlement_lights.gd:197"],
        "condition": "Explicit/debug artwork audits sample original pixel coordinates. Keep them deferred until full pixels are present or explicitly adapt their data source; do not silently weaken them.",
    },
    "code-held-textures": {
        "evidence": ["godot/scripts/meadow_fauna_art.gd:5",
                     "godot/scripts/meadow_wildlife.gd:96",
                     "godot/scripts/meadow_wildlife.gd:103",
                     "godot/scripts/meadow_wildlife.gd:141",
                     "godot/scripts/meadow_wildlife.gd:380"],
        "condition": "Main selected public CompressedTexture2D.load(unique_full_alias) in place, preserving the Texture2D object and its script/material/atlas references. Emit inPlace:true; validate success and logical dimensions in main. This solves held-reference upgrade, not initial low-pixel mesh construction.",
    },
    "cutout-footprint": {
        "evidence": ["godot/shaders/meadow_cutout_surface.gdshaderinc:126",
                     "godot/shaders/meadow_cutout_surface.gdshaderinc:142"],
        "condition": "textureSize-dependent edge inset/normal sampling gets coarser. Copied alpha is exact to the selected mip, not pixel-identical to the full texture; bootstrap visibility/white halos require main visual QA.",
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def gz_size(data):
    return len(gzip.compress(data, compresslevel=6, mtime=0))


def parse_ctex(blob):
    """Validate container/image headers without decoding or re-encoding pixels."""
    require(len(blob) >= 56 and blob[:4] == b"GST2", "Expected CTEX GST2")
    require(struct.unpack_from("<I", blob, 4)[0] == 1, "Expected CTEX version 1")
    logical = struct.unpack_from("<II", blob, 8)
    kind, width, height, count, image_format = struct.unpack_from("<IHHII", blob, 36)
    require(all(logical) and width > 0 and height > 0, "Positive dimensions required")
    require(kind == 2 and image_format in (4, 5) and count <= 16, "Expected WebP RGB(A) mip chain")
    require(count == 0 or count == max(width, height).bit_length() - 1,
            "Expected a single mip or complete retained chain")
    offset, levels = 52, []
    for index in range(count + 1):
        start = offset
        require(offset + 4 <= len(blob), "Truncated mip size")
        length = struct.unpack_from("<I", blob, offset)[0]
        offset += 4
        require(length >= 20 and offset + length <= len(blob), "Truncated mip payload")
        payload = blob[offset:offset + length]
        offset += length
        require(payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
                and struct.unpack_from("<I", payload, 4)[0] + 8 == length, "Invalid WebP RIFF")
        size = (max(1, width >> index), max(1, height >> index))
        with Image.open(io.BytesIO(payload)) as image:
            require(image.format == "WEBP" and image.size == size, "Mip image dimensions disagree")
        levels.append({"record": blob[start:offset], "payload": payload, "size": size})
    require(offset == len(blob), "Trailing CTEX bytes")
    return {"logical": logical, "physical": (width, height), "format": image_format, "levels": levels}


def copy_from_level(blob, drop):
    source = parse_ctex(blob)
    require(type(drop) is int and 0 <= drop < len(source["levels"]), "Invalid mip drop")
    if drop == 0:
        return blob
    levels = source["levels"][drop:]
    result = bytearray(blob[:52])
    struct.pack_into("<HHI", result, 40, *levels[0]["size"], len(levels) - 1)
    result.extend(b"".join(level["record"] for level in levels))
    return bytes(result)


def select_bootstrap(blob, limit):
    require(type(limit) is int and limit > 0, "Positive integer size limit required")
    parsed = parse_ctex(blob)
    selected = next((i for i, row in enumerate(parsed["levels"]) if max(row["size"]) <= limit), None)
    if selected is None:
        return blob, 0, "no-existing-small-mip"
    return copy_from_level(blob, selected), selected, "selected-existing-mip" if selected else "already-small"


def verify_copy(original, candidate, drop):
    before, after = parse_ctex(original), parse_ctex(candidate)
    require(original[:40] == candidate[:40] and original[48:52] == candidate[48:52],
            "Logical size, flags, reserved fields, encoding or format changed")
    require(before["logical"] == after["logical"], "Logical atlas dimensions changed")
    expected = before["levels"][drop:]
    require(len(expected) == len(after["levels"]), "Missing remaining mip")
    records = []
    for index, (source, result) in enumerate(zip(expected, after["levels"]), drop):
        require(source["record"] == result["record"] and source["size"] == result["size"],
                "Retained encoded mip changed")
        records.append({"sourceMip": index, "physicalSize": list(source["size"]),
                        "encodedBytes": len(source["payload"]), "encodedSha256": sha(source["payload"]),
                        "lengthAndPayloadSha256": sha(source["record"])})
    return {"logicalDimensionsAndHeaderExact": True, "remainingMipsByteExact": True,
            "alphaExactToSelectedMipByEncodedIdentity": True, "pixelReencoding": False,
            "levels": records}


def pinned_entries(path, expected):
    blob = path.read_bytes()
    require(sha(blob) == expected, f"Frozen input SHA mismatch: {path}")
    inventory = read_pack(path, verify=True)
    return {row["path"]: blob[row["offset"]:row["offset"] + row["bytes"]] for row in inventory["entries"]}


def import_map(entries):
    result = {}
    for entry, blob in entries.items():
        if not entry.endswith(".png.import"):
            continue
        value = blob.rstrip(b"\0").decode("utf-8")
        target = re.search(r'^path="res://([^"\n]+\.ctex)"', value, re.M)
        require(target is not None, f"Expected exact texture remap: {entry}")
        uid = re.search(r'^uid="([^"]+)"', value, re.M)
        resource = target[1]
        require(resource in entries and resource not in result, "Missing/duplicate texture remap")
        result[resource] = {"source": "res://" + entry[:-7], "importEntry": entry,
                            "importSha256": sha(blob), "uid": uid[1] if uid else None}
    textures = {entry for entry in entries if entry.endswith(".ctex")}
    require(set(result) == textures, "All CTEX entries must have one exact source remap")
    return result


def reference_inventory(entries, mappings):
    """Scoped source review only; no claim that local GD recompiles to packed GDC."""
    refs = {entry: [] for entry in mappings}
    scripts, image_reads, shader_reads = [], [], []
    for entry in sorted(entries):
        if not entry.startswith("scripts/") or not entry.endswith(".gdc"):
            continue
        local = ROOT / "godot" / (entry[:-1])
        if not local.is_file():
            scripts.append({"packedEntry": entry, "localMissing": True})
            continue
        raw = local.read_bytes()
        scripts.append({"path": local.relative_to(ROOT).as_posix(), "localSha256": sha(raw),
                        "packedEntry": entry, "packedSha256": sha(entries[entry]),
                        "compiledSourceEquivalenceAttestedHere": False})
        for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
            for texture_entry, mapping in mappings.items():
                if mapping["source"] in line:
                    refs[texture_entry].append({"path": local.relative_to(ROOT).as_posix(),
                                                "line": number, "text": line.strip()})
            if "get_image(" in line or "get_pixel(" in line or "source.get_size(" in line:
                image_reads.append({"path": local.relative_to(ROOT).as_posix(), "line": number, "text": line.strip()})
    for entry, raw in sorted(entries.items()):
        if entry.endswith((".gdshader", ".gdshaderinc")):
            for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                if "textureSize(" in line or "texelFetch(" in line:
                    shader_reads.append({"packedEntry": entry, "sha256": sha(raw), "line": number, "text": line.strip()})
    return {"directPngReferences": refs, "sourceReviewPins": scripts,
            "cpuImageAccesses": image_reads, "packedShaderPhysicalPixelAccesses": shader_reads,
            "runtimeHeldReferences": ["meadow_scene preload texture constants",
                                      "builder/edge/far-sward TURF, STONE, GRASS, WOOD and FENCE constants",
                                      "meadow_herb_modules.TEXTURE / meadow_scrub_modules.TEXTURE",
                                      "meadow_mountain_groves.ATLAS / meadow_road_lights.ATLAS",
                                      "meadow_dragon_art.TEXTURE / meadow_wildlife.dragon_texture",
                                      "meadow_fauna_art.PATHS dynamic load / meadow_wildlife.animals[].texture (all four species)",
                                      "existing, cached and later-instantiated material/surface/override texture bindings"],
            "sourceReviewLimit": "Local source reads are hashed but not newly compiled/attested. Shader evidence is read from the pinned actual PCK. Main owns runtime adaptation and full-reference upgrade proof."}


def inventory():
    source = pinned_entries(SOURCE, SOURCE_SHA)
    core = pinned_entries(OBSERVED_CORE, CORE_SHA)
    mappings = import_map(source)
    require(len(mappings) == 32, "Expected exact v134 inventory of 32 CTEX entries")
    require({p for p in core if p.endswith(".ctex")} == set(mappings), "Core CTEX set changed")
    references = reference_inventory(source, mappings)
    rows, candidates = [], {profile: {} for profile in PROFILES}
    for entry, mapping in sorted(mappings.items()):
        original = source[entry]
        parsed = parse_ctex(original)
        name = Path(mapping["source"]).stem
        water = name == WATER_NAME
        current = core[entry]
        require(current == (copy_from_level(original, 2) if water else original),
                f"Unexpected core texture change: {entry}")
        row = {"name": name, "entry": entry, **mapping,
               "logicalDimensions": list(parsed["logical"]), "sourcePhysical": list(parsed["physical"]),
               "sourceMipCount": len(parsed["levels"]), "singleMip": len(parsed["levels"]) == 1,
               "sourceSha256": sha(original), "sourceBytes": len(original), "sourceGzip6Bytes": gz_size(original),
               "observedCoreSha256": sha(current), "observedCoreBytes": len(current), "observedCoreGzip6Bytes": gz_size(current),
               "initialIntegrationConditions": INITIAL_CONTRACTS.get(name, []),
               "pixelCoordinateAudit": name in PIXEL_AUDITS,
               "directCodeReferences": references["directPngReferences"][entry], "profiles": {}}
        for profile, limit in PROFILES.items():
            if water:
                result, drop, reason = current, 2, "existing-water-drop2-not-emitted-or-dropped-again"
            else:
                result, drop, reason = select_bootstrap(original, limit)
                candidates[profile][entry] = result
            proof = verify_copy(original, result, drop)
            row["profiles"][profile] = {"bytes": len(result), "gzip6Bytes": gz_size(result),
                "sha256": sha(result), "physicalSize": list(parse_ctex(result)["physical"]),
                "dropFromV134": drop, "reason": reason, "proof": proof}
        rows.append(row)
    totals = {"sourceTextureBytes": sum(r["sourceBytes"] for r in rows),
              "sourceTextureGzip6Bytes": sum(r["sourceGzip6Bytes"] for r in rows),
              "observedCoreTextureBytes": sum(r["observedCoreBytes"] for r in rows),
              "observedCoreTextureGzip6Bytes": sum(r["observedCoreGzip6Bytes"] for r in rows), "profiles": {}}
    for profile in PROFILES:
        after = sum(r["profiles"][profile]["bytes"] for r in rows)
        gzip_after = sum(r["profiles"][profile]["gzip6Bytes"] for r in rows)
        held = sum(r["observedCoreBytes"] if r["initialIntegrationConditions"] else r["profiles"][profile]["bytes"] for r in rows)
        totals["profiles"][profile] = {"coreTextureBytesIncludingExistingWater": after,
            "coreTextureGzip6BytesIncludingExistingWater": gzip_after,
            "rawSavingsVsObservedCore": totals["observedCoreTextureBytes"] - after,
            "gzip6SavingsVsObservedCore": totals["observedCoreTextureGzip6Bytes"] - gzip_after,
            "bytesIfEightInitialContractTexturesStayOriginal": held,
            "rawSavingsIfEightInitialContractTexturesStayOriginal": totals["observedCoreTextureBytes"] - held}
    report = {"schema": "meadow-progressive-texture-inventory-v135-1", "sourcePack": str(SOURCE),
              "sourcePackSha256": SOURCE_SHA, "observedCorePack": str(OBSERVED_CORE), "observedCorePackSha256": CORE_SHA,
              "budgetUnits": "bytes; gzip6 sums individually compressed CTEX, not PCK/engine/Brotli/network measurements",
              "singleMipTextures": [r["entry"] for r in rows if r["singleMip"]],
              "initialContractTextures": sorted(INITIAL_CONTRACTS), "totals": totals,
              "textures": rows, "codeReferences": references, "integrationConditions": CONTRACT_NOTES}
    return report, source, candidates


def write_new(path, data):
    target = path.resolve()
    require(target.is_relative_to(SCOPE.resolve()) and target != SCOPE.resolve(), "Output must be a new texture artifact")
    require(not target.exists(), f"Refusing overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(data)


def write_json(path, value):
    write_new(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def sampler_policy(report, profile):
    """A manifest-only safe selection view; does not generate a third profile."""
    require(profile in PROFILES, "Unknown bootstrap profile")
    rows = report["textures"]
    apply = [r for r in rows if r["name"] not in SAMPLER_RETENTION and r["name"] != WATER_NAME]
    keep = [r for r in rows if r["name"] in SAMPLER_RETENTION]
    water = next(r for r in rows if r["name"] == WATER_NAME)
    raw = sum(r["observedCoreBytes"] for r in keep) + water["observedCoreBytes"] + sum(r["profiles"][profile]["bytes"] for r in apply)
    gzip_bytes = sum(r["observedCoreGzip6Bytes"] for r in keep) + water["observedCoreGzip6Bytes"] + sum(r["profiles"][profile]["gzip6Bytes"] for r in apply)
    return {"policy": "retain-all-cpu-sampler-textures-and-dragon-apply-only-listed-entries",
            "applyEntries": [r["entry"] for r in apply], "applyTextureCount": len(apply),
            "keepOriginal": [{"name": r["name"], "source": r["source"], "entry": r["entry"],
                              "sha256": r["sourceSha256"], "bytes": r["sourceBytes"],
                              "samplerUse": SAMPLER_RETENTION[r["name"]][0],
                              "evidence": ["godot/scripts/" + p for p in SAMPLER_RETENTION[r["name"]][1]]} for r in keep],
            "water": "leave-existing-drop2-and-existing-final-water-chunk",
            "coreTextureBytesIncludingExistingWater": raw, "coreTextureGzip6BytesIncludingExistingWater": gzip_bytes,
            "rawSavingsVsObservedCore": report["totals"]["observedCoreTextureBytes"] - raw,
            "gzip6SavingsVsObservedCore": report["totals"]["observedCoreTextureGzip6Bytes"] - gzip_bytes,
            "exactFullUpgradeTextureBytes": sum(r["sourceBytes"] for r in apply),
            "upgradeInPlace": True,
            "finalGeometryRationale": "Retained CPU source images remain byte-exact from first construction; texture upgrade is not claimed to repair geometry. Dragon keeps its original physical-pixel shader contract. Four animal atlases only use logical dimensions for frame registration.",
            "integration": "Filter replacements by applyEntries for BOTH initial core overrides and late full texture copies; do not retransmit retained originals. For each selected texture use textureSpec with inPlace:true. This is byte/source-review evidence, not native/browser acceptance."}


def generate(output):
    output = output.resolve()
    require(output.is_relative_to(SCOPE.resolve()) and output != SCOPE.resolve() and not output.exists(),
            "Candidate output must be new and inside the dedicated texture scope")
    report, source, candidates = inventory()
    require(all(row["rawSavingsVsObservedCore"] >= 2_000_000 for row in report["totals"]["profiles"].values()),
            "Full conditional candidates do not meet the 2 MB generation threshold")
    write_json(output / "inventory.json", report)
    full = {}
    for row in report["textures"]:
        if row["name"] == WATER_NAME:
            continue
        path = output / "full-v134" / (row["name"] + ".ctex")
        write_new(path, source[row["entry"]])
        require(path.read_bytes() == source[row["entry"]], "Full restore file changed")
        full[row["entry"]] = {"path": path.as_posix(), "entry": "progressive/textures/full-v134/" + path.name,
                              "sha256": row["sourceSha256"], "bytes": row["sourceBytes"]}
    manifests = {}
    water = next(row for row in report["textures"] if row["name"] == WATER_NAME)
    for profile, limit in PROFILES.items():
        mappings = []
        for row in report["textures"]:
            entry = row["entry"]
            if entry not in candidates[profile]:
                continue
            data = candidates[profile][entry]
            path = output / profile / "ctex" / (row["name"] + ".ctex")
            write_new(path, data)
            proof = verify_copy(source[entry], path.read_bytes(), row["profiles"][profile]["dropFromV134"])
            mappings.append({"source": row["source"], "entry": entry, "sourceSha256": row["sourceSha256"],
                "sourcePathAliases": [row["source"], "res://" + entry, row["uid"]],
                "importEntry": row["importEntry"], "importSha256": row["importSha256"],
                "logicalDimensions": row["logicalDimensions"], "initialFile": path.as_posix(),
                "initial": {k: v for k, v in row["profiles"][profile].items() if k != "proof"},
                "proof": proof, "full": full[entry],
                "textureSpec": {"source": row["source"], "resource": "res://" + full[entry]["entry"], "inPlace": True},
                "initialIntegrationConditions": row["initialIntegrationConditions"],
                "keepOriginalUntilInitialConditionsHandled": bool(row["initialIntegrationConditions"]),
                "pixelCoordinateAudit": row["pixelCoordinateAudit"], "directCodeReferences": row["directCodeReferences"]})
        manifest = {"schema": "meadow-progressive-textures-v135-1", "profile": profile, "maxPhysicalEdge": limit,
            "status": "OFFLINE_MIP_BYTES_EXACT_RUNTIME_ADAPTATION_REQUIRED", "runtimeReady": False,
            "sourcePackSha256": SOURCE_SHA, "observedCorePackSha256": CORE_SHA,
            "inventory": (output / "inventory.json").as_posix(),
            "budget": report["totals"]["profiles"][profile], "replacements": mappings,
            "recommendedSamplerPolicy": sampler_policy(report, profile),
            "water": {"action": "leave-existing-core-and-full-upgrade-unchanged; no water file emitted",
                      "source": water["source"], "entry": water["entry"],
                      "expectedCoreSha256": water["observedCoreSha256"], "expectedCoreBytes": water["observedCoreBytes"],
                      "requiredFullSha256": water["sourceSha256"], "requiredFullBytes": water["sourceBytes"],
                      "existingFullResource": "res://progressive/textures/river-ripples-full.ctex"},
            "allImportRemapsAndLogicalDimensionsUnchanged": True, "allRetainedEncodedMipRecordsExact": True,
            "fullFilesByteExactToV134": True, "waterUpgradeOwnedByExistingMainChunk": True,
            "nonTextureOrScriptEdits": False, "packGenerated": False, "integrationConditions": CONTRACT_NOTES,
            "limits": ["Not a runtime-safe drop-in pack; the eight initial pixel/geometry contracts need main-owned handling or original CTEX retention.",
                       "Exact encoded selected alpha is not full-resolution visual equality. Odd dimensions may produce a size well below the cap.",
                       "Late CTEX bytes are exact, but full world parity also requires original alpha-derived geometry and all live/code/cache references.",
                       "No engine/native/export/compile/browser/service was invoked; no controlled loading performance is claimed."]}
        manifest_path = output / profile / "manifest.json"
        write_json(manifest_path, manifest)
        manifests[profile] = {"path": manifest_path.as_posix(), "sha256": sha(manifest_path.read_bytes()), "count": len(mappings)}
    require(sha(SOURCE.read_bytes()) == SOURCE_SHA and sha(OBSERVED_CORE.read_bytes()) == CORE_SHA,
            "Input pack changed during offline generation")
    proof = {"status": "PASS_OFFLINE_BYTES_ONLY", "sourcePackSha256": SOURCE_SHA,
             "observedCorePackSha256": CORE_SHA, "inputPacksUnchanged": True,
             "texturesInventoried": len(report["textures"]), "singleMipTextures": report["singleMipTextures"],
             "initialContractTextureCount": len(INITIAL_CONTRACTS), "candidateTextureCopies": 62,
             "exactFullTextureCopies": len(full), "waterFilesEmitted": 0, "packWrites": 0,
             "manifests": manifests, "totals": report["totals"], "noPixelReencoding": True,
             "runtimeOrVisualAcceptance": False}
    write_json(output / "proof.json", proof)
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-only", action="store_true", help="Read-only; prints inventory without producing files")
    parser.add_argument("--output", type=Path, default=SCOPE / "candidate-01")
    args = parser.parse_args()
    result = inventory()[0] if args.inventory_only else generate(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
