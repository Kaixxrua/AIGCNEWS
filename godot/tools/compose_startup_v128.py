"""Compose the pinned v128 leaf/AO packs with exactly the attested edge cache.

No export, compilation, precision changes, or re-encoding of existing resources.
The shipping pack requires RSCC mode 5; the logical twin uses stock codecs.
Run with --audit for one full existing native runtime probe plus edge checks.
All generated files are confined to artifacts/startup-v128/combined-01.
"""
from pathlib import Path
import argparse
import difflib
import gzip
import hashlib
import json
import os
import re
import struct
import subprocess
import time
import unittest

from inspect_web_pack import read_pack
from repack_web_cache import _unpack
from build_filtered_scene_pack_v128 import decode, encode

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/startup-v128/combined-01"
EDGE = ROOT / "artifacts/startup-v128/edge-growth/controller-01"
STANDARD = ROOT / "artifacts/startup-v128/ready-ao/candidate-01/index-lite.pck"
FILTERED = ROOT / "artifacts/startup-v128/filtered-scenes/candidate-01/index-lite.pck"
STANDARD_SHA = "1182ea711300b62fc4cd097acb1321840e75b53d02e884fbcdf02a2e15796460"
FILTERED_SHA = "dfae7b33bbf28a12a456610abb7dd80da36bd5158b5b5cfc8f1527c5150cadfc"
ENTRY = "scripts/meadow_edge_growth.gdc"
CACHE = "assets/baked/lite-v128/crown-edge-controller.scn"
OLD_GDC = "d9c169719a93563757b636c96eeba758c12e3e9f9047adc46308d312601b3e13"
NEW_GDC = "0b7ae4607dc969daa1a30506e9400424c9c040ef9a0a1cc5c1a00a21fdb4af74"
CACHE_SHA = "34489228f43904d70402efff0c86986434288d44552463b0723d08f529682592"
CACHE_RAW_SHA = "756ca41dbcb702f7f45aead587e224e882579c98e6afaca27d31493011a4d340"
ORIGINAL_SOURCE_SHA = "33f445246f5d23c338a22407207d0dc498469fd19ee8067f402adabf3090337e"
LITE_SOURCE_SHA = "727ba184bb2ac426e1f9e92dde4cec9822034ae6798dc37ac584be65707b95ed"
PROBE = ROOT / "godot/tools/test_lite_runtime_v128.gd"
PROBE_SHA = "e1029c656e5c9f35ea022c18c8f02a801e9ea67602e69a7282314ab5ab65051e"
EDGE_PROBE = ROOT / "godot/tools/bake_lite_edge_growth_v128.gd"
EDGE_PROBE_SHA = "627d4435f6e26ba5a9970e86b703d82bc6dd60a98914a9d457208a01741c4e3a"
ENGINE = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64.exe"
ENGINE_SHA = "ab1824f85bfd8e0e4128182c000c4003a3e042245b2967848d089b2a04b22424"
PINS = {
    "artifacts/startup-v128/edge-growth/controller-01/edge-growth-replacements.final.json": "bb89e990519fb04794acad9fb651fa872f0c0d2b0160030afe55bc5246ec66e9",
    "artifacts/startup-v128/edge-growth/controller-01/final-proof.json": "94565cd7409678f09ab0a1feda7c53f69df30e4878dd412828efae8f7365f350",
    "artifacts/startup-v128/edge-growth/controller-01/proof.json": "91817cc479ce4076836b8676d094e24971bfe12c9d5115d45c0931119e8b94b3",
    "artifacts/startup-v128/edge-growth/controller-01/source-contract.json": "c4e5ccd843867fcba78528f7acfdcdb5037796c2a98236118fb669d9f1649eda",
    "artifacts/startup-v128/independent/ready-ao-01-scene-contract.json": "604e02a86ef67fd70b7516d776221c885126c9a75e7269e9a84de32513096344",
    "artifacts/startup-v128/ready-ao/candidate-01/proof.json": "c167420ccd978cb2b774c45963decbf5e2c55f4fbc9ced3bae7c6f58888abeed",
    "artifacts/startup-v128/filtered-scenes/candidate-01/proof.json": "5de6115c86ede5f11fe3a44411d35cfd91ec2cb7d427e28ee21a2e24f7e2a36f",
    "godot/tools/build_filtered_scene_pack_v128.py": "d18e14c96d49283efacfdc06d42629bb4709b6a51fb4adffa73a341bd74d80dd",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def pinned(path, expected):
    data = path.read_bytes()
    require(sha(data) == expected, f"SHA256 mismatch: {path}")
    return data


def write_new(path, data):
    path = path.resolve()
    require(path.is_relative_to(OUT.resolve()), "Output outside exclusive combined-01 scope")
    require(not path.exists(), f"Refuse to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def json_new(path, data):
    write_new(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())


def pack_entries(path, expected=None):
    data = pinned(path, expected) if expected else path.read_bytes()
    inventory = read_pack(path, verify=True)
    require(inventory["version"] == 4 and struct.unpack_from("<I", data, 20)[0] == 2,
            "Only observed unencrypted relative-base PCK v4")
    return data, {e["path"]: data[e["offset"]:e["offset"] + e["bytes"]] for e in inventory["entries"]}


def logical(blob):
    if blob[:4] != b"RSCC":
        return blob
    mode = struct.unpack_from("<I", blob, 4)[0]
    require(mode in (2, 5), "Only attested stock or filtered resource codecs")
    return decode(blob) if mode == 5 else _unpack(blob)


def compose_bytes(header, entries, gdc, cache):
    require(ENTRY in entries and sha(entries[ENTRY]) == OLD_GDC, "Exact old edge GDC required")
    require(CACHE not in entries, "New cache must not already exist")
    require(sha(gdc) == NEW_GDC and sha(logical(cache)) == CACHE_RAW_SHA, "Exact replacement data")
    values = dict(entries)
    values[ENTRY] = gdc
    values[CACHE] = cache
    result = bytearray(header[:112])
    require(len(result) == 112 and result[:4] == b"GDPC", "Observed header required")
    struct.pack_into("<Q", result, 24, 112)
    directory = []
    for name, value in values.items():
        require(name and not name.startswith("/") and ".." not in name and "\\" not in name, "Safe resource name")
        result.extend(b"\0" * (-len(result) % 16))
        directory.append((name, len(result) - 112, len(value), hashlib.md5(value).digest()))
        result.extend(value)
    result.extend(b"\0" * (-len(result) % 16))
    struct.pack_into("<Q", result, 32, len(result))
    result.extend(struct.pack("<I", len(directory)))
    for name, offset, size, digest in directory:
        path = name.encode() + b"\0"
        path += b"\0" * (-len(path) % 4)
        result.extend(struct.pack("<I", len(path)) + path + struct.pack("<QQ", offset, size) + digest + struct.pack("<I", 0))
    return bytes(result), values


def functions(source):
    matches = list(re.finditer(rb"^(?:static )?func ([A-Za-z_][A-Za-z_0-9]*)\(", source, re.M))
    require(len(matches) == len({m[1] for m in matches}), "Unique function names")
    return {m[1].decode(): source[m.start():matches[i + 1].start() if i + 1 < len(matches) else len(source)]
            for i, m in enumerate(matches)}


def verify_source():
    before = pinned(EDGE / "source/meadow_edge_growth.original.gd", ORIGINAL_SOURCE_SHA)
    after = pinned(EDGE / "source/meadow_edge_growth.lite.gd", LITE_SOURCE_SHA)
    original, candidate = functions(before), functions(after)
    require(original.keys() == candidate.keys(), "Method set unchanged")
    require([key for key in original if original[key] != candidate[key]] == ["_build"], "Only _build changes")
    require(after.replace(candidate["_build"], original["_build"], 1) == before, "All bytes outside _build exact")
    require(candidate["_build"].endswith(original["_build"].split(b"\n", 1)[1]), "Exact original fallback body")
    for directory, source_sha, gdc_sha in (("compile-original", ORIGINAL_SOURCE_SHA, OLD_GDC),
                                         ("compile-candidate", LITE_SOURCE_SHA, NEW_GDC),
                                         ("compile-repeat", LITE_SOURCE_SHA, NEW_GDC)):
        report = json.loads((EDGE / directory / "compilation.json").read_bytes())
        require(report["sourceSha256"] == source_sha and report["outputSha256"] == gdc_sha
                and report["stockCompilerExecutableSha256"] == ENGINE_SHA, "Attested compiler pairing")
        pinned(EDGE / directory / "meadow_edge_growth.gdc", gdc_sha)
    return {"originalSourceSha256": ORIGINAL_SOURCE_SHA, "liteSourceSha256": LITE_SOURCE_SHA,
            "originalGdcSha256": OLD_GDC, "newGdcSha256": NEW_GDC,
            "changedMethods": ["_build"], "allOutsideFunctionBytesExact": True,
            "originalFallbackBodyExact": True, "originalCompileByteExact": True, "candidateCompileRepeatByteExact": True,
            "unchangedFunctions": {key: sha(value) for key, value in original.items() if key != "_build"},
            "compilationThisTask": False}


def compose():
    require(not (OUT / "composition-proof.json").exists(), "Already composed; use --audit-only if needed")
    for path, expected in PINS.items():
        pinned(ROOT / path, expected)
    source_proof = verify_source()
    standard_blob, standard = pack_entries(STANDARD, STANDARD_SHA)
    filtered_blob, filtered = pack_entries(FILTERED, FILTERED_SHA)
    require(len(standard) == 184 and list(standard) == list(filtered), "184 identical ordered source paths")
    manifest = json.loads((EDGE / "edge-growth-replacements.final.json").read_bytes())
    require(manifest["existingEntryReplacement"]["entry"] == ENTRY and manifest["newEntry"]["entry"] == CACHE,
            "Exactly the two manifest entries")
    for name, expected in manifest["dependencySha256"].items():
        require(sha(standard[name]) == expected and sha(filtered[name]) == expected, f"Pinned dependency {name}")
    source_diff = []
    for name in standard:
        if standard[name] == filtered[name]:
            continue
        require(name.startswith("assets/baked/") and name.endswith(".scn"), f"Unexpected source difference: {name}")
        raw = logical(standard[name])
        require(decode(filtered[name]) == raw, f"Source logical equivalence: {name}")
        source_diff.append({"entry": name, "decodedBytes": len(raw), "decodedSha256": sha(raw),
                            "standardSha256": sha(standard[name]), "filteredSha256": sha(filtered[name]),
                            "reencodedThisTask": False})
    require(len(source_diff) == 6, "Exactly six pre-existing filtered resources")
    gdc = pinned(EDGE / "meadow_edge_growth.gdc", NEW_GDC)
    cache = pinned(EDGE / "cache/crown-edge-controller.dense.scn", CACHE_SHA)
    raw = logical(cache)
    require(len(raw) == 2146590 and sha(raw) == CACHE_RAW_SHA, "Exact decoded edge cache")
    print("COMBINED: input pins and six logical resource comparisons PASS; encoding only the new cache", flush=True)
    started = time.perf_counter()
    encoded, modes = encode(raw)
    before_gz = len(gzip.compress(cache, compresslevel=6, mtime=0))
    after_gz = len(gzip.compress(encoded, compresslevel=6, mtime=0))
    selected = after_gz < before_gz
    ship_cache = encoded if selected else cache
    cache_proof = {"entry": CACHE, "standardSha256": CACHE_SHA, "shippingSha256": sha(ship_cache),
                   "decodedSha256": CACHE_RAW_SHA, "decodedBytes": len(raw), "allDecodedBytesExact": decode(encoded) == raw,
                   "standardBytes": len(cache), "encodedBytes": len(encoded), "standardGzip6Bytes": before_gz,
                   "encodedGzip6Bytes": after_gz, "selectedMode5": selected, "filters": modes,
                   "encodeSeconds": time.perf_counter() - started, "onlyResourceEncodedThisTask": True}
    require(cache_proof["allDecodedBytesExact"], "New cache roundtrip exact")
    write_new(OUT / "cache/crown-edge-controller.shipping.scn", ship_cache)
    artifacts = {}
    packed_maps = {}
    for label, filename, header, source, selected_cache, input_sha in (
        ("shipping", "index-lite.pck", filtered_blob, filtered, ship_cache, FILTERED_SHA),
        ("nativeAuditTwin", "native-audit-twin.pck", standard_blob, standard, cache, STANDARD_SHA),
    ):
        blob, expected = compose_bytes(header, source, gdc, selected_cache)
        path = OUT / filename
        write_new(path, blob)
        _, actual = pack_entries(path)
        require(actual == expected and list(actual) == list(expected), "Every output payload and order exact")
        require(len(actual) == 185 and [name for name in source if actual[name] != source[name]] == [ENTRY], "183 old entries exact, one changed, one new")
        packed_maps[label] = actual
        gzip_blob = gzip.compress(blob, compresslevel=6, mtime=0)
        if label == "shipping":
            write_new(path.with_suffix(".pck.gz"), gzip_blob)
        artifacts[label] = {"path": str(path), "sha256": sha(blob), "bytes": len(blob), "gzip6Bytes": len(gzip_blob),
                            "inputPackSha256": input_sha, "entryCount": 185, "unchangedExistingEntries": 183,
                            "changedExistingEntries": [ENTRY], "addedEntries": [CACHE]}
        print(json.dumps({label: artifacts[label]}), flush=True)
    rows = []
    for name, twin_value in packed_maps["nativeAuditTwin"].items():
        ship_value = packed_maps["shipping"][name]
        exact = ship_value == twin_value
        raw_twin = logical(twin_value) if not exact else twin_value
        require(exact or logical(ship_value) == raw_twin, "Combined twins logically equivalent: " + name)
        rows.append({"entry": name, "nativeSha256": sha(twin_value), "shippingSha256": sha(ship_value),
                     "byteExactBetweenTwins": exact, "logicalExactBetweenTwins": True,
                     "logicalSha256IfDifferent": sha(raw_twin) if not exact else None})
    require(pinned(STANDARD, STANDARD_SHA) == standard_blob and pinned(FILTERED, FILTERED_SHA) == filtered_blob, "Frozen inputs unchanged")
    proof = {"schemaVersion": 1, "status": "PASS_COMPOSITION_NATIVE_PENDING", "artifacts": artifacts,
             "sourcePins": PINS, "sourceFunctionProof": source_proof, "cacheEncoding": cache_proof,
             "preservedExistingFilteredResources": source_diff, "entries": rows,
             "all185LogicalEntriesEqualBetweenTwins": True, "all183UntargetedEntriesByteExactPerInput": True,
             "mainSceneGdcUnchangedSha256": sha(standard["scripts/meadow_scene.gdc"]),
             "precisionIntegrated": False, "collisionRepresentationChanged": False, "shaderOrWaterEdits": False,
             "requiresEngineCodec": 5, "nativeAuditPerformed": False, "browserAcceptance": "main-owned pending",
             "composerSha256": sha(Path(__file__).read_bytes())}
    json_new(OUT / "composition-proof.json", proof)
    return proof


def native_audit(proof):
    pinned(ENGINE, ENGINE_SHA)
    runtime = next((OUT / f"runtime-{i:02}" for i in range(1, 10) if not (OUT / f"runtime-{i:02}").exists()), None)
    require(runtime is not None, "Bounded fresh audit attempts exhausted")
    twin = Path(proof["artifacts"]["nativeAuditTwin"]["path"])
    twin_sha = proof["artifacts"]["nativeAuditTwin"]["sha256"]
    pinned(twin, twin_sha)
    original_probe = pinned(PROBE, PROBE_SHA).decode()
    # A mechanically derived new probe: no change to any old checks/comparisons.
    adapted = original_probe.replace('const OUTPUT_ROOT := "E:/Projects/Godot-Octopath2/artifacts/startup-v128/independent/runtime"',
                                      f'const OUTPUT_ROOT := "{runtime.as_posix()}"')
    adapted = adapted.replace(f'const EXPECTED_PACK_SHA := "{STANDARD_SHA}"', f'const EXPECTED_PACK_SHA := "{twin_sha}"')
    require(adapted != original_probe and adapted.count(twin_sha) == 1, "Exact probe target pin substitution")
    hook = "\troot.add_child(scene)\n"
    require(adapted.count(hook) == 1, "Unique post-parent-ready hook")
    adapted = adapted.replace(hook, hook + "\tvar edge_combined := _edge_combined_contract()\n")
    report_hook = '\treport["aoPair"] = ao_pair\n'
    require(adapted.count(report_hook) == 1, "Unique report extension")
    adapted = adapted.replace(report_hook, report_hook + '\treport["edgeCombined"] = edge_combined\n')
    edge_source = pinned(EDGE_PROBE, EDGE_PROBE_SHA)
    borrowed = functions(edge_source)
    adapted += "\n# Exact existing edge fingerprints; added checks, no relaxed comparisons.\n"
    for name in ("_properties", "_stable", "_contract", "_snapshot", "_physical"):
        require(f"func {name}(" not in original_probe, "No helper name collision")
        adapted += borrowed[name].decode() + "\n"
    extra = (OUT / "audit-extension.gd.txt").read_text(encoding="utf-8")
    adapted += extra
    probe_path = runtime / "test_combined_runtime.gd"
    write_new(probe_path, adapted.encode())
    write_new(runtime / "probe.diff", "".join(difflib.unified_diff(original_probe.splitlines(True), adapted.splitlines(True),
              fromfile=PROBE.as_posix(), tofile=probe_path.as_posix())).encode())
    for name in ("_bind_pack", "_inventory", "_compare", "_compare_v127", "_check_ao_pair", "_record_lights", "_sample_route"):
        require(functions(original_probe.encode())[name] == functions(adapted.encode())[name], f"Existing strict probe function exact: {name}")
    env = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        path = runtime / key.lower()
        path.mkdir(exist_ok=False)
        env[key] = str(path)
    output = runtime / "combined.json"
    command = [str(ENGINE), "--headless", "--path", str(runtime), "--main-pack", str(twin),
               "--log-file", str(runtime / "engine.log"), "--script", str(probe_path), "--",
               "--pack-file", str(twin), "--output", str(output), "--baseline", str(ROOT / "artifacts/loading-v115/runtime/original.json")]
    print("COMBINED: starting one full stock-native twin runtime contract (not Web timing)", flush=True)
    started = time.perf_counter()
    result = subprocess.run(command, cwd=runtime, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=120,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    elapsed = time.perf_counter() - started
    log = result.stdout + result.stderr
    write_new(runtime / "process.log", log.encode())
    json_new(runtime / "invocation.json", {"command": command, "seconds": elapsed, "returncode": result.returncode,
             "engineSha256": ENGINE_SHA, "originalProbeSha256": PROBE_SHA, "adaptedProbeSha256": sha(adapted.encode()),
             "edgeProbeSha256": EDGE_PROBE_SHA, "additionalChecksSha256": sha(extra.encode()), "captureKind": "headless_no_render"})
    require(result.returncode == 0 and "SCRIPT ERROR" not in log and "ERROR:" not in log, f"Native runtime failed; see {runtime / 'process.log'}\n" + log[-3500:])
    report = json.loads(output.read_bytes())
    require(report["status"] == "PASS" and report["packBinding"]["matchedLoadedEntries"] == 185, "Full 185-entry mounted pack runtime PASS")
    require(report["comparison"]["status"] == "PASS" and all(report["v127Comparison"]["checks"].values()), "All original and v127 comparisons PASS")
    require(report["edgeCombined"]["snapshotExact"] and report["edgeCombined"]["supportGeometryExact"]
            and report["edgeCombined"]["compiledContractsEqual"], "Combined edge controller contract PASS")
    pinned(twin, twin_sha)
    pinned(FILTERED, FILTERED_SHA)
    pinned(STANDARD, STANDARD_SHA)
    pinned(PROBE, PROBE_SHA)
    final = {"schemaVersion": 1, "status": "PASS_COMBINED_NATIVE_CONTRACT", "shipping": proof["artifacts"]["shipping"],
             "nativeAuditTwin": proof["artifacts"]["nativeAuditTwin"], "compositionProofSha256": sha((OUT / "composition-proof.json").read_bytes()),
             "runtimeReport": str(output), "runtimeReportSha256": sha(output.read_bytes()),
             "all185LogicalEntriesEqualBetweenTwins": True, "oldStrictProbeUnmodified": True,
             "originalChecks": report["comparison"]["checks"], "v127Checks": report["v127Comparison"]["checks"],
             "nodeCount": report["inventory"]["nodeCount"], "colliderCount": report["inventory"]["colliderCount"],
             "colliderSetSha256": report["inventory"]["colliderSetSha256"], "lightPhases": report["lightPhases"],
             "edgeCombined": report["edgeCombined"], "sourceFunctionProof": proof["sourceFunctionProof"],
             "nativeProcessSeconds": elapsed, "browserAcceptance": "not performed; main-owned",
             "limitations": ["Stock-native mode-2 twin, not a mode-5 Web loader or GPU test.",
                 "Only _build source changes; script token offsets may differ elsewhere after compilation.",
                 "Native probe disables automatic physics audits and advances a manual clock; not production startup timing.",
                 "New shipping SHA needs its own main-owned render-contract mapping."]}
    json_new(OUT / "final-proof.json", final)
    print(json.dumps({"status": final["status"], "shipping": final["shipping"], "nativeSeconds": elapsed,
                      "nodes": final["nodeCount"], "colliders": final["colliderCount"], "finalProof": str(OUT / "final-proof.json")}), flush=True)


class FocusedTests(unittest.TestCase):
    def test_one_function_attestation(self):
        self.assertEqual(verify_source()["changedMethods"], ["_build"])

    def test_future_pack_pin_rejected(self):
        with self.assertRaises(ValueError):
            pinned(EDGE / "meadow_edge_growth.gdc", "0" * 64)

    def test_unknown_controller_and_existing_cache_rejected(self):
        gdc = pinned(EDGE / "meadow_edge_growth.gdc", NEW_GDC)
        cache = pinned(EDGE / "cache/crown-edge-controller.dense.scn", CACHE_SHA)
        with self.assertRaises(ValueError):
            compose_bytes(b"GDPC", {ENTRY: b"unknown"}, gdc, cache)
        original = pinned(EDGE / "compile-original/meadow_edge_growth.gdc", OLD_GDC)
        with self.assertRaises(ValueError):
            compose_bytes(b"GDPC", {ENTRY: original, CACHE: cache}, gdc, cache)

    def test_exact_cache_logical_pin(self):
        raw = logical(pinned(EDGE / "cache/crown-edge-controller.dense.scn", CACHE_SHA))
        self.assertEqual((len(raw), sha(raw)), (2146590, CACHE_RAW_SHA))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        unittest.main(argv=[__file__])
    else:
        proof = json.loads((OUT / "composition-proof.json").read_bytes()) if args.audit_only else compose()
        if args.audit or args.audit_only:
            native_audit(proof)
