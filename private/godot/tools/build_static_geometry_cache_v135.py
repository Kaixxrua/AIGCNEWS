"""Exact, bounded three-script static geometry cache overlay for candidate07.

Tiny script tokenization only. One native original-function capture followed by
one native cached full-progressive audit; no original export or pack staging.
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
import build_progressive_support_v135 as support
from build_progressive_web_v135 import pack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v135/static-cache"
OUT = SCOPE / "candidate-01"
OLD = ROOT / "artifacts/startup-v135/support/candidate-01"
CORE = ROOT / "artifacts/startup-v135/build/candidate-07/native/index-lite.pck"
CORE_SHA = "a52b946f255ab9197aee180550274ddf336bc228aca9dff1a6f9551bf08f2d50"
NAMES = ("meadow_herb_modules", "meadow_village_builder", "meadow_mountain_relief")
HELPER = "scripts/meadow_static_geometry_cache.gd"
CAPTURE = "tools/build_static_geometry_cache_v135.capture.gd"
AUDIT = OLD / "static-cache-native-01"


def sha(data):
    return support.sha(data)


def pin(path):
    path = Path(path)
    return {"file": str(path), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}


def write(path, value):
    path = Path(path).resolve()
    assert (path.is_relative_to(OUT) or path.is_relative_to(AUDIT)) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value)


def write_json(path, value):
    write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def substitute(source, before, after):
    assert source.count(before) == 1, before[:160]
    return source.replace(before, after, 1)


def transform(name, data, capture=False):
    nl = "\r\n" if b"\r\n" in data else "\n"
    original = data.decode()
    text = original.replace("\r\n", "\n")
    target = CAPTURE if capture else HELPER
    call = 'preload("res://' + target + '")'
    if name == "meadow_herb_modules":
        anchor = '\tvar source := image_source if image_source != null else preload("res://scripts/meadow_progressive_support.gd").image(TEXTURE)'
        text = substitute(text, anchor,
            '\tvar static_cached: Dictionary = ' + call + '.load_cached(scene, plant, "herb", [crop, basal_band, surface != null])\n'
            '\tif not static_cached.is_empty():\n\t\treturn\n' + anchor)
        if capture:
            text = substitute(text, '\tplant.set_meta("herb_source_bottoms", bottoms)',
                '\tplant.set_meta("herb_source_bottoms", bottoms)\n\t' + call + '.finish(scene, plant, "herb")')
    elif name == "meadow_mountain_relief":
        anchor = '\tvar source := preload("res://scripts/meadow_progressive_support.gd").image(texture)'
        text = substitute(text, anchor,
            '\tvar static_cached: Dictionary = ' + call + '.load_cached(scene, mountain, "mountain", [])\n'
            '\tif not static_cached.is_empty():\n\t\treturn\n' + anchor)
        if capture:
            anchor = '\tprint("MEADOW_MOUNTAIN_RELIEF:'
            start = text.index(anchor)
            end = text.index('\n', start)
            text = text[:end] + '\n\t' + call + '.finish(scene, mountain, "mountain")' + text[end:]
    elif name == "meadow_village_builder":
        begin = text.index('\tvar source := preload("res://scripts/meadow_progressive_support.gd").image(texture)')
        end = text.index('\n\tfor i in range(2):', begin)
        block = text[begin:end].replace('\tvar source :=', '\tsource =', 1)
        replacement = ('\tvar static_cached: Dictionary = ' + call + '.load_cached(meadow, village, "village", [width, height, hubs])\n'
            '\tvar source: Image\n\tif static_cached.is_empty():\n' + '\n'.join('\t' + line for line in block.split('\n')))
        if capture:
            replacement += '\n\tvar static_radii := PackedFloat64Array()'
        text = text[:begin] + replacement + text[end:]
        anchor = '\t\tvar radius := 0.0'
        start = text.index(anchor)
        end = text.index('\n\t\tassert(radius >', start)
        block = text[start + len(anchor) + 1:end]
        replacement = '\t\tvar radius: float = 0.0 if static_cached.is_empty() else static_cached.radii[i]\n\t\tif static_cached.is_empty():\n'
        replacement += '\n'.join('\t' + line for line in block.split('\n'))
        if capture:
            replacement += '\n\t\tstatic_radii.append(radius)'
        text = text[:start] + replacement + text[end:]
        if capture:
            anchor = '\tprint("MEADOW_VILLAGE_READY:'
            start = text.index(anchor)
            end = text.index('\n', start)
            text = text[:end] + '\n\t' + call + '.finish(meadow, village, "village", {"radii": static_radii})' + text[end:]
    else:
        raise ValueError(name)
    return text.replace('\n', nl).encode()


def run_native(label, script, request):
    stage = OUT / label
    stage.mkdir()
    write_json(stage / "request.json", request)
    runtime = stage / "runtime"
    runtime.mkdir()
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = stage / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    executable = OUT / "compiler-runtime/Godot_v4.7.2-stable_win64.exe"
    command = [str(executable), "--headless", "--path", str(runtime), "--main-pack", str(CORE),
        "--log-file", str(stage / "engine.log"), "--script", str(script), "--", str(stage / "request.json")]
    started = time.monotonic()
    result = subprocess.run(command, env=env, capture_output=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    log = result.stdout + result.stderr
    write(stage / "process.log", log)
    write_json(stage / "invocation.json", {"command": command, "exitCode": result.returncode,
        "wallSeconds": round(time.monotonic() - started, 3), "engine": pin(executable), "timeoutSeconds": 90})
    assert result.returncode == 0 and b"SCRIPT ERROR" not in log and b"Parse Error" not in log, log[-5000:].decode(errors="replace")


def prepare():
    assert not OUT.exists(), "Fresh candidate only"
    assert sha(CORE.read_bytes()) == CORE_SHA
    OUT.mkdir(parents=True)
    source = {"scripts/" + name + ".gd": (OLD / "patched-compile/project/scripts" / (name + ".gd")).read_bytes() for name in NAMES}
    support.OUT = OUT
    executable = support.private_runtime()
    actual = support.compile_batch("baseline-compile", source, executable)
    base = support.entries(CORE)
    baseline_checks = []
    for path, content in source.items():
        gdc = path[:-3] + ".gdc"
        assert actual[gdc] == base[gdc], "Cannot replace optimized07 source unless stock GDC byte-exact: " + path
        write(OUT / "frozen" / path, content)
        baseline_checks.append({"source": path, "sourceSha256": sha(content), "actual07GdcSha256": sha(base[gdc]), "stockCompileExact": True})
    write_json(OUT / "baseline-proof.json", {"sourceCore": pin(CORE), "checks": baseline_checks})
    helper = (ROOT / "godot" / HELPER).read_bytes()
    captured = {path: transform(Path(path).stem, content, True) for path, content in source.items()}
    captured[HELPER] = helper
    captured[CAPTURE] = (ROOT / "godot" / CAPTURE).read_bytes()
    compiled = support.compile_batch("capture-compile", captured, executable)
    capture_entries = {}
    for path in captured:
        for entry in (path[:-3] + ".gdc", path + ".remap"):
            capture_entries[entry] = compiled[entry]
    overlay = OUT / "capture-overlay.pck"
    write(overlay, pack(CORE.read_bytes()[:112], capture_entries))
    cache = OUT / "cache"
    cache.mkdir()
    request = {"core": CORE.as_posix(), "overlay": overlay.as_posix(), "overlaySha256": sha(overlay.read_bytes()),
               "cacheDir": cache.as_posix(), "report": (OUT / "capture-report.json").as_posix()}
    print("Baseline three private07 scripts reproduce byte-exactly; running one bounded capture.", flush=True)
    run_native("capture-native", ROOT / "godot/tools/build_static_geometry_cache_v135.gd", request)


def finish():
    assert (OUT / "capture-report.json").exists() and not (OUT / "manifest.json").exists()
    capture = json.loads((OUT / "capture-report.json").read_bytes())
    assert capture["status"] == "PASS_CAPTURE_EXACT_RELOAD" and len(capture["records"]) == 17
    source = {"scripts/" + name + ".gd": (OUT / "frozen/scripts" / (name + ".gd")).read_bytes() for name in NAMES}
    patched = {path: transform(Path(path).stem, value) for path, value in source.items()}
    patched[HELPER] = (ROOT / "godot" / HELPER).read_bytes()
    support.OUT = OUT
    compiled = support.compile_batch("shipping-compile", patched, OUT / "compiler-runtime/Godot_v4.7.2-stable_win64_console.exe")
    prior_support = json.loads((OLD / "manifest.json").read_bytes())
    assert prior_support["baselineCompilerAllExact"] and prior_support["sourcePackSha256"] == "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3"
    base = support.entries(CORE)
    values = {}
    original_before = {}
    for item in prior_support["entries"]:
        data = Path(item["path"]).read_bytes()
        assert sha(data) == item["sha256"] and data == base[item["entry"]]
        values[item["entry"]] = data
        original_before[item["entry"]] = item.get("beforeSha256")
    items = []
    for path, data in patched.items():
        if path in source:
            diff = ''.join(difflib.unified_diff(source[path].decode().splitlines(True), data.decode().splitlines(True), fromfile=path, tofile='private-cache/' + path))
            write(OUT / "diffs" / (Path(path).stem + ".diff"), diff.encode())
        for entry in (path[:-3] + ".gdc", path + ".remap"):
            values[entry] = compiled[entry]
    dependencies = {"res://" + p: sha(base[p]) for p in ["scripts/meadow_scene.gdc", "scripts/meadow_progressive_support.gdc", "progressive/alpha-manifest.json"]}
    runtime = {"version": 1, "dependencies": dependencies, "entries": {}}
    totals = {}
    for record in capture["records"]:
        path = Path(record["path"])
        assert pin(path)["sha256"] == record["resourceSha256"] and record["rawReloadExact"]
        entry = "progressive/static-cache/" + path.name
        values[entry] = path.read_bytes()
        runtime["entries"][record["key"]] = {"resource": "res://" + entry, "sha256": sha(values[entry])}
        totals[record["kind"]] = totals.get(record["kind"], 0.0) + record["elapsedOriginalFunctionMs"]
    values["progressive/static-cache/manifest.json"] = (json.dumps(runtime, sort_keys=True, separators=(',', ':')) + '\n').encode()
    for entry, data in sorted(values.items()):
        target = OUT / "entries" / entry
        write(target, data)
        items.append({"entry": entry, "path": str(target), "sha256": sha(data), "bytes": len(data),
                      "beforeSha256": original_before.get(entry),
                      "beforeSupportSha256": sha(base[entry]) if entry in base else None})
    overlay = OUT / "shipping-overlay.pck"
    write(overlay, pack(CORE.read_bytes()[:112], values))
    # Size only: constructing bytes in memory does not stage or mutate a core pack.
    composed = pack(CORE.read_bytes()[:112], {**base, **values})
    before_gzip = len(gzip.compress(CORE.read_bytes(), compresslevel=9, mtime=0))
    after_gzip = len(gzip.compress(composed, compresslevel=9, mtime=0))
    increase = after_gzip - before_gzip
    assert increase < 400_000, ("Candidate exceeds extra core transfer bound", increase)
    manifest = {"schema": "progressive-static-cache-overlay-v1", "sourceCoreSha256": CORE_SHA,
        "sourcePackSha256": prior_support["sourcePackSha256"], "baselineCompilerAllExact": True,
        "baselineCompilerProof": pin(OLD / "baseline-compiler-proof.json"),
        "supportCompilerProof": pin(OUT / "baseline-proof.json"),
        "supersetOfSupportManifest": pin(OLD / "manifest.json"),
        "sourceMode5Sha256": "78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5",
        "entries": items, "overlay": pin(overlay), "originalFunctionsProfiledNativeMs": totals,
        "size": {"nativeCoreBeforeBytes": CORE.stat().st_size, "nativeCoreAfterBytes": len(composed),
                 "nativeCoreBeforeGzipBytes": before_gzip, "nativeCoreAfterGzipBytes": after_gzip,
                 "incrementalGzipBytes": increase, "cacheResourceBytes": sum(len(v) for p, v in values.items() if p.endswith('.res'))},
        "runtimeAudit": "PENDING", "scope": {"privateConsumerScripts": list(NAMES), "cachedMeshes": 17,
        "unchanged": ["main/controller", "all render shaders and materials", "all colliders", "weather/animation", "wildlife support queries", "original/balanced packs"]},
        "risk": "Exact context mismatch, including viewport/camera differences, falls back to original code; Web hit count and CPU benefit must be measured."}
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({"manifest": str(OUT / "manifest.json"), "nativeOriginalFunctionsMs": totals,
                      "incrementalGzipBytes": increase}, indent=2), flush=True)


def audit():
    assert not AUDIT.exists()
    manifest = json.loads((OUT / "manifest.json").read_bytes())
    request = json.loads((OLD / "integrated07-native-01/request.json").read_bytes())
    request["out"] = (AUDIT / "native.json").as_posix()
    request["overlays"] = [manifest["overlay"]]
    changed = {item["entry"]: item for item in manifest["entries"]}
    for item in request["scriptEntries"]:
        if item["entry"] in changed:
            item["sha256"] = changed[item["entry"]]["sha256"]
    for entry in [HELPER[:-3] + ".gdc", HELPER + ".remap"]:
        request["scriptEntries"].append(changed[entry])
    request["staticCaptureReport"] = (OUT / "capture-report.json").as_posix()
    AUDIT.mkdir()
    write_json(AUDIT / "request.json", request)
    run_native("cached-native", ROOT / "godot/tools/audit_progressive_v135.static.gd", request)
    reports = {}
    for name in ["native.json", "proxy-observations.json", "support-observations.json", "texture-observations.json", "static-cache-observations.json"]:
        path = AUDIT / name
        report = json.loads(path.read_bytes())
        assert not report["errors"], (name, report["errors"])
        reports[name] = pin(path)
    assert sha(CORE.read_bytes()) == CORE_SHA
    original_source = json.loads((OLD / "source-pins.json").read_bytes())["sources"]
    assert all(sha((ROOT / "godot" / p).read_bytes()) == value for p, value in original_source.items())
    write_json(OUT / "validation.json", {"status": "PASS_EXACT_STATIC_CACHE_NATIVE_FULL_PROGRESSIVE", "reports": reports,
        "manifest": pin(OUT / "manifest.json"), "allScopedOriginalSourcesFrozen": True,
        "corePackFrozen": pin(CORE), "webPerformance": "NOT MEASURED"})
    print("PASS: 17 exact cached meshes; full twelve chunks, geometry, collider/query, texture and light audit.", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('step', choices=['prepare', 'finish', 'audit', 'all'])
    args = parser.parse_args()
    for name, operation in [('prepare', prepare), ('finish', finish), ('audit', audit)]:
        if args.step in (name, 'all'):
            operation()
