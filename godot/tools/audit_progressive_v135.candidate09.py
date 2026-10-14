"""Exactly one actual09 native full audit plus read-only complete mode5 twin proof."""
from pathlib import Path
import difflib
import json
import os
import struct
import subprocess
import sys
import time

sys.dont_write_bytecode = True
from build_progressive_support_v135 import entries, sha
from build_filtered_scene_pack_v128 import decode as decode_mode5
from repack_web_cache import _unpack

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "artifacts/startup-v135/support/candidate-01"
OUT = OLD / "integrated09-native-01"
BUILD = ROOT / "artifacts/startup-v135/build/candidate-09"
STATIC = ROOT / "artifacts/startup-v135/static-cache/candidate-01"
PROXY = ROOT / "artifacts/startup-v135/scenes/proxy-03/manifest.json"
PINS = {"native": "9472167e7e416eca07e9a217eba189b1ddeecb149faa86b121f9c0a097fe3e93",
        "mode5": "a26785c2765d1d5237c73510359b107432d7065626a24726eac6b03ed7f2728d"}


def pin(path):
    path = Path(path)
    return {"file": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}


def write(path, value):
    path = Path(path).resolve()
    assert path.is_relative_to(OUT) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value)


def write_json(path, value):
    write(path, (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode())


def logical(blob):
    if not blob.startswith(b"RSCC"):
        return blob
    return decode_mode5(blob) if struct.unpack_from('<I', blob, 4)[0] == 5 else _unpack(blob)


def normalize(manifest):
    return {**manifest, "chunks": [{k: v for k, v in c.items() if k not in ("file", "sha256", "bytes")} for c in manifest["chunks"]]}


def harness():
    rows = []
    for name in ["audit-base-private.gd", "audit-proxy-private.gd", "audit-support.gd", "audit-integrated06.gd", "audit-static.gd"]:
        original = ROOT / "godot/tools/audit_progressive_v135.static.gd" if name == "audit-static.gd" else OLD / name
        data = original.read_bytes()
        patched = data
        if name == "audit-proxy-private.gd":
            before = b'== 70386, "Initial compact AO prefix exactly 70386"'
            after = b'== int(request.proxyContract.proxyAoPrefix), "Initial compact AO prefix equals pinned proxy contract"'
            assert data.count(before) == 1
            patched = data.replace(before, after, 1)
        elif name == "audit-static.gd":
            lines = data.splitlines(keepends=True)
            patched = b'extends "audit-integrated06.gd"\n' + b''.join(lines[1:])
        path = OUT / "harness" / name
        write(path, patched)
        rows.append({"original": pin(original), "privateCopy": pin(path), "byteExact": data == patched,
                     "diff": ''.join(difflib.unified_diff(data.decode().splitlines(True), patched.decode().splitlines(True)))})
    return rows


def twin(a, b):
    ma, mb = json.loads(a["progressive/manifest.json"]), json.loads(b["progressive/manifest.json"])
    assert normalize(ma) == normalize(mb)
    pairs = [("core", BUILD / "native/index-lite.pck", BUILD / "mode5/index-lite.pck", a, b)]
    for ca, cb in zip(ma["chunks"], mb["chunks"], strict=True):
        pa, pb = BUILD / "native" / ca["file"], BUILD / "mode5" / cb["file"]
        assert pin(pa)["sha256"] == ca["sha256"] and pa.stat().st_size == ca["bytes"]
        assert pin(pb)["sha256"] == cb["sha256"] and pb.stat().st_size == cb["bytes"]
        pairs.append((str(ca["index"]), pa, pb, entries(pa), entries(pb)))
    checks = []
    for label, pa, pb, aa, bb in pairs:
        assert aa.keys() == bb.keys()
        same, decoded = [], []
        for key, value in aa.items():
            if key == "progressive/manifest.json":
                continue
            if value == bb[key]:
                same.append(key)
            else:
                assert value.startswith(b'RSCC') and bb[key].startswith(b'RSCC'), key
                raw = logical(value)
                assert raw == logical(bb[key]), (label, key)
                decoded.append({"entry": key, "logicalBytes": len(raw), "logicalSha256": sha(raw)})
        checks.append({"chunk": label, "native": pin(pa), "mode5": pin(pb), "byteExactEntries": same, "decodedExactEntries": decoded})
    result = {"status": "PASS_EXACT_LOGICAL_NATIVE_WEB_TWIN", "pairs": checks,
        "manifestDifference": "Only physical chunk file names, sizes and SHA256 fields",
        "limits": "Actual complete resource byte equality, not Web renderer or performance acceptance."}
    write_json(OUT / "web-twin-proof.json", result)
    return ma


def run():
    assert not OUT.exists(), "One fresh native audit only"
    core_pins = {kind: pin(BUILD / kind / "index-lite.pck") for kind in PINS}
    assert all(core_pins[k]["sha256"] == value for k, value in PINS.items())
    assert pin(PROXY)["sha256"] == "dc01a9e7b19b2f4a1e3a16770cd4364dc76a7ff134825edf801cd8be4752c040"
    proxy = json.loads(PROXY.read_bytes())
    a, b = entries(BUILD / "native/index-lite.pck"), entries(BUILD / "mode5/index-lite.pck")
    previous = entries(ROOT / "artifacts/startup-v135/build/candidate-07/native/index-lite.pck")
    static_manifest = json.loads((STATIC / "manifest.json").read_bytes())
    assert pin(STATIC / "manifest.json")["sha256"] == "3aa2ebaf950b371b97b291b31668c6d047cf89ea4ea091996cc51361112a06f0"
    for item in static_manifest["entries"]:
        assert sha(a[item["entry"]]) == item["sha256"] and a[item["entry"]] == b[item["entry"]], "Encoded cache/runtime pins must work on both packs"
    proof = json.loads((BUILD / "script-proof.json").read_bytes())
    assert proof == json.loads((ROOT / "artifacts/startup-v135/build/candidate-07/script-proof.json").read_bytes())
    for name, key in [("meadow_scene", "mainGdcSha256"), ("meadow_progressive", "controllerGdcSha256")]:
        entry = "scripts/" + name + ".gdc"
        assert a[entry] == previous[entry] == b[entry] and sha(a[entry]) == proof[key]
    assert sha((BUILD / "meadow_scene.progressive.gd").read_bytes()) == proof["mainSourceSha256"]
    assert sha((ROOT / "godot/scripts/meadow_scene.gd").read_bytes()) == proof["originalSourceSha256"]
    assert sha((ROOT / "godot/scripts/meadow_progressive.gd").read_bytes()) == proof["controllerSourceSha256"]
    permitted = {x["entry"] for x in static_manifest["entries"]} | {"assets/baked/v77/terrain.scn", "assets/baked/v77/detail.scn"}
    assert set(a) - set(previous) <= permitted
    assert not (set(previous) - set(a))
    differences = {path for path in set(a) & set(previous) if a[path] != previous[path]}
    assert differences <= permitted, differences
    OUT.mkdir()
    private_harness = harness()
    manifest = twin(a, b)
    request = json.loads((OLD / "static-cache-native-01/request.json").read_bytes())
    request.update({"out": (OUT / "native.json").as_posix(), "corePack": core_pins["native"], "overlays": []})
    request["proxy02References"] = request["proxyContract"]["references"]
    request["originalMountainSource"] = pin(STATIC / "frozen/scripts/meadow_mountain_relief.gd")
    contract = json.loads(json.dumps(request["proxyContract"]))
    contract.update({"manifest": pin(PROXY), "proxyAoPrefix": 48360, "scriptContract": proof})
    for ref, label in zip(contract["references"], ["terrain-core", "detail-core"], strict=True):
        resource = proxy["resources"][label]
        info = resource["encodings"]["native"]
        assert pin(info["path"])["sha256"] == info["sha256"] == sha(a[ref["entry"]])
        assert sha(b[ref["entry"]]) == resource["encodings"]["mode5"]["sha256"]
        ref.update(pin(info["path"]))
    request["proxyContract"] = contract
    assert len(manifest["chunks"]) == len(request["detailPacks"]) == 12
    for chunk, spec in zip(request["detailPacks"], manifest["chunks"], strict=True):
        actual = BUILD / "native" / spec["file"]
        assert actual.read_bytes() == Path(chunk["file"]).read_bytes(), "Final twelve actual packs unchanged07"
        assert all(chunk[k] == value for k, value in spec.items() if k != "file")
        chunk["file"] = actual.as_posix()
    write_json(OUT / "request.json", request)
    source_paths = [ROOT / "godot/scripts/meadow_scene.gd", ROOT / "godot/scripts/meadow_progressive.gd",
        ROOT / "godot/scripts/meadow_static_geometry_cache.gd", ROOT / "godot/tools/audit_progressive_v135.candidate09.gd",
        ROOT / "godot/tools/audit_progressive_v135.candidate09.py", ROOT / "godot/tools/test_lite_runtime_v128.gd"]
    source_paths.extend(ROOT / "godot" / path for path in json.loads((OLD / "source-pins.json").read_bytes())["sources"])
    source_pins = [pin(path) for path in dict.fromkeys(source_paths)]
    write_json(OUT / "code-pins.json", {"sources": source_pins, "privateHarness": private_harness,
        "originalProductionMainAndControllerByteExact07": True, "scriptProof": proof})
    write_json(OUT / "pack-contract.json", {"core": core_pins, "proxyManifest": pin(PROXY),
        "supportManifest": pin(STATIC / "manifest.json"), "changedExistingEntriesVs07": sorted(differences),
        "all44EncodedSupportEntriesExactInBothPacks": True, "all12DetailPacksExact07": True,
        "proxyInitialAoPrefix": 48360, "finalAoPrefix": 317556})
    runtime = OUT / "runtime"
    runtime.mkdir()
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        path = OUT / key.lower()
        path.mkdir()
        env[key] = str(path)
    executable = STATIC / "compiler-runtime/Godot_v4.7.2-stable_win64.exe"
    command = [str(executable), "--headless", "--path", str(runtime), "--main-pack", core_pins["native"]["file"],
        "--log-file", str(OUT / "engine.log"), "--script", str(ROOT / "godot/tools/audit_progressive_v135.candidate09.gd"),
        "--", str(OUT / "request.json")]
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, env=env, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    elapsed = round(time.monotonic() - started, 3)
    log = result.stdout + result.stderr
    write(OUT / "process.log", log)
    intact = all(pin(row["file"]) == row for row in source_pins)
    intact = intact and all(pin(BUILD / k / "index-lite.pck") == row for k, row in core_pins.items())
    intact = intact and all(pin(c["file"])["sha256"] == c["sha256"] for c in request["detailPacks"])
    write_json(OUT / "invocation.json", {"command": command, "exitCode": result.returncode,
        "wallSeconds": elapsed, "nativeProcessCount": 1, "timeoutSeconds": 90, "engine": pin(executable), "allPinnedInputsFrozen": intact})
    reports = {}
    for name in ["native.json", "proxy-observations.json", "support-observations.json", "texture-observations.json",
                 "static-cache-observations.json", "proxy-context-observations.json"]:
        path = OUT / name
        if path.exists():
            record = json.loads(path.read_bytes())
            reports[name] = {**pin(path), "status": record["status"], "errors": record["errors"]}
    passed = result.returncode == 0 and intact and len(reports) == 6 and all(not r["errors"] for r in reports.values())
    passed = passed and b"SCRIPT ERROR" not in log and b"Parse Error" not in log
    summary = {"status": "PASS_ACTUAL09_NATIVE_COMPLETE_AND_TWIN" if passed else "FAIL",
        "core": core_pins, "reports": reports, "codePins": pin(OUT / "code-pins.json"),
        "twinProof": pin(OUT / "web-twin-proof.json"), "nativeProcessCount": 1,
        "nativeWallSecondsWholeAuditNotStartup": elapsed, "allPinnedInputsFrozen": intact,
        "limitations": ["No browser, network, GL shader compilation or visible frame evidence.",
                       "Existing deterministic clock/physics-audit controls affect the probe only."]}
    write_json(OUT / "validation.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    assert passed, "Preserve actual failed run; no silent retry"


if __name__ == '__main__':
    run()
