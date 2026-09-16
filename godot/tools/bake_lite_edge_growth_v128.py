"""Bake ONLY meadow_edge_growth._build for frozen v127 lite, in new artifacts.

Uses the attested stock-4.7.2 source/GDC pair, recompiles only a tiny script
project, and preserves every byte outside one source function. No full export.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time

import brotli

from inspect_web_pack import read_pack
from repack_web_cache import _pack, _unpack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v128/edge-growth"
BASE = ROOT / "artifacts/v127/index-lite.pck"
BASE_SHA = "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"
SOURCE = ROOT / "godot/scripts/meadow_edge_growth.gd"
SOURCE_SHA = "33f445246f5d23c338a22407207d0dc498469fd19ee8067f402adabf3090337e"
GDC_SHA = "d9c169719a93563757b636c96eeba758c12e3e9f9047adc46308d312601b3e13"
GODOT = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe"
ENGINE_SHA = "ab1824f85bfd8e0e4128182c000c4003a3e042245b2967848d089b2a04b22424"
ENTRY = "scripts/meadow_edge_growth.gdc"
CACHE_ENTRY = "assets/baked/lite-v128/crown-edge-controller.scn"
METHOD = "_build"
SUPPORT = [dict(resource="res://assets/baked/v77/terrain.scn", node="ContinuousMeadow"),
           dict(resource="res://assets/baked/v77/detail.scn", node="SolidLimestoneGeology")]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def scoped(path):
    resolved = Path(path).resolve()
    require(SCOPE.resolve() == SCOPE and resolved.is_relative_to(SCOPE) and resolved != SCOPE, "Edge-growth artifact scope")
    return resolved


def write(path, data):
    path = scoped(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(data)
    require(path.read_bytes() == data, "Artifact readback")
    return path


def write_json(path, value):
    return write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def entries(path):
    blob = Path(path).read_bytes()
    inventory = read_pack(Path(path), verify=True)
    return {row["path"]: blob[row["offset"]:row["offset"] + row["bytes"]] for row in inventory["entries"]}


def functions(source):
    matches = list(re.finditer(rb"^(?:static )?func ([A-Za-z_][A-Za-z_0-9]*)\(", source, re.M))
    require(len(matches) == len({m[1] for m in matches}), "Unique function declarations")
    return {match[1].decode(): source[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(source)]
            for i, match in enumerate(matches)}


def patched_source(source):
    before = functions(source)
    original = before[METHOD]
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    header, body = original.split(newline, 1)
    require(header == b"func _build() -> void:", "Pinned function signature")
    prefix = '''	# Offline exact fringe + branchlets, restored synchronously on parent-ready.
	# Copy mutable mesh/material resources so repeated scene instances remain independent.
	var edge_cache_path := "res://%s"
	if ResourceLoader.exists(edge_cache_path):
		var edge_restore_started := Time.get_ticks_msec()
		var edge_cache := load(edge_cache_path) as PackedScene
		if edge_cache != null and edge_cache.get_meta("edge_growth_schema", "") == "edge-controller-v128-1" \\
				and edge_cache.get_meta("source_sha256", "") == "%s":
			var edge_root := edge_cache.instantiate()
			var edge_children := edge_root.get_children()
			if edge_children.size() == 2 and edge_children[0].name == &"CrownToTurfFringe" \\
					and edge_children[1].name == &"CrownTransitionBranchlets":
				for edge_child: MeshInstance3D in edge_children:
					edge_root.remove_child(edge_child)
					edge_child.owner = null
					edge_child.mesh = edge_child.mesh.duplicate(false)
					edge_child.material_override = edge_child.material_override.duplicate(false)
					edge_child.set_meta("build_ms", Time.get_ticks_msec() - edge_restore_started)
					add_child(edge_child)
				edge_root.free()
				land = null
				rocks = null
				ready_complete = true
				print("MEADOW_EDGE_GROWTH_CACHE: exact fringe and branchlets restored; ready_complete=true; restore_ms=", Time.get_ticks_msec() - edge_restore_started)
				return
			edge_root.free()
	# Preserve the exact generator for a missing/stale cache. No delayed construction.
''' % (CACHE_ENTRY, SOURCE_SHA)
    replacement = header + newline + prefix.replace("\n", newline.decode()).encode() + body
    candidate = source.replace(original, replacement, 1)
    require(candidate.replace(replacement, original, 1) == source, "All bytes outside target function exact")
    after = functions(candidate)
    require(before.keys() == after.keys() and all(after[key] == value for key, value in before.items() if key != METHOD),
            "All other methods, including static geometry/AO/physics/animation, exact")
    return candidate, dict(changedMethods=[METHOD], allOutsideFunctionBytesExact=True, originalFallbackBodyExact=True,
                           originalFunctionSha256=sha(original), patchedFunctionSha256=sha(replacement),
                           unchangedFunctionSha256={key: sha(value) for key, value in before.items() if key != METHOD})


def runtime(output):
    directory = scoped(output / "compiler-runtime")
    require(not directory.exists(), "Fresh private compiler runtime")
    for name in (GODOT.name, "Godot_v4.7.2-stable_win64.exe"):
        data = (GODOT.parent / name).read_bytes()
        if name.endswith("win64.exe"):
            require(sha(data) == ENGINE_SHA, "Attested stock Godot executable")
        write(directory / name, data)
    write(directory / "_sc_", b"")
    write(directory / "editor_data/editor_settings-4.7.tres", b'[gd_resource type="EditorSettings" format=3]\n[resource]\nnetwork/language_server/remote_host="192.0.2.1"\nnetwork/debug_adapter/remote_host="192.0.2.1"\nnetwork/debug/remote_host="192.0.2.1"\nnetwork/debug_adapter/enabled=false\n')
    return directory / GODOT.name


def sandbox(directory):
    directory = scoped(directory)
    require(not directory.exists(), "Fresh native stage")
    project = directory / "project"
    write(project / "project.godot", b'config_version=5\n[application]\nconfig/name="OfflineLiteEdgeGrowth"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[shader_globals]\nmeadow_clock={"type":"float","value":0.0}\nmeadow_night={"type":"float","value":0.0}\n')
    env = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        path = directory / key.lower()
        path.mkdir()
        env[key] = str(path)
    return project, env


def process(command, directory, env, native=False):
    print(f"EDGE_STAGE {directory.name}", flush=True)
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    log = result.stdout + result.stderr
    write(directory / "process.log", log.encode())
    require("language server started" not in log and "Debug Adapter started" not in log, "No editor listeners")
    require(result.returncode == 0, f"Native process failed: {log[-4500:]}")
    if native:
        require("EDGE_GROWTH_V128: PASS" in log and "ERROR:" not in log and "SCRIPT ERROR" not in log,
                f"Bounded function verification failed: {log[-4500:]}")
    return time.perf_counter() - started


def compile_single(directory, executable, source):
    project, env = sandbox(directory)
    write(project / "scripts/meadow_edge_growth.gd", source)
    write(project / "export_presets.cfg", b'[preset.0]\nname="ScriptOnly"\nplatform="Web"\nrunnable=false\nexport_filter="all_resources"\ninclude_filter=""\nexclude_filter=""\nscript_export_mode=2\n[preset.0.options]\nvariant/thread_support=false\nvariant/extensions_support=false\nhtml/export_icon=false\n')
    target = directory / "script-only.pck"
    command = [str(executable), "--headless", "--recovery-mode", "--path", str(project), "--log-file", str(directory / "engine.log"),
               "--export-pack", "ScriptOnly", str(target)]
    elapsed = process(command, directory, env)
    emitted = entries(target)
    require(ENTRY in emitted and len(emitted) <= 12 and sum(map(len, emitted.values())) < 2_000_000, "Tiny script-only tokenizer output")
    gdc = emitted[ENTRY]
    require(gdc[:4] == b"GDSC", "Stock GDScript binary tokens")
    write(directory / "meadow_edge_growth.gdc", gdc)
    write_json(directory / "compilation.json", dict(sourceSha256=sha(source), outputSha256=sha(gdc), outputBytes=len(gdc),
               privateExportEntries={key: {"bytes": len(value), "sha256": sha(value)} for key, value in emitted.items()},
               stockCompilerExecutableSha256=ENGINE_SHA, seconds=elapsed,
               note="Tokenization only; full dependency/type/runtime validation is a separate native stage."))
    return gdc


def native(directory, executable, request):
    project, env = sandbox(directory)
    request = dict(request, output=str(directory), pack=str(BASE), original_gdc_sha256=GDC_SHA,
                   cache_resource="res://" + CACHE_ENTRY, support=SUPPORT, source_sha256=SOURCE_SHA)
    request_path = write_json(directory / "request.json", request)
    command = [str(executable), "--headless", "--path", str(project), "--script", str(Path(__file__).with_suffix(".gd")),
               "--log-file", str(directory / "engine.log"), "--", str(request_path)]
    elapsed = process(command, directory, env, native=True)
    result = json.loads((directory / "result.json").read_text())
    require(result["failures"] == 0, "No native fidelity failures")
    result["stageSeconds"] = elapsed
    return result


def compose(source, source_entries, gdc, cache, destination):
    """Existing PCK reader/layout, plus the one explicitly pinned new asset."""
    require(CACHE_ENTRY not in source_entries and len(source_entries) == 184, "Exactly one new cache entry")
    require(sha(source_entries[ENTRY]) == GDC_SHA, "Only pinned edge-controller GDC replacement")
    inventory = read_pack(BASE, verify=True)
    require(inventory["version"] == 4, "Observed standalone v4 layout")
    selected = dict(source_entries)
    selected[ENTRY] = gdc
    selected[CACHE_ENTRY] = cache
    header = bytearray(source[:112])
    struct.pack_into("<Q", header, 24, 112)
    result = bytearray(header)
    table = []
    for name, blob in selected.items():
        result.extend(b"\0" * (-len(result) % 16))
        table.append((name, len(result) - 112, len(blob), hashlib.md5(blob).digest()))
        result.extend(blob)
    result.extend(b"\0" * (-len(result) % 16))
    directory_offset = len(result)
    result.extend(struct.pack("<I", len(table)))
    for name, offset, size, digest in table:
        path = name.encode()
        path += b"\0" * (-len(path) % 4)
        result.extend(struct.pack("<I", len(path)) + path + struct.pack("<QQ", offset, size) + digest + struct.pack("<I", 0))
    struct.pack_into("<Q", result, 32, directory_offset)
    if destination.exists():
        require(destination.read_bytes() == result, "Exact incomplete-candidate recovery only")
    else:
        write(destination, result)
    actual = entries(destination)
    require(actual == selected, "All 185 final entry bytes independently read back")
    require(list(actual) == list(source_entries) + [CACHE_ENTRY], "Old resource order exact; cache appended")
    return bytes(result)


def dense_cache(output, cache_path):
    """One fixed, lossless container pass on the NEW cache only."""
    before = cache_path.read_bytes()
    raw = _unpack(before)
    after = _pack(raw, 1048576, 19)
    require(_unpack(after) == raw, "Every decoded cache byte exact after lossless packing")
    require(len(after) < len(before), "Dense new-cache pass must reduce stored bytes")
    path = scoped(output / "cache/crown-edge-controller.dense.scn")
    if path.exists():
        require(path.read_bytes() == after, "Exact incomplete dense-cache recovery only")
    else:
        write(path, after)
    return path, dict(beforeBytes=len(before), afterBytes=len(after), allDecodedBytesExact=True,
                      decodedBytes=len(raw), decodedSha256=sha(raw), blockBytes=1048576, zstdLevel=19)


def build(output):
    output = scoped(output)
    require(not output.exists(), "New candidate directory only")
    source = SOURCE.read_bytes()
    packed = BASE.read_bytes()
    require(sha(source) == SOURCE_SHA and sha(packed) == BASE_SHA, "Attested frozen v127 source/pack")
    packed_entries = entries(BASE)
    require(sha(packed_entries[ENTRY]) == GDC_SHA, "Actual shipped .gdc matches attested source compilation")
    patched, source_proof = patched_source(source)
    write(output / "source/meadow_edge_growth.original.gd", source)
    write(output / "source/meadow_edge_growth.lite.gd", patched)
    original_gdc = write(output / "source/meadow_edge_growth.original.gdc", packed_entries[ENTRY])
    write_json(output / "source-contract.json", source_proof)
    write(output / "one-function.diff", "".join(difflib.unified_diff(source.decode().splitlines(keepends=True), patched.decode().splitlines(keepends=True),
          fromfile="v127/scripts/meadow_edge_growth.gd", tofile="edge-cache-lite/scripts/meadow_edge_growth.gd")).encode())
    executable = runtime(output)
    cache_path = scoped(output / "cache/crown-edge-controller.scn")
    cache_path.parent.mkdir()
    bake = native(output / "bake", executable, dict(mode="bake", original_gdc=str(original_gdc),
                  cache_output=str(cache_path)))
    print(json.dumps({"bake": bake["bake"]["nativeCacheRoundtripExact"], "cacheBytes": bake["bake"]["cacheBytes"],
                      "originalLifecycleUsec": bake["bake"]["originalLifecycleUsec"]}), flush=True)
    cache_path, cache_compression = dense_cache(output, cache_path)
    baseline = compile_single(output / "compile-original", executable, source)
    require(baseline == packed_entries[ENTRY], "Current stock compiler exactly reproduces v127 GDC")
    candidate = compile_single(output / "compile-candidate", executable, patched)
    repeat = compile_single(output / "compile-repeat", executable, patched)
    require(candidate == repeat, "Two independent candidate compiles byte-exact")
    candidate_gdc = write(output / "meadow_edge_growth.gdc", candidate)
    validation_args = dict(mode="verify", original_gdc=str(original_gdc), patched_gdc=str(candidate_gdc), patched_gdc_sha256=sha(candidate))
    fallback = native(output / "verify-missing-cache", executable, validation_args)
    require(not fallback["cachePresent"], "Missing-cache fallback actually exercised")
    destination = output / "index-lite-edge-growth-candidate.pck"
    candidate_pack = compose(packed, packed_entries, candidate, cache_path.read_bytes(), destination)
    verified = native(output / "verify-cache", executable, dict(validation_args, candidate_pack=str(destination)))
    require(verified["cachePresent"], "Actual newly packed cache available")
    warm_verified = native(output / "verify-cache-warm-extended", executable,
                           dict(validation_args, candidate_pack=str(destination), warm_support=True, extended=True))
    gzip_before = gzip.compress(packed, compresslevel=6, mtime=0)
    gzip_after = gzip.compress(candidate_pack, compresslevel=6, mtime=0)
    br_before = brotli.compress(packed, quality=6)
    br_after = brotli.compress(candidate_pack, quality=6)
    write(destination.with_suffix(".pck.gz"), gzip_after)
    write(destination.with_suffix(".pck.br"), br_after)
    require(BASE.read_bytes() == packed and SOURCE.read_bytes() == source, "Frozen pack/source unchanged")
    proof = dict(basePack=str(BASE), baseSha256=BASE_SHA, sourcePath=str(SOURCE), sourceSha256=SOURCE_SHA,
                 baselineGdcSha256=GDC_SHA, originalCompileReproducedShippedGdc=True, candidateCompileDeterministic=True,
                 changedSourceMethods=[METHOD], sourceContract=str(output / "source-contract.json"),
                 candidatePack=str(destination), candidatePackSha256=sha(candidate_pack),
                 beforeRawBytes=len(packed), afterRawBytes=len(candidate_pack), beforeGzip6Bytes=len(gzip_before), afterGzip6Bytes=len(gzip_after),
                 beforeBrotli6Bytes=len(br_before), afterBrotli6Bytes=len(br_after),
                 originalEntries=184, candidateEntries=185, existingEntriesExact=183, addedEntries=[CACHE_ENTRY], changedEntries=[ENTRY],
                 collidersRenderCachesTexturesWaterShadersAllByteExact=True,
                 bake=bake, missingCacheValidation=fallback, cacheValidation=verified,
                 cacheCompression=cache_compression, warmCacheValidation=warm_verified,
                 nativeScope="Real edge-controller ready lifecycle on isolated two-support-mesh main subclass with _ready overridden and processing disabled; no full scene/main build/AO/physics/wildlife.",
                 diagnosticException="Only metadata/build_ms is excluded from exact comparisons; key remains and reports actual restore duration, not historic bake time.",
                 status="offline-validated-candidate-for-main-integration-not-browser-approved")
    write_json(output / "proof.json", proof)
    manifest = dict(schema="lite-edge-growth-replacements-v128-1", status=proof["status"], inputPackSha256=BASE_SHA,
                    proof=str(output / "proof.json"), existingEntryReplacement={"entry": ENTRY, "originalSha256": GDC_SHA,
                    "path": str(candidate_gdc), "sha256": sha(candidate), "bytes": len(candidate)},
                    newEntry={"entry": CACHE_ENTRY, "mustNotExist": True, "path": str(cache_path), "sha256": sha(cache_path.read_bytes()), "bytes": cache_path.stat().st_size},
                    supportGeometry=bake["supportGeometry"],
                    dependencySha256={key: sha(value) for key, value in packed_entries.items() if key.startswith("scripts/") or key.startswith("shaders/")},
                    composition="Merge exactly this controller script replacement plus one cache. Main-script GDC stays exact. Require identical decoded terrain/rock positions+indices (recorded supportGeometry); AO color-only and other leaf changes do not change those supports. Never replace concurrent render/AO scene entries with this standalone PCK.",
                    shaderFeatureContract="Pack SHA changes; main must prove/reissue any exact-hash render contract. No original/balanced changes.")
    write_json(output / "edge-growth-replacements.json", manifest)
    print(json.dumps({key: proof[key] for key in ("candidatePack", "afterRawBytes", "afterGzip6Bytes", "afterBrotli6Bytes", "existingEntriesExact", "status")}), flush=True)


def finalize_existing(output):
    """Finish the existing controller-01 candidate without rebaking/recompiling."""
    output = scoped(output)
    before_proof = json.loads((output / "proof.json").read_text())
    source = BASE.read_bytes()
    require(sha(source) == BASE_SHA and before_proof["baseSha256"] == BASE_SHA, "Frozen actual baseline")
    source_entries = entries(BASE)
    require(sha(source_entries[ENTRY]) == GDC_SHA, "Controller source pin")
    candidate_gdc = output / "meadow_edge_growth.gdc"
    candidate = candidate_gdc.read_bytes()
    for label in ("compile-candidate", "compile-repeat"):
        require((output / label / "meadow_edge_growth.gdc").read_bytes() == candidate, "Exact prior deterministic stock output")
    require((output / "compile-original/meadow_edge_growth.gdc").read_bytes() == source_entries[ENTRY], "Exact baseline compile")
    cache_path, compression = dense_cache(output, output / "cache/crown-edge-controller.scn")
    destination = output / "index-lite-edge-growth-final-candidate.pck"
    packed = compose(source, source_entries, candidate, cache_path.read_bytes(), destination)
    executable = output / "compiler-runtime" / GODOT.name
    validation_path = output / "verify-final-warm-extended"
    for attempt in range(1, 4):
        if not validation_path.exists():
            break
        validation_path = output / f"verify-final-warm-extended-{attempt + 1:02d}"
    require(not validation_path.exists(), "Bounded final validation retry limit")
    validation = native(validation_path, executable, dict(
        mode="verify", original_gdc=str(output / "source/meadow_edge_growth.original.gdc"),
        patched_gdc=str(candidate_gdc), patched_gdc_sha256=sha(candidate), candidate_pack=str(destination),
        warm_support=True, extended=True))
    require(validation["cachePresent"] and validation["extended"]["validCacheSurfaceCalls"] == 0, "Real cache path validated")
    gzip_after = gzip.compress(packed, compresslevel=6, mtime=0)
    br_after = brotli.compress(packed, quality=6)
    write(destination.with_suffix(".pck.gz"), gzip_after)
    write(destination.with_suffix(".pck.br"), br_after)
    proof = dict(baseSha256=BASE_SHA, candidatePack=str(destination), candidatePackSha256=sha(packed),
                 beforeRawBytes=len(source), afterRawBytes=len(packed), beforeGzip6Bytes=before_proof["beforeGzip6Bytes"],
                 afterGzip6Bytes=len(gzip_after), beforeBrotli6Bytes=before_proof["beforeBrotli6Bytes"], afterBrotli6Bytes=len(br_after),
                 inheritedCompilationAndOriginalCacheProof=str(output / "proof.json"), cacheCompression=compression,
                 validation=validation, existingEntriesExact=183, newEntries=1,
                 onlyExistingReplacement=ENTRY, mainSceneGdcAllCollidersAndOtherExistingEntriesExact=True,
                 status="offline-validated-candidate-for-main-integration-not-browser-approved")
    write_json(output / "final-proof.json", proof)
    manifest = json.loads((output / "edge-growth-replacements.json").read_text())
    manifest["schema"] = "lite-edge-growth-replacements-v128-2"
    manifest["proof"] = str(output / "final-proof.json")
    manifest["newEntry"] = dict(entry=CACHE_ENTRY, mustNotExist=True, path=str(cache_path), sha256=sha(cache_path.read_bytes()), bytes=cache_path.stat().st_size)
    manifest["candidatePack"] = dict(path=str(destination), sha256=sha(packed))
    manifest["supersedes"] = str(output / "edge-growth-replacements.json")
    write_json(output / "edge-growth-replacements.final.json", manifest)
    require(BASE.read_bytes() == source, "Frozen source PCK remains exact")
    print(json.dumps({key: proof[key] for key in ("candidatePack", "afterRawBytes", "afterGzip6Bytes", "afterBrotli6Bytes", "status")}), flush=True)


def self_test():
    import unittest

    class EdgeTests(unittest.TestCase):
        def test_pinned_source_and_one_function_only(self):
            source = SOURCE.read_bytes()
            self.assertEqual(sha(source), SOURCE_SHA)
            candidate, proof = patched_source(source)
            self.assertEqual(proof["changedMethods"], [METHOD])
            old, new = functions(source), functions(candidate)
            self.assertEqual(old.keys(), new.keys())
            for name in old:
                if name != METHOD:
                    self.assertEqual(old[name], new[name], name)

        def test_exact_original_fallback_no_random_changes(self):
            source = SOURCE.read_bytes()
            candidate, _ = patched_source(source)
            before, after = functions(source)[METHOD], functions(candidate)[METHOD]
            self.assertTrue(after.endswith(before.split(b"\n", 1)[1]))
            for guard in (b"ResourceLoader.exists", b"source_sha256", b"edge_root.free()", b"ready_complete = true"):
                self.assertIn(guard, after)

        def test_ready_metadata_and_instance_independence(self):
            candidate, _ = patched_source(SOURCE.read_bytes())
            method = functions(candidate)[METHOD]
            for token in (b'edge_child.set_meta("build_ms"', b"land = null", b"rocks = null", b"ready_complete = true",
                          b"edge_child.owner = null", b"edge_child.mesh.duplicate(false)", b"edge_child.material_override.duplicate(false)"):
                self.assertIn(token, method)

        def test_scope_and_duplicate_function_guard(self):
            for path in (ROOT, SCOPE, ROOT / "godot/scripts/meadow_edge_growth.gd"):
                with self.assertRaises(ValueError):
                    scoped(path)
            with self.assertRaises(ValueError):
                functions(b"func a():\n pass\nfunc a():\n pass\n")

    return unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EdgeTests)).wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SCOPE / "controller-01")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--finalize-existing", action="store_true", help="Finish existing controller-01 without another bake or compile")
    arguments = parser.parse_args()
    if arguments.self_test:
        raise SystemExit(0 if self_test() else 1)
    if arguments.finalize_existing:
        finalize_existing(arguments.output)
    else:
        build(arguments.output)
