"""Single bounded native08 lighting/complete-geometry audit; no builds or staging."""
from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True
from build_progressive_support_v135 import entries, sha, write, write_json

ROOT = Path(__file__).resolve().parents[2]
OWN = ROOT / "artifacts/startup-v135/support/candidate-01"
STAGE = OWN / "integrated08-native-01"
BUILD = ROOT / "artifacts/startup-v135/build/candidate-08"
EXPECTED = {"native": "e1cc8b4d9f2edc78e976b497db9ab2ad9ddc0365237da57355246a6908714165",
            "mode5": "825f8c97372354dfac573875a13a5417293944be8c1f4956abc8846faf904429"}


def pin(path):
    path = Path(path)
    return {"file": str(path), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}


def run():
    assert not STAGE.exists(), "Fresh audit only; no duplicate process or overwritten evidence"
    pins = {kind: pin(BUILD / kind / "index-lite.pck") for kind in EXPECTED}
    assert all(pins[k]["sha256"] == v for k, v in EXPECTED.items())
    previous = entries(ROOT / "artifacts/startup-v135/build/candidate-07/native/index-lite.pck")
    current = entries(pins["native"]["file"])
    assert current.keys() == previous.keys()
    differences = {p for p in current if current[p] != previous[p]}
    assert differences == {"scripts/meadow_progressive.gdc", "progressive/manifest.json"}, differences
    manifest = json.loads(current["progressive/manifest.json"])
    before_manifest = json.loads(previous["progressive/manifest.json"])
    assert manifest == {**before_manifest, "deferLighting": True}
    assert manifest == json.loads((BUILD / "native/progressive-manifest.json").read_bytes())
    proof = json.loads((BUILD / "script-proof.json").read_bytes())
    assert sha(current["scripts/meadow_progressive.gdc"]) == proof["controllerGdcSha256"]
    assert sha((ROOT / "godot/scripts/meadow_progressive.gd").read_bytes()) == proof["controllerSourceSha256"]
    assert sha(current["scripts/meadow_scene.gdc"]) == proof["mainGdcSha256"]
    assert sha((BUILD / "meadow_scene.progressive.gd").read_bytes()) == proof["mainSourceSha256"]
    assert sha((ROOT / "godot/scripts/meadow_scene.gd").read_bytes()) == proof["originalSourceSha256"]
    request = json.loads((OWN / "integrated07-native-01/request.json").read_bytes())
    original_request = copy.deepcopy(request)
    request.update({"out": (STAGE / "native.json").as_posix(), "corePack": pins["native"],
                    "lightingBaseline": (OWN / "integrated07-native-01/native.json").as_posix()})
    request["proxyContract"]["scriptContract"] = proof
    for chunk, spec in zip(request["detailPacks"], manifest["chunks"], strict=True):
        actual = BUILD / "native" / spec["file"]
        assert actual.read_bytes() == Path(chunk["file"]).read_bytes(), "All detail packs exact07"
        assert pin(actual)["sha256"] == spec["sha256"] and actual.stat().st_size == spec["bytes"]
        assert all(chunk[key] == value for key, value in spec.items() if key != "file")
        chunk["file"] = str(actual)
    assert len(request["detailPacks"]) == 12 and len(request["textureSpecs"]) == 30
    # Compiler/support/alpha/texture proofs are reused only after actual byte equality.
    for item in request["scriptEntries"]:
        assert sha(current[item["entry"]]) == item["sha256"]
    protected = {ROOT / "godot/scripts/meadow_scene.gd": proof["originalSourceSha256"],
                 ROOT / "godot/scripts/meadow_progressive.gd": proof["controllerSourceSha256"]}
    for path, value in json.loads((OWN / "source-pins.json").read_bytes())["sources"].items():
        protected[ROOT / "godot" / path] = value
    STAGE.mkdir()
    write_json(STAGE / "request.json", request)
    write_json(STAGE / "pack-contract.json", {"packs": pins, "exactChangedEntriesVs07": sorted(differences),
        "unchangedEntryCount": len(current) - len(differences), "deferLightingOnlyManifestDelta": True,
        "all12DetailPacksByteExact07": True, "allSupportAlphaTextureShaderSceneBytesExact07": True,
        "baselineRequest": pin(OWN / "integrated07-native-01/request.json"), "scriptProof": proof,
        "note": "Mode5 exact hash is pinned; standard native twin runs, no stock decoder on mode5."})
    runtime = STAGE / "runtime"
    runtime.mkdir()
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = STAGE / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    executable = OWN / "compiler-runtime/Godot_v4.7.2-stable_win64.exe"
    command = [str(executable), "--headless", "--path", str(runtime), "--main-pack", pins["native"]["file"],
               "--log-file", str(STAGE / "engine.log"), "--script", str(ROOT / "godot/tools/audit_progressive_v135.lighting.gd"),
               "--", str(STAGE / "request.json")]
    started = time.monotonic()
    result = subprocess.run(command, env=env, capture_output=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    elapsed = round(time.monotonic() - started, 3)
    log = result.stdout + result.stderr
    write(STAGE / "process.log", log)
    intact = all(sha(path.read_bytes()) == digest for path, digest in protected.items())
    packs_intact = all(pin(BUILD / kind / "index-lite.pck") == value for kind, value in pins.items()) and all(
        pin(c["file"])["sha256"] == c["sha256"] for c in request["detailPacks"])
    write_json(STAGE / "invocation.json", {"command": command, "exitCode": result.returncode,
        "wallSeconds": elapsed, "timeoutSeconds": 90, "engine": pin(executable),
        "allScopedSourcesFrozen": intact, "allActualPacksFrozen": packs_intact, "nativeProcessCount": 1})
    reports = {}
    for name in ["native.json", "proxy-observations.json", "support-observations.json", "texture-observations.json", "lighting-observations.json"]:
        path = STAGE / name
        if path.exists():
            data = json.loads(path.read_bytes())
            reports[name] = {"status": data["status"], "errors": data["errors"], **pin(path)}
    passed = result.returncode == 0 and intact and packs_intact and len(reports) == 5 and all(not v["errors"] for v in reports.values())
    passed = passed and b"SCRIPT ERROR" not in log and b"Parse Error" not in log
    summary = {"status": "PASS_NATIVE08_COMPLETE_AND_LIGHTING" if passed else "FAIL",
               "packs": pins, "reports": reports, "nativeProcessCount": 1,
               "coreRootsReplaced": 9, "meshesReplaced": 2, "inPlaceTextures": 30,
               "wallSecondsWholeAuditNotStartup": elapsed,
               "originalScriptsPacksFrozen": intact and packs_intact,
               "limitations": ["No Web shader compilation, GPU, physical presentation or performance claim.",
                    "Pending real weather ticks observed after production enforcer; deterministic geometry probe otherwise pauses clocks.",
                    "Predicate alpha pixels unchanged07: three predicates exact, not continuous alpha equality."]}
    write_json(STAGE / "validation.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    assert passed, "Preserve failed actual audit; do not silently rerun"


if __name__ == "__main__":
    run()
