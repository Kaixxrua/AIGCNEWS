"""Add exactly one CPU memoization target, without changing main/controller.

Requires the single actual09 profile capture. Emits a superset support manifest,
an explicit main-owner hook proposal and one native bounded exactness audit.
"""
from pathlib import Path
import argparse
import difflib
import gzip
import json
import os
import subprocess
import sys
import time
import unittest

sys.dont_write_bytecode = True
import build_progressive_support_v135 as support
from build_progressive_web_v135 import pack

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/startup-v135/root-conform/candidate-01"
OLD = ROOT / "artifacts/startup-v135/static-cache/candidate-01"
PROFILE = ROOT / "artifacts/startup-v135/static-cache/remaining-profile-01"
CORE = ROOT / "artifacts/startup-v135/build/candidate-09/native/index-lite.pck"
MAIN = CORE.parents[1] / "meadow_scene.progressive.gd"
HELPER = "scripts/meadow_root_conform_cache.gd"
RESOURCE = "progressive/root-conform/meshes.res"
RUNTIME = "progressive/root-conform/manifest.json"
ENGINE = OLD / "compiler-runtime/Godot_v4.7.2-stable_win64.exe"
ANCHOR = "func _conform_root_line(instance: MeshInstance3D, follow_whole_column: bool = false) -> void:\n"
INSERT = '\tif preload("res://scripts/meadow_root_conform_cache.gd").restore(self, instance, follow_whole_column):\n\t\treturn\n'


def sha(data):
    return support.sha(data)


def pin(path):
    path = Path(path)
    return {"path": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}


def write(path, data):
    path = Path(path).resolve()
    assert path.is_relative_to(OUT) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path, value):
    write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def proposed_hook(data):
    nl = b"\r\n" if b"\r\n" in data else b"\n"
    anchor, insert = ANCHOR.encode().replace(b"\n", nl), INSERT.encode().replace(b"\n", nl)
    assert data.count(anchor) == 1 and insert not in data
    patched = data.replace(anchor, anchor + insert, 1)
    assert patched.replace(anchor + insert, anchor, 1) == data
    return patched


def build():
    assert not OUT.exists(), "New candidate only; earlier artifacts remain immutable"
    assert sha(CORE.read_bytes()) == "9472167e7e416eca07e9a217eba189b1ddeecb149faa86b121f9c0a097fe3e93"
    assert sha(MAIN.read_bytes()) == "a29aef468e6f0b5e333577ef2b4e34db06632c767ada9454ce08e2ca03f1b30d"
    assert sha((OLD / "manifest.json").read_bytes()) == "3aa2ebaf950b371b97b291b31668c6d047cf89ea4ea091996cc51361112a06f0"
    profile = json.loads((PROFILE / "profile.json").read_bytes())
    assert profile["status"] == "PASS_ONE_NATIVE_PROFILE" and profile["rootMeshCount"] == 50
    assert len(profile["cache"]["hits"]) == 17 and not profile["cache"]["misses"]
    core = support.entries(CORE)
    original = support.entries(support.BASE)
    old_manifest = json.loads((OLD / "manifest.json").read_bytes())
    for entry in old_manifest["entries"]:
        assert sha(core[entry["entry"]]) == entry["sha256"] == sha(Path(entry["path"]).read_bytes())
    source = (ROOT / "godot" / HELPER).read_bytes()
    support.OUT = OUT
    compiled = support.compile_batch("helper-compile", {HELPER: source}, ENGINE)
    additions = {entry: compiled[entry] for entry in (HELPER[:-3] + ".gdc", HELPER + ".remap")}
    additions[RESOURCE] = (PROFILE / "root-results.res").read_bytes()
    additions[RUNTIME] = (json.dumps({"version": 1, "count": 50, "resource": "res://" + RESOURCE,
        "sha256": sha(additions[RESOURCE]), "mainDependencyManifest": "res://progressive/static-cache/manifest.json",
        "captureSourceCoreSha256": sha(CORE.read_bytes()), "captureMainGdcSha256": sha(core["scripts/meadow_scene.gdc"])},
        indent=2) + "\n").encode()
    assert not (additions.keys() & core.keys()), "Only four new entries"
    rows = list(old_manifest["entries"])
    for entry, data in additions.items():
        output = OUT / "entries" / entry
        write(output, data)
        rows.append({"entry": entry, "path": output.as_posix(), "sha256": sha(data),
            "bytes": len(data), "beforeSha256": sha(original[entry]) if entry in original else None})
    added_pack = pack(CORE.read_bytes()[:112], {**core, **additions})
    delta_raw = len(added_pack) - CORE.stat().st_size
    delta_gzip = len(gzip.compress(added_pack, compresslevel=9, mtime=0)) - len(gzip.compress(CORE.read_bytes(), compresslevel=9, mtime=0))
    assert delta_raw <= 150_000, (delta_raw, "Raw incremental PCK cap, not merely compressed")
    write(OUT / "test-only-additions.pck", pack(CORE.read_bytes()[:112], additions))
    assert support.entries(OUT / "test-only-additions.pck") == additions
    old_source = MAIN.read_bytes()
    suggested = proposed_hook(old_source)
    write(OUT / "main-hook.diff", ''.join(difflib.unified_diff(old_source.decode().splitlines(True),
        suggested.decode().splitlines(True), fromfile="private/meadow_scene.progressive.gd", tofile="proposed/private/meadow_scene.progressive.gd")).encode())
    write_json(OUT / "main-hook.json", {"source": pin(MAIN), "anchor": ANCHOR, "insertAfter": INSERT,
        "roundtripExact": True, "notAppliedByThisBuilder": True,
        "requiredPostCompileRepin": {"entry": "progressive/static-cache/manifest.json",
            "field": "dependencies.res://scripts/meadow_scene.gdc", "value": "SHA256 of the ACTUAL newly compiled main GDC; never a guessed hash"},
        "note": "Keep all other dependency pins/17 records exact. This helper shares that validated main dependency; no second main pin is needed."})
    manifest = {**old_manifest, "schema": "progressive-root-conform-cache-overlay-v1", "entries": rows,
        "sourceCoreSha256": sha(CORE.read_bytes()), "supersetOfStaticManifest": pin(OLD / "manifest.json"),
        "mainHook": pin(OUT / "main-hook.json"), "nativeProfile": pin(PROFILE / "profile.json"),
        "runtimeValidation": "PENDING bounded actual09 plus inherited hook audit; final integrated new main remains main-owner test",
        "incrementalSizes": {"newEntryBytes": sum(map(len, additions.values())), "rawNativeCorePckBytes": delta_raw,
            "gzip9NativeCorePckBytes": delta_gzip, "rawBudgetBytes": 150000, "excludesPendingMainGdcHookDelta": True},
        "notes": ["44 existing entries byte-identical; 4 additive entries; no existing GDC changed.",
            "Main/controller are not included in this manifest. Apply proposed private main hook and exact post-compile dependency repin before integration.",
            "Only _conform_root_line cached; no terrain, water, weather, shadows, ready or runtime actor logic changed."]}
    write_json(OUT / "manifest.json", manifest)
    write_json(OUT / "provenance.json", {"sourceCore": pin(CORE), "profile": pin(PROFILE / "profile.json"),
        "profileSourceProof": pin(PROFILE / "source-proof.json"), "captureResource": pin(PROFILE / "root-results.res"),
        "helperSource": pin(ROOT / "godot" / HELPER), "helperCompiled": pin(OUT / "entries" / (HELPER[:-3] + ".gdc")),
        "priorExactCompilerProof": old_manifest["baselineCompilerProof"], "priorSupportCompilerProof": old_manifest["supportCompilerProof"],
        "preservedEntryPins": [{"entry": e["entry"], "sha256": e["sha256"]} for e in old_manifest["entries"]]})
    print(json.dumps({"manifest": pin(OUT / "manifest.json"), "sizes": manifest["incrementalSizes"]}, indent=2), flush=True)


def audit(label="native-audit-02"):
    assert label.startswith("native-audit-") and label.replace("-", "").isalnum()
    stage = OUT / label
    assert not stage.exists(), "One new bounded native validation"
    stage.mkdir()
    derived = '''extends "res://scripts/meadow_scene.gd"
var root_before: Dictionary = {}
var cache_usec: int = 0
func _conform_root_line(instance: MeshInstance3D, follow_whole_column: bool = false) -> void:
\troot_before[str(instance.name)] = {"quad": instance.mesh, "whole": follow_whole_column,
\t\t"nodeId": instance.get_instance_id(), "materialId": instance.material_override.get_instance_id(),
\t\t"transform": instance.transform, "metadata": _root_metadata(instance), "children": instance.get_children()}
\tvar started := Time.get_ticks_usec()
\tif preload("res://scripts/meadow_root_conform_cache.gd").restore(self, instance, follow_whole_column):
\t\tcache_usec += Time.get_ticks_usec() - started
\t\tvar before: Dictionary = root_before[str(instance.name)]
\t\tassert(instance.get_instance_id() == before.nodeId and instance.material_override.get_instance_id() == before.materialId)
\t\tassert(instance.transform == before.transform and _root_metadata(instance) == before.metadata and instance.get_children() == before.children)
\t\treturn
\tassert(false, "Expected exact fixed-scene cache hit")
\tsuper._conform_root_line(instance, follow_whole_column)

func _root_metadata(node: Node) -> Dictionary:
\tvar values := {}
\tfor key: StringName in node.get_meta_list():
\t\tvalues[str(key)] = node.get_meta(key)
\treturn values

func root_reference(node: MeshInstance3D) -> Mesh:
\tvar cached := node.mesh
\tvar before: Dictionary = root_before[str(node.name)]
\tnode.mesh = before.quad
\tsuper._conform_root_line(node, before.whole)
\tvar original := node.mesh
\tnode.mesh = cached
\treturn original
'''
    write(stage / "audit-main.gd", derived.encode())
    request = {"core": CORE.as_posix(), "derived": (stage / "audit-main.gd").as_posix(),
        "overlay": pin(OUT / "test-only-additions.pck"), "report": (stage / "validation.json").as_posix(),
        "baselineMainSha256": "1f35a8946ffd947565b4e71728c2f5e0569e6d0206e9fb9ab4c49e2a08ea712a"}
    write_json(stage / "request.json", request)
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = stage / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    runtime = stage / "runtime"
    runtime.mkdir()
    command = [str(ENGINE), "--headless", "--path", str(runtime), "--main-pack", str(CORE),
        "--log-file", str(stage / "engine.log"), "--script", str(ROOT / "godot/tools/audit_root_conform_cache_v135.gd"),
        "--", str(stage / "request.json")]
    started = time.monotonic()
    result = subprocess.run(command, env=env, capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    log = result.stdout + result.stderr
    write(stage / "process.log", log)
    write_json(stage / "invocation.json", {"command": command, "exitCode": result.returncode,
        "wallSeconds": time.monotonic() - started, "engine": pin(ENGINE)})
    assert result.returncode == 0 and b"SCRIPT ERROR" not in log and b"Parse Error" not in log, log[-6000:].decode(errors="replace")
    report = json.loads((stage / "validation.json").read_bytes())
    assert report["status"] == "PASS_ROOT_CONFORM_CACHE_50_EXACT_NATIVE"
    assert sha(CORE.read_bytes()) == "9472167e7e416eca07e9a217eba189b1ddeecb149faa86b121f9c0a097fe3e93"
    print(json.dumps({"report": pin(stage / "validation.json"), "readyMs": report["readyMs"],
        "cacheRestoreMs": report["cacheRestoreMs"], "hits": len(report["records"]), "oldHits": report["oldCacheHits"]}, indent=2))


def seal():
    manifest = json.loads((OUT / "manifest.json").read_bytes())
    report = json.loads((OUT / "native-audit-02/validation.json").read_bytes())
    assert report["status"] == "PASS_ROOT_CONFORM_CACHE_50_EXACT_NATIVE"
    assert len(manifest["entries"]) == 48 and len(report["records"]) == 50 and report["oldCacheHits"] == 17
    for row in manifest["entries"]:
        assert pin(row["path"])["sha256"] == row["sha256"]
    mode5 = CORE.parents[1] / "mode5/index-lite.pck"
    assert sha(mode5.read_bytes()) == "a26785c2765d1d5237c73510359b107432d7065626a24726eac6b03ed7f2728d"
    assert sha((ROOT / "godot/scripts/meadow_scene.gd").read_bytes()) == "c8b80de0348f094fa43135cecbd57f971fd75afe022dc19727b95e5ff1edfd2d"
    assert sha((ROOT / "godot/scripts/meadow_progressive.gd").read_bytes()) == "b02effb14cd07fe8df500319513f6aaf7dd25809cbd9367bc8da0450bb6ecd6f"
    manifest.update({"sourceMode5Sha256": sha(mode5.read_bytes()),
        "runtimeValidation": "PASS_ROOT_CONFORM_CACHE_50_EXACT_NATIVE; final newly compiled main hook and Web require main-owner integration test",
        "boundedNativeValidation": pin(OUT / "native-audit-02/validation.json"),
        "shippingHelperMatchesAuditedGdc": True,
        "finalIntegrationRequired": ["Apply main-hook.json to the private compiled main only.",
            "After stock compilation, repin dependencies[res://scripts/meadow_scene.gdc] in progressive/static-cache/manifest.json to the ACTUAL final GDC SHA256; retain every other dependency and record.",
            "Keep progressive/root-conform/meshes.res encoded bytes exact: runtime checks its actual encoded SHA256.",
            "Check 50 root hits plus the original 17 hits, then measure real Web ready. Native data does not prove 0.4 seconds Web savings."]})
    write_json(OUT / "validated-manifest.json", manifest)
    write_json(OUT / "final-pins.json", {"manifest": pin(OUT / "validated-manifest.json"),
        "validation": pin(OUT / "native-audit-02/validation.json"), "mainHook": pin(OUT / "main-hook.json"),
        "builder": pin(Path(__file__)), "audit": pin(ROOT / "godot/tools/audit_root_conform_cache_v135.gd"),
        "frozenOriginalMain": pin(ROOT / "godot/scripts/meadow_scene.gd"),
        "frozenController": pin(ROOT / "godot/scripts/meadow_progressive.gd"),
        "sourceNative": pin(CORE), "sourceMode5": pin(mode5)})
    print(json.dumps(pin(OUT / "validated-manifest.json"), indent=2))


class Tests(unittest.TestCase):
    def test_exact_two_line_hook_roundtrip(self):
        data = MAIN.read_bytes()
        patched = proposed_hook(data)
        self.assertEqual(patched.count(b'meadow_root_conform_cache.gd'), 1)
        self.assertEqual(len(patched) - len(data), len(INSERT.replace("\n", "\r\n" if b"\r\n" in data else "\n").encode()))

    def test_ambiguous_or_repeated_hook_rejected(self):
        with self.assertRaises(AssertionError): proposed_hook(ANCHOR.encode() * 2)
        with self.assertRaises(AssertionError): proposed_hook((ANCHOR + INSERT).encode())

    def test_only_single_target(self):
        helper = (ROOT / "godot" / HELPER).read_text(encoding="utf-8")
        self.assertEqual(helper.count("node.mesh ="), 1)
        for forbidden in ("material_override =", "add_child(", "queue_free(", "get_image(", "sceneReady", "set_shader_parameter"):
            self.assertNotIn(forbidden, helper)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--audit-label", default="native-audit-02")
    args = parser.parse_args()
    if args.self_test: unittest.main(argv=[sys.argv[0]], verbosity=2)
    else:
        if args.build: build()
        if args.audit: audit(args.audit_label)
        if args.seal: seal()
        if not (args.build or args.audit or args.seal): parser.error("Choose --build, --audit, --seal or --self-test")
