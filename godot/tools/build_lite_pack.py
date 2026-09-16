"""Build a separate complete-scene low-resolution PCK, never overwrite originals.

Use the already alpha-filtered imported mip chain, not a naive resample across
atlas cells. CTEX logical dimensions remain original (Godot's size-limit contract)
so measured UV crops and world proportions remain stable. Pixel-sampled assets
stay at their original physical dimensions. Every retained mip keeps exact alpha.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from inspect_web_pack import read_pack
from build_web_quality import write_pack


PRESERVE_PHYSICAL = {
    "castle-dragon-turns-v57", "castle-town-v62", "windmill-village-v50",
    "mountain-massif-v106", "wooded-hills-v107", "mountain-groves-v100",
    "meadow-herbs-v73", "meadow-scrub-v74", "road-lanterns-v52",
    "foreground-lantern-v1",
}
MATERIALS = {
    "bridge-oak-v39", "limestone-fractured-v61", "meadow-sward-v60",
    "ochre-trail-v39", "riverbank-limestone-v68",
}
PRESERVE_BYTES = {"river-ripples-v37"}

# Opt-in v126 texture-only composition, not a new default for the legacy builder.
# New encodes must originate in the pinned lossless original, never a lossy lite.
TEXTURE_BASE_SHA256 = "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"
TEXTURE_ORIGINAL_SHA256 = "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d"
TEXTURE_PROFILES = {"mip2-q60": 60, "mip2-q48": 48}
EXTRA_MIP_TEXTURES = {
    "meadow-patches-v37", "woodland-groups-v37", "living-meadow-v38",
    "distant-groves-v57", "valley-colonies-v41", "woodland-belts-v39",
    "frame-growth-v43", "reference-trees-v40", "limestone-escarpments-v46",
    "meadow-colonies-v44", "foreground-oak-v39", "country-fence-v47",
}
KEEP_LITE_TEXTURES = PRESERVE_BYTES | MATERIALS | {
    "moon-stag-v54", "bud-deer-v54", "leaf-hare-v54", "gold-fox-v54",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode_ctex(blob):
    if len(blob) < 56 or blob[:4] != b"GST2" or struct.unpack_from("<I", blob, 4)[0] != 1:
        raise ValueError("Expected pinned Godot GST2 version 1")
    logical = struct.unpack_from("<II", blob, 8)
    kind, width, height, count, image_format = struct.unpack_from("<IHHII", blob, 36)
    if kind != 2 or image_format not in (4, 5) or count > 16 or not width or not height:
        raise ValueError("Expected WebP RGB(A) mip chain")
    offset, levels = 52, []
    for level in range(count + 1):
        if offset + 4 > len(blob):
            raise ValueError("Truncated mip size")
        length = struct.unpack_from("<I", blob, offset)[0]
        offset += 4
        data = blob[offset:offset + length]
        offset += length
        if not length or len(data) != length:
            raise ValueError("Truncated mip payload")
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        if image.size != (max(1, width >> level), max(1, height >> level)):
            raise ValueError("Mismatched image/mip dimensions")
        levels.append((data, image))
    if offset != len(blob):
        raise ValueError("Trailing CTEX bytes")
    return logical, image_format, levels


def compress_ctex(blob, name, *, mip_drop=None, quality=None):
    logical, image_format, levels = decode_ctex(blob)
    drop = (0 if name in PRESERVE_PHYSICAL else 2 if name in MATERIALS else 1) if mip_drop is None else mip_drop
    if type(drop) is not int or drop < 0:
        raise ValueError("Mip drop must be a nonnegative integer")
    if name in PRESERVE_PHYSICAL and drop:
        raise ValueError("Pixel-coordinate textures must keep physical dimensions")
    drop = min(drop, len(levels) - 1)
    quality = (68 if name in MATERIALS else 76) if quality is None else quality
    if type(quality) is not int or not 1 <= quality <= 100:
        raise ValueError("WebP quality must be an integer in 1..100")
    width, height = levels[drop][1].size
    header = bytearray(blob[:52])
    struct.pack_into("<IHHII", header, 36, 2, width, height, len(levels) - drop - 1, image_format)
    result, evidence = bytearray(header), []
    for source_level, (source, image) in enumerate(levels[drop:], drop):
        buffer = io.BytesIO()
        image_to_save = image.convert("RGB") if image_format == 4 else image
        image_to_save.save(buffer, "WEBP", quality=quality, method=6, exact=True, alpha_quality=100)
        candidate = buffer.getvalue()
        if len(candidate) >= len(source):
            candidate = source
        decoded = Image.open(io.BytesIO(candidate)).convert("RGBA")
        before, after = np.asarray(image), np.asarray(decoded)
        if decoded.size != image.size or not np.array_equal(before[:, :, 3], after[:, :, 3]):
            raise ValueError(f"{name}: changed retained mip alpha or dimensions")
        visible = before[:, :, 3] >= 16
        delta = before[:, :, :3].astype(np.float32) - after[:, :, :3]
        mse = float(np.mean(delta[visible] ** 2)) if visible.any() else 0.0
        evidence.append({"sourceLevel": source_level, "size": list(image.size),
                         "bytes": len(candidate), "alphaExact": True,
                         "sourceWebpSha256": sha(source), "webpSha256": sha(candidate),
                         "alphaSha256": sha(after[:, :, 3].tobytes()),
                         "visibleRgbRmse": round(mse ** 0.5, 4)})
        result.extend(struct.pack("<I", len(candidate)))
        result.extend(candidate)
    return bytes(result), {"logicalSize": list(logical), "physicalBefore": list(levels[0][1].size),
                           "physicalAfter": [width, height], "mipDrop": drop,
                           "quality": quality, "levels": evidence,
                           "reason": "pixel-registration" if name in PRESERVE_PHYSICAL else "screen-detail-budget"}


def is_lossless_webp(data):
    """Inspect RIFF chunks, not a substring that could occur inside image data."""
    if (len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP"
            or struct.unpack_from("<I", data, 4)[0] != len(data) - 8):
        raise ValueError("Invalid WebP RIFF container")
    offset, codecs = 12, []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("Truncated WebP chunk")
        tag, size = data[offset:offset + 4], struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8 + size + (size & 1)
        if offset > len(data):
            raise ValueError("Truncated WebP chunk payload")
        if tag in (b"VP8 ", b"VP8L", b"ANIM", b"ANMF"):
            codecs.append(tag)
    return codecs == [b"VP8L"]


def texture_recipe(name, profile):
    if profile not in TEXTURE_PROFILES:
        raise ValueError(f"Unknown bounded texture profile: {profile}")
    if name in KEEP_LITE_TEXTURES:
        return None
    if name not in PRESERVE_PHYSICAL | EXTRA_MIP_TEXTURES:
        raise ValueError(f"Unreviewed texture: {name}")
    return {"mip_drop": 0 if name in PRESERVE_PHYSICAL else 2,
            "quality": TEXTURE_PROFILES[profile]}


def verify_texture(original, candidate, name):
    """Decode every retained mip and prove selected-source alpha/registration.

    This is a structural proof, not whole-scene visual acceptance. No crop,
    resample, synthetic padding, or regeneration of missing mips is permitted.
    """
    logical, fmt, before = decode_ctex(original)
    result_logical, result_fmt, after = decode_ctex(candidate)
    if not all(is_lossless_webp(encoded) for encoded, _ in before):
        raise ValueError(f"{name}: original contains a lossy/re-encoded mip")
    if len(before) != max(before[0][1].size).bit_length() or before[-1][1].size != (1, 1):
        raise ValueError(f"{name}: original mip chain is incomplete")
    drop = len(before) - len(after)
    if (original[:36] != candidate[:36] or logical != result_logical or fmt != result_fmt
            or drop < 0 or after[-1][1].size != (1, 1)):
        raise ValueError(f"{name}: changed logical/header/format or incomplete mip chain")
    if name in PRESERVE_PHYSICAL | PRESERVE_BYTES and drop:
        raise ValueError(f"{name}: changed pixel registration")
    if name in PRESERVE_BYTES and candidate != original:
        raise ValueError(f"{name}: water must remain byte-exact")
    records = []
    for source_level, (encoded, image) in enumerate(after, drop):
        original_encoded, original_image = before[source_level]
        a, b = np.asarray(original_image), np.asarray(image)
        if image.size != original_image.size or not np.array_equal(a[:, :, 3], b[:, :, 3]):
            raise ValueError(f"{name}: mip {source_level} alpha/dimensions changed")
        visible = a[:, :, 3] >= 16
        delta = a[:, :, :3].astype(np.float32) - b[:, :, :3]
        mse = float(np.mean(delta[visible] ** 2)) if visible.any() else 0.0
        records.append(dict(sourceLevel=source_level, size=list(image.size),
                            sourceWebpSha256=sha(original_encoded), webpSha256=sha(encoded),
                            alphaExact=True, alphaSha256=sha(b[:, :, 3].tobytes()),
                            visibleRgbRmse=round(mse ** 0.5, 4)))
    return dict(logicalSize=list(logical), physicalAfter=list(after[0][1].size),
                mipDrop=drop, allRemainingMips=True, levels=records)


def build_texture_candidate(base, destination, texture_original, profile):
    """Compose only reviewed CTEX changes onto the frozen v125 combined pack.

    All other resources (including the six v125 shader changes), exact water,
    fauna and already-small material textures are copied from base. A candidate
    is only certified when smaller in both raw and gzip-9 than the same base.
    """
    if profile not in TEXTURE_PROFILES:
        raise ValueError(f"Unknown bounded texture profile: {profile}")
    base, texture_original = base.resolve(strict=True), texture_original.resolve(strict=True)
    destination = destination.resolve()
    manifest_path = destination.with_name("lite-build.json")
    gzip_path = destination.with_suffix(destination.suffix + ".gz")
    if any(path.exists() for path in (destination, gzip_path, manifest_path,
                                    destination.with_name(destination.name + ".building"))):
        raise ValueError("Use a fresh candidate directory; never overwrite a pack/proof")
    base_bytes, original_bytes = base.read_bytes(), texture_original.read_bytes()
    if sha(base_bytes) != TEXTURE_BASE_SHA256 or sha(original_bytes) != TEXTURE_ORIGINAL_SHA256:
        raise ValueError("Texture composition requires the pinned v125 base and v114 original")
    base_inventory, original_inventory = read_pack(base), read_pack(texture_original)
    original_entries = {row["path"]: row for row in original_inventory["entries"]}
    base_entries = {row["path"]: row for row in base_inventory["entries"]}
    if base_entries.keys() != original_entries.keys():
        raise ValueError("Base/original resource set changed")
    texture_names = {Path(path).name.split(".png-")[0] for path in base_entries if path.endswith(".ctex")}
    if texture_names != KEEP_LITE_TEXTURES | PRESERVE_PHYSICAL | EXTRA_MIP_TEXTURES:
        raise ValueError("Pinned texture inventory does not match the reviewed 32 textures")
    replacements, changes, textures = {}, [], []
    categories = {}
    for path, entry in base_entries.items():
        extension = Path(path).suffix or "(none)"
        category = categories.setdefault(extension, {"count": 0, "bytes": 0})
        category["count"] += 1
        category["bytes"] += entry["bytes"]
        if not path.endswith(".ctex"):
            continue
        name = Path(path).name.split(".png-")[0]
        before = base_bytes[entry["offset"]:entry["offset"] + entry["bytes"]]
        original_entry = original_entries[path]
        original = original_bytes[original_entry["offset"]:original_entry["offset"] + original_entry["bytes"]]
        recipe = texture_recipe(name, profile)
        # Validate even retained entries; never accept a lossy original as an
        # encoding source, or silently trust the old lite alpha/header contract.
        base_proof = verify_texture(original, before, name)
        after = before
        if recipe:
            if recipe["mip_drop"] - base_proof["mipDrop"] not in (0, 1):
                raise ValueError(f"{name}: profile must drop at most one additional mip")
            candidate, _ = compress_ctex(original, name, **recipe)
            # Keep an existing lite entry byte-for-byte if a new encode loses.
            # It is never used as the input to an encoder.
            if (len(candidate) < len(before) and
                    len(gzip.compress(candidate, compresslevel=9, mtime=0)) <
                    len(gzip.compress(before, compresslevel=9, mtime=0))):
                after = candidate
                replacements[path] = after
        proof = verify_texture(original, after, name)
        record = dict(path=path, kind="lite-ctex", before=len(before), after=len(after),
                      beforeSha256=sha(before), afterSha256=sha(after),
                      originalSha256=sha(original), originalBytes=len(original),
                      origin="frozen-original-mips" if after != before else "v125-byte-exact",
                      baseMipDrop=base_proof["mipDrop"],
                      extraMipDrop=proof["mipDrop"] - base_proof["mipDrop"],
                      requestedQuality=recipe["quality"] if recipe else None,
                      physicalBefore=base_proof["physicalAfter"], **proof)
        textures.append(record)
        if after != before:
            changes.append(record)
        print(f"TEXTURE {name}: {len(before)} -> {len(after)}; {record['origin']}; "
              f"extra mip {record['extraMipDrop']}", flush=True)
    if not replacements:
        raise ValueError("Profile has no smaller texture replacements")
    write_pack(base, base_inventory, destination, replacements)
    candidate_bytes = destination.read_bytes()
    candidate_inventory = read_pack(destination)
    after_entries = {row["path"]: row for row in candidate_inventory["entries"]}
    if after_entries.keys() != base_entries.keys():
        raise ValueError("Candidate changed resource set")
    exact, entry_proofs = 0, []
    for path, entry in base_entries.items():
        after_entry = after_entries[path]
        before = base_bytes[entry["offset"]:entry["offset"] + entry["bytes"]]
        after = candidate_bytes[after_entry["offset"]:after_entry["offset"] + after_entry["bytes"]]
        if after != replacements.get(path, before):
            raise ValueError(f"Candidate entry differs from the scoped replacement: {path}")
        exact += before == after
        entry_proofs.append(dict(path=path, byteExact=before == after,
                                 beforeSha256=sha(before), afterSha256=sha(after)))
    packed = gzip.compress(candidate_bytes, compresslevel=9, mtime=0)
    base_gzip = gzip.compress(base_bytes, compresslevel=9, mtime=0)
    if len(candidate_bytes) >= len(base_bytes) or len(packed) >= len(base_gzip):
        raise ValueError("Candidate does not improve raw and measured gzip size")
    if sha(base.read_bytes()) != TEXTURE_BASE_SHA256 or sha(texture_original.read_bytes()) != TEXTURE_ORIGINAL_SHA256:
        raise ValueError("Frozen input pack changed during build")
    with gzip_path.open("xb") as writer:
        writer.write(packed)
    if gzip.decompress(gzip_path.read_bytes()) != candidate_bytes:
        raise ValueError("Candidate gzip round-trip failed")
    report = dict(schemaVersion=2, profile=profile, source=str(base),
                  sourceSha256=TEXTURE_BASE_SHA256, textureOriginal=str(texture_original),
                  textureOriginalSha256=TEXTURE_ORIGINAL_SHA256, sourceBytes=len(base_bytes),
                  sourceGzipBytes=len(base_gzip), liteBytes=len(candidate_bytes), liteGzipBytes=len(packed),
                  gzipLevel=9, gzipMtime=0, liteSha256=sha(candidate_bytes), liteGzipSha256=sha(packed),
                  fullScene=True, allNonTexturesByteExact=True, waterTextureUnchanged=True,
                  entryCount=len(base_entries), exactEntryCount=exact, inputsUnchanged=True,
                  visualAcceptance="pending main QHD day/night/animation review",
                  renderContract="new pack hash; main must validate and integrate; not automatically eligible",
                  categoriesBefore=categories, changes=changes, textures=textures, entries=entry_proofs)
    with manifest_path.open("x", encoding="utf-8") as writer:
        json.dump(report, writer, indent=2)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("changes", "textures", "entries")}, indent=2), flush=True)
    return report


def runtime_replacements(source, by_name, manifest_path, source_sha):
    """Accept only the independently compiled, pinned startup-audit entry."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("sourcePckSha256") != source_sha:
        raise ValueError("Runtime manifest uses a different original pack")
    records = manifest.get("replacements", [])
    if len(records) != 1 or records[0].get("path") != "scripts/meadow_scene.gdc":
        raise ValueError("Runtime scope is exactly the main scene startup-audit script")
    record = records[0]
    name = record["path"]
    entry = by_name[name]
    with source.open("rb") as reader:
        reader.seek(entry["offset"])
        before = reader.read(entry["bytes"])
    if sha(before) != record["beforeSha256"]:
        raise ValueError("Runtime original bytecode checksum mismatch")
    candidate = Path(record["file"])
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    after = candidate.read_bytes()
    if sha(after) != record["afterSha256"]:
        raise ValueError("Runtime candidate bytecode checksum mismatch")
    if not before.startswith(b"GDSC") or after[:8] != before[:8]:
        raise ValueError("Runtime candidate must use the original compiled-script format/version")
    proof = Path(record["proof"])
    if not proof.is_absolute():
        proof = manifest_path.parent / proof
    # A proof is recorded, not treated as a substitute for independent review.
    proof_bytes = proof.read_bytes()
    change = {**record, "kind": "lite-runtime", "before": len(before), "after": len(after),
              "proofSha256": sha(proof_bytes),
              "reason": "Only gate and time optional startup diagnostics; preserve gameplay and rendering"}
    return {name: after}, [change]


def build(source, destination, geometry_manifest=None, project_binary=None, texture_seed=None, runtime_manifest=None):
    source, destination = source.resolve(strict=True), destination.resolve()
    if destination.exists() or destination == source:
        raise ValueError("Output must be a new independent pack")
    manifest_path = destination.with_name("lite-build.json")
    if manifest_path.exists():
        raise ValueError("Output manifest already exists; use a fresh candidate directory")
    source_sha = sha(source.read_bytes())
    inventory = read_pack(source)
    by_name = {entry["path"]: entry for entry in inventory["entries"]}
    replacements, changes = {}, []
    if texture_seed:
        seed_report = json.loads(texture_seed.with_name("lite-build.json").read_text(encoding="utf-8"))
        if seed_report["sourceSha256"] != source_sha:
            raise ValueError("Texture seed uses a different original pack")
        if sha(texture_seed.read_bytes()) != seed_report["liteSha256"]:
            raise ValueError("Texture seed checksum mismatch")
        seed_entries = {entry["path"]: entry for entry in read_pack(texture_seed)["entries"]}
        with texture_seed.open("rb") as reader:
            for record in seed_report["changes"]:
                if record["kind"] != "lite-ctex":
                    continue
                name = record["path"]
                entry = seed_entries[name]
                reader.seek(entry["offset"])
                after = reader.read(entry["bytes"])
                if sha(after) != record["afterSha256"]:
                    raise ValueError("Texture seed entry checksum mismatch")
                replacements[name] = after
                changes.append(record)
    with source.open("rb") as reader:
        for entry in inventory["entries"]:
            if texture_seed:
                break
            if not entry["path"].endswith(".ctex"):
                continue
            name = Path(entry["path"]).name.split(".png-")[0]
            if name in PRESERVE_BYTES:
                continue
            reader.seek(entry["offset"])
            before = reader.read(entry["bytes"])
            after, record = compress_ctex(before, name)
            replacements[entry["path"]] = after
            record.update(path=entry["path"], kind="lite-ctex", before=len(before), after=len(after),
                          beforeSha256=sha(before), afterSha256=sha(after))
            changes.append(record)
            print(f"TEXTURE {name}: {record['physicalBefore']} -> {record['physicalAfter']}, {len(before)} -> {len(after)}", flush=True)
    if geometry_manifest:
        geometry = json.loads(geometry_manifest.read_text(encoding="utf-8-sig"))
        for record in geometry["replacements"]:
            name = record["path"]
            if name not in by_name or name in replacements or not name.startswith("assets/baked/"):
                raise ValueError(f"Unscoped geometry replacement {name}")
            entry = by_name[name]
            with source.open("rb") as reader:
                reader.seek(entry["offset"])
                before = reader.read(entry["bytes"])
            if sha(before) != record["beforeSha256"]:
                raise ValueError(f"Geometry source mismatch {name}")
            candidate_path = Path(record["file"])
            if not candidate_path.is_absolute():
                candidate_path = geometry_manifest.parent / candidate_path
            after = candidate_path.read_bytes()
            if sha(after) != record["afterSha256"]:
                raise ValueError(f"Geometry candidate mismatch {name}")
            replacements[name] = after
            changes.append({**record, "kind": "lite-geometry", "before": len(before), "after": len(after)})
    if project_binary:
        after = project_binary.read_bytes()
        if not after.startswith(b"ECFG"):
            raise ValueError("Expected Godot exported project settings")
        entry = by_name["project.binary"]
        with source.open("rb") as reader:
            reader.seek(entry["offset"])
            before = reader.read(entry["bytes"])
        replacements["project.binary"] = after
        changes.append(dict(path="project.binary", kind="lite-project-settings", before=len(before), after=len(after),
                            beforeSha256=sha(before), afterSha256=sha(after)))
    if runtime_manifest:
        runtime, runtime_changes = runtime_replacements(source, by_name, runtime_manifest, source_sha)
        if replacements.keys() & runtime.keys():
            raise ValueError("Duplicate runtime replacement")
        replacements.update(runtime)
        changes.extend(runtime_changes)
    write_pack(source, inventory, destination, replacements)
    if sha(source.read_bytes()) != source_sha:
        raise ValueError("Source pack changed during build")
    report = dict(schemaVersion=1, source=str(source), sourceSha256=source_sha,
                  sourceBytes=source.stat().st_size, liteBytes=destination.stat().st_size,
                  liteSha256=sha(destination.read_bytes()), fullScene=True,
                  waterTextureUnchanged=True, changes=changes)
    manifest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "changes"}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--geometry-manifest", type=Path)
    parser.add_argument("--project-binary", type=Path)
    parser.add_argument("--texture-seed", type=Path, help="Reuse a verified texture trial without recompressing")
    parser.add_argument("--runtime-manifest", type=Path, help="Pinned, independently reviewed startup-audit bytecode only")
    parser.add_argument("--texture-profile", choices=TEXTURE_PROFILES,
                        help="Opt-in v126 texture-only composition onto the pinned v125 base")
    parser.add_argument("--texture-original", type=Path,
                        help="Frozen lossless v114 pack, required with --texture-profile")
    args = parser.parse_args()
    if args.texture_profile or args.texture_original:
        if not args.texture_profile or not args.texture_original:
            parser.error("--texture-profile and --texture-original must be supplied together")
        if any((args.geometry_manifest, args.project_binary, args.texture_seed, args.runtime_manifest)):
            parser.error("Texture-only composition cannot mix geometry/settings/seed/runtime replacements")
        build_texture_candidate(args.source, args.destination, args.texture_original, args.texture_profile)
    else:
        build(args.source, args.destination, args.geometry_manifest, args.project_binary, args.texture_seed, args.runtime_manifest)
