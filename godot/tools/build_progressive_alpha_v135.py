"""CPU-only exact alpha overlay for v134. No visible texture or pack edits.

Decode the full physical top mip once, retain its 8-bit alpha, and encode LA8 PNG
with L=255. These files are CPU Image inputs, never material/atlas textures.
"""
import argparse
import io
import json
from pathlib import Path
import re
import struct

from PIL import Image

import build_progressive_textures_v135 as textures


ROOT = textures.ROOT
SCOPE = textures.SCOPE
SOURCE = textures.SOURCE
SOURCE_SHA = textures.SOURCE_SHA
CANDIDATE = SCOPE / "candidate-01"
INPUT_MANIFEST_SHA = "d459c5a8f37c97d35d5d3f0dc8ff9b6218a11a0bdd840694f88100d43758b478"
TARGETS = {
    "castle-town-v62": ["city-foundation", "settlement-window-alpha-audit"],
    "windmill-village-v50": ["village-foundation", "rotor-radius", "settlement-window-alpha-audit"],
    "meadow-herbs-v73": ["herb-support-conform"],
    "meadow-scrub-v74": ["original-image-size-uv-normalization", "scrub-support-conform"],
    "mountain-groves-v100": ["grove-support-conform"],
    "mountain-massif-v106": ["mountain-alpha-relief"],
    "wooded-hills-v107": ["mountain-alpha-relief"],
    "road-lanterns-v52": ["explicit-debug-lantern-alpha-audit"],
}
SAMPLER_FILES = ["meadow_city_builder.gd", "meadow_village_builder.gd", "meadow_herb_modules.gd",
                 "meadow_scrub_modules.gd", "meadow_mountain_groves.gd", "meadow_mountain_relief.gd",
                 "meadow_road_lights.gd", "meadow_settlement_lights.gd"]
require, sha, gz_size = textures.require, textures.sha, textures.gz_size


def top_alpha(ctex):
    parsed = textures.parse_ctex(ctex)
    require(parsed["format"] == 5, "Expected original RGBA texture")
    payload = parsed["levels"][0]["payload"]
    with Image.open(io.BytesIO(payload)) as image:
        rgba = image.convert("RGBA")
        require(rgba.size == parsed["physical"], "Physical source size mismatch")
        alpha = rgba.getchannel("A").tobytes()
    return parsed, alpha, sha(payload)


def encode_alpha(alpha, width, height):
    require(type(width) is int and type(height) is int and width > 0 and height > 0,
            "Positive integer dimensions required")
    require(len(alpha) == width * height, "Alpha byte length mismatch")
    channel = Image.frombytes("L", (width, height), alpha)
    image = Image.merge("LA", (Image.new("L", (width, height), 255), channel))
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=9, optimize=False)
    return stream.getvalue()


def verify_alpha(png, alpha, width, height):
    require(png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR", "Expected PNG IHDR")
    require(struct.unpack_from(">II", png, 16) == (width, height), "PNG dimensions changed")
    require(png[24:29] == bytes((8, 4, 0, 0, 0)), "Expected non-interlaced LA8 PNG")
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        require(image.mode == "LA" and image.size == (width, height), "Expected decoded LA8")
        luminance = image.getchannel("L")
        decoded_alpha = image.getchannel("A").tobytes()
        require(luminance.getextrema() == (255, 255), "CPU luminance must be constant 255")
        require(decoded_alpha == alpha and len(alpha) == width * height, "Full alpha bytes changed")
    return {"mode": "LA8", "luminanceConstant": 255, "alphaSha256": sha(alpha),
            "allAlphaPixelsExact": True, "fullPhysicalDimensionsExact": True,
            "rawAlphaBytes": len(alpha), "rawLA8Bytes": len(alpha) * 2}


def sampler_evidence():
    evidence = []
    for filename in SAMPLER_FILES:
        path = ROOT / "godot/scripts" / filename
        raw = path.read_bytes()
        accesses = []
        for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
            if ".get_pixel(" in line:
                require(re.search(r"\.get_pixel\(.+\)\.a\b", line) is not None,
                        f"Unexpected RGB/image pixel consumer needs review: {filename}:{number}")
            if any(token in line for token in (".get_image(", ".get_pixel(", "source.get_size(")):
                accesses.append({"line": number, "text": line.strip()})
        evidence.append({"path": path.relative_to(ROOT).as_posix(), "localSourceSha256": sha(raw),
                         "imageAccesses": accesses, "newCompiledEquivalenceProof": False})
    return evidence


def snapshot_candidates():
    # Small disjoint inventory only, not a repository-wide scan.
    return {path.relative_to(CANDIDATE).as_posix(): sha(path.read_bytes())
            for path in sorted(CANDIDATE.rglob("*")) if path.is_file()}


def generate(output):
    output = output.resolve()
    require(output.is_relative_to(SCOPE.resolve()) and output != SCOPE.resolve() and not output.exists(),
            "Alpha output must be a new dedicated artifact directory")
    before = snapshot_candidates()
    manifest_path = CANDIDATE / "bootstrap256/manifest.json"
    require(sha(manifest_path.read_bytes()) == INPUT_MANIFEST_SHA, "Fixed bootstrap256 manifest changed")
    bootstrap = json.loads(manifest_path.read_text(encoding="utf-8"))
    inventory = json.loads((CANDIDATE / "inventory.json").read_text(encoding="utf-8"))
    source = textures.pinned_entries(SOURCE, SOURCE_SHA)
    mappings = textures.import_map(source)
    by_name = {Path(value["source"]).stem: (entry, value) for entry, value in mappings.items()}
    require(set(TARGETS).issubset(by_name) and "castle-dragon-turns-v57" not in TARGETS,
            "Exact alpha target allowlist required")
    code = sampler_evidence()
    entries, rows, runtime = [], [], {"textures": {}}
    for name, uses in TARGETS.items():
        entry, mapping = by_name[name]
        original = source[entry]
        parsed, alpha, mip_sha = top_alpha(original)
        width, height = parsed["physical"]
        require(parsed["logical"] == (width, height), "These CPU images require the original full physical top mip")
        png = encode_alpha(alpha, width, height)
        proof = verify_alpha(png, alpha, width, height)
        path = output / "png" / (name + ".png")
        textures.write_new(path, png)
        verify_alpha(path.read_bytes(), alpha, width, height)
        packed_entry = "progressive/alpha/" + path.name
        entries.append({"entry": packed_entry, "path": path.as_posix(), "sha256": sha(png)})
        runtime["textures"][mapping["source"]] = {"resource": "res://" + packed_entry,
            "width": width, "height": height, "alphaSha256": sha(alpha)}
        rows.append({"name": name, "sourceTexture": mapping["source"], "sourceCtexEntry": entry,
            "sourceCtexSha256": sha(original), "sourceTopEncodedMipSha256": mip_sha,
            "sourceMip": 0, "width": width, "height": height,
            "entry": packed_entry, "path": path.as_posix(), "sha256": sha(png),
            "pngBytes": len(png), "gzip6Bytes": gz_size(png), "uses": uses, "proof": proof,
            "cpuOnly": True, "mayBindToVisibleMaterial": False})
    runtime_path = output / "alpha-manifest.json"
    textures.write_json(runtime_path, runtime)
    runtime_bytes = runtime_path.read_bytes()
    entries.append({"entry": "progressive/alpha-manifest.json", "path": runtime_path.as_posix(), "sha256": sha(runtime_bytes)})
    dragon = next(row for row in inventory["textures"] if row["name"] == "castle-dragon-turns-v57")
    png_total = sum(row["pngBytes"] for row in rows)
    gzip_total = sum(row["gzip6Bytes"] for row in rows)
    texture_bytes = bootstrap["budget"]["coreTextureBytesIncludingExistingWater"] + dragon["sourceBytes"] - dragon["profiles"]["bootstrap256"]["bytes"]
    texture_gzip = bootstrap["budget"]["coreTextureGzip6BytesIncludingExistingWater"] + dragon["sourceGzip6Bytes"] - dragon["profiles"]["bootstrap256"]["gzip6Bytes"]
    combined = texture_bytes + png_total + len(runtime_bytes)
    combined_gzip = texture_gzip + gzip_total + gz_size(runtime_bytes)
    budget = {"units": "bytes; gzip6 is sum of separately compressed resources, not final PCK/engine/network performance",
        "fullAlphaRawBytes": sum(row["proof"]["rawAlphaBytes"] for row in rows),
        "rawLA8Bytes": sum(row["proof"]["rawLA8Bytes"] for row in rows),
        "alphaPngBytes": png_total, "alphaPngGzip6Bytes": gzip_total,
        "runtimeManifestBytes": len(runtime_bytes), "runtimeManifestGzip6Bytes": gz_size(runtime_bytes),
        "bootstrap256CtexBytesWithOriginalDragonAndExistingWater": texture_bytes,
        "bootstrap256CtexGzip6BytesWithOriginalDragonAndExistingWater": texture_gzip,
        "combinedCtexAlphaAndRuntimeManifestBytes": combined,
        "combinedCtexAlphaAndRuntimeManifestGzip6Bytes": combined_gzip,
        "rawSavingsVsObservedCoreCtex": inventory["totals"]["observedCoreTextureBytes"] - combined,
        "gzip6SavingsVsObservedCoreCtex": inventory["totals"]["observedCoreTextureGzip6Bytes"] - combined_gzip,
        "additionalRawSavingsVsRetainAllCpuSamplers": bootstrap["recommendedSamplerPolicy"]["coreTextureBytesIncludingExistingWater"] - combined}
    require(sha(SOURCE.read_bytes()) == SOURCE_SHA and snapshot_candidates() == before,
            "Source PCK or existing texture candidates changed")
    overlay = {"schema": "meadow-progressive-cpu-alpha-overlay-v135-1", "status": "PASS_OFFLINE_ALPHA_BYTES_RUNTIME_INTEGRATION_PENDING",
        "sourcePack": SOURCE.as_posix(), "sourcePackSha256": SOURCE_SHA,
        "bootstrap256Manifest": manifest_path.as_posix(), "bootstrap256ManifestSha256": INPUT_MANIFEST_SHA,
        "entries": entries, "textures": rows, "budget": budget, "samplerSourceEvidence": code,
        "existingTextureCandidatesUnchanged": True, "existingCandidateFileCount": len(before),
        "existingCandidateFileHashes": before, "sourcePackUnchanged": True,
        "integration": {"runtimeResource": "res://progressive/alpha-manifest.json",
            "runtimeSchema": "{textures:{sourcePath:{resource,width,height,alphaSha256}}}",
            "consumer": "CPU Image only; public support.image must return exact dimensions/alpha from these PNGs before any original image-dependent construction or audit.",
            "bootstrapProfile": "bootstrap256", "applyExistingTextureCandidatesExcept": ["castle-dragon-turns-v57"],
            "visibleTextureReplacementCount": 30, "inPlaceFullUpgrade": True,
            "dragon": "Keep original 550352-byte CTEX and its physical textureSize contract; no dragon/shader changes.",
            "water": "Keep existing drop2 core and original final water chunk; no water entry emitted.",
            "finalParityLimit": "Full physical alpha and logical texture sizes are exact inputs; main/A must verify helper consumers and final runtime geometry. This offline artifact does not claim a newly run full-scene parity audit."},
        "noPackWrite": True, "noVisibleTextureEncoding": True, "noRuntimeScriptEditOrCompilation": True}
    textures.write_json(output / "manifest.json", overlay)
    summary = {"overlay": (output / "manifest.json").as_posix(),
               "overlaySha256": sha((output / "manifest.json").read_bytes()), "pngCount": len(rows),
               "packedEntryCount": len(entries), "budget": budget,
               "existingTextureCandidatesUnchanged": True, "sourcePackUnchanged": True}
    textures.write_json(output / "proof.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SCOPE / "alpha-data-01")
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False, indent=2))
