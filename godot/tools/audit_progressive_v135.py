"""Independent progressive-pack/source checks and one bounded native audit.

Writes only new artifacts/startup-v135/independent outputs. No export, engine
build, source patch, browser automation, or readiness/GL surrogate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import unittest

sys.dont_write_bytecode = True
from inspect_web_pack import read_pack

ROOT = Path(__file__).resolve().parents[2]
OWNED = ROOT / "artifacts/startup-v135/independent"
NATIVE = ROOT / "artifacts/startup-v128/combined-01/native-audit-twin.pck"
NATIVE_SHA = "83caf8ac1126ccacea3a2146109d234193a3de60a887cff2d383e4cfb21c6ce6"
ENGINE = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64.exe"
ENGINE_SHA = "ab1824f85bfd8e0e4128182c000c4003a3e042245b2967848d089b2a04b22424"
PROBE = Path(__file__).with_suffix(".gd")
REFERENCE_REPORT = ROOT / "artifacts/startup-v128/combined-01/runtime-01/combined.json"
REFERENCE_REPORT_SHA = "67757ec83385a75a315e8947f97679169df2b8a0c23a1d81c4a90d2117338764"
WATER_SOURCE = "res://assets/materials/river-ripples-v37.png"
SCENES = {
    "assets/baked/v77/terrain.scn": ["ContinuousMeadow"],
    "assets/baked/v77/detail.scn": ["SolidLimestoneGeology", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
    "assets/baked/v77/foothill.scn": ["CastleFoothillWoodland"],
    "assets/baked/v77/riverbank.scn": ["EmbeddedRiverbankStrata", "RootedRiparianCover"],
    "assets/baked/v77/brush.scn": ["MiddleMeadowBrush"],
    "assets/baked/v113/far-sward.scn": ["DistantMeadowSward"],
    "assets/baked/lite-v128/crown-edge-controller.scn": [],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pin(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"file": str(path), "bytes": path.stat().st_size, "sha256": digest}


def verify_pin(row):
    actual = pin(row["file"])
    require(actual["sha256"] == row["sha256"], f"Pin mismatch: {row['file']}")
    return actual


def write_new(path, data):
    path = Path(path).resolve()
    require(path.is_relative_to(OWNED.resolve()), "Output outside independent scope")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def json_new(path, value):
    write_new(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def entries(path):
    inventory = read_pack(Path(path), verify=True)
    require(inventory["version"] == 4, "Pinned project uses PCK v4")
    with Path(path).open("rb") as stream:
        result = {}
        for row in inventory["entries"]:
            stream.seek(row["offset"])
            result[row["path"]] = stream.read(row["bytes"])
    return result


def frozen_sources():
    paths = []
    for directory in ("scripts", "shaders", "assets", "scenes"):
        paths.extend(p for p in (ROOT / "godot" / directory).rglob("*") if p.is_file())
    paths.append(ROOT / "godot/project.godot")
    return [pin(p) for p in sorted(paths)]


def shader_inventory(pack):
    rows = []
    for path, data in pack.items():
        if path.endswith((".gdshader", ".gdshaderinc")):
            code = data.decode("utf-8")
            loops = [{"line": i, "text": line.strip()} for i, line in enumerate(code.splitlines(), 1)
                     if re.search(r"\b(for|while)\s*\(", line)]
            rows.append({"path": path, "bytes": len(data), "sha256": sha(data), "loops": loops,
                         "includes": re.findall(r'#include\s+"([^"]+)"', code),
                         "renderModes": re.findall(r"render_mode\s+([^;]+);", code),
                         "note": "Textual loop count is not generated GL variant count or measured compiler cost."})
    return rows


def source_review(out):
    require(not out.exists(), "Fresh source output required")
    verify_pin({"file": NATIVE, "sha256": NATIVE_SHA})
    verify_pin({"file": REFERENCE_REPORT, "sha256": REFERENCE_REPORT_SHA})
    pack = entries(NATIVE)
    references = []
    for i, (path, roots) in enumerate(SCENES.items()):
        data = pack[path]
        require(data[:4] == b"RSCC" and struct.unpack_from("<I", data, 4)[0] == 2,
                "Stock-codec reference required")
        target = out / "reference" / f"{i:02d}-{Path(path).name}"
        write_new(target, data)
        references.append({"resource": path, "roots": roots, **pin(target)})
    shaders = shader_inventory(pack)
    report = {"schema": "progressive-independent-source-v1", "nativeTwin": pin(NATIVE),
              "baselineReport": pin(REFERENCE_REPORT), "referenceScenes": references,
              "frozenSources": frozen_sources(), "shaders": shaders,
              "mainGdcSha256": sha(pack["scripts/meadow_scene.gdc"]),
              "entryCount": len(pack), "shaderEntryCount": len(shaders),
              "limitations": ["Read-only source/PCK review, no render/first-frame evidence.",
                              "Native twin is for auditing, never the shipping byte budget."]}
    json_new(out / "source.json", report)
    print(json.dumps({"sourceReport": str(out / "source.json"), "entries": len(pack),
                      "shaderEntries": len(shaders), "references": len(references)}, indent=2))


def compare_frozen_payloads(baseline, candidate):
    # Shaders, textures and their maps are never a partitioning casualty.
    exact, missing, changed = [], [], []
    for path, data in baseline.items():
        if path.endswith((".gdshader", ".gdshaderinc", ".ctex", ".import")):
            if path not in candidate:
                missing.append(path)
            elif candidate[path] != data:
                changed.append(path)
            else:
                exact.append(path)
    return {"exact": exact, "missing": missing, "changed": changed}


def stock_codecs(pack):
    return {path: struct.unpack_from("<I", data, 4)[0] for path, data in pack.items()
            if data[:4] == b"RSCC"}


def make_plan(core_path, source_report, out):
    pack = entries(core_path)
    manifest = json.loads(pack["progressive/manifest.json"])
    require(manifest["version"] == 1, "Actual mounted manifest version 1")
    groups = []
    for chunk in manifest["chunks"]:
        roots = []
        for part in chunk["scenes"]:
            parent = part.get("parent", ".")
            roots.extend(name if parent == "." else parent + "/" + name for name in part["roots"])
        group = {**chunk, "file": str((core_path.parent / chunk["file"]).resolve()), "roots": roots}
        verify_pin(group)
        groups.append(group)
    plan = {"corePack": pin(core_path), "detailPacks": groups, "controllerMethod": "apply_chunk",
            "controllerScript": "res://scripts/meadow_progressive.gd", "sourceReport": str(source_report.resolve()),
            "waterTextureProgression": "Only water's existing mip suffix is initially coarse; exact full CTEX in last chunk.",
            "baselinePathAliases": {},
            "aliasScope": "Candidate-02 retains the actual MeadowEdgeGrowth parent; candidate-01 is rejected."}
    validate_plan(plan)
    json_new(out, plan)
    print(json.dumps({"plan": str(out), "coreSha256": plan["corePack"]["sha256"], "chunks": len(groups)}, indent=2))


def validate_plan(plan):
    require(isinstance(plan.get("corePack"), dict), "corePack file + sha256 required")
    require(isinstance(plan.get("detailPacks"), list), "Ordered detailPacks required")
    roots = [root for group in plan["detailPacks"] for root in group["roots"]]
    require(roots and len(roots) == len(set(roots)), "Each deferred root occurs exactly once")
    require(all(isinstance(root, str) and root and not root.startswith("/") and ".." not in root
                for root in roots), "Exact safe node paths required")
    require([group["index"] for group in plan["detailPacks"]] == list(range(len(plan["detailPacks"]))),
            "Contiguous zero-based group indexes required")
    require(isinstance(plan.get("controllerMethod"), str) and plan["controllerMethod"],
            "Use the observed native controller method, not a guessed callback")
    require(plan.get("controllerScript") == "res://scripts/meadow_progressive.gd",
            "Only main's progressive controller")
    return roots


def native_audit(request_path, out, timeout):
    require(out.is_relative_to(OWNED.resolve()), "Output outside independent scope")
    require(not out.exists(), "Fresh native output required")
    require(1 <= timeout <= 240, "Bounded timeout <=240 seconds")
    plan = json.loads(request_path.read_text(encoding="utf-8"))
    roots = validate_plan(plan)
    source_path = Path(plan["sourceReport"]).resolve()
    source = json.loads(source_path.read_text(encoding="utf-8"))
    verify_pin({"file": ROOT / "godot/tools/test_lite_runtime_v128.gd",
                "sha256": "e1029c656e5c9f35ea022c18c8f02a801e9ea67602e69a7282314ab5ab65051e"})
    verify_pin({"file": ENGINE, "sha256": ENGINE_SHA})
    verify_pin(source["nativeTwin"])
    baseline = entries(Path(source["nativeTwin"]["file"]))
    core_pin = verify_pin(plan["corePack"])
    core = entries(Path(core_pin["file"]))
    transport = compare_frozen_payloads(baseline, core)
    water_import = baseline[WATER_SOURCE[6:] + ".import"].decode("utf-8")
    water_ctex = re.search(r'^path="res://([^"]+)"', water_import, re.M).group(1)
    require(not transport["missing"] and set(transport["changed"]) <= {water_ctex},
            "Only authorized water mip suffix may differ; other textures/maps/shaders exact")
    if transport["changed"]:
        require(plan.get("waterTextureProgression"), "Explicit water progression contract required")
        original, initial = baseline[water_ctex], core[water_ctex]
        require(original[:36] == initial[:36], "Water CTEX logical dimensions/header retained")
        require(struct.unpack_from("<I", initial, 36)[0] == 2, "Pinned WebP CTEX")
    texture_rows = [(i, row) for i, group in enumerate(plan["detailPacks"]) for row in group.get("textures", [])]
    require(len(texture_rows) == 1 and texture_rows[0][0] == len(plan["detailPacks"]) - 1,
            "Exactly one water upgrade after all geometry")
    require(texture_rows[0][1]["source"] == WATER_SOURCE, "Only water texture upgrade")
    last_pack = entries(Path(plan["detailPacks"][-1]["file"]))
    require(last_pack[texture_rows[0][1]["resource"][6:]] == baseline[water_ctex], "Final water CTEX byte-exact baseline")
    packs = []
    for row in [plan["corePack"], *plan["detailPacks"]]:
        packs.append(verify_pin(row))
        codecs = stock_codecs(entries(Path(row["file"])))
        require(all(mode in (0, 1, 2, 3, 4) for mode in codecs.values()),
                "Stock-native audit requires verified standard-codec twin, not mode5 shipping pack")
    for row in source["referenceScenes"]:
        verify_pin(row)
    frozen = frozen_sources()
    expected = {"nodePaths": [], "report": source["baselineReport"],
                "referenceScenes": source["referenceScenes"], "coreWaterCtexSha256": sha(core[water_ctex]),
                "waterCtex": water_ctex, "fullWaterCtexSha256": sha(baseline[water_ctex])}
    verify_pin(expected["report"])
    expanded = {**plan, "corePack": core_pin, "expected": expected, "out": str((out / "native.json").resolve()),
                "deferredRoots": roots, "captureKind": "headless_no_render"}
    out.mkdir(parents=True)
    runtime = out / "runtime"
    runtime.mkdir()
    json_new(out / "request.json", expanded)
    command = [str(ENGINE), "--headless", "--path", str(runtime), "--main-pack", core_pin["file"],
               "--log-file", str(out / "engine.log"), "--script", str(PROBE), "--", str(out / "request.json")]
    env = os.environ.copy()
    for name in ("APPDATA", "LOCALAPPDATA"):
        target = runtime / name.lower()
        target.mkdir()
        env[name] = str(target)
    lock = OWNED / "native-process.lock"
    with lock.open("x", encoding="ascii") as stream:
        stream.write(str(os.getpid()))
    started = time.monotonic()
    record = {"command": command, "engine": pin(ENGINE), "probe": pin(PROBE), "packs": packs,
              "timeoutSeconds": timeout, "captureKind": "headless_no_render", "sourceReport": pin(source_path)}
    try:
        with (out / "console.log").open("xb") as log:
            process = subprocess.Popen(command, cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            record["pid"] = process.pid
            try:
                record["exitCode"] = process.wait(timeout=timeout)
                record["timedOut"] = False
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                record.update(exitCode=process.returncode, timedOut=True)
    finally:
        lock.unlink()
        record["wallSeconds"] = round(time.monotonic() - started, 3)
        record["allFrozenSourcesExact"] = all(pin(row["file"])["sha256"] == row["sha256"] for row in frozen)
        record["allInputPacksExact"] = all(pin(row["file"])["sha256"] == row["sha256"] for row in packs)
        json_new(out / "invocation.json", record)
    require(record.get("exitCode") == 0 and not record.get("timedOut"), "Native audit failed; see preserved logs")
    require("SCRIPT ERROR:" not in (out / "console.log").read_text(encoding="utf-8", errors="replace"),
            "Actual GDScript runtime/parser errors cannot be accepted")
    report = json.loads((out / "native.json").read_text(encoding="utf-8"))
    require(report.get("status") == "PASS_CPU_STRUCTURAL_ONLY", "Native checks did not pass")
    require(record["allFrozenSourcesExact"] and record["allInputPacksExact"], "Frozen inputs changed")
    json_new(out / "payload-proof.json", {"frozenCorePayloads": transport, "baseline": pin(NATIVE),
                                        "core": core_pin, "detailPacks": packs[1:]})
    print(json.dumps({"status": report["status"], "wallSeconds": record["wallSeconds"],
                      "report": str(out / "native.json"), "cpu": report.get("cpu"),
                      "renderAcceptance": "NOT TESTED: main-owned Web draw, network and visual acceptance"}, indent=2))


class Tests(unittest.TestCase):
    def test_duplicate_roots_rejected(self):
        plan = {"corePack": {}, "detailPacks": [{"index": 0, "roots": ["A", "A"]}],
                "controllerMethod": "observed", "controllerScript": "res://scripts/meadow_progressive.gd"}
        with self.assertRaisesRegex(ValueError, "exactly once"):
            validate_plan(plan)

    def test_shader_or_texture_change_not_hidden(self):
        result = compare_frozen_payloads({"a.gdshader": b"A", "b.ctex": b"B", "ignored.gdc": b"C"},
                                         {"a.gdshader": b"Z", "ignored.gdc": b"D"})
        self.assertEqual(result["changed"], ["a.gdshader"])
        self.assertEqual(result["missing"], ["b.ctex"])

    def test_codec_detection(self):
        self.assertEqual(stock_codecs({"x": b"RSCC" + struct.pack("<I", 5), "y": b"text"}), {"x": 5})

    def test_no_output_escape(self):
        with self.assertRaisesRegex(ValueError, "scope"):
            write_new(ROOT / "unowned-v135-test", b"no")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    review = sub.add_parser("source")
    review.add_argument("--out", type=Path, required=True)
    native = sub.add_parser("native")
    native.add_argument("--request", type=Path, required=True)
    native.add_argument("--out", type=Path, required=True)
    native.add_argument("--timeout", type=int, default=120)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--core", type=Path, required=True)
    plan_parser.add_argument("--source-report", type=Path, required=True)
    plan_parser.add_argument("--out", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.mode == "source":
        source_review(args.out.resolve())
    elif args.mode == "native":
        native_audit(args.request.resolve(), args.out.resolve(), args.timeout)
    elif args.mode == "plan":
        make_plan(args.core.resolve(), args.source_report.resolve(), args.out.resolve())
    else:
        unittest.main(argv=[sys.argv[0]], verbosity=2)
