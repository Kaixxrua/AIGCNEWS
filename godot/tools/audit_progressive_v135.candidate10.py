"""One actual10 complete native audit; no builds, renderer or source overlays."""
from pathlib import Path
import difflib
import importlib.util
import json
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True
from build_progressive_support_v135 import entries, sha
from build_root_conform_cache_v135 import proposed_hook

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "artifacts/startup-v135/support/candidate-01"
OUT = OLD / "integrated10-native-01"
BUILD = ROOT / "artifacts/startup-v135/build/candidate-10"
PREVIOUS = ROOT / "artifacts/startup-v135/build/candidate-09"
STATIC = ROOT / "artifacts/startup-v135/static-cache/candidate-01"
ROOT_CACHE = ROOT / "artifacts/startup-v135/root-conform/candidate-01"
PROXY = ROOT / "artifacts/startup-v135/scenes/proxy-04/manifest.json"
AO = "assets/baked/v110/rock-occlusion.bin"
AO_SHA = "bb2fe3c1abd30b2092cdb17ca0bc0a6b634438ab82a18b52ded2ece8646261b2"
PINS = {"native": "7622eb8f1c0f687a9c640ac0e2e0c818e005ad4ff6605fc353368849768d1988",
        "mode5": "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b"}

spec = importlib.util.spec_from_file_location("previous_audit09", Path(__file__).with_name("audit_progressive_v135.candidate09.py"))
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
prior.OUT, prior.BUILD = OUT, BUILD
pin, write, write_json = prior.pin, prior.write, prior.write_json


def run():
    assert not OUT.exists(), "One fresh complete actual10 run only"
    assert (BUILD / "proof.json").exists(), "Wait for completed builder proof"
    pins = {kind: pin(BUILD / kind / "index-lite.pck") for kind in PINS}
    assert all(pins[k]["sha256"] == value for k, value in PINS.items())
    proof = json.loads((BUILD / "proof.json").read_bytes())
    assert all(proof[k]["coreSha256"] == value and proof[k]["chunks"] == 12 for k, value in PINS.items())
    assert pin(PROXY)["sha256"] == "b1eaa033475161cf985b8bf139a6c8afd20b9eb69ef023c202144ee957f2210c"
    proxy = json.loads(PROXY.read_bytes())
    a, b = entries(BUILD / "native/index-lite.pck"), entries(BUILD / "mode5/index-lite.pck")
    old = entries(PREVIOUS / "native/index-lite.pck")
    script_proof = json.loads((BUILD / "script-proof.json").read_bytes())
    previous_main = (PREVIOUS / "meadow_scene.progressive.gd").read_bytes()
    current_main = (BUILD / "meadow_scene.progressive.gd").read_bytes()
    assert current_main == proposed_hook(previous_main), "Exactly approved two-line private main hook"
    assert sha(current_main) == script_proof["mainSourceSha256"]
    assert sha(a["scripts/meadow_scene.gdc"]) == script_proof["mainGdcSha256"]
    assert a["scripts/meadow_progressive.gdc"] == old["scripts/meadow_progressive.gdc"]
    assert sha(a["scripts/meadow_progressive.gdc"]) == script_proof["controllerGdcSha256"]
    assert sha((ROOT / "godot/scripts/meadow_scene.gd").read_bytes()) == script_proof["originalSourceSha256"]
    assert sha((ROOT / "godot/scripts/meadow_progressive.gd").read_bytes()) == script_proof["controllerSourceSha256"]
    baseline_static = json.loads(old["progressive/static-cache/manifest.json"])
    baseline_static["dependencies"]["res://scripts/meadow_scene.gdc"] = script_proof["mainGdcSha256"]
    assert json.loads(a["progressive/static-cache/manifest.json"]) == baseline_static, "Only actual main dependency repin"
    root_manifest = json.loads((ROOT_CACHE / "validated-manifest.json").read_bytes())
    assert sha((ROOT_CACHE / "validated-manifest.json").read_bytes()) == "5f7c2b75634e94245069793f494029c64e870509871e59a082f991323ed23c3c"
    for item in root_manifest["entries"]:
        assert a[item["entry"]] == b[item["entry"]], "Both engines use identical encoded cache/runtime entry"
        if item["entry"] != "progressive/static-cache/manifest.json":
            assert sha(a[item["entry"]]) == item["sha256"] == sha(Path(item["path"]).read_bytes())
    added = {x["entry"] for x in root_manifest["entries"]} - old.keys()
    assert set(a) - set(old) == added and len(added) == 4
    assert set(old) - set(a) == {AO} and AO not in b and sha(old[AO]) == AO_SHA
    changes = {k for k in a.keys() & old.keys() if a[k] != old[k]}
    assert changes == {"assets/baked/v77/detail.scn", "assets/baked/v77/terrain.scn", "progressive/manifest.json",
                       "progressive/static-cache/manifest.json", "scripts/meadow_scene.gdc"}
    OUT.mkdir()
    harness = prior.harness()
    context_original = ROOT / "godot/tools/audit_progressive_v135.candidate09.gd"
    data = context_original.read_bytes()
    lines = data.splitlines(keepends=True)
    patched = b'extends "audit-static.gd"\n' + b''.join(lines[1:])
    patched = patched.replace(b"Actual assembled09", b"Actual assembled10").replace(b"actual09", b"actual10").replace(b"actual09Aabb", b"actual10Aabb")
    patched = patched.replace(b"PASS_PROXY03_CACHE_CONTEXT", b"PASS_PROXY04_CACHE_CONTEXT")
    destination = OUT / "harness/audit-context.gd"
    write(destination, patched)
    harness.append({"original": pin(context_original), "privateCopy": pin(destination),
        "diff": ''.join(difflib.unified_diff(data.decode().splitlines(True), patched.decode().splitlines(True)))})
    manifest = prior.twin(a, b)
    previous_manifest = json.loads(old["progressive/manifest.json"])
    assert prior.normalize(manifest) == prior.normalize(previous_manifest), "All scene/texture semantics unchanged09"
    request = json.loads((OLD / "integrated09-native-01/request.json").read_bytes())
    request.update({"out": (OUT / "native.json").as_posix(), "corePack": pins["native"], "overlays": [],
        "rootCacheValidation": pin(ROOT_CACHE / "native-audit-02/validation.json"),
        "deferredAo": {"resource": "res://" + AO, "bytes": len(old[AO]), "sha256": AO_SHA, "chunk": 10}})
    request["proxyContract"].update({"manifest": pin(PROXY), "proxyAoPrefix": 48360, "scriptContract": script_proof})
    for ref, label in zip(request["proxyContract"]["references"], ["terrain-core", "detail-core"], strict=True):
        info = proxy["resources"][label]["encodings"]
        assert pin(info["native"]["path"])["sha256"] == info["native"]["sha256"] == sha(a[ref["entry"]])
        assert sha(b[ref["entry"]]) == info["mode5"]["sha256"]
        ref.update(pin(info["native"]["path"]))
    request["scriptEntries"] = [{"entry": item["entry"], "sha256": sha(a[item["entry"]])}
        for item in root_manifest["entries"]]
    request["scriptEntries"].extend({"entry": path, "sha256": sha(a[path])}
        for path in ["scripts/meadow_scene.gdc", "scripts/meadow_progressive.gdc"])
    chunk_changes = []
    for group, actual, old_spec in zip(request["detailPacks"], manifest["chunks"], previous_manifest["chunks"], strict=True):
        path = BUILD / "native" / actual["file"]
        before_path = PREVIOUS / "native" / old_spec["file"]
        if actual["index"] != 10:
            assert path.read_bytes() == before_path.read_bytes(), "Other eleven actual chunk packs unchanged"
            assert AO not in entries(path)
        else:
            before, after = entries(before_path), entries(path)
            assert set(after) - set(before) == {AO} and not set(before) - set(after)
            assert all(after[k] == value for k, value in before.items())
            assert after[AO] == old[AO] and sha(after[AO]) == AO_SHA
            chunk_changes.append({"index": 10, "before": pin(before_path), "after": pin(path),
                "addedEntry": AO, "bytes": len(after[AO]), "sha256": sha(after[AO]), "allPreviousEntriesExact": True})
        group.update(actual)
        group["file"] = path.as_posix()
    # Existing expensive alpha predicate proof and texture specs are unchanged.
    # The actual helper query/grounding and 30 live texture objects are still checked.
    write_json(OUT / "request.json", request)
    listed = subprocess.run(["rg", "--files", "godot/scripts", "godot/shaders"], cwd=ROOT,
        capture_output=True, check=True).stdout.decode().splitlines()
    source_paths = [ROOT / value for value in listed]
    source_paths.extend([ROOT / "godot/project.godot", ROOT / "godot/tools/audit_progressive_v135.candidate10.py",
        ROOT / "godot/tools/audit_progressive_v135.candidate10.gd", ROOT / "godot/tools/test_lite_runtime_v128.gd",
        BUILD / "meadow_scene.progressive.gd", BUILD / "script-proof.json", BUILD / "proof.json"])
    source_pins = [pin(path) for path in dict.fromkeys(source_paths)]
    write_json(OUT / "code-pins.json", {"sources": source_pins, "privateHarness": harness,
        "allScriptShaderAndProjectSourcesPinned": True, "originalMainAndControllerFrozen": True,
        "privateMainDiff": ''.join(difflib.unified_diff(previous_main.decode().splitlines(True), current_main.decode().splitlines(True))),
        "scriptProof": script_proof, "onlyStaticDependencyRepin": script_proof["mainGdcSha256"]})
    write_json(OUT / "pack-contract.json", {"core": pins, "proxyManifest": pin(PROXY),
        "rootCacheManifest": pin(ROOT_CACHE / "validated-manifest.json"), "addedEntries": sorted(added),
        "removedEntry": AO, "changedExistingEntriesVs09": sorted(changes), "chunkChanges": chunk_changes,
        "allOtherCoreEntriesAndElevenChunksExact": True, "all48CacheSupportEncodedEntriesNativeMode5Equal": True,
        "proxyInitialAoPrefix": 48360, "finalAoPrefix": 317556})
    runtime = OUT / "runtime"
    runtime.mkdir()
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = OUT / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    engine = STATIC / "compiler-runtime/Godot_v4.7.2-stable_win64.exe"
    command = [str(engine), "--headless", "--path", str(runtime), "--main-pack", pins["native"]["file"],
        "--log-file", str(OUT / "engine.log"), "--script", str(ROOT / "godot/tools/audit_progressive_v135.candidate10.gd"),
        "--", str(OUT / "request.json")]
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, env=env, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    elapsed = round(time.monotonic() - started, 3)
    log = result.stdout + result.stderr
    write(OUT / "process.log", log)
    frozen = all(pin(row["file"]) == row for row in source_pins)
    frozen = frozen and all(pin(BUILD / k / "index-lite.pck") == row for k, row in pins.items())
    frozen = frozen and all(pin(g["file"])["sha256"] == g["sha256"] for g in request["detailPacks"])
    write_json(OUT / "invocation.json", {"command": command, "exitCode": result.returncode, "wallSeconds": elapsed,
        "nativeProcessCount": 1, "timeoutSeconds": 90, "engine": pin(engine), "allPinnedInputsFrozen": frozen})
    reports = {}
    for name in ["native.json", "proxy-observations.json", "support-observations.json", "texture-observations.json",
                 "static-cache-observations.json", "proxy-context-observations.json", "root-ao-observations.json"]:
        path = OUT / name
        if path.exists():
            report = json.loads(path.read_bytes())
            reports[name] = {**pin(path), "status": report["status"], "errors": report["errors"]}
    passed = result.returncode == 0 and frozen and len(reports) == 7 and all(not r["errors"] for r in reports.values())
    passed = passed and b"SCRIPT ERROR" not in log and b"Parse Error" not in log
    summary = {"status": "PASS_ACTUAL10_NATIVE_COMPLETE_AND_TWIN" if passed else "FAIL", "core": pins,
        "reports": reports, "codePins": pin(OUT / "code-pins.json"), "packContract": pin(OUT / "pack-contract.json"),
        "twinProof": pin(OUT / "web-twin-proof.json"), "nativeProcessCount": 1,
        "nativeWallSecondsWholeAuditNotStartup": elapsed, "allPinnedInputsFrozen": frozen,
        "limitations": ["No builds/browser/GL/first-paint or network-performance evidence.",
            "Full deterministic native runtime regression only; main owns final real Web acceptance."]}
    write_json(OUT / "validation.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    assert passed, "Preserve failed actual run; no silent repeat"


if __name__ == "__main__":
    run()
