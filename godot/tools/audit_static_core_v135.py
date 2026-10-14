"""Prepare/run/compare an independent static-core audit after explicit authorization.

prepare requires the actual assembled candidate and reviewed entry-change pins.
It writes two requests and explicit native CLIs into a NEW directory. Run them
only after main authorizes the candidate, in separate fresh processes, then
compare. No capture/prebuild/warmup is performed by this harness or its probe.

Allowed-change JSON (no wildcards): {"sourceSha256": "...", "candidateSha256":
"...", "changes": [{"path": "scripts/meadow_scene.gdc", "beforeSha256": "...",
"afterSha256": "..."}, {"path": "scenes/main.tscn.remap", "beforeSha256": "...",
"afterSha256": "..."}, {"path": "progressive/static-core/world.scn",
"beforeSha256": null, "afterSha256": "..."}, ...]}. Only private main and the
explicitly pinned main.tscn.remap may replace old entries. New static resources
and the exact private restore.gdc/remap pair need individual pins, never globs.
The final 403-byte thin scene has root, dummy camera and the original EdgeGrowth
controller. Only the 26 exact deletion pins in the reviewed final overlay are
allowed (not a prefix rule). A deletion may also be listed in changes with
afterSha256=null. Pretty/compact progressive manifests have separate frozen pins
and must decode to the same complete JSON value.
This is an identity gate, NOT approval of arbitrary new resources or main code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath

from inspect_web_pack import read_pack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v135/independent/static-core"
SOURCE = ROOT / "artifacts/startup-v135/build/candidate-10/native/index-lite.pck"
SOURCE_SHA = "7622eb8f1c0f687a9c640ac0e2e0c818e005ad4ff6605fc353368849768d1988"
FINAL_OVERLAY = ROOT / "artifacts/startup-v135/static-core/candidate-01/manifest.json"
FINAL_OVERLAY_SHA = "64431a48225cdf625bc8a8a346fb83f284246523f20912679e9868b1d5222afb"
THIN_SHA = "608a0ca3f6598eb98f28c1c780e6e47a7718a74803ee224c398af596e265b885"
EXTERNAL_MANIFEST_SHA = "d01af3a6844bbf4ac8d2d18c27f415f026c7689cdccd7d50d116a59647674ab4"
EMBEDDED_MANIFEST_SHA = "fe0a534353ed6110f2a7088ffd0defd46e0215a152f2e516d8e684b5ef70bb36"
RESTORE = {"progressive/static-core/restore.gdc", "progressive/static-core/restore.gd.remap"}
PROBE = Path(__file__).with_suffix(".gd")
ENCODER = PROBE.with_name("audit_lite_runtime.gd")
EVIDENCE = {
    "integrated10-native-01": "487e0442ec9d4b6a4546682a9fd2a54069e1a50b75af85af7d8a07f21fd4dbc2",
    "integrated12-native-01": "47220154013b94e9acf3e0a51f1021e2850434a000cd08e1356d0d3833d885e1",
}
LABELS = ["core", "transition-half", "reduced-night", "reduced-day"] + [f"chunk-{i}" for i in range(12)] + ["final-night", "final-day"]
LIGHTS = {"DirectionalLight3D": 4, "OmniLight3D": 9, "SpotLight3D": 0, "AreaLight3D": 0}
LIMITS = ["Native structural comparison only; no Web/GPU/presentation or <=10s claim.",
          "Dummy renderer cannot observe live shader globals; main owns real day/night/motion validation.",
          "Separate native process per input; CPU span includes resource load/instantiate/ready, not process/PCK mount.",
          "Offline capture is a build step, never run before the candidate's measured startup.",
          "Exact equality by default; no geometry/transform tolerance or hash normalization bypass."]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"file": path.as_posix(), "bytes": path.stat().st_size, "sha256": digest}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pack_entries(path):
    result = {}
    with Path(path).open("rb") as stream:
        for entry in read_pack(Path(path))["entries"]:
            name = entry["path"]
            parts = PurePosixPath(name).parts
            require(parts and not name.startswith(("/", "res://")) and ".." not in parts and "\\" not in name,
                    "Unsafe pack entry")
            stream.seek(entry["offset"])
            data = stream.read(entry["bytes"])
            result[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return result


def check_changes(source, candidate, changes):
    removals = approved_removals()
    require(isinstance(changes, list) and 2 <= len(changes) <= 16 + len(removals), "Explicit bounded changes required")
    names = [row["path"] for row in changes]
    require(len(names) == len(set(names)), "Duplicate change record")
    require("scripts/meadow_scene.gdc" in names, "Private compiled main must be explicitly pinned")
    require(set(source) - set(candidate) == set(removals), "Only ALL 26 reviewed exact deletions are permitted")
    for name, digest in removals.items():
        require(source[name]["sha256"] == digest, "Deleted source entry has wrong reviewed pin: " + name)
    observed = {name for name in candidate if source.get(name) != candidate[name]}
    declared_present = {row["path"] for row in changes if row.get("afterSha256") is not None}
    require(observed == declared_present, "Actual PCK changes differ from explicit manifest")
    for row in changes:
        name = row["path"]
        old = source.get(name)
        require(row.get("beforeSha256") == (old["sha256"] if old else None), "Wrong before pin: " + name)
        if row.get("afterSha256") is None:
            require(name in removals and row["beforeSha256"] == removals[name], "Unreviewed deletion record: " + name)
            continue
        require(row["afterSha256"] == candidate[name]["sha256"], "Wrong after pin: " + name)
        if old is not None:
            require(name in {"scripts/meadow_scene.gdc", "scenes/main.tscn.remap"}, "Only private main/thin entry mapping can change: " + name)
        else:
            require(name in RESTORE | {"scenes/main.tscn", "progressive/static-core/manifest.json"}
                    or (name.startswith("progressive/static-core/") and PurePosixPath(name).suffix in {".scn", ".res", ".tscn"}),
                    "Only explicit private static-core resource entries: " + name)
    require("scenes/main.tscn.remap" in names, "Old export remap would still load heavy main scene")
    require(not (RESTORE & set(names)) or RESTORE <= set(names), "Private restore script/remap must be paired")
    return {"unchangedEntries": len(set(source) & set(candidate)) - len(declared_present & set(source)), "changes": changes,
            "removedEntries": removals, "removalAuthoritySha256": FINAL_OVERLAY_SHA,
            "semanticStatus": "PENDING_ACTUAL_NATIVE_AND_PRIVATE_MAIN_SOURCE_REVIEW"}


def approved_removals():
    blob = FINAL_OVERLAY.read_bytes()
    require(hashlib.sha256(blob).hexdigest() == FINAL_OVERLAY_SHA, "Reviewed final overlay manifest changed")
    manifest = json.loads(blob)
    require(manifest["status"] == "PASS_STATIC_RESTORE" and manifest["sourcePacks"]["native"] == SOURCE_SHA,
            "Deletion authority must be reviewed source10 restore04")
    rows = manifest["removeEntries"]
    require(len(rows) == 26 and len({row["entry"] for row in rows}) == 26, "Exactly 26 individually pinned removals")
    return {row["entry"]: row["beforeSha256"] for row in rows}


def check_progressive_manifests(external, embedded):
    require(hashlib.sha256(external).hexdigest() == EXTERNAL_MANIFEST_SHA, "Frozen pretty manifest pin")
    require(hashlib.sha256(embedded).hexdigest() == EMBEDDED_MANIFEST_SHA, "Frozen embedded compact manifest pin")
    outer, inner = json.loads(external), json.loads(embedded)
    require(outer == inner, "Complete decoded progressive manifests differ")
    return outer


def entry_bytes(pack, name):
    item = next(row for row in read_pack(Path(pack), verify=False)["entries"] if row["path"] == name)
    with Path(pack).open("rb") as stream:
        stream.seek(item["offset"])
        return stream.read(item["bytes"])


def thin_target(remap):
    match = re.fullmatch(r'\s*\[remap\]\s*path\s*=\s*"res://([^"]+)"\s*', remap)
    require(match is not None, "Explicit single main-scene remap required")
    target = match[1]
    require(target == "progressive/static-core/entry.tscn", "Only reviewed final thin entry remap accepted")
    return target


def check_thin_entry(text, original_text):
    """Fail closed text-scene check; no Godot loader or scene evaluation."""
    encoded = text.encode("utf-8")
    require(len(encoded) == 403 and hashlib.sha256(encoded).hexdigest() == THIN_SHA, "Exact reviewed 403-byte thin entry pin")
    headers = re.findall(r"^\[([^\n]+)\]", text, re.M)
    require(len(headers) == 6 and headers[0].startswith("gd_scene "), "Thin entry: scene/two scripts/three nodes only")
    external = [h for h in headers if h.startswith("ext_resource ")]
    require(len(external) == 2 and all('type="Script"' in row for row in external)
            and 'path="res://scripts/meadow_scene.gd"' in external[0]
            and 'path="res://scripts/meadow_edge_growth.gd"' in external[1], "Only main and original EdgeGrowth scripts; no heavy scenes")
    nodes = [h for h in headers if h.startswith("node ")]
    original_root = re.search(r'^\[node name="([^"]+)" type="Node3D"[^\n]*\]', original_text, re.M)
    require(original_root is not None and len(nodes) == 3, "Exact root/camera/original EdgeGrowth required")
    require(re.fullmatch(r'node name="' + re.escape(original_root[1]) + r'" type="Node3D"', nodes[0]) is not None,
            "Thin root name/type/ownership changed")
    require(nodes[1] == 'node name="Camera3D" type="Camera3D" parent="."', "Only one dummy Camera3D child")
    require(nodes[2] == 'node name="MeadowEdgeGrowth" type="Node3D" parent="."', "Original EdgeGrowth is retained, not baked-ready")
    assignments = re.findall(r"^(\w+)\s*=", text, re.M)
    require(set(assignments) <= {"script", "transform", "position", "rotation", "scale", "current", "fov", "near", "far", "keep_aspect"},
            "Unexpected thin-scene property/resource")
    require("SubResource(" not in text and len(re.findall(r"^script\s*=\s*ExtResource\(", text, re.M)) == 2, "Exactly two actual script attachments")
    script_id = re.search(r'\bid="([^"]+)"', external[0])
    root_body = re.split(r"^\[node ", text, flags=re.M)[1]
    require(script_id is not None and re.search(r'^script\s*=\s*ExtResource\("' + re.escape(script_id[1]) + r'"\)', root_body, re.M),
            "Actual private script must attach to root, using declared ID")
    def root_transform(source):
        root = re.split(r"^\[node ", source, flags=re.M)[1]
        return [(key, value.strip()) for key, value in re.findall(r"^(transform|position|rotation|scale)\s*=\s*(.+)$", root, re.M)]
    require(root_transform(text) == root_transform(original_text), "Original root transform must remain exact")
    return {"thinEntry": True, "nodeCountBeforeReady": 3, "heavyScenePreloads": 0, "sha256": THIN_SHA}


def prepare(candidate, allowed_file, engine, out):
    out = Path(out).resolve()
    require(out.is_relative_to(SCOPE.resolve()) and out != SCOPE.resolve() and not out.exists(), "Fresh scoped output directory only")
    original_pin, candidate_pin, engine_pin = pin(SOURCE), pin(candidate), pin(engine)
    require(original_pin["sha256"] == SOURCE_SHA, "Frozen actual10 source core pin")
    allowed = read_json(allowed_file)
    require(allowed["sourceSha256"] == SOURCE_SHA and allowed["candidateSha256"] == candidate_pin["sha256"], "Source/candidate pins do not match")
    prior = {}
    for folder, digest in EVIDENCE.items():
        item = pin(ROOT / "artifacts/startup-v135/support/candidate-01" / folder / "validation.json")
        require(item["sha256"] == digest, "Prior actual10/12 evidence changed")
        prior[folder] = item
    entries = pack_entries(SOURCE)
    candidate_entries = pack_entries(candidate)
    identity = check_changes(entries, candidate_entries, allowed["changes"])
    target = thin_target(entry_bytes(candidate, "scenes/main.tscn.remap").decode("utf-8"))
    # Actual10's main root is MeadowPlain / identity; the native probe asserts
    # this in BOTH inputs before _ready as well (not inferred from worktree TSCN).
    identity["entry"] = check_thin_entry(entry_bytes(candidate, target).decode("utf-8"),
                                         '[node name="MeadowPlain" type="Node3D"]\n')
    identity["entry"]["resolvedRemap"] = target
    # Pretty/compact encodings legitimately differ; independently pin BOTH,
    # compare the whole decoded JSON, then rehash every exact approved chunk.
    manifest_path = SOURCE.parent / "progressive-manifest.json"
    manifest = check_progressive_manifests(manifest_path.read_bytes(), entry_bytes(SOURCE, "progressive/manifest.json"))
    require(manifest["version"] == 1 and len(manifest["chunks"]) == 12, "Actual twelve-chunk manifest required")
    chunks = []
    for index, row in enumerate(manifest["chunks"]):
        require(row["index"] == index and Path(row["file"]).name == row["file"], "Ordered root-level chunk file required")
        chunk = pin(SOURCE.parent / row["file"])
        require(chunk["sha256"] == row["sha256"] and chunk["bytes"] == row["bytes"], "Frozen actual10 chunk pin")
        chunks.append({**row, **chunk})
    out.mkdir(parents=True)
    requests, commands = {}, {}
    for role, core, inventory in [("source", original_pin, entries), ("candidate", candidate_pin, candidate_entries)]:
        directory = out / role
        directory.mkdir()
        request = {"schema": "static-core-request-v1", "role": role, "corePack": core,
                   "entryCount": len(inventory), "detailPacks": chunks, "probe": pin(PROBE), "encoder": pin(ENCODER),
                   "out": (directory / "native.json").as_posix()}
        path = directory / "request.json"
        write_new(path, request)
        requests[role] = pin(path)
        commands[role] = [engine_pin["file"], "--headless", "--path", directory.as_posix(),
                          "--main-pack", core["file"], "--log-file", (directory / "engine.log").as_posix(),
                          "--script", PROBE.as_posix(), "--", path.as_posix()]
    result = {"schema": "static-core-prepared-v1", "status": "PREPARED_NOT_RUN", "identity": identity,
              "engine": engine_pin, "allowedChanges": pin(allowed_file), "priorEvidence": prior,
              "finalOverlay": pin(FINAL_OVERLAY), "progressiveManifestPins": {"external": pin(manifest_path), "embeddedSha256": EMBEDDED_MANIFEST_SHA},
              "requests": requests, "commandsOnlyNotExecuted": commands, "limits": LIMITS,
              "runInstructions": "Main authorization first. Separate processes with fresh local APPDATA/LOCALAPPDATA/TEMP/TMP per run, <=90s cap; no parallel native audit. Never run the capture builder here."}
    write_new(out / "prepared.json", result)
    return result


def check_timing(timing):
    keys = ["probeEnteredUs", "loadBeginUs", "loadEndUs", "instantiateEndUs", "readyEndUs", "firstObservationUs"]
    values = [timing[k] for k in keys]
    require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values), "Invalid CPU markers")
    require(values == sorted(values) and values[4] > values[1], "CPU markers inverted/empty")
    for key, start, end in [("loadMainMs", 1, 2), ("instantiateMs", 2, 3), ("readyCallMs", 3, 4), ("cpuLoadThroughReadyMs", 1, 4)]:
        require(timing[key] == (values[end] - values[start]) / 1000, "CPU span excludes work or is invented: " + key)
    for key in ["offlineCaptureIncluded", "probePreloadsWorld", "packMountIncluded", "renderReadyClaim"]:
        require(timing[key] is False, "Unsupported startup measurement claim: " + key)


def differences(a, b, path="", found=None):
    found = [] if found is None else found
    if len(found) >= 40:
        return found
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                found.append(path + "/" + str(key) + ": missing/extra")
            else:
                differences(a[key], b[key], path + "/" + str(key), found)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            found.append(path + ": length")
        for index, (left, right) in enumerate(zip(a, b)):
            differences(left, right, path + "/" + str(index), found)
    elif a != b or isinstance(a, bool) != isinstance(b, bool):
        found.append(path + ": value")
    return found[:40]


def compare_reports(source, candidate):
    for report in (source, candidate):
        require(report["schema"] == "static-core-observation-v1" and report["status"] == "OBSERVED_CPU_ONLY" and not report["errors"], "Native report failed/incomplete")
        binding = report["packBinding"]
        require(binding["allLoadedEntryMd5Match"] is True and binding["entryCount"] == binding["matchedLoadedEntries"], "Mounted pack not fully bound")
        check_timing(report["timing"])
        require([s["contract"]["label"] for s in report["snapshots"]] == LABELS, "Missing/reordered core/transition/chunk/final snapshots")
        require([c["index"] for c in report["chunks"]] == list(range(12)), "Missing/reordered chunk application")
        for snapshot in report["snapshots"]:
            contract = snapshot["contract"]
            require(contract["lights"] == LIGHTS and len(contract["colliders"]) == 5, "Light/collider regression")
            require(contract["nodes"] and contract["resources"] and contract["members"], "Empty scene graph")
        require(len(report["routes"]) == 2 and all(r["pauseExact"] and r["invalidSampledPoints"] == 0 for r in report["routes"]), "Route/pause checks missing/failed")
        require(len(report["inputChecks"]) == 3 and all(row["after"] != row["before"] for row in report["inputChecks"]), "Missing actual C/D/G input test")
    diff = differences(source["startup"], candidate["startup"], "/startup")
    differences(source["inputChecks"], candidate["inputChecks"], "/inputChecks", diff)
    differences([s["contract"] for s in source["snapshots"]], [s["contract"] for s in candidate["snapshots"]], "/snapshots", diff)
    differences(source["routes"], candidate["routes"], "/routes", diff)
    differences([(c["index"], c["sha256"]) for c in source["chunks"]], [(c["index"], c["sha256"]) for c in candidate["chunks"]], "/chunkPins", diff)
    return {"status": "PASS_NATIVE_EXACT_STATIC_CORE_CONTRACT" if not diff else "FAIL", "differences": diff[:40],
            "sourceCore": source["corePack"], "candidateCore": candidate["corePack"],
            "cpuObservationsNotWebBenchmark": {"source": source["timing"], "candidate": candidate["timing"]},
            "limits": LIMITS}


def compare_prepared(prepared_file):
    prepared = read_json(prepared_file)
    require(prepared["schema"] == "static-core-prepared-v1", "Prepared request required")
    reports = []
    for role in ["source", "candidate"]:
        request_pin = prepared["requests"][role]
        require(pin(request_pin["file"]) == request_pin, "Request mutated")
        request = read_json(request_pin["file"])
        for item in [request["corePack"], request["probe"], request["encoder"], prepared["engine"]] + request["detailPacks"]:
            actual = pin(item["file"])
            require(actual["sha256"] == item["sha256"] and actual["bytes"] == item["bytes"], "Audit input/source mutated")
        report = read_json(request["out"])
        require(report["requestSha256"] == request_pin["sha256"] and report["corePack"] == request["corePack"], "Report/core/request mixed")
        require(report["packBinding"]["entryCount"] == request["entryCount"], "Wrong mounted inventory")
        if role == "candidate":
            require(report["entryBeforeReady"] == {"nodes": 3, "meshes": 0, "shapes": 0}, "Actual entry loaded old heavy scene")
        log = Path(request["out"]).with_name("engine.log").read_text(encoding="utf-8")
        require(not any(token in log for token in ["SCRIPT ERROR:", "Parse Error:", "ERROR:"]), "Native engine error; no silent acceptance")
        reports.append(report)
    return compare_reports(*reports)


def invoke_bounded(command, directory, timeout_seconds):
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 90, "Native timeout must be 1..90 seconds")
    directory = Path(directory).resolve()
    require(directory.is_relative_to(SCOPE.resolve()), "Only owned native output directory")
    runtime = directory / "fresh-runtime"
    require(not runtime.exists() and not (directory / "process.json").exists(), "Never rerun/overwrite an observed role")
    runtime.mkdir()
    env = os.environ.copy()
    for key in ["APPDATA", "LOCALAPPDATA", "TEMP", "TMP"]:
        target = runtime / key.lower()
        target.mkdir()
        env[key] = str(target)
    # Run the actual binary, not the console launcher (which spawns a child).
    # A's original directory has _sc_; copying the identical executable avoids
    # writing its self-contained editor_data and bounds termination to one PID.
    executable = Path(command[0])
    require(not executable.stem.endswith("_console"), "Use actual Godot exe, not a child-process launcher")
    private_exe = runtime / "Godot.exe"
    shutil.copyfile(executable, private_exe)
    require(pin(executable)["sha256"] == pin(private_exe)["sha256"], "Private executable copy mismatch")
    actual_command = [str(private_exe), *command[1:]]
    started = time.perf_counter()
    result = {"status": "NOT_STARTED", "timeoutSeconds": timeout_seconds, "command": actual_command,
              "engine": pin(private_exe), "freshEnvironment": {k: env[k] for k in ["APPDATA", "LOCALAPPDATA", "TEMP", "TMP"]}}
    with (directory / "stdout.log").open("xb") as stream:
        try:
            process = subprocess.run(actual_command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT, timeout=timeout_seconds,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                     check=False, shell=False)
            result.update(status="EXITED", exitCode=process.returncode)
        except subprocess.TimeoutExpired:
            # subprocess.run kills AND waits for this direct child on timeout.
            result.update(status="TIMEOUT_KILLED", exitCode=None)
        except OSError as exc:
            result.update(status="LAUNCH_FAILED", exitCode=None, error=str(exc))
    result["processWallSecondsNotWebTiming"] = time.perf_counter() - started
    write_new(directory / "process.json", result)
    return result


def run_role(prepared_file, role, timeout_seconds):
    prepared_file = Path(prepared_file).resolve()
    require(prepared_file.is_relative_to(SCOPE.resolve()), "Owned prepared inputs only")
    prepared = read_json(prepared_file)
    require(prepared["schema"] == "static-core-prepared-v1", "Prepared request required")
    if role == "candidate":
        prior = read_json(prepared_file.parent / "source/process.json")
        require(prior["status"] == "EXITED" and prior["exitCode"] == 0, "Source must finish successfully before candidate starts")
    request_pin = prepared["requests"][role]
    require(pin(request_pin["file"]) == request_pin, "Request mutated")
    request = read_json(request_pin["file"])
    for item in [request["corePack"], request["probe"], request["encoder"], prepared["engine"]] + request["detailPacks"]:
        current = pin(item["file"])
        require(current["sha256"] == item["sha256"] and current["bytes"] == item["bytes"], "Audit input/source mutated")
    directory = prepared_file.parent / role
    require(Path(request["out"]).resolve() == directory / "native.json" and not Path(request["out"]).exists(), "Fresh report only")
    command = [prepared["engine"]["file"], "--headless", "--path", directory.as_posix(),
               "--main-pack", request["corePack"]["file"], "--log-file", (directory / "engine.log").as_posix(),
               "--script", request["probe"]["file"], "--", request_pin["file"]]
    require(command == prepared["commandsOnlyNotExecuted"][role], "Command differs from pinned preparation")
    return invoke_bounded(command, directory, timeout_seconds)


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="pins/requests only, NO native process")
    for name in ["candidate", "allowed-changes", "engine", "out"]:
        p.add_argument("--" + name, type=Path, required=True)
    p = commands.add_parser("compare")
    p.add_argument("prepared", type=Path)
    p = commands.add_parser("run-role", help="ONLY after main authorizes actual native; never run roles concurrently")
    p.add_argument("prepared", type=Path)
    p.add_argument("role", choices=["source", "candidate"])
    p.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.candidate, args.allowed_changes, args.engine, args.out)
    elif args.command == "run-role":
        result = run_role(args.prepared, args.role, args.timeout)
    else:
        result = compare_prepared(args.prepared)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result["status"] in {"FAIL", "TIMEOUT_KILLED", "LAUNCH_FAILED"} or result.get("exitCode", 0) not in (None, 0))


if __name__ == "__main__":
    raise SystemExit(main())
