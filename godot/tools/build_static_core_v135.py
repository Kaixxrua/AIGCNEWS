"""Pinned candidate10 static-world sidecar. No full pack or shared source writes.

The only exports are tiny stock GDScript-tokenizer projects. Capture and restore
are separate bounded native processes. Each attempt is retained, including errors.
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

sys.dont_write_bytecode = True
import build_progressive_support_v135 as compiler

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/startup-v135/static-core/candidate-01"
BASE = ROOT / "artifacts/startup-v135/build/candidate-10"
PINS = {
    "native": "7622eb8f1c0f687a9c640ac0e2e0c818e005ad4ff6605fc353368849768d1988",
    "mode5": "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b",
}
MAIN = "scripts/meadow_scene.gd"
GDC = "scripts/meadow_scene.gdc"
HELPER = "progressive/static-core/restore.gd"
SCENE = "progressive/static-core/world.scn"
MANIFEST = "progressive/static-core/manifest.json"
STATE_FIELDS = ["ground_material", "focus_material", "focus_enabled", "shadow_ellipses",
                "asset_paths", "occupied_art_regions", "travel", "route_length",
                "audit_complete", "render_metrics_samples"]
NODE_FIELDS = ["camera", "scale_guide", "walker"]


def sha(data):
    return compiler.sha(data)


def pin(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": path.as_posix(), "bytes": len(data), "sha256": sha(data)}


def write(path, data):
    path = Path(path).resolve()
    assert path.is_relative_to(OUT) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path, data):
    write(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def selected_capture():
    paths = sorted(OUT.glob("selected-capture*.json"), key=lambda p: p.stat().st_mtime_ns)
    assert paths
    return json.loads(paths[-1].read_bytes())


def selected_release():
    paths = sorted(OUT.glob("selected-release-*.json"))
    assert paths
    return json.loads(paths[-1].read_bytes())


def typed_array_contract(snapshot):
    """Restore only actual captured typed Arrays erased by ResourceSaver.

    Values remain in the saved scene, already independently hash-compared.
    Resource chains identify live shared instances, never ObjectIDs.
    """
    bindings = {}
    def visit(value, node, chain, seen):
        if not isinstance(value, dict) or "resource" not in value:
            return
        label = value["resource"]
        if label in seen:
            return
        bindings.setdefault(label, (node, chain))
        for key, child in snapshot["resources"][label]["properties"].items():
            visit(child, node, chain + [key], seen | {label})
    result = []
    for node, row in snapshot["nodes"].items():
        for key, value in row["properties"].items():
            visit(value, node, [key], set())
        for key, value in row["metadata"].items():
            if isinstance(value, dict) and value.get("typed", 0):
                result.append({"node": node, "chain": [], "metadata": key,
                    "type": int(value["typed"]), "count": len(value["array"])})
    for label, row in snapshot["resources"].items():
        for key, value in row.get("uniforms", {}).items():
            if isinstance(value, dict) and value.get("typed", 0):
                assert label in bindings, ("No public live resource locator", label)
                node, chain = bindings[label]
                result.append({"node": node, "chain": chain, "uniform": key,
                    "type": int(value["typed"]), "count": len(value["array"])})
    assert len(result) == 21, ("Pinned actual10 typed metadata/uniform inventory", result)
    return result


def source_parts(data):
    start = data.index(b"func _ready() -> void:\n")
    middle = data.index(b"\tvar weather := WEATHER_CONTROLLER.new()\n", start)
    end = data.index(b"\nfunc _setup_view()", middle)
    assert data[start:middle].endswith(b"\t_build_focus()\n")
    return start, middle, end


def prepare():
    assert not (OUT / "prepared.json").exists()
    for kind, expected in PINS.items():
        assert pin(BASE / kind / "index-lite.pck")["sha256"] == expected
    original = (BASE / "meadow_scene.progressive.gd").read_bytes()
    assert sha(original) == "94bca8a98f11c31688ecc8ce193df0adf4ad007d068143a0963517f5169bab73"
    assert b"\r" not in original
    start, middle, end = source_parts(original)
    write(OUT / "frozen/meadow_scene.gd", original)
    compiler.OUT = OUT
    engine = compiler.private_runtime()
    stock = compiler.compile_batch("baseline-compile", {MAIN: original}, engine)
    a = compiler.entries(BASE / "native/index-lite.pck")
    b = compiler.entries(BASE / "mode5/index-lite.pck")
    assert stock[GDC] == a[GDC] == b[GDC], "Baseline compiler must reproduce actual10 GDC"
    frozen = {}
    for folder in [ROOT / "godot/scripts", ROOT / "godot/shaders"]:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                frozen[path.as_posix()] = sha(path.read_bytes())
    for path in [ROOT / "godot/project.godot", ROOT / "godot/scenes/main.tscn"]:
        frozen[path.as_posix()] = sha(path.read_bytes())
    write_json(OUT / "frozen/pins.json", {"sources": frozen, "basePacks": PINS,
        "baselineCompiledSha256": sha(stock[GDC]), "baselineCompilerExact": True})
    recorder = (OUT / "recorder.gd").as_posix()
    capture = original[:start] + original[start:middle].replace(
        b"\t_setup_view()\n", ('\tvar static_context: PackedByteArray = load("' + recorder + '").context(self)\n\t_setup_view()\n').encode(), 1)
    capture += ('\tload("' + recorder + '").capture(self, static_context, scene_start)\n').encode() + original[end:]
    write(OUT / "capture-main.gd", capture)
    helper = 'load("res://' + HELPER + '")'
    replacement = ("func _ready() -> void:\n\tvar scene_start := Time.get_ticks_msec()\n"
        f"\tif not {helper}.restore(self):\n"
        '\t\tpush_error("MEADOW_STATIC_CORE_REJECTED: context/content mismatch; no ready emitted")\n'
        '\t\tset_process(false)\n\t\tset_physics_process(false)\n\t\treturn\n').encode()
    shipping = original[:start] + replacement + original[middle:]
    assert shipping[shipping.index(b"\tvar weather :="):shipping.index(b"\nfunc _setup_view()") ] == original[middle:end]
    assert shipping[shipping.index(b"\nfunc _setup_view()"): ] == original[end:]
    write(OUT / "cached-main.gd", shipping)
    write(OUT / "source.diff", ''.join(difflib.unified_diff(original.decode().splitlines(True),
        shipping.decode().splitlines(True), fromfile="actual10/main", tofile="private/static-core-main")).encode())
    write_json(OUT / "prepared.json", {"baselineCompilerExact": True, "stateFields": STATE_FIELDS,
        "nodePathFields": NODE_FIELDS, "dynamicTailByteExact": True,
        "allOtherFunctionsByteExact": True, "source": pin(OUT / "frozen/meadow_scene.gd"),
        "cachedSource": pin(OUT / "cached-main.gd"), "captureSource": pin(OUT / "capture-main.gd")})


def native(mode, attempt):
    assert mode in ("capture", "restore")
    stage = OUT / f"{mode}-{attempt:02d}"
    assert not stage.exists(), "Retain prior attempts; choose a new attempt number"
    stage.mkdir(parents=True)
    request = {"mode": mode, "out": stage.as_posix(), "root": OUT.as_posix(),
        "core": (BASE / "native/index-lite.pck").as_posix(), "sourceSha256": PINS["native"],
        "sceneEntry": "res://scenes/main.tscn", "stateFields": STATE_FIELDS,
        "nodeFields": NODE_FIELDS, "sceneOutput": (stage / "world.scn").as_posix()}
    if mode == "restore":
        release = selected_release()
        request["capture"] = selected_capture()["report"]
        request["core"] = release["sanitized"]
        request["sourceSha256"] = pin(request["core"])["sha256"]
        request["removed"] = release["removed"]
        request["shippingManifest"] = release["manifest"]
    write_json(stage / "request.json", request)
    for name in ["runner.gd", "recorder.gd", "restore.gd", "capture-main.gd", "cached-main.gd"]:
        write(stage / "inputs" / name, (OUT / name).read_bytes())
    env = os.environ.copy()
    for key in ["APPDATA", "LOCALAPPDATA", "TEMP", "TMP"]:
        folder = stage / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    runtime = stage / "runtime"
    runtime.mkdir()
    engine = OUT / "compiler-runtime/Godot_v4.7.2-stable_win64.exe"
    cmd = [str(engine), "--headless", "--path", str(runtime), "--main-pack", request["core"],
           "--log-file", str(stage / "engine.log"), "--script", str(OUT / "runner.gd"),
           "--", str(stage / "request.json")]
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, timeout=40,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        log = result.stdout + result.stderr
        code = result.returncode
    except subprocess.TimeoutExpired as exc:
        log = (exc.stdout or b"") + (exc.stderr or b"")
        code = "TIMEOUT_KILLED"
    write(stage / "process.log", log)
    write_json(stage / "invocation.json", {"command": cmd, "exitCode": code,
        "wallSeconds": round(time.monotonic() - started, 3), "timeoutSeconds": 40,
        "engine": pin(engine), "noRendererTimingClaim": True})
    assert code == 0 and b"SCRIPT ERROR" not in log, log[-7000:].decode(errors="replace")
    report = json.loads((stage / "report.json").read_bytes())
    assert not report["errors"], report["errors"][:20]
    if mode == "capture":
        write_json(OUT / f"selected-capture-{attempt:02d}.json", {"report": (stage / "report.json").as_posix(),
            "scene": request["sceneOutput"], "sha256": report["sceneSha256"]})
    else:
        write_json(OUT / "selected-restore.json", {"report": (stage / "report.json").as_posix()})
    print(json.dumps({"mode": mode, "status": report["status"], "out": str(stage)}, ensure_ascii=False), flush=True)


def compile_candidate():
    selected = selected_capture()
    report = json.loads(Path(selected["report"]).read_bytes())
    assert report["status"] == "PASS_STATIC_CAPTURE" and not report["errors"]
    index = 1 + len(list(OUT.glob("selected-release-*.json")))
    release = OUT / f"release-{index:02d}"
    assert not release.exists()
    release.mkdir()
    compiler.OUT = OUT
    compiled = compiler.compile_batch(f"shipping-compile-{index:02d}", {
        MAIN: (OUT / "cached-main.gd").read_bytes(),
        HELPER: (OUT / "restore.gd").read_bytes()},
        OUT / "compiler-runtime/Godot_v4.7.2-stable_win64_console.exe")
    a = compiler.entries(BASE / "native/index-lite.pck")
    b = compiler.entries(BASE / "mode5/index-lite.pck")
    values = {p: compiled[p] for p in (GDC, MAIN + ".remap", HELPER[:-3] + ".gdc", HELPER + ".remap")}
    values["progressive/static-core/entry.tscn"] = (
        '[gd_scene load_steps=3 format=3]\n'
        '[ext_resource type="Script" path="res://scripts/meadow_scene.gd" id="1_main"]\n'
        '[ext_resource type="Script" path="res://scripts/meadow_edge_growth.gd" id="2_edge"]\n'
        '[node name="MeadowPlain" type="Node3D"]\nscript = ExtResource("1_main")\n'
        '[node name="Camera3D" type="Camera3D" parent="."]\n'
        '[node name="MeadowEdgeGrowth" type="Node3D" parent="."]\nscript = ExtResource("2_edge")\n').encode()
    values["scenes/main.tscn.remap"] = b'[remap]\npath="res://progressive/static-core/entry.tscn"\n'
    saved = Path(selected["scene"]).read_bytes()
    assert sha(saved) == selected["sha256"]
    from repack_web_cache import _unpack, _pack
    decoded = _unpack(saved)
    values[SCENE] = _pack(decoded, 1048576, 19)
    assert _unpack(values[SCENE]) == decoded
    removed = sorted(p for p in a if p in {
        "assets/baked/v77/terrain.scn", "assets/baked/v77/detail.scn", "assets/baked/v77/riverbank.scn",
        "assets/baked/v77/foothill.scn", "assets/baked/v77/brush.scn"}
        or p.startswith(("progressive/static-cache/", "progressive/root-conform/"))
        or p.startswith(".godot/exported/") and p.endswith("-main.scn"))
    # All original entry bytes are guarded. Encoded mode5 alternatives are explicit,
    # never inferred from disk. Original static-cache dependency pins stay intact.
    dependencies = {"res://" + p: sorted({sha(a[p]), sha(b[p])}) for p in a
                    if p != GDC and p != "progressive/manifest.json" and p not in removed}
    dependencies["res://" + GDC] = [sha(values[GDC])]
    for p in ("scenes/main.tscn.remap", "progressive/static-core/entry.tscn"):
        dependencies["res://" + p] = [sha(values[p])]
    runtime = {"version": 1, "sourcePacks": PINS, "contextHex": report["contextHex"],
        "scene": "res://" + SCENE, "sceneSha256": sha(values[SCENE]),
        "nodes": report["bakedNodes"], "dependencies": dependencies,
        "stateFields": STATE_FIELDS, "nodeFields": NODE_FIELDS,
        "typedArrays": typed_array_contract(report["snapshot"])}
    values[MANIFEST] = (json.dumps(runtime, sort_keys=True, separators=(',', ':')) + "\n").encode()
    items = []
    for p, data in values.items():
        target = release / "entries" / p
        write(target, data)
        items.append({"entry": p, "path": target.as_posix(), "sha256": sha(data),
                      "beforeSha256": sha(a[p]) if p in a else None, "bytes": len(data),
                      "gzipBytes": len(gzip.compress(data, compresslevel=9, mtime=0))})
    # User-authorized test-only sanitized mirror, never a Web shipping PCK.
    from build_progressive_web_v135 import pack
    overlay = pack((BASE / "native/index-lite.pck").read_bytes()[:112], values)
    write(release / "audit-overlay.pck", overlay)
    sanitized = pack((BASE / "native/index-lite.pck").read_bytes()[:112], {**{p: v for p, v in a.items() if p not in removed}, **values})
    write(release / "test-only-sanitized.pck", sanitized)
    assert not set(removed) & compiler.entries(release / "test-only-sanitized.pck").keys()
    write_json(release / "manifest.pending.json", {"schema": "static-core-overlay-v1", "sourcePacks": PINS,
        "baselineCompilerAllExact": True, "entries": items, "runtimeValidation": "PENDING",
        "size": {"overlayBytes": len(overlay), "overlayGzipBytes": len(gzip.compress(overlay, compresslevel=9, mtime=0)),
                 "bakedSceneBytes": len(values[SCENE]), "bakedSceneGzipBytes": len(gzip.compress(values[SCENE], compresslevel=9, mtime=0)),
                 "sourceNativeGzipBytes": len(gzip.compress((BASE / "native/index-lite.pck").read_bytes(), compresslevel=9, mtime=0)),
                 "sanitizedNativeGzipBytes": len(gzip.compress(sanitized, compresslevel=9, mtime=0)),
                 "sanitizedNativeBytes": len(sanitized),
                 "removedEncodedBytes": sum(len(a[p]) for p in removed),
                 "sumEntryGzipDeltaNotWholePack": sum(x["gzipBytes"] - (len(gzip.compress(a[x["entry"]], compresslevel=9, mtime=0)) if x["entry"] in a else 0) for x in items)},
        "removeEntries": [{"entry": p, "beforeSha256": sha(a[p]), "mode5BeforeSha256": sha(b[p])} for p in removed],
        "mustKeep": ["assets/baked/lite-v128/crown-edge-controller.scn", "assets/baked/v113/far-sward.scn",
                     "progressive/alpha-manifest.json", "progressive/alpha/*", "all original texture/import/shader/script entries", "progressive/manifest.json"],
        "sceneContainerProof": {"originalSave": pin(selected["scene"]), "logicalSha256": sha(decoded),
                                "decodedBytesExact": True, "blockBytes": 1048576, "zstdLevel": 19},
        "unchangedDynamicTail": True, "failurePolicy": "Reject unknown context/content before original tail, never emit ready.",
        "thinEntry": {"entry": "scenes/main.tscn.remap", "initialNodes": ["MeadowPlain", "Camera3D", "MeadowEdgeGrowth"],
                      "originalProjectBinaryUnchanged": True, "initialMeshAndShapeCount": 0},
        "retainedRuntimeConstruction": ["Original MeadowEdgeGrowth child-ready/parent.ready one-shot", "Original _build_scale_guide(), including exact 65-vertex ImmediateMesh"],
        "fallback": {"included": False, "requires": "Restore original b34b main GDC, original scene remap and every removeEntries artifact from preserved candidate10."}})
    write_json(OUT / f"selected-release-{index:02d}.json", {"manifest": (release / "manifest.pending.json").as_posix(),
        "sanitized": (release / "test-only-sanitized.pck").as_posix(), "removed": removed})


def finish():
    restore = json.loads((OUT / "selected-restore.json").read_bytes())
    report = json.loads(Path(restore["report"]).read_bytes())
    assert report["status"] == "PASS_STATIC_RESTORE" and not report["errors"]
    frozen = json.loads((OUT / "frozen/pins.json").read_bytes())
    assert all(sha(Path(p).read_bytes()) == h for p, h in frozen["sources"].items()), "Shared source changed during attempt"
    assert all(pin(BASE / k / "index-lite.pck")["sha256"] == h for k, h in PINS.items())
    manifest = json.loads(Path(selected_release()["manifest"]).read_bytes())
    manifest["runtimeValidation"] = pin(restore["report"])
    manifest["status"] = report["status"]
    manifest["proof"] = {"capture": pin(selected_capture()["report"]),
                         "restore": pin(restore["report"]), "source": pin(OUT / "prepared.json"),
                         "sharedSourcesAndPacksFrozen": True, "webPerformance": "NOT MEASURED"}
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({"manifest": str(OUT / "manifest.json"), "size": manifest["size"]}, indent=2), flush=True)


def measure():
    """Codec-only transfer accounting; never stage a final Web pack or run Godot."""
    from copy import deepcopy
    import brotli
    from repack_web_cache import _unpack
    from build_filtered_scene_pack_v128 import encode, decode
    from build_progressive_web_v135 import pack
    stage = OUT / "transfer"
    assert not stage.exists()
    stage.mkdir()
    manifest = json.loads((OUT / "manifest.json").read_bytes())
    assert manifest["status"] == "PASS_STATIC_RESTORE"
    rows = {x["entry"]: x for x in manifest["entries"]}
    standard = Path(rows[SCENE]["path"]).read_bytes()
    raw = _unpack(standard)
    started = time.monotonic()
    filtered, modes = encode(raw, level=19)
    assert decode(filtered) == raw
    write(stage / "world.mode5.scn", filtered)
    web = deepcopy(manifest)
    web["sourcePackSha256"] = PINS["mode5"]
    web["encoding"] = "Mode5 encoding of the exact native-tested logical resource; no engine change"
    runtime = json.loads(Path(rows[MANIFEST]["path"]).read_bytes())
    runtime["sceneSha256"] = sha(filtered)
    runtime_bytes = (json.dumps(runtime, sort_keys=True, separators=(',', ':')) + "\n").encode()
    write(stage / "runtime-manifest.mode5.json", runtime_bytes)
    replacements = {SCENE: stage / "world.mode5.scn", MANIFEST: stage / "runtime-manifest.mode5.json"}
    b = compiler.entries(BASE / "mode5/index-lite.pck")
    for item in web["entries"]:
        p = item["entry"]
        if p in replacements:
            data = replacements[p].read_bytes()
            item.update({"path": replacements[p].as_posix(), "sha256": sha(data), "bytes": len(data),
                         "gzipBytes": len(gzip.compress(data, compresslevel=9, mtime=0))})
        item["beforeSha256"] = sha(b[p]) if p in b else None
    for item in web["removeEntries"]:
        item["beforeSha256"] = sha(b[item["entry"]])
    removed = {x["entry"] for x in web["removeEntries"]}
    entries_after = {**{p: v for p, v in b.items() if p not in removed},
                     **{x["entry"]: Path(x["path"]).read_bytes() for x in web["entries"]}}
    original = (BASE / "mode5/index-lite.pck").read_bytes()
    # In-memory accounting only: no final Web PCK is written.
    combined_bytes = pack(original[:112], entries_after)
    def metrics(data):
        return {"bytes": len(data), "gzip9Bytes": len(gzip.compress(data, compresslevel=9, mtime=0)),
                "brotli11Bytes": len(brotli.compress(data, quality=11))}
    result = {"source": metrics(original), "candidateMode5InMemory": metrics(combined_bytes),
        "nativeValidatedScene": pin(rows[SCENE]["path"]), "mode5Scene": pin(stage / "world.mode5.scn"),
        "logicalSha256": sha(raw), "logicalBytes": len(raw), "exactLogicalRoundtrip": True,
        "filterModes": modes, "encoderLevel": 19, "elapsedSeconds": round(time.monotonic() - started, 3),
        "webPackWritten": False, "webDecodeAndPerformance": "Not tested here; main owns browser integration"}
    web["transferProof"] = (stage / "metrics.json").as_posix()
    web["size"] = result
    web["nativeEquivalentManifest"] = pin(OUT / "manifest.json")
    write_json(stage / "metrics.json", result)
    write_json(OUT / "manifest.mode5.json", web)
    print(json.dumps(result, indent=2), flush=True)


def tests():
    """Read-only artifact/source contract tests; no Godot or build subprocess."""
    import unittest
    from repack_web_cache import _unpack
    class Contract(unittest.TestCase):
        def test_exact_source_boundary(self):
            a = (OUT / "frozen/meadow_scene.gd").read_bytes()
            b = (OUT / "cached-main.gd").read_bytes()
            start, middle, end = source_parts(a)
            self.assertEqual(a[:start], b[:start])
            self.assertEqual(a[middle:], b[b.index(b"\tvar weather := WEATHER_CONTROLLER.new()\n"):])
            self.assertIn(b"set_physics_process(false)", b[start:])
        def test_actual_native_and_removed_entries(self):
            report = json.loads(Path(json.loads((OUT / "selected-restore.json").read_bytes())["report"]).read_bytes())
            self.assertEqual(report["status"], "PASS_STATIC_RESTORE")
            self.assertEqual(report["differences"], [])
            self.assertEqual(report["snapshot"]["nodeCount"], 124)
            self.assertEqual(len(report["snapshot"]["colliders"]), 5)
            release = selected_release()
            packed = compiler.entries(Path(release["sanitized"]))
            self.assertFalse(set(release["removed"]) & packed.keys())
            self.assertEqual(len(release["removed"]), 26)
            self.assertIn("assets/baked/lite-v128/crown-edge-controller.scn", packed)
            self.assertIn("assets/baked/v113/far-sward.scn", packed)
            self.assertIn("progressive/alpha-manifest.json", packed)
            self.assertIn(b"progressive/static-core/entry.tscn", packed["scenes/main.tscn.remap"])
        def test_scene_lossless_container_and_pins(self):
            m = json.loads((OUT / "manifest.json").read_bytes())
            capture = selected_capture()
            for row in m["entries"]:
                self.assertEqual(sha(Path(row["path"]).read_bytes()), row["sha256"])
            scene = next(x for x in m["entries"] if x["entry"] == SCENE)
            self.assertEqual(_unpack(Path(scene["path"]).read_bytes()), _unpack(Path(capture["scene"]).read_bytes()))
            frozen = json.loads((OUT / "frozen/pins.json").read_bytes())
            self.assertTrue(all(sha(Path(p).read_bytes()) == h for p, h in frozen["sources"].items()))
            for k, h in PINS.items(): self.assertEqual(pin(BASE / k / "index-lite.pck")["sha256"], h)
        def test_typed_array_and_path_contract(self):
            capture = json.loads(Path(selected_capture()["report"]).read_bytes())
            typed = typed_array_contract(capture["snapshot"])
            self.assertEqual(len(typed), 21)
            self.assertTrue(all("node" in x and "chain" in x for x in typed))
            for x in typed: self.assertNotIn("ObjectID", json.dumps(x))
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contract))
    assert outcome.wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["prepare", "capture", "compile", "restore", "finish", "measure", "tests"])
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    if args.step in ("capture", "restore"):
        native(args.step, args.attempt)
    else:
        {"prepare": prepare, "compile": compile_candidate, "finish": finish, "measure": measure, "tests": tests}[args.step]()
