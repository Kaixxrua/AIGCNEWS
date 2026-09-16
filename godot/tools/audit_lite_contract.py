"""Read-only original/lite PCK audit. JSON stdout; no extraction, engine or writes.

--original ORIGINAL.pck --lite LITE.pck --manifest CONTRACT.json
--manifest-example prints schema v1. Run with -B to also disable startup pycache.
Exit 0 = structural pass, 1 = broken contract, 2 = invalid/unsupported input.
A structural pass NEVER certifies geometry, compiled scripts, visuals or speed.
"""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
import re
import struct
import sys

sys.dont_write_bytecode = True

import numpy as np
from PIL import Image, ImageFilter

from audit_loading_contract import (CRITICAL, MAX_BYTES, Package, check_package,
                                    parse_pck, safe_name, sha)


MAX_PIXELS = 16 * 1024 * 1024
WATER = "assets/materials/river-ripples-v37.png"
AO_PATH = "assets/baked/v110/rock-occlusion.bin"
AO_ORIGINAL_SHA256 = "f3f86ff17ed6da347d7fa155562b3ca4048bac04b52eebf560aa3d8113371577"
AO_REBIND_KIND = "signature_only_rebind_exact_original_visibility_and_sampling_geometry"
GEOMETRY_SET = {f"assets/baked/v77/{n}.scn" for n in
                ("terrain", "detail", "brush", "foothill", "riverbank")} | {
                    "assets/baked/v113/far-sward.scn", AO_PATH}
KINDS = {"texture", "geometry", "runtime", "project", "lossless-rscc"}
STARTUP_PATH = "scripts/meadow_scene.gdc"
STARTUP_ROOT = Path(__file__).resolve().parents[2] / "artifacts/loading-v115/startup"
STARTUP_PACK_SHA256 = "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d"
STARTUP_GDC_SHA256 = "2a6ec2c6ffbf82013ba2e101c15c063affca22548b6f12e0c7e35280d0ee7be8"
STARTUP_SOURCE_SHA256 = "3477a2bd4bd67c8de488b977c81ffa76726844e004886b86b77e6f3d2b519d12"
# Independently reviewed C/main gate + telemetry, not arbitrary helper bodies.
# A different source revision needs a new review, even with fresh proof hashes.
STARTUP_PATCHED_SHA256 = "c8b80de0348f094fa43135cecbd57f971fd75afe022dc19727b95e5ff1edfd2d"
STARTUP_PREVIOUS_PATCHED_SHA256 = "62ce48e83dc4e409fd202759772bf57359b1ffa2dd8922a5ca389c11975afd0c"
STARTUP_HELPERS = ["_startup_audit_enabled", "_report_startup_audit"]
# Source-reviewed usage contracts, not a claim that every packed PNG is used.
ANIMALS = {f"assets/creatures/{name}-v54.png" for name in
           ("leaf-hare", "bud-deer", "gold-fox", "moon-stag")}
DRAGON = "assets/creatures/castle-dragon-turns-v57.png"
DRAGON_RECTS = [
    [23,22,207,227], [261,24,183,223], [475,26,196,224], [683,25,186,225],
    [913,18,173,239], [1129,24,185,226], [1326,26,196,224], [1554,24,184,223],
    [9,311,229,133], [241,311,218,138], [472,310,199,139], [677,306,207,147],
    [888,317,222,142], [1114,305,207,148], [1326,310,199,139], [1538,311,229,138],
    [23,492,208,163], [256,506,189,149], [474,506,179,149], [667,498,214,157],
    [899,492,201,162], [1118,498,213,157], [1345,506,178,149], [1552,506,193,149],
    [20,673,212,183], [247,679,199,173], [475,679,195,178], [683,679,185,177],
    [908,679,183,192], [1130,679,185,178], [1328,679,194,178], [1551,675,203,178],
]
RECT_COUNTS = {
    "reference-trees-v40.png": 4, "meadow-patches-v37.png": 8,
    "living-meadow-v38.png": 8, "woodland-groups-v37.png": 8,
    "woodland-belts-v39.png": 2, "distant-groves-v57.png": 6,
    "valley-colonies-v41.png": 8, "frame-growth-v43.png": 4,
    "meadow-colonies-v44.png": 4, "meadow-herbs-v73.png": 2,
    "meadow-scrub-v74.png": 6, "mountain-groves-v100.png": 6,
    "windmill-village-v50.png": 3, "road-lanterns-v52.png": 3,
}
CPU_CROPS = {
    "windmill-village-v50.png": ("meadow_village_builder",),
    "meadow-herbs-v73.png": ("meadow_herb_modules",),
    "meadow-scrub-v74.png": ("meadow_scrub_modules", "meadow_herb_modules"),
    "mountain-groves-v100.png": ("meadow_mountain_groves", "meadow_herb_modules"),
}
PIXEL_COORDINATES = {
    "castle-dragon-turns-v57.png": ("meadow_dragon_art", "meadow_wildlife"),
    "castle-town-v62.png": ("meadow_architecture_profiles", "meadow_settlement_lights"),
    "windmill-village-v50.png": ("meadow_village_builder", "meadow_architecture_profiles",
                                 "meadow_settlement_lights"),
    "road-lanterns-v52.png": ("meadow_road_lights", "meadow_settlement_lights"),
    "meadow-herbs-v73.png": ("meadow_herb_modules",),
    "mountain-groves-v100.png": ("meadow_mountain_groves",),
}
# Main's coordinated v115 plan keeps these GPU/CPU pixel consumers at their
# original physical resolution; alpha remains exact even when RGB is lossy.
KEEP_PHYSICAL = {
    "castle-dragon-turns-v57.png", "castle-town-v62.png", "windmill-village-v50.png",
    "mountain-massif-v106.png", "wooded-hills-v107.png", "mountain-groves-v100.png",
    "meadow-herbs-v73.png", "meadow-scrub-v74.png", "road-lanterns-v52.png",
    "foreground-lantern-v1.png",
}
# Measured source rectangles, in unchanged outer logical pixels. These are
# copied from the reviewed runtime, not inferred by splitting an image evenly.
SOURCE_RECTS = {
    "reference-trees-v40.png": [[32,20,728,578], [801,90,428,507], [40,614,587,600], [651,759,578,445]],
    "meadow-patches-v37.png": [[17,53,601,272], [633,50,605,274], [22,357,595,298], [637,338,600,310],
                                [20,662,604,300], [646,709,590,246], [26,975,590,245], [641,987,598,237]],
    "woodland-groups-v37.png": [[92,23,487,314], [725,15,437,326], [70,349,542,287], [691,365,501,274],
                                [75,644,507,280], [663,656,545,280], [69,924,494,311], [671,1015,523,218]],
    "living-meadow-v38.png": [[24,57,604,277], [651,44,583,291], [23,366,592,252], [644,354,586,275],
                              [18,625,606,294], [651,659,584,244], [21,925,603,275], [643,934,590,282]],
    "woodland-belts-v39.png": [[24,941,572,279], [635,961,590,261]],
    "distant-groves-v57.png": [[52,y,1434,h] for y,h in [(0,187), (187,179), (366,169), (535,145), (680,177), (857,167)]],
    "valley-colonies-v41.png": [[45,74,572,247], [670,38,548,297], [36,367,571,247], [668,366,548,256],
                                [39,682,576,248], [677,625,517,339], [47,957,556,262], [668,1018,536,202]],
    "frame-growth-v43.png": [[10,25,658,722], [700,162,537,568], [42,810,575,408], [660,890,574,326]],
    "meadow-colonies-v44.png": [[13,205,587,318], [658,177,588,358], [13,758,603,346], [648,795,593,323]],
    "meadow-herbs-v73.png": [[24,260,905,344], [998,208,882,414]],
    "meadow-scrub-v74.png": [[19,41,484,389], [536,90,613,337], [1161,126,599,299],
                             [29,485,508,363], [595,459,510,394], [1165,564,591,285]],
    "mountain-groves-v100.png": [[38,54,565,362], [676,87,550,334], [32,460,572,349],
                                 [668,459,558,356], [31,848,575,355], [681,851,544,355]],
    "windmill-village-v50.png": [[16,48,1743,365], [320,450,393,392], [1050,451,378,383]],
    "road-lanterns-v52.png": [[65,102,349,1022], [509,440,278,692], [908,123,287,994]],
    "castle-dragon-turns-v57.png": DRAGON_RECTS,
}
LITE_SETTINGS = {
    "rendering/scaling_3d/scale": 0.5,
    "rendering/scaling_3d/mode": 0,
    "rendering/lights_and_shadows/directional_shadow/size": 2048,
    "rendering/anti_aliasing/quality/msaa_3d": 1,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def dimensions(value, label):
    require(isinstance(value, list) and len(value) == 2 and
            all(type(n) is int and 0 < n <= 65535 for n in value),
            f"{label}: expected two positive integer dimensions")
    return tuple(value)


def digest_value(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            f"{label}: expected lowercase SHA256")
    return value


def json_bytes(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    require(len(data) <= 4 * 1024 * 1024, "Manifest exceeds 4 MiB")
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=lambda v: require(False, f"Nonfinite JSON number: {v}"))


def load_json(path):
    require(path.stat().st_size <= 4 * 1024 * 1024, "Manifest exceeds 4 MiB")
    return json_bytes(path.read_bytes())


def read_startup_file(value):
    """Read bounded local attestation evidence only; never execute its contents."""
    require(isinstance(value, (str, Path)), "Startup proof needs an absolute local path")
    path = Path(value)
    require(path.is_absolute(), "Startup proof needs an absolute local path")
    # Reject foreign/UNC paths before any filesystem lookup, not after resolve.
    require(path.is_relative_to(STARTUP_ROOT), "Startup proof evidence must stay inside startup artifacts")
    path = path.resolve(strict=True)
    require(path.is_relative_to(STARTUP_ROOT.resolve()) and path.is_file(),
            "Startup proof evidence must stay inside startup artifacts")
    require(path.stat().st_size <= 4 * 1024 * 1024, "Startup proof evidence exceeds 4 MiB")
    data = path.read_bytes()
    require(len(data) <= 4 * 1024 * 1024, "Startup proof evidence grew beyond 4 MiB")
    return data


def startup_functions(source):
    matches = list(re.finditer(rb"^(?:static )?func ([A-Za-z_][A-Za-z_0-9]*)\(", source, re.M))
    result = {}
    for index, match in enumerate(matches):
        name = match[1].decode()
        require(name not in result, "Duplicate startup source method")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        result[name] = source[match.start():end]
    return result


def verify_startup_source(before, after):
    require(sha(before) == STARTUP_SOURCE_SHA256 and
            sha(after) in (STARTUP_PATCHED_SHA256, STARTUP_PREVIOUS_PATCHED_SHA256),
            "Startup source differs from independently reviewed frozen source pins")
    a, b = startup_functions(before), startup_functions(after)
    require(set(b) - set(a) == set(STARTUP_HELPERS) and not (set(a) - set(b)),
            "Startup source must add only the two reviewed gate/report helpers")
    restored = after
    for name in STARTUP_HELPERS:
        restored = restored.replace(b[name], b"", 1)
    require("_physics_process" in a and "_physics_process" in b, "Missing startup physics method")
    restored = restored.replace(b["_physics_process"], a["_physics_process"], 1)
    require(restored == before, "Startup source changed outside gate/report patch")
    marker = b"\tif not scale_guide.visible:"
    require(marker in a["_physics_process"] and marker in b["_physics_process"] and
            a["_physics_process"].split(marker, 1)[1] == b["_physics_process"].split(marker, 1)[1],
            "Ordinary physics movement tail changed")
    return a, b


def verify_startup_validation(report):
    require(isinstance(report, dict) and report.get("failures") == 0 and
            report.get("mode") == "validate" and re.match(r"4\.7\.2(?:[.-]|$)", str(report.get("engine", ""))),
            "Compiled startup validation did not pass on Godot 4.7.2")
    for flag in ("original_and_patched_compiled_scripts_valid", "existing_script_contracts_equal",
                 "no_main_scene_instantiation", "test_build_flag_injected_only_in_function_harness"):
        require(report.get(flag) is True, f"Missing compiled startup validation: {flag}")
    require(report.get("added_methods") == STARTUP_HELPERS, "Unexpected compiled startup helpers")
    a, b = report.get("original_contract"), report.get("patched_contract")
    require(isinstance(a, dict) and isinstance(b, dict) and isinstance(b.get("methods"), list),
            "Missing full compiled script contracts")
    added = [m for m in b["methods"] if m.get("name") in STARTUP_HELPERS]
    require(sorted(m["name"] for m in added) == sorted(STARTUP_HELPERS),
            "Compiled helper identities are missing or duplicated")
    shared = {**b, "methods": [m for m in b["methods"] if m.get("name") not in STARTUP_HELPERS]}
    require(a == shared, "Existing compiled methods/properties/signals changed")
    cases = {"original_release_function": 1, "patched_release_function": 0, "patched_debug_function": 1}
    branches = {"release_web_default": 0, "exact_cli_opt_in": 1, "cli_lookalike": 0,
                "web_query_opt_in": 1, "native_ignores_web_query": 0,
                "architecture_independent": 0, "debug_reentry_guard": 1}
    require(isinstance(report.get("branch_cases"), dict), "Missing extracted-GDScript branch evidence")
    for name, count in {**cases, **branches}.items():
        row = report.get(name) if name in cases else report["branch_cases"].get(name)
        require(isinstance(row, dict) and row.get("audit_calls") == count and
                row.get("audit_complete") is True and row.get("off_tree") is True and
                row.get("travel") == 0.75, f"Startup once-only/movement branch failed: {name}")
        point = row.get("walker_position")
        require(isinstance(point, list) and len(point) == 3 and all(
            type(x) in (int, float) and math.isfinite(x) and abs(x - y) < 1e-6
            for x, y in zip(point, (0.75, 1.02, -12.0))), f"Startup walker position changed: {name}")
        if count and name != "original_release_function":
            require(row.get("guard_set_during_audit") is True, f"Startup reentry guard missing: {name}")


def verify_runtime_proof(original, lite, rule):
    """Bind reviewed source, stock-compiler evidence and exactly one packed GDC.

    This is an offline attestation consistency check, not a compiler invocation
    or final-pack/release-Web runtime acceptance. Semantic status stays pending.
    """
    require(rule["path"] == STARTUP_PATH, "Attested runtime scope is exactly meadow_scene.gdc")
    a, b = bytes(original.entries[STARTUP_PATH]), bytes(lite.entries[STARTUP_PATH])
    require(original.header["sha256"] == STARTUP_PACK_SHA256 and sha(a) == STARTUP_GDC_SHA256,
            "Startup proof requires the frozen original PCK and compiled script")
    require(sha(a) == rule["before_sha256"] and sha(b) == rule["after_sha256"] and a != b,
            "Startup entry hashes disagree or replacement is unchanged")
    require(len(a) >= 12 and len(b) >= 12 and a[:4] == b"GDSC" and b[:8] == a[:8],
            "Startup replacement must retain original GDSC format/version")
    scripts = {n for n in set(original.entries) | set(lite.entries)
               if n.startswith("scripts/") or n.endswith((".gd", ".gdc"))}
    changed = {n for n in scripts if original.entries.get(n) != lite.entries.get(n)}
    require(changed == {STARTUP_PATH}, "Startup exception permits exactly one changed runtime entry")
    record = rule.get("builder_record", rule)
    proof_path = record.get("proof")
    require(isinstance(proof_path, str) and Path(proof_path).is_absolute() and
            Path(proof_path).suffix == ".json", "Runtime requires an absolute proof JSON path")
    proof_blob = read_startup_file(proof_path)
    require(sha(proof_blob) == digest_value(record.get("proofSha256"), "proofSha256"),
            "Startup proofSha256 mismatch")
    proof = json_bytes(proof_blob)
    require(isinstance(proof, dict) and proof.get("schema") == "lite-startup-compiler-proof-v115-1" and
            proof.get("status") == "passed", "Unsupported or unfinished compiled-source attestation")
    pin = proof.get("originalPck", {})
    require(pin.get("sha256") == STARTUP_PACK_SHA256 and pin.get("entry") == STARTUP_PATH and
            pin.get("entrySha256") == sha(a), "Attestation original PCK/script pin mismatch")
    sources = []
    for key in ("originalSource", "patchedSource"):
        entry = proof.get(key, {})
        source = read_startup_file(entry.get("path"))
        allowed = (STARTUP_SOURCE_SHA256,) if key == "originalSource" else (
            STARTUP_PATCHED_SHA256, STARTUP_PREVIOUS_PATCHED_SHA256)
        require(entry.get("sha256") == sha(source) and sha(source) in allowed, f"Attestation {key} hash mismatch")
        sources.append(source)
    funcs_a, funcs_b = verify_startup_source(*sources)
    candidate = proof.get("candidateGdc", {})
    require(candidate.get("sha256") == sha(b) and candidate.get("bytes") == len(b) and
            read_startup_file(candidate.get("path")) == b, "Attested candidate differs from actual packed GDC")
    reports = proof.get("compilerReports")
    base = Path(proof_path).parent
    expected_reports = [base / folder / "compilation.json" for folder in
                        ("original-compile", "patched-compile", "patched-repeat")]
    require(isinstance(reports, list) and all(isinstance(p, str) for p in reports) and
            [Path(p) for p in reports] == expected_reports,
            "Need distinct original/patched/repeat stock compilation reports")
    for path, source, output in zip(expected_reports, (sources[0], sources[1], sources[1]), (a, b, b)):
        info = json_bytes(read_startup_file(path))
        require(info.get("sourceSha256") == sha(source) and info.get("outputSha256") == sha(output) and
                info.get("outputBytes") == len(output) and info.get("stockGodotTokenizer") is True,
                "Compiler report input/output pins disagree")
        require(read_startup_file(path.parent / "project/scripts/meadow_scene.gd") == source and
                read_startup_file(path.parent / "meadow_scene.gdc") == output,
                "Compiler source/output sidecar bytes disagree")
        small = Snapshot(read_startup_file(path.parent / "script-only.pck"))
        require(len(small.entries) <= 12 and small.entries.get(STARTUP_PATH) == output,
                "Stock script-only PCK does not contain the attested compiler output")
        pins = {n: {"bytes": len(d), "sha256": sha(d)} for n, d in small.entries.items()}
        require(info.get("privateExportEntries") == pins, "Compiler private-PCK entry pins disagree")
    evidence_path = proof.get("compiledContractEvidence")
    require(isinstance(evidence_path, str) and Path(evidence_path).is_absolute() and
            Path(evidence_path).is_relative_to(base) and Path(evidence_path).name == "result.json",
            "Compiled validation must be a sidecar inside the pinned proof directory")
    validation = json_bytes(read_startup_file(evidence_path))
    require(validation == proof.get("validation"), "Compiled validation sidecar differs from attestation")
    request = json_bytes(read_startup_file(Path(evidence_path).parent / "request.json"))
    require(request.get("original_sha256") == sha(a) and request.get("patched_sha256") == sha(b) and
            read_startup_file(request.get("original")) == a and read_startup_file(request.get("patched")) == b,
            "Compiled validation request does not bind actual before/after GDC bytes")
    require(request.get("original_physics") == funcs_a["_physics_process"].decode().rstrip("\n") + "\n" and
            request.get("patched_physics") == funcs_b["_physics_process"].decode().rstrip("\n") + "\n" and
            request.get("patched_helpers") == "\n".join(funcs_b[n].decode() for n in STARTUP_HELPERS) and
            request.get("added_methods") == STARTUP_HELPERS,
            "Extracted runtime harness differs from the reviewed compiler source")
    verify_startup_validation(validation)
    return {"runtime_proof_status": "PINNED_SOURCE_COMPILER_ATTESTATION_VERIFIED",
            "proof": proof_path, "proof_sha256": sha(proof_blob), "after_sha256": sha(b),
            "gdsc_version": struct.unpack_from("<I", b, 4)[0], "exact_runtime_exception": STARTUP_PATH,
            "reviewed_source_sha256": sha(sources[1]),
            "source_scope": "Reviewed first-physics gate/report only; all other source byte-exact",
            "compiler_original_and_repeat_bytes_verified": True, "semantic_status": "REVIEW_REQUIRED",
            "semantic_limit": "Evidence is offline; final integrated pack and real release-Web startup remain required"}


class Snapshot(Package):
    """One immutable, bounds/overlap/MD5-checked v4 snapshot; never extracted."""

    def __init__(self, blob, label="memory"):
        require(len(blob) <= MAX_BYTES, "PCK exceeds audit size limit")
        self.path, self.web = Path(label), None
        self.entries, self.header = parse_pck(blob)
        self.header.update(bytes=len(blob), sha256=sha(blob))
        self.maps = {}
        for name, data in self.entries.items():
            if not name.endswith((".import", ".remap")):
                continue
            targets = re.findall(r'^path(?:\.[\w.]+)?\s*=\s*"(res://[^"\r\n]+)"',
                                 bytes(data).decode("utf-8").rstrip("\0"), re.M)
            require(len(targets) == 1, f"Unsupported remap: {name}")
            logical = name.rsplit(".", 1)[0]
            require(logical not in self.maps, f"Conflicting remap: {name}")
            self.maps[logical] = safe_name(targets[0])

    @classmethod
    def read(cls, path):
        path = path.resolve(strict=True)
        require(path.is_file() and path.stat().st_size <= MAX_BYTES,
                "Expected a standalone PCK within audit size limit")
        return cls(path.read_bytes(), str(path))


def decode_texture(data):
    """Decode the observed GST2/WebP RGB(A) format, including every mip."""
    blob = bytes(data)
    require(len(blob) >= 56 and blob[:4] == b"GST2", "Truncated/unsupported CTEX")
    version, lw, lh = struct.unpack_from("<3I", blob, 4)
    kind, width, height, mips, fmt = struct.unpack_from("<IHHII", blob, 36)
    require(version == 1 and kind == 2 and fmt in (4, 5), "Unsupported CTEX version/codec/format")
    require(lw > 0 and lh > 0 and width > 0 and height > 0 and
            max(lw * lh, width * height) <= MAX_PIXELS, "Invalid/excessive CTEX dimensions")
    require(mips in (0, max(width, height).bit_length() - 1), "Incomplete/excessive mip chain")
    cursor, levels, encoded_sizes = 52, [], []
    for level in range(mips + 1):
        require(cursor + 4 <= len(blob), "Missing mip length")
        size = struct.unpack_from("<I", blob, cursor)[0]
        cursor += 4
        require(0 < size <= len(blob) - cursor, "Truncated/empty mip payload")
        encoded = blob[cursor:cursor + size]
        require(encoded[:4] == b"RIFF" and len(encoded) >= 12 and
                encoded[8:12] == b"WEBP" and struct.unpack_from("<I", encoded, 4)[0] + 8 == size,
                "Invalid WebP container length")
        with Image.open(io.BytesIO(encoded)) as im:
            expected = (max(1, width >> level), max(1, height >> level))
            require(im.format == "WEBP" and im.size == expected and getattr(im, "n_frames", 1) == 1,
                    f"Mip {level}: decoded codec/dimensions/frame mismatch")
            rgba = im.convert("RGBA")
            require(fmt != 4 or rgba.getchannel("A").getextrema() == (255, 255),
                    "RGB CTEX declares an alpha-bearing image")
            levels.append(rgba)
            encoded_sizes.append(size)
        cursor += size
    require(cursor == len(blob), "Unexpected CTEX trailing data")
    return {"logical": (lw, lh), "stored": (width, height), "levels": levels,
            "encoded_sizes": encoded_sizes,
            "immutable_header": blob[16:40] + blob[48:52]}


def runtime_atlas(resource, logical_size):
    if resource in ANIMALS:
        return {"layout": "grid", "grid": [4, 2]}
    rects = SOURCE_RECTS.get(Path(resource).name)
    if rects:
        return {"layout": "rects", "rects": rects, "lite_rects": rects,
                "coordinate_size": list(logical_size)}
    return {"layout": "whole"}


def verify_ao_rebind(before, after, rule, changes, original, lite, runtime_proofs=None):
    """Prove the AO byte envelope, bind A's semantic evidence to all seven files.

    Does not treat boolean claims/decoded-channel hashes as an independent
    geometry decoder. Those remain REVIEW_REQUIRED alongside native evidence.
    The original AO is pinned; arbitrary offsets/fields/rebakes are not allowed.
    """
    a, b = bytes(before), bytes(after)
    evidence = rule.get("builder_record", rule).get("checks", {})
    require(isinstance(evidence, dict) and evidence.get("kind") == AO_REBIND_KIND,
            "Changed AO requires explicit signature-only-rebind proof")
    require(sha(a) == AO_ORIGINAL_SHA256, "AO proof requires the frozen original AO")
    patches = evidence.get("patches")
    require(isinstance(patches, list) and len(patches) == 1 and isinstance(patches[0], dict),
            "AO permits exactly one signature patch")
    patch = patches[0]
    require(patch.get("field") == "mesh_signature" and type(patch.get("offset")) is int and
            patch["offset"] == 68 and type(patch.get("length")) is int and patch["length"] == 64,
            "AO patch must be the original 64-byte mesh_signature field at offset 68")
    old = digest_value(patch.get("before"), "AO original mesh_signature")
    new = digest_value(patch.get("after"), "AO rebound mesh_signature")
    require(old != new and len(a) == len(b) and a[68:132] == old.encode() and b[68:132] == new.encode(),
            "AO signature values/length disagree with actual bytes")
    # FileAccess.store_var envelope and the exact serialized key/value prefix.
    key_prefix = struct.pack("<II", 4, 14) + b"mesh_signature\0\0" + struct.pack("<II", 4, 64)
    require(struct.unpack_from("<I", a)[0] == len(a) - 4 and a[36:68] == key_prefix,
            "AO patch is not the serialized mesh_signature value")
    require(a[:68] == b[:68] and a[132:] == b[132:],
            "AO visibility, prefix, sampling metadata or other non-signature bytes changed")
    for field in ("visibility_and_sampling_geometry_exact", "original_rock_POSITION_NORMAL_TANGENT_COLOR_INDEX_exact",
                  "all_original_terrain_arrays_exact", "visibility_prefix_bytes_and_mapping_exact"):
        require(evidence.get(field) is True, f"AO semantic proof missing: {field}")
    require(evidence.get("signature_bypass") is False, "AO signature validation must not be bypassed")
    probe = evidence.get("runtime_probe", {})
    require(isinstance(probe, dict) and all(probe.get(k) is True for k in
            ("applied", "original_runtime_helper", "off_tree", "all_sample_indices_and_nonblue_attributes_exact")),
            "AO proof needs original runtime acceptance and complete sample mapping")
    require(probe.get("mesh_signature") == new and probe.get("visibility_samples_checked") == 317556 and
            probe.get("collision_shapes_checked") == 1,
            "AO runtime proof has wrong signature/sample/collider count")
    terrain_signature = digest_value(probe.get("terrain_signature"), "AO terrain signature")
    require(a[168:232] == terrain_signature.encode(), "AO terrain signature proof disagrees with original bytes")
    bound = {}
    for name in sorted(GEOMETRY_SET):
        record = changes.get(name)
        require(record is not None and record.get("kind") == "geometry" and
                name in original.entries and name in lite.entries,
                f"AO rebind requires the complete seven-resource geometry set: {name}")
        require(record.get("before_sha256") == sha(original.entries[name]) and
                record.get("after_sha256") == sha(lite.entries[name]),
                f"AO companion geometry hash mismatch: {name}")
        bound[name] = record["after_sha256"]
    for path, label, channels in (("assets/baked/v77/detail.scn", "SolidLimestoneGeology", ("0", "1", "2", "3")),
                                  ("assets/baked/v77/terrain.scn", "ContinuousMeadow", ("0", "1", "2", "3", "4", "5"))):
        record = changes[path]
        proof = record.get("builder_record", record).get("checks", {})
        require(proof.get("topology_vertex_index_triangle_order_exact") is True and
                proof.get("collision_arrays_and_node_material_mesh_metadata_exact") is True and
                proof.get("signature_bypass") is False, "AO companion topology/transforms/collision proof missing")
        surfaces = [s for s in proof.get("surfaces", []) if isinstance(s, dict) and s.get("label") == label]
        require(len(surfaces) == 1, "AO sampling mesh proof must identify one surface")
        surface = surfaces[0]
        hashes_a, hashes_b = surface.get("decoded_channel_sha256_before", {}), surface.get("decoded_channel_sha256_after", {})
        # Terrain has no COLOR array; absence must match, not be fabricated.
        for channel in channels:
            if channel == "3" and label == "ContinuousMeadow" and channel not in hashes_a and channel not in hashes_b:
                continue
            digest_value(hashes_a.get(channel), "AO sampled channel hash")
            require(hashes_a[channel] == hashes_b.get(channel), "AO sampling POSITION/NORMAL/TANGENT/COLOR data changed")
        require(surface.get("position_max_vector_error") == 0 and surface.get("normal_max_angle_degrees") == 0,
                "AO sampling geometry must remain exact, not approximately close")
        require(surface.get("topology", {}).get("new_degenerate_triangles") == 0 and
                surface.get("topology", {}).get("winding_reversals") == 0,
                "AO topology proof is inconsistent")
    # A kind/hash allowlist alone cannot waive original AO validation. Only the
    # independently verified, source-pinned startup gate may differ; the AO
    # helper and every other script still have to be exactly original.
    runtime_proofs = runtime_proofs or {}
    for name in original.entries:
        if name.startswith("scripts/"):
            proof = runtime_proofs.get(name, {})
            if (name == STARTUP_PATH and proof.get("runtime_proof_status") ==
                    "PINNED_SOURCE_COMPILER_ATTESTATION_VERIFIED" and
                    proof.get("exact_runtime_exception") == name and name in lite.entries and
                    proof.get("after_sha256") == sha(lite.entries[name])):
                continue
            require(name in lite.entries and original.entries[name] == lite.entries[name],
                    "AO rebind requires unchanged original runtime scripts")
    return {"ao_status": "SIGNATURE_ONLY_REBIND_BYTE_PROOF", "patch_offset": 68, "patch_bytes": 64,
            "all_other_ao_bytes_exact": True, "mesh_signature_before": old, "mesh_signature_after": new,
            "terrain_signature": terrain_signature, "bound_geometry_sha256": bound,
            "attested_runtime_exceptions": sorted(runtime_proofs),
            "visibility_samples": 317556, "semantic_evidence_consistency_checked": True,
            "semantic_status": "REVIEW_REQUIRED",
            "semantic_limit": "Companion channel/runtime claims need independently reviewed decoded/native evidence; not inferred from hashes"}


def normalize_manifest(manifest, original, lite):
    """Accept main's actual lite-build.json, independently verify its claims."""
    if not isinstance(manifest, dict) or "schemaVersion" not in manifest:
        return manifest
    require(type(manifest["schemaVersion"]) is int and manifest["schemaVersion"] == 1,
            "Unsupported builder schemaVersion")
    require(manifest.get("fullScene") is True and manifest.get("waterTextureUnchanged") is True,
            "Builder must declare the full-scene/water contract")
    require(manifest.get("sourceBytes") == original.header["bytes"] and
            manifest.get("liteBytes") == lite.header["bytes"], "Builder whole-pack byte counts disagree")
    require(isinstance(manifest.get("changes"), list), "Builder changes must be a list")
    changes = []
    kinds = {"lite-ctex": "texture", "lite-geometry": "geometry", "lite-project-settings": "project",
             "lite-runtime": "runtime"}
    runtime_records = [e for e in manifest["changes"] if isinstance(e, dict) and e.get("kind") == "lite-runtime"]
    require(not runtime_records or (len(runtime_records) == 1 and runtime_records[0].get("path") == STARTUP_PATH),
            "Builder lite-runtime permits exactly one meadow_scene.gdc replacement")
    for entry in manifest["changes"]:
        require(isinstance(entry, dict), "Invalid builder change record")
        name = safe_name(entry.get("path", ""))
        require(entry.get("kind") in kinds and name in original.entries and name in lite.entries,
                f"Unsupported builder change kind/path: {name}")
        require(entry.get("before") == len(original.entries[name]) and entry.get("after") == len(lite.entries[name]),
                f"Builder entry byte counts disagree: {name}")
        row = {"path": name, "kind": kinds[entry["kind"]],
               "before_sha256": entry.get("beforeSha256"), "after_sha256": entry.get("afterSha256"),
               "reason": entry.get("reason") or entry["kind"], "builder_record": entry}
        if row["kind"] == "texture":
            logical = [key for key in original.maps if key.endswith(".png") and original.resolve(key) == name]
            require(len(logical) == 1, f"Texture needs one unambiguous original PNG remap: {name}")
            resource = logical[0]
            row.update(resource=resource, logical_size=entry.get("logicalSize"), stored_size=entry.get("physicalAfter"),
                       source_mip=entry.get("mipDrop"), atlas=runtime_atlas(resource, entry.get("logicalSize", [])),
                       runtime={"coordinates": "logical-preserved", "adapted_scripts": []})
        changes.append(row)
    return {"schema_version": 1, "original_sha256": manifest.get("sourceSha256"),
            "lite_sha256": manifest.get("liteSha256"), "changes": changes,
            "manifest_format": "build_lite_pack.schemaVersion1", "source": manifest.get("source")}


def project_records(blob):
    """Parse only ECFG's key/value envelope. Unchanged Variant bytes stay opaque."""
    blob = bytes(blob)
    require(len(blob) >= 8 and blob[:4] == b"ECFG", "Invalid project.binary ECFG header")
    count = struct.unpack_from("<I", blob, 4)[0]
    require(count <= 10000, "Excessive project setting count")
    cursor, result = 8, {}
    for _ in range(count):
        values = []
        for _ in range(2):
            require(cursor + 4 <= len(blob), "Truncated ECFG record length")
            length = struct.unpack_from("<I", blob, cursor)[0]
            cursor += 4
            require(0 < length <= len(blob) - cursor, "Truncated/empty ECFG record")
            values.append(blob[cursor:cursor + length])
            cursor += length
        key = values[0].decode("utf-8")
        require(key not in result, f"Duplicate ECFG setting: {key}")
        result[key] = values[1]
    require(cursor == len(blob), "Trailing ECFG data")
    return result


def numeric_variant(blob):
    require(len(blob) >= 8, "Truncated numeric Variant")
    code = struct.unpack_from("<I", blob)[0]
    formats = {2: "<i", 2 | (1 << 16): "<q", 3: "<f", 3 | (1 << 16): "<d"}
    require(code in formats, "Expected numeric Variant for approved render setting")
    fmt = formats[code]
    require(len(blob) == 4 + struct.calcsize(fmt), "Invalid numeric Variant length")
    value = struct.unpack_from(fmt, blob, 4)[0]
    require(math.isfinite(value), "Nonfinite render setting")
    return value


def verify_project(before, after):
    a, b = project_records(before), project_records(after)
    require(set(a) <= set(b), "Project settings removed")
    changed = {key for key in b if a.get(key) != b[key]}
    require(changed <= set(LITE_SETTINGS), "Unapproved project settings changed: " + ", ".join(sorted(changed - set(LITE_SETTINGS))))
    verified = {}
    for key, expected in LITE_SETTINGS.items():
        # save_custom may omit bilinear mode because zero is the engine default.
        require(key in b or key == "rendering/scaling_3d/mode", f"Missing lite render setting: {key}")
        actual = numeric_variant(b[key]) if key in b else 0
        require(actual == expected, f"Unexpected lite render setting: {key}={actual}")
        verified[key] = actual
    return {"changed_keys": sorted(changed), "verified_values": verified,
            "all_other_variant_bytes_exact": True, "runtime_render_resolution": "NOT_RUN"}


def normalized_rects(rects, size, label):
    require(isinstance(rects, list) and 0 < len(rects) <= 256, f"{label}: missing/excessive rectangles")
    result = []
    w, h = size
    for rect in rects:
        require(isinstance(rect, list) and len(rect) == 4 and
                all(type(n) in (int, float) and math.isfinite(n) for n in rect),
                f"{label}: invalid rectangle")
        x, y, rw, rh = rect
        require(x >= 0 and y >= 0 and rw > 0 and rh > 0 and
                x + rw <= w + 1e-6 and y + rh <= h + 1e-6, f"{label}: out-of-bounds rectangle")
        result.append([x / w, y / h, rw / w, rh / h])
    for i, a in enumerate(result):
        for b in result[:i]:
            require(min(a[0] + a[2], b[0] + b[2]) <= max(a[0], b[0]) + 1e-9 or
                    min(a[1] + a[3], b[1] + b[3]) <= max(a[1], b[1]) + 1e-9,
                    f"{label}: overlapping/duplicate rectangles")
    return result


def atlas_regions(rule, before, after):
    resource, atlas = rule["resource"], rule.get("atlas")
    require(isinstance(atlas, dict), "Explicit atlas layout required (whole/grid/rects)")
    layout = atlas.get("layout")
    if resource in ANIMALS:
        require(layout == "grid" and atlas.get("grid") == [4, 2], "Animal atlas must retain 4-by-2/eight frames")
    if resource == DRAGON:
        require(layout == "rects" and atlas.get("rects") == DRAGON_RECTS,
                "Dragon must retain its 32 measured irregular frames in order")
    expected_count = RECT_COUNTS.get(Path(resource).name)
    if expected_count:
        require(layout == "rects" and len(atlas.get("rects", [])) == expected_count,
                f"Atlas must retain {expected_count} measured regions")
    if layout == "whole":
        return [[0.0, 0.0, 1.0, 1.0]]
    if layout == "grid":
        columns, rows = dimensions(atlas.get("grid"), "frame grid")
        require(columns * rows <= 256, "Excessive frame grid")
        # Fractional cells are established for hare/stag; no divisibility test.
        return [[x / columns, y / rows, 1 / columns, 1 / rows]
                for y in range(rows) for x in range(columns)]
    require(layout == "rects", "Unsupported atlas layout")
    original = normalized_rects(atlas.get("rects"), before["logical"], "original atlas")
    coordinate_size = dimensions(atlas.get("coordinate_size"), "atlas coordinate_size")
    require(coordinate_size in (after["logical"], after["stored"]),
            "Atlas coordinates do not match texture or CPU image dimensions")
    candidate = normalized_rects(atlas.get("lite_rects"), coordinate_size, "lite atlas")
    require(len(original) == len(candidate), "Atlas frame/region count changed")
    # Permit at most half a destination pixel of rounding, preserving frame order.
    tolerance = np.array([0.5 / after["stored"][0], 0.5 / after["stored"][1]] * 2)
    require(np.all(np.abs(np.array(original) - candidate) <= tolerance + 1e-9),
            "Atlas normalized frame layout/ratio/order changed")
    return original


def alpha_metrics(reference, candidate):
    """Resolution-matched measures; never demand original alpha byte identity."""
    a, b = (np.asarray(im, dtype=np.float32) / 255 for im in (reference, candidate))
    aa, ab = a[:, :, 3], b[:, :, 3]
    # Compare alpha mass and shape, with no visible-pixel count penalty for blur.
    coverage_a, coverage_b = float(aa.mean()), float(ab.mean())
    alpha_mae = float(np.abs(aa - ab).mean())
    # Cutout boundaries include fully transparent neighbouring RGB, which GPU
    # linear filtering can mix into a halo. Sample channels independently.
    def filtered(im):
        target = (im.width + 1, im.height + 1)
        rgb = np.asarray(im.convert("RGB").resize(target, Image.Resampling.BILINEAR), dtype=np.float32) / 255
        alpha = np.asarray(im.getchannel("A").resize(target, Image.Resampling.BILINEAR), dtype=np.float32) / 255
        return rgb * alpha[:, :, None], alpha
    ca, fa = filtered(reference)
    cb, fb = filtered(candidate)
    edge = (fa > 0.02) & (fa < 0.98) & (fb > 0.02)
    bright = np.maximum((cb - ca).mean(axis=2), 0)
    edge_brightening = float(bright[edge].mean()) if edge.any() else 0.0
    # Only preserve *existing* transparent gutters, never invent padding on a
    # tightly cropped original. A one-pixel filtering skirt is allowed.
    halo = reference.getchannel("A").point(lambda x: 255 if x > 2 else 0).filter(ImageFilter.MaxFilter(3))
    clear = np.asarray(halo) == 0
    gutter_leak = float(ab[clear].mean()) if clear.any() else 0.0
    return {"alpha_coverage_reference": coverage_a, "alpha_coverage_lite": coverage_b,
            "alpha_mae": alpha_mae, "edge_brightening": edge_brightening,
            "transparent_gutter_alpha": gutter_leak}


def check_metrics(metrics, label, errors):
    a, b = metrics["alpha_coverage_reference"], metrics["alpha_coverage_lite"]
    if metrics["alpha_mae"] > 0.05:
        errors.append(f"{label}: alpha shape changed beyond downsample tolerance")
    if abs(a - b) > max(0.008, a * 0.20):
        errors.append(f"{label}: alpha coverage lost/gained beyond downsample tolerance")
    if a > 0.001 and b < a * 0.25:
        errors.append(f"{label}: formerly visible frame/region lost")
    if metrics["edge_brightening"] > 0.10:
        errors.append(f"{label}: new bright fringe in linear-filtered transparent edges")
    if metrics["transparent_gutter_alpha"] > 0.015:
        errors.append(f"{label}: previously clear atlas gutter contaminated")


def crop_region(image, region):
    x, y, w, h = region
    # Keep fractional grid boundaries until choosing covered pixels for metrics.
    left, top = math.floor(x * image.width + 1e-9), math.floor(y * image.height + 1e-9)
    right = min(image.width, math.ceil((x + w) * image.width - 1e-9))
    bottom = min(image.height, math.ceil((y + h) * image.height - 1e-9))
    require(right > left and bottom > top, "Atlas cell has no destination pixels")
    return image.crop((left, top, right, bottom))


def verify_texture(before_blob, after_blob, rule):
    a, b = decode_texture(before_blob), decode_texture(after_blob)
    require(dimensions(rule.get("logical_size"), "logical_size") == b["logical"],
            "Runtime logical texture size disagrees with CTEX header")
    require(dimensions(rule.get("stored_size"), "stored_size") == b["stored"],
            "Stored size disagrees with decoded CTEX")
    require(a["immutable_header"] == b["immutable_header"], "CTEX flags/codec/format metadata changed")
    require(a["logical"] == b["logical"], "v115 preserves original outer logical dimensions")
    source_mip = rule.get("source_mip")
    require(type(source_mip) is int and 0 <= source_mip < len(a["levels"]),
            "Texture requires source_mip identifying the selected existing mip")
    require(a["levels"][source_mip].size == b["stored"] and
            len(b["levels"]) == len(a["levels"]) - source_mip,
            "Lite mip chain must retain every level from selected source_mip")
    if Path(rule["resource"]).name in KEEP_PHYSICAL:
        require(source_mip == 0 and a["stored"] == b["stored"],
                "Measured CPU/GPU pixel consumer must retain physical resolution")
    evidence = rule.get("builder_record")
    if evidence is not None:
        require(dimensions(evidence.get("physicalBefore"), "physicalBefore") == a["stored"],
                "Builder physicalBefore disagrees with source CTEX")
        require(isinstance(evidence.get("levels"), list) and len(evidence["levels"]) == len(b["levels"]),
                "Builder level evidence count disagrees with CTEX")
    require(all(x <= y for x, y in zip(b["stored"], a["stored"])), "Lite texture unexpectedly upscaled")
    # One destination texel covers ordinary odd-size mip rounding.
    for key in ("logical", "stored"):
        aw, ah = a[key]
        bw, bh = b[key]
        require(abs(bw * ah - bh * aw) <= max(aw, ah), f"Texture {key} aspect ratio changed")
    if len(a["levels"]) > 1:
        require(len(b["levels"]) == max(b["stored"]).bit_length(), "Downsampled mip chain is incomplete")
    regions, errors, levels = atlas_regions(rule, a, b), [], []
    for index, candidate in enumerate(b["levels"]):
        reference = a["levels"][source_mip + index]
        require(reference.size == candidate.size, f"Mip {index}: selected source dimensions differ")
        require(reference.getchannel("A").tobytes() == candidate.getchannel("A").tobytes(),
                f"Mip {index}: alpha differs from selected source mip {source_mip + index}")
        metrics = alpha_metrics(reference, candidate)
        if evidence is not None:
            declared = evidence["levels"][index]
            require(isinstance(declared, dict) and declared.get("sourceLevel") == source_mip + index and
                    declared.get("size") == list(candidate.size) and declared.get("bytes") == b["encoded_sizes"][index] and
                    declared.get("alphaExact") is True and
                    declared.get("alphaSha256") == sha(candidate.getchannel("A").tobytes()),
                    f"Mip {index}: builder alpha/size/level/byte evidence disagrees")
            before_rgb, after_rgb = np.asarray(reference).astype(np.float32), np.asarray(candidate).astype(np.float32)
            visible = before_rgb[:, :, 3] >= 16
            delta = before_rgb[:, :, :3] - after_rgb[:, :, :3]
            rmse = float(np.mean(delta[visible] ** 2)) ** 0.5 if visible.any() else 0.0
            require(type(declared.get("visibleRgbRmse")) in (int, float) and
                    abs(declared["visibleRgbRmse"] - rmse) <= 0.00011,
                    f"Mip {index}: builder visibleRgbRmse disagrees")
            metrics["visible_rgb_rmse"] = round(rmse, 4)
        if a["levels"][0].getchannel("A").getextrema() == (255, 255):
            require(candidate.getchannel("A").getextrema() == (255, 255), "Opaque texture acquired transparency")
        check_metrics(metrics, f"mip {index}", errors)
        levels.append({"level": index, "source_level": source_mip + index,
                       "alpha_exact_to_selected_mip": True, "size": list(candidate.size), **metrics})
    frames = []
    reference, candidate = a["levels"][source_mip], b["levels"][0]
    for index, region in enumerate(regions):
        metrics = alpha_metrics(crop_region(reference, region), crop_region(candidate, region))
        check_metrics(metrics, f"frame/region {index}", errors)
        # Exact alpha versus an existing small mip does not prove that mip
        # still contains each formerly visible design. Compare normalized mass
        # against the full-resolution frame as well, allowing blur/rounding.
        full = np.asarray(crop_region(a["levels"][0], region).getchannel("A"), dtype=np.float32) / 255
        full_coverage = float(full.mean())
        metrics["full_resolution_alpha_coverage"] = full_coverage
        if full_coverage > 0.002 and metrics["alpha_coverage_lite"] < full_coverage * 0.25:
            errors.append(f"frame/region {index}: selected mip loses formerly visible design")
        frames.append({"index": index, **metrics})
    return {"errors": errors, "logical_size": list(b["logical"]), "stored_size": list(b["stored"]),
            "frame_count": len(regions), "levels": levels, "frames": frames}, a, b


def runtime_dimensions(rule, before, after, original, lite, runtime_paths):
    runtime = rule.get("runtime")
    require(isinstance(runtime, dict), "Texture requires explicit runtime coordinate handling")
    mode = runtime.get("coordinates")
    require(mode in ("logical-preserved", "scaled-coordinates", "normalized"), "Unknown runtime coordinates")
    if mode == "logical-preserved":
        require(before["logical"] == after["logical"], "Logical-preserved texture dimensions changed")
    scripts = runtime.get("adapted_scripts", [])
    require(isinstance(scripts, list), "adapted_scripts must be a list")
    adapted = set()
    for script in scripts:
        script = safe_name(script)
        target = lite.resolve(script)
        require(target in runtime_paths, f"Runtime adaptation not pinned as changed script: {script}")
        adapted.add(script)
    name = Path(rule["resource"]).name
    required = set()
    if before["logical"] != after["logical"]:
        required.update(PIXEL_COORDINATES.get(name, ()))
    if before["stored"] != after["stored"] and name in CPU_CROPS:
        handling = runtime.get("cpu_image")
        require(handling in ("scaled-coordinates", "restored-logical", "prebaked"),
                "Resized CPU pixel crops need scaled coordinates, restored image, or reviewed prebake")
        # A prebaked replacement must change its caller; merely declaring the
        # old construction dead is not proof. Geometry semantics stay pending.
        required.update(CPU_CROPS[name][:1] if handling == "prebaked" else CPU_CROPS[name])
    for consumer in sorted(required):
        require(f"scripts/{consumer}.gd" in adapted or f"scripts/{consumer}.gdc" in adapted,
                f"Missing runtime dimension adaptation: scripts/{consumer}.gd")
    return {"coordinates": mode, "cpu_image": runtime.get("cpu_image"),
            "adapted_scripts": sorted(adapted), "evidence": "declarations_and_hash_pins_only"}


def audit(original, lite, manifest, required_resources=CRITICAL):
    manifest = normalize_manifest(manifest, original, lite)
    require(isinstance(manifest, dict) and manifest.get("schema_version") == 1, "Expected manifest schema_version 1")
    for key in ("original_sha256", "lite_sha256"):
        digest_value(manifest.get(key), key)
    require(isinstance(manifest.get("changes"), list), "Manifest changes must be an explicit list")
    errors, pending, checks = [], [], []
    for pkg, key in ((original, "original_sha256"), (lite, "lite_sha256")):
        if pkg.header["sha256"] != manifest[key]:
            errors.append(f"Whole-pack {key} mismatch (headers/directory/padding included)")
    if original.header["engine"] != lite.header["engine"]:
        errors.append("Packs target different Godot engine versions")
    for name in sorted(set(required_resources) | set(manifest.get("required_resources", []))):
        if original.resolve(name) is None or lite.resolve(name) is None:
            errors.append(f"Required scene/runtime resource missing: {name}")
    for label, pkg in (("original", original), ("lite", lite)):
        for logical in pkg.maps:
            if pkg.resolve(logical) is None:
                errors.append(f"{label}: dangling import/remap: {logical}")
        if required_resources:
            errors.extend(f"{label}: {error}" for error in check_package(pkg)["errors"])
    before_names, after_names = set(original.entries), set(lite.entries)
    removed = sorted(before_names - after_names)
    if removed:
        errors.append("Original packed resources removed: " + ", ".join(removed))
    changes = {}
    for record in manifest["changes"]:
        require(isinstance(record, dict), "Invalid manifest change")
        name = safe_name(record.get("path", ""))
        require(name not in changes and name == record["path"], "Duplicate/noncanonical change path")
        require(record.get("kind") in KINDS and isinstance(record.get("reason"), str) and record["reason"].strip(),
                f"Change requires known kind and review reason: {name}")
        digest_value(record.get("after_sha256"), f"{name} after_sha256")
        if name in before_names:
            digest_value(record.get("before_sha256"), f"{name} before_sha256")
        else:
            require(record.get("before_sha256") is None and record["kind"] == "runtime",
                    "Only explicitly hash-pinned runtime helpers may be added")
        changes[name] = record
    runtime_paths = {n for n, r in changes.items() if r["kind"] == "runtime" and n.endswith((".gd", ".gdc"))}
    protected = {n for n in before_names if n.endswith((".import", ".remap", ".gdshader", ".gdshaderinc"))}
    if original.resolve(WATER):
        protected.add(original.resolve(WATER))
    actual_changes = {n for n in after_names if n not in before_names or sha(original.entries[n]) != sha(lite.entries[n])}
    # AO sorts before scripts. Validate the narrow script attestation first;
    # unverified/missing proof must never unlock that earlier AO check.
    runtime_proofs, runtime_failures = {}, set()
    for name, record in changes.items():
        if record["kind"] == "runtime" and name == STARTUP_PATH:
            try:
                require(name in before_names and name in after_names, "Startup runtime must replace an existing script")
                runtime_proofs[name] = verify_runtime_proof(original, lite, record)
            except (ValueError, OSError, struct.error, TypeError, KeyError, UnicodeError, AttributeError) as exc:
                errors.append(f"{name}: {exc}")
                runtime_failures.add(name)
    for name in sorted(actual_changes | set(changes)):
        record = changes.get(name)
        if name in protected:
            errors.append(f"Protected water/shader/import/remap entry allowlisted or changed: {name}")
            continue
        if record is None:
            errors.append(f"Unmanifested packed entry changed/added: {name}")
            continue
        if name not in after_names or (name not in actual_changes and "builder_record" not in record):
            errors.append(f"Stale manifest change (not actually changed/present): {name}")
            continue
        a, b = original.entries.get(name), lite.entries[name]
        if (a is not None and sha(a) != record["before_sha256"]) or sha(b) != record["after_sha256"]:
            errors.append(f"Manifest entry SHA256 mismatch: {name}")
            continue
        kind = record["kind"]
        if name in runtime_failures:
            continue
        try:
            row = {"path": name, "kind": kind}
            if kind == "texture":
                resource = safe_name(record.get("resource", ""))
                require(resource == record["resource"] and original.resolve(resource) == name and
                        lite.resolve(resource) == name and name.endswith(".ctex"), "Texture logical/import target mismatch")
                result, old, new = verify_texture(a, b, record)
                errors.extend(f"{name}: {err}" for err in result.pop("errors"))
                row.update(result)
                row["runtime"] = runtime_dimensions(record, old, new, original, lite, runtime_paths)
            elif kind == "lossless-rscc":
                from repack_web_cache import _unpack
                require(name.endswith(".scn") and a is not None, "Lossless RSCC rule needs existing scene")
                raw_a, raw_b = _unpack(bytes(a)), _unpack(bytes(b))
                require(raw_a == raw_b, "Lossless RSCC decoded geometry/metadata changed")
                row.update(decoded_exact=True, decoded_sha256=sha(raw_a))
            elif kind == "project":
                require(name == "project.binary", "Project rule must target project.binary")
                row.update(verify_project(a, b))
            elif kind == "geometry" and name == AO_PATH and name in actual_changes:
                row.update(verify_ao_rebind(a, b, record, changes, original, lite, runtime_proofs))
                pending.append(f"{name}: signature-only byte proof verified; companion sampling geometry/native evidence review required")
            elif name in runtime_proofs:
                row.update(runtime_proofs[name])
                pending.append(f"{name}: offline startup attestation verified; final-pack native/release-Web semantics still required")
            else:
                valid = ((kind == "geometry" and name.startswith("assets/baked/") and name.endswith((".scn", ".bin"))) or
                         (kind == "runtime" and name.startswith("scripts/") and name.endswith((".gd", ".gdc", ".gd.remap"))) or
                         (kind == "project" and name == "project.binary"))
                require(valid, "Kind does not match permitted packed path")
                if name in actual_changes:
                    pending.append(f"{name}: hash-pinned {kind}; semantic scene/walking/Boss/water/animation review required")
                    row["semantic_status"] = "REVIEW_REQUIRED"
                else:
                    row["unchanged_replacement"] = True
            checks.append(row)
        except (ValueError, OSError, struct.error) as exc:
            errors.append(f"{name}: {exc}")
    return {"status": "FAIL" if errors else "STRUCTURAL_PASS", "errors": errors,
            "original": original.header, "lite": lite.header, "manifest_schema_version": 1,
            "manifest_format": manifest.get("manifest_format", "explicit-schema-v1"),
            "original_frozen": original.header["sha256"] == manifest["original_sha256"],
            "entry_count": len(lite.entries), "changed_entries": sorted(actual_changes),
            "unchanged_entries": len(before_names & after_names) - len(actual_changes & before_names),
            "checks": checks, "pending": pending,
            "visual_status": "NOT_REVIEWED", "runtime_status": "NOT_RUN",
            "limitations": ["No engine, browser, services, extraction, file writes or network measurements",
                            "Geometry/GDScript hash pins are not semantic or scene-node equivalence",
                            "Startup compiler attestation is not execution of the final pack or true release-Web gate",
                            "Approved project-setting bytes do not measure the actual rendered buffer",
                            "Runtime coordinate declarations need implementation review and runtime evidence",
                            "Alpha/fringe tolerances are regression guards, not visual acceptance",
                            "Whole-frame day/night, animation, water, walking and Boss space remain to verify"]}


def manifest_example():
    return {"schema_version": 1, "original_sha256": "0" * 64, "lite_sha256": "1" * 64,
            "changes": [{"path": ".godot/imported/EXACT-TARGET.ctex", "kind": "texture",
                         "before_sha256": "2" * 64, "after_sha256": "3" * 64,
                         "reason": "Authorized lower-resolution atlas; reviewed runtime mapping",
                         "resource": "assets/creatures/leaf-hare-v54.png",
                         "logical_size": [1774, 887], "stored_size": [887, 443],
                         "source_mip": 1,
                         "atlas": {"layout": "grid", "grid": [4, 2]},
                         "runtime": {"coordinates": "logical-preserved", "adapted_scripts": []}}],
            "_example_notes": ["Replace all placeholder hashes and packed path; list EVERY actual changed entry",
                               "Whole-image atlas: {layout: whole}; measured atlas: {layout: rects, rects: original pixel rectangles, lite_rects: runtime rectangles, coordinate_size: [w,h]}",
                               "For resized CPU-crop assets set runtime.cpu_image to scaled-coordinates, restored-logical or prebaked; pin each adapted script separately",
                               "CLI status covers structure only; pending semantic and visual checks are not waived"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--lite", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-example", action="store_true")
    args = parser.parse_args(argv)
    if args.manifest_example:
        print(json.dumps(manifest_example(), indent=2))
        return 0
    if not all((args.original, args.lite, args.manifest)):
        parser.error("--original --lite --manifest are required")
    try:
        require(args.original.resolve() != args.lite.resolve(), "Original and lite must be distinct PCK files")
        result = audit(Snapshot.read(args.original), Snapshot.read(args.lite), load_json(args.manifest))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 0
    except (ValueError, OSError, UnicodeError, struct.error, TypeError, KeyError, ImportError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
