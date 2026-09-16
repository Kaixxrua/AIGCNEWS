"""CPU-only four-value masks preserving the three pinned Godot alpha predicates.

Not exact alpha or visible art. No native/engine/compile/pack operation. The
existing exact-alpha overlay and every bootstrap CTEX candidate remain frozen.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct

import build_progressive_alpha_v135 as exact


ROOT, SCOPE = exact.ROOT, exact.SCOPE
require, sha, gz_size = exact.require, exact.sha, exact.gz_size
EXACT_DIRECTORY = SCOPE / "alpha-data-01"
EXACT_MANIFEST_SHA = "15ca80af55da6290c082c146ad6ae214ff6a3114237caa88cfeedf4f806da33e"
ENGINE_ROOT = ROOT / ".tools/godot-web-v126/src"
ENGINE_PINS = {
    "core/io/image.cpp": "e38d8ac2275202a8de9978fba3059ca9dc69b127c2536adab842fdc341095611",
    "core/math/color.h": "a77f15bba7efaea92171388c041079c5711c914c1a71121d8a9497278410edac",
    "core/variant/variant_setget.h": "c99e4cd6b952c09d1adb0aa97acbfce10ff5b6496b382261e6eca305a9e31898",
    "core/variant/variant_setget.cpp": "e3f73e1df096bedd4856e29227b302f879d0520c66718467338556b589f685c9",
    "core/variant/variant.h": "3d7d7c8bdc02d4ac73d06b16f487a9ba0f9a188c854ab0befc57b98f807523b2",
    "core/variant/variant.cpp": "4af0a620aa59d2376d1b35ab201f26edd352f056c908b970890ad9a3449bb5c0",
    "core/variant/variant_op.h": "6a7a37456297b8a52f7b6c3f13a9379548a4c73e3177df80d0664b3b498e1a94",
    "core/variant/variant_op.cpp": "0ddccc0fc3a98daa2fe0bbcaecbdb9d4e609e864637eb26ba4adb549355d3e6b",
    "modules/gdscript/gdscript_tokenizer.cpp": "6d956bc85ad7455110977974ce62f24ba5a2e864968296c7d65cde67bfa634a8",
}
THRESHOLDS = (0.60, 0.9, 0.95)
REPRESENTATIVES = (0, 204, 236, 255)
EXPECTED_PIXEL_LINES = {
    "meadow_city_builder.gd": ['if source.get_pixel(pixel_x, y).a > 0.60:'],
    "meadow_village_builder.gd": ['if source.get_pixel(x, y).a > 0.60:', 'if source.get_pixel(pixel_x, y).a > 0.60:'],
    "meadow_herb_modules.gd": ['solid += int(source.get_pixel(clampi(pixel_x + dx, 0, source.get_width() - 1), y).a > 0.60)'],
    "meadow_scrub_modules.gd": [],
    "meadow_mountain_groves.gd": [],
    "meadow_mountain_relief.gd": ['if source.get_pixel(pixel_x, y).a > 0.60:'],
    "meadow_road_lights.gd": ['assert(image.get_pixel(int(GLASS[i].x), int(GLASS[i].y)).a > 0.95, "Light must align to opaque lantern glass")'],
    "meadow_settlement_lights.gd": ['assert(source.get_pixel(int(opening.x), int(opening.y)).a > 0.9, "Window centre must be on opaque artwork")'],
}


def godot_alpha(byte):
    require(type(byte) is int and 0 <= byte <= 255, "Expected A8 byte")
    # image.cpp: double division assigned to float, Color.a float promoted to
    # Variant double. Threshold literals are tokenizer double, not float32.
    return struct.unpack("<f", struct.pack("<f", byte / 255.0))[0]


def predicate_bits(byte):
    value = godot_alpha(byte)
    return sum((1 << index) for index, threshold in enumerate(THRESHOLDS) if value > threshold)


def build_lut():
    representatives = {predicate_bits(value): value for value in REPRESENTATIVES}
    require(set(representatives) == {0, 1, 3, 7}, "Representatives must span all predicate classes")
    table, rows = bytearray(), []
    for value in range(256):
        bits = predicate_bits(value)
        mapped = representatives[bits]
        require(predicate_bits(mapped) == bits, "Predicate mapping changed behavior")
        table.append(mapped)
        rows.append({"originalByte": value, "originalFloat32AsDouble": godot_alpha(value),
                     "mappedByte": mapped, "mappedFloat32AsDouble": godot_alpha(mapped),
                     "originalPredicateBits": bits, "mappedPredicateBits": predicate_bits(mapped)})
    require(table[152] == 0 and table[153] == 204 and table[229] == 204
            and table[230] == 236 and table[242] == 236 and table[243] == 255,
            "Float32 boundary contract changed")
    return bytes(table), rows


def verify_semantics(original, mapped):
    require(len(original) == len(mapped), "Pixel count changed")
    lut, _ = build_lut()
    require(mapped == original.translate(lut), "Mask is not the exact approved four-value mapping")
    bits = bytes(predicate_bits(value) for value in range(256))
    before, after = original.translate(bits), mapped.translate(bits)
    require(before == after, "At least one original pixel predicate changed")
    histogram = Counter(original)
    return {"semanticsOnly": True, "originalAlphaSha256": sha(original),
            "mappedAlphaSha256": sha(mapped), "predicateBitsSha256": sha(before),
            "pixelsChecked": len(original), "predicatesPerPixel": 3,
            "allPixelPredicateBitsExact": True, "predicateMismatchCount": 0,
            "alphaBytesExact": mapped == original,
            "changedAlphaPixelCount": sum(count for value, count in histogram.items() if value != lut[value]),
            "predicateClassCounts": {str(value): before.count(value) for value in (0, 1, 3, 7)}}


def validate_consumer_text(filename, text, expected_sha=None):
    require(filename in EXPECTED_PIXEL_LINES, "Unknown CPU Image consumer")
    raw = text if isinstance(text, bytes) else text.encode("utf-8")
    if expected_sha is not None:
        require(sha(raw) == expected_sha, f"Pinned consumer source changed: {filename}")
    # Exact source pins reject unreviewed get_data/RGB/alias accesses as well;
    # exact lines also make threshold/operator/count drift fail explicitly.
    lines = [line.strip() for line in raw.decode("utf-8-sig").splitlines()
             if re.search(r"\bget_pixel(?:v)?\s*\(", line)]
    require(lines == EXPECTED_PIXEL_LINES[filename], f"Unreviewed get_pixel predicate set: {filename}")
    return lines


def validate_consumers(exact_manifest):
    source_pins = {Path(row["path"]).name: row for row in exact_manifest["samplerSourceEvidence"]}
    require(set(source_pins) == set(EXPECTED_PIXEL_LINES), "CPU consumer file set changed")
    result = []
    for filename, record in source_pins.items():
        path = ROOT / record["path"]
        raw = path.read_bytes()
        lines = validate_consumer_text(filename, raw, record["localSourceSha256"])
        result.append({"path": record["path"], "sha256": sha(raw), "getPixelPredicateLines": lines})
    require(sum(len(row["getPixelPredicateLines"]) for row in result) == 7, "Expected exactly seven current pixel comparisons")
    return result


def validate_engine(root=ENGINE_ROOT, pins=None):
    result = []
    for relative, expected in (ENGINE_PINS if pins is None else pins).items():
        path = root / relative
        require(sha(path.read_bytes()) == expected, f"Pinned float conversion source changed: {relative}")
        result.append({"path": path.as_posix(), "sha256": expected})
    return {"sources": result,
            "expression": "double(float32(double(A8) / 255.0)) > double(threshold)",
            "evidence": ["core/io/image.cpp:3441 LA8 and :3461 RGBA8 assign alpha division to float",
                         "core/io/image.cpp:3687 get_pixel delegates to _get_color_at_ofs",
                         "core/math/color.h:45 Color.a is float",
                         "core/variant/variant_setget.h:345 SETGET_NUMBER_STRUCT(Color, double, a)",
                         "core/variant/variant.h:253 Variant stores double",
                         "core/variant/variant_op.cpp:766 double/double greater registration",
                         "modules/gdscript/gdscript_tokenizer.cpp:841 decimal literal is double"],
            "engineExecutedOrCompiled": False}


def snapshot_directory(directory):
    return {p.relative_to(directory).as_posix(): sha(p.read_bytes()) for p in sorted(directory.rglob("*")) if p.is_file()}


def generate(output):
    output = output.resolve()
    require(output.is_relative_to(SCOPE.resolve()) and output != SCOPE.resolve() and not output.exists(),
            "Predicate output must be a new dedicated artifact directory")
    existing_candidates = exact.snapshot_candidates()
    existing_exact = snapshot_directory(EXACT_DIRECTORY)
    exact_path = EXACT_DIRECTORY / "manifest.json"
    require(sha(exact_path.read_bytes()) == EXACT_MANIFEST_SHA, "Exact-alpha overlay pin changed")
    original_overlay = json.loads(exact_path.read_text(encoding="utf-8"))
    engine = validate_engine()
    consumers = validate_consumers(original_overlay)
    source = exact.textures.pinned_entries(exact.SOURCE, exact.SOURCE_SHA)
    lut, enumeration = build_lut()
    rows, entries = [], []
    runtime = {"textures": {}, "semanticsOnly": True}
    for original_row in original_overlay["textures"]:
        ctex = source[original_row["sourceCtexEntry"]]
        parsed, alpha, encoded_sha = exact.top_alpha(ctex)
        require(sha(alpha) == original_row["proof"]["alphaSha256"] and encoded_sha == original_row["sourceTopEncodedMipSha256"],
                "Original full alpha source changed")
        width, height = parsed["physical"]
        original_png = Path(original_row["path"]).read_bytes()
        require(sha(original_png) == original_row["sha256"], "Exact alpha PNG changed")
        exact.verify_alpha(original_png, alpha, width, height)
        mapped = alpha.translate(lut)
        semantics = verify_semantics(alpha, mapped)
        png = exact.encode_alpha(mapped, width, height)
        exact.verify_alpha(png, mapped, width, height)
        path = output / "png" / (original_row["name"] + ".png")
        exact.textures.write_new(path, png)
        exact.verify_alpha(path.read_bytes(), mapped, width, height)
        # Same packed entries intentionally form an alternative --alpha overlay.
        packed_entry = "progressive/alpha/" + path.name
        entries.append({"entry": packed_entry, "path": path.as_posix(), "sha256": sha(png)})
        runtime["textures"][original_row["sourceTexture"]] = {
            "resource": "res://" + packed_entry, "width": width, "height": height,
            "alphaSha256": sha(mapped)}
        rows.append({"name": original_row["name"], "sourceTexture": original_row["sourceTexture"],
            "sourceCtexEntry": original_row["sourceCtexEntry"], "sourceCtexSha256": sha(ctex),
            "sourceTopEncodedMipSha256": encoded_sha, "width": width, "height": height,
            "entry": packed_entry, "path": path.as_posix(), "sha256": sha(png),
            "pngBytes": len(png), "gzip6Bytes": gz_size(png), "semanticsOnly": True,
            "cpuOnly": True, "mayBindToVisibleMaterial": False,
            "nonAlphaPixelChannelsExactToExactAlphaOverlay": True, "luminanceConstant": 255,
            "dimensionsExact": True, "uses": original_row["uses"], "proof": semantics})
    require({row["name"] for row in rows} == set(exact.TARGETS), "Eight alpha target set changed")
    runtime_path = output / "alpha-manifest.json"
    exact.textures.write_json(runtime_path, runtime)
    runtime_bytes = runtime_path.read_bytes()
    entries.append({"entry": "progressive/alpha-manifest.json", "path": runtime_path.as_posix(), "sha256": sha(runtime_bytes)})
    png_bytes = sum(row["pngBytes"] for row in rows)
    png_gzip = sum(row["gzip6Bytes"] for row in rows)
    base_budget = original_overlay["budget"]
    combined = base_budget["bootstrap256CtexBytesWithOriginalDragonAndExistingWater"] + png_bytes + len(runtime_bytes)
    combined_gzip = base_budget["bootstrap256CtexGzip6BytesWithOriginalDragonAndExistingWater"] + png_gzip + gz_size(runtime_bytes)
    budget = {"units": "bytes; gzip6 sums separate resource files, not staged PCK/network/engine results",
        "predicatePngBytes": png_bytes, "predicatePngGzip6Bytes": png_gzip,
        "runtimeManifestBytes": len(runtime_bytes), "runtimeManifestGzip6Bytes": gz_size(runtime_bytes),
        "bootstrap256CtexBytesWithOriginalDragonAndExistingWater": base_budget["bootstrap256CtexBytesWithOriginalDragonAndExistingWater"],
        "combinedCtexMasksAndRuntimeManifestBytes": combined,
        "combinedCtexMasksAndRuntimeManifestGzip6Bytes": combined_gzip,
        "rawSavingsVsObservedCoreCtex": 5295824 - combined,
        "gzip6SavingsVsObservedCoreCtex": 5280536 - combined_gzip,
        "additionalRawSavingsVsExactAlphaOverlay": base_budget["combinedCtexAlphaAndRuntimeManifestBytes"] - combined,
        "additionalGzip6SavingsVsExactAlphaOverlay": base_budget["combinedCtexAlphaAndRuntimeManifestGzip6Bytes"] - combined_gzip}
    require(exact.snapshot_candidates() == existing_candidates and snapshot_directory(EXACT_DIRECTORY) == existing_exact
            and sha(exact.SOURCE.read_bytes()) == exact.SOURCE_SHA, "Frozen input changed during generation")
    validate_engine()
    require(validate_consumers(original_overlay) == consumers, "Consumers changed during generation")
    enum_path = output / "enumeration.json"
    exact.textures.write_json(enum_path, {"thresholds": list(THRESHOLDS), "operator": ">", "representatives": list(REPRESENTATIVES),
        "alpha153Float32AsDouble": godot_alpha(153), "alpha153PassesPoint6": predicate_bits(153) == 1,
        "lutSha256": sha(lut), "all256InputsExact": True, "rows": enumeration})
    overlay = {"schema": "meadow-progressive-cpu-alpha-overlay-v135-1", "semanticsOnly": True,
        "status": "PASS_OFFLINE_PREDICATE_BITS_RUNTIME_GEOMETRY_QA_PENDING",
        "entries": entries, "textures": rows, "budget": budget,
        "sourcePackSha256": exact.SOURCE_SHA, "exactAlphaOverlay": exact_path.as_posix(),
        "exactAlphaOverlaySha256": EXACT_MANIFEST_SHA, "enginePrecisionContract": engine,
        "pinnedCurrentConsumers": consumers, "allowedPredicates": [">0.60", ">0.9", ">0.95"],
        "enumeration": {"path": enum_path.as_posix(), "sha256": sha(enum_path.read_bytes()), "lutSha256": sha(lut)},
        "totalPixelsChecked": sum(row["proof"]["pixelsChecked"] for row in rows),
        "totalPredicateChecks": sum(row["proof"]["pixelsChecked"] * 3 for row in rows),
        "predicateMismatchCount": 0, "nonAlphaPixelChannelsExactToExactAlphaOverlay": True,
        "existingExactAlphaDataUnchanged": True, "existingExactAlphaFileHashes": existing_exact,
        "existingTextureCandidatesUnchanged": True, "existingTextureCandidateFileHashes": existing_candidates,
        "noVisibleTextureOrScriptOrPackEdits": True,
        "integration": {"runtimeResource": "res://progressive/alpha-manifest.json", "alternativeToExactAlphaOverlay": True,
            "cpuOnly": True, "mayBindToVisibleMaterial": False, "bootstrapProfile": "bootstrap256",
            "visibleTextureReplacementCount": 30, "dragon": "Keep original CTEX and shader", "water": "Keep existing drop2 and final water chunk",
            "alphaSha256Meaning": "Hash of mapped A8 row-major bytes. Original alpha hash is separately stored in each proof; these are not exact-alpha images.",
            "requirements": "Use only with pinned current get_pixel(...).a >0.60/>0.9/>0.95 consumers. Any threshold/operator/RGB/continuous-alpha consumer change invalidates this semantic overlay; fail closed or use unchanged exact-alpha-data-01.",
            "finalGeometryLimit": "All current predicate inputs and dimensions are equivalent offline; A/main must independently verify actual integrated full geometry. No native/engine build or run was performed."}}
    exact.textures.write_json(output / "manifest.json", overlay)
    summary = {"overlay": (output / "manifest.json").as_posix(), "overlaySha256": sha((output / "manifest.json").read_bytes()),
        "semanticsOnly": True, "pngCount": len(rows), "packedEntries": len(entries), "budget": budget,
        "all256InputsExact": True, "totalPixelsChecked": overlay["totalPixelsChecked"],
        "totalPredicateChecks": overlay["totalPredicateChecks"], "predicateMismatchCount": 0,
        "existingExactAlphaDataAndTextureCandidatesUnchanged": True}
    exact.textures.write_json(output / "proof.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SCOPE / "alpha-predicates-01")
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False, indent=2))
