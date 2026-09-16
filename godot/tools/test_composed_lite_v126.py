"""One read-only proof of the pinned v126 composition; no builds or native runs.

This checks actual payloads, not the builder's Boolean assertions. The two
contributions must reverse independently, and both must reverse to the base.
Run: E:/Anaconda3/python.exe -B godot/tools/test_composed_lite_v126.py
"""
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct

from PIL import Image

from inspect_web_pack import read_pack
from test_dense_scene_containers_v126 import ALLOWED, decode_rscc


ROOT = Path(__file__).resolve().parents[2]
PINS = {
    "base": ("artifacts/v125/index-lite.pck", "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"),
    "dense": ("artifacts/startup-v126/dense-scenes/candidate-01/index-lite.pck", "1486269c29086c476a18550d6b2baf59be970cb1ca7a323899f9c4a2f945210c"),
    "texture": ("artifacts/startup-v126/textures/mip2-q60/index-lite.pck", "a55f331daee2cda8594f9f784482dd580cb331fcda1962f4e1adc69df40228a4"),
    "composed": ("artifacts/startup-v126/composed/dense-q60-01/index-lite.pck", "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"),
}
ORIGINAL = ("artifacts/v114/index.pck", "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d")
FULL_PHYSICAL = {
    "castle-dragon-turns-v57", "castle-town-v62", "windmill-village-v50",
    "mountain-massif-v106", "wooded-hills-v107", "mountain-groves-v100",
    "meadow-herbs-v73", "meadow-scrub-v74", "road-lanterns-v52", "foreground-lantern-v1",
}
MIP2 = {
    "meadow-patches-v37", "woodland-groups-v37", "living-meadow-v38",
    "distant-groves-v57", "valley-colonies-v41", "woodland-belts-v39",
    "frame-growth-v43", "reference-trees-v40", "limestone-escarpments-v46",
    "meadow-colonies-v44", "foreground-oak-v39", "country-fence-v47",
}
SOURCE_PROOF = ROOT / "artifacts/startup-v118/independent/zero-unused-light-contract-review.json"
SOURCE_PROOF_SHA = "d4aef8ada6cd54be0c8bc95861757e2e67e554a95fbce744c2a48dbb1d97c0e3"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def unique_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def payloads(relative, digest):
    path = ROOT / relative
    blob = path.read_bytes()
    require(sha(blob) == digest, f"Pack SHA mismatch: {relative}")
    inventory = read_pack(path)  # Bounded directory plus every entry MD5.
    require(len(inventory["entries"]) == 184, f"184-entry inventory: {relative}")
    data = {r["path"]: blob[r["offset"]:r["offset"] + r["bytes"]] for r in inventory["entries"]}
    return blob, inventory, data


def ctex(blob):
    require(blob[:8] == b"GST2\x01\0\0\0" and len(blob) >= 56, "CTEX header")
    logical = list(struct.unpack_from("<II", blob, 8))
    mode, width, height, mips, fmt = struct.unpack_from("<IHHII", blob, 36)
    require(mode == 2 and fmt in (4, 5) and 0 < width <= 4096 and 0 < height <= 4096, "WebP RGB(A) CTEX")
    require(mips == max(width, height).bit_length() - 1, "Complete CTEX mip chain through 1x1")
    cursor, levels = 52, []
    for level in range(mips + 1):
        require(cursor + 4 <= len(blob), "CTEX mip header bound")
        length = struct.unpack_from("<I", blob, cursor)[0]
        cursor += 4
        data = blob[cursor:cursor + length]
        require(length > 0 and len(data) == length, "CTEX mip payload bound")
        cursor += length
        with Image.open(io.BytesIO(data)) as image:
            require(image.format == "WEBP" and image.size == (max(1, width >> level), max(1, height >> level)),
                    "Physical dimensions follow integer-halved source mips")
            rgba = image.convert("RGBA")
        levels.append((data, rgba))
    require(cursor == len(blob), "No CTEX trailing bytes")
    return logical, fmt, levels


def audit():
    blobs, inventories, maps = {}, {}, {}
    for label, pin in PINS.items():
        blobs[label], inventories[label], maps[label] = payloads(*pin)
    base, final = maps["base"], maps["composed"]
    for label in maps:
        require(list(maps[label]) == list(base), f"Inventory paths/order changed: {label}")
        require((inventories[label]["version"], inventories[label]["engine"]) ==
                (inventories["base"]["version"], inventories["base"]["engine"]), "PCK engine/format changed")
    dense = {p for p in base if maps["dense"][p] != base[p]}
    texture = {p for p in base if maps["texture"][p] != base[p]}
    require(dense == ALLOWED and len(texture) == 22 and dense.isdisjoint(texture), "Disjoint 5+22 changes")
    require(all(p.endswith(".ctex") for p in texture), "Texture-only contribution")
    require({p for p in base if final[p] != base[p]} == dense | texture, "Exact 27-change composition")
    for p in base:
        expected = maps["dense"][p] if p in dense else maps["texture"][p] if p in texture else base[p]
        require(final[p] == expected, f"Actual composed payload differs: {p}")
    require({p: base[p] if p in dense else final[p] for p in base} == maps["texture"], "Reverse dense -> texture")
    require({p: base[p] if p in texture else final[p] for p in base} == maps["dense"], "Reverse texture -> dense")
    require({p: base[p] if p in dense | texture else final[p] for p in base} == base, "Reverse both -> base")
    proof_path = (ROOT / PINS["composed"][0]).with_name("proof.json")
    proof = unique_json(proof_path)
    require(proof["schemaVersion"] == 1 and proof["profile"] == "v126-dense-scenes-mip2-q60", "Composition schema")
    require(set(proof["inputs"]) == {"base", "dense", "texture"}, "Exactly three composition inputs")
    for label, entry in proof["inputs"].items():
        require(Path(entry["path"]).resolve() == (ROOT / PINS[label][0]).resolve() and
                entry["sha256"] == PINS[label][1], "Composition input attestation")
    changes = {r["path"]: r for r in proof["changes"]}
    require(len(changes) == len(proof["changes"]) == 27 and changes.keys() == dense | texture, "Proof records")
    for p, row in changes.items():
        require(row == {"path": p, "candidate": "dense" if p in dense else "texture",
                        "beforeSha256": sha(base[p]), "afterSha256": sha(final[p]), "bytes": len(final[p])},
                f"Actual payload differs from proof: {p}")
    decoded = []
    for p in sorted(dense):
        before_raw, _ = decode_rscc(base[p])
        after_raw, info = decode_rscc(final[p])
        require(before_raw == after_raw, f"Scene raw bytes changed: {p}")
        decoded.append({"path": p, **info, "decodedByteExact": True})
    # Revalidate selected mips from the frozen lossless original, never from
    # an already lossy lite. Identical alpha covers transparent gutters/edges
    # at the selected mip, not visual equality to the higher-resolution image.
    original_blob, _, original = payloads(*ORIGINAL)
    texture_proof_path = (ROOT / PINS["texture"][0]).with_name("lite-build.json")
    q = unique_json(texture_proof_path)
    require(q["schemaVersion"] == 2 and q["profile"] == "mip2-q60" and q["sourceSha256"] == PINS["base"][1]
            and q["textureOriginalSha256"] == ORIGINAL[1] and q["liteSha256"] == PINS["texture"][1], "Q60 proof pins")
    qr = {r["path"]: r for r in q["changes"]}
    require(len(qr) == len(q["changes"]) == 22 and qr.keys() == texture, "Q60 records cover actual changes")
    require({Path(p).name.split(".png-")[0] for p in texture} == FULL_PHYSICAL | MIP2, "Explicit texture allowlist")
    textures, alpha_levels = [], 0
    for p in sorted(texture):
        row = qr[p]
        name = Path(p).name.split(".png-")[0]
        logical, fmt, levels = ctex(final[p])
        ol, of, source_levels = ctex(original[p])
        bl, bf, before_levels = ctex(base[p])
        drop = 0 if name in FULL_PHYSICAL else 2
        require(final[p][:36] == base[p][:36] == original[p][:36] and logical == bl == ol and fmt == bf == of,
                f"Original logical dimensions/header/image format: {p}")
        require(row["beforeSha256"] == sha(base[p]) and row["afterSha256"] == sha(final[p]) and
                row["originalSha256"] == sha(original[p]), "Texture payload hashes")
        require(row["before"] == len(base[p]) and row["after"] == len(final[p]) and row["mipDrop"] == drop
                and row["physicalAfter"] == list(levels[0][1].size)
                and row["physicalBefore"] == list(before_levels[0][1].size)
                and row["logicalSize"] == logical and row["allRemainingMips"] is True, "Texture size/drop proof")
        require(len(levels) == len(source_levels) - drop == len(row["levels"]), "Retained mip count")
        if name in FULL_PHYSICAL:
            require(levels[0][1].size == source_levels[0][1].size, "CPU/dragon full physical dimensions")
        for i, ((webp, image), level) in enumerate(zip(levels, row["levels"])):
            source_webp, source_image = source_levels[i + drop]
            alpha = image.getchannel("A").tobytes()
            require(image.size == source_image.size and alpha == source_image.getchannel("A").tobytes(),
                    f"Selected source mip dimension/alpha mismatch: {p} mip {i}")
            require(level["sourceLevel"] == i + drop and level["size"] == list(image.size) and
                    level["sourceWebpSha256"] == sha(source_webp) and level["webpSha256"] == sha(webp)
                    and level["alphaExact"] is True and level["alphaSha256"] == sha(alpha), "Mip proof")
            alpha_levels += 1
        textures.append({"path": p, "logicalSize": logical, "physicalSize": list(levels[0][1].size),
                         "originalMipDrop": drop, "mipCount": len(levels), "allSelectedMipAlphaExact": True})
    frozen_categories = {}
    for label, selector in {
        "compiledScripts": lambda p: p.endswith(".gdc"),
        "shaderSourcesAndIncludes": lambda p: p.endswith((".gdshader", ".gdshaderinc")),
        "settings": lambda p: p == "project.binary",
        "terrain": lambda p: "terrain" in p.lower(),
        "waterNamedAssetsAndShaders": lambda p: any(s in p.lower() for s in ("river-ripples", "water")),
        "unchangedTextures": lambda p: p.endswith(".ctex") and p not in texture,
    }.items():
        paths = [p for p in base if selector(p)]
        require(paths and all(final[p] == base[p] for p in paths), f"Frozen category: {label}")
        frozen_categories[label] = {"count": len(paths), "paths": paths, "allByteExact": True}
    require(sha(SOURCE_PROOF.read_bytes()) == SOURCE_PROOF_SHA, "Prior no-new-light lifetime proof pin")
    lifetime = unique_json(SOURCE_PROOF)
    require(lifetime["packSha256"] == PINS["base"][1] and lifetime["sceneContractAccepted"] is True and
            not lifetime["spotAreaOrDynamicFactoryMatches"], "Applicable prior light source proof")
    script_pins = {p: s for p, s in lifetime["sourcePins"].items() if p.endswith(".gd")}
    require(len(script_pins) == 40 and all(sha(Path(p).read_bytes()) == s for p, s in script_pins.items()),
            "The 40 previously reviewed script source pins remain exact")
    gzip_sizes = {str(level): len(gzip.compress(blobs["composed"], compresslevel=level, mtime=0)) for level in (6, 9)}
    require(len(blobs["composed"]) == proof["bytes"] == 34261596 and proof["packSha256"] == PINS["composed"][1]
            and proof["entryCount"] == 184 and proof["exactEntries"] == 157, "Composed raw counts")
    require(gzip_sizes == {"6": 30928686, "9": 30925939} and
            proof["offlineGzip6Bytes"] == gzip_sizes["6"] and proof["offlineGzip9Bytes"] == gzip_sizes["9"], "Offline gzip size proof")
    for label, (relative, _) in PINS.items():
        require((ROOT / relative).read_bytes() == blobs[label], "Composition inputs/output changed during read-only audit")
    require((ROOT / ORIGINAL[0]).read_bytes() == original_blob, "Frozen original changed during audit")
    frozen = unique_json(ROOT / "artifacts/startup-v126/independent/baseline-source-pins.json")["frozen"]
    for row in frozen:
        require(sha((ROOT / row["path"]).read_bytes()) == row["expectedSha256"], "Frozen v125 engine/PCK/icon changed")
    return {"schemaVersion": 1, "status": "PASS_PINNED_COMPOSITION_AND_SELECTED_MIP_ALPHA",
            "packs": {k: {"path": str(ROOT / v[0]), "sha256": v[1], "bytes": len(blobs[k])} for k, v in PINS.items()},
            "entries": 184, "allPackEntryMd5Checked": True, "baseExactEntries": 157,
            "denseChanges": 5, "textureChanges": 22, "contributionsDisjoint": True,
            "reverseDenseEqualsTexture": True, "reverseTextureEqualsDense": True, "reverseBothEqualsBase": True,
            "denseDecodedByteIdentity": decoded, "selectedTextureMips": textures, "alphaExactLevels": alpha_levels,
            "fullPhysicalProtectedTextures": 10, "originalLogicalHeadersExact": True,
            "frozenCategories": frozen_categories, "frozenV125FilesRehashed": len(frozen),
            "zeroTypeLifetimeEvidence": {"path": str(SOURCE_PROOF), "sha256": SOURCE_PROOF_SHA,
                                         "sourcePinsExact": 40, "compiledScriptsExactToReviewedPack": True,
                                         "allSceneDecodedBytesExactToReviewedPack": True},
            "offlineGzipBytes": gzip_sizes, "proofSha256": sha(proof_path.read_bytes()),
            "textureProofSha256": sha(texture_proof_path.read_bytes()), "checkerSha256": sha(Path(__file__).read_bytes()),
            "inputFilesUnchanged": True, "builds": 0, "nativeRuns": 0, "browserActions": 0,
            "limitations": ["Offline gzip sizes are not observed HTTP transfer or Godot startup time.",
                            "Exact selected-mip alpha preserves its gutters/edge coverage, not high-resolution RGB or visual sharpness.",
                            "No GPU/shader/2K visual or performance acceptance; final native scene evidence is separate."]}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
