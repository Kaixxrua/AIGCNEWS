"""Bounded stock-Godot script compilation in NEW artifact-only projects.

Never writes the source project, original PCK, geometry, or another builder.
Default input is the immediate frozen pre-main-edit source. Output .gdc must be
emitted by stock Godot, never by Python token invention/patching.
"""
from __future__ import annotations
import argparse
import difflib
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
from inspect_web_pack import read_pack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/loading-v115/startup"
GODOT = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe"
PACK = ROOT / "artifacts/v114/index.pck"
SOURCE = SCOPE / "freeze-01/meadow_scene.original.gd"
SOURCE_SHA = "3477a2bd4bd67c8de488b977c81ffa76726844e004886b86b77e6f3d2b519d12"
SCRIPT_ENTRY = "scripts/meadow_scene.gdc"
SCRIPT_SHA = "2a6ec2c6ffbf82013ba2e101c15c063affca22548b6f12e0c7e35280d0ee7be8"
PACK_SHA = "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d"
ADDED_METHODS = ["_startup_audit_enabled", "_report_startup_audit"]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def new_dir(path):
    path = Path(path).resolve()
    if SCOPE.resolve() != SCOPE or not path.is_relative_to(SCOPE) or path == SCOPE or path.exists():
        raise ValueError("Require a NEW directory inside startup artifacts")
    path.mkdir(parents=True)
    return path

def write(path, data):
    path = Path(path)
    if not path.resolve().is_relative_to(SCOPE) or path.is_symlink():
        raise ValueError("Startup artifact write scope violation")
    with path.open("xb") as file:
        file.write(data)
    if path.read_bytes() != data:
        raise ValueError("Artifact readback mismatch")

def write_json(path, value):
    write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())

def packed_entries(path):
    result = {}
    with Path(path).open("rb") as stream:
        for row in read_pack(Path(path), verify=True)["entries"]:
            stream.seek(row["offset"])
            result[row["path"].removeprefix("res://")] = stream.read(row["bytes"])
    return result

def pin_original():
    source = SOURCE.read_bytes()
    if sha(source) != SOURCE_SHA or sha(PACK.read_bytes()) != PACK_SHA:
        raise ValueError("Frozen original source/PCK fingerprint changed")
    entries = packed_entries(PACK)
    if sha(entries[SCRIPT_ENTRY]) != SCRIPT_SHA:
        raise ValueError("Original PCK script changed")
    freeze = SOURCE.parent
    for name, data in (("meadow_scene.original.gdc", entries[SCRIPT_ENTRY]),
                       ("meadow_scene.gd.remap", entries["scripts/meadow_scene.gd.remap"])):
        target = freeze / name
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError("Original pin copy changed")
        else:
            write(target, data)
    manifest = freeze / "pins.json"
    if not manifest.exists():
        write_json(manifest, {"source": str(SOURCE), "sourceSha256": SOURCE_SHA,
                   "sourcePck": str(PACK), "sourcePckSha256": PACK_SHA, "entry": SCRIPT_ENTRY,
                   "entrySha256": SCRIPT_SHA, "entryBytes": len(entries[SCRIPT_ENTRY]),
                   "allEntrySha256": {k: sha(v) for k, v in entries.items()}})
    return source, entries

def sandbox(path):
    stage = new_dir(path)
    project = new_dir(stage / "project")
    write(project / "project.godot", b'config_version=5\n[application]\nconfig/name="OfflineLiteStartupCompiler"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[shader_globals]\nmeadow_clock={"type":"float","value":0.0}\nmeadow_night={"type":"float","value":0.0}\n')
    env = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = new_dir(stage / key.lower())
        env[key] = str(directory)
    return stage, project, env

def run_probe(output):
    pin_original()
    stage, project, env = sandbox(output)
    request = stage / "request.json"
    write_json(request, {"mode":"probe", "output":str(stage), "pack":str(PACK)})
    cmd = [str(GODOT), "--headless", "--path", str(project), "--script", str(ROOT / "godot/tools/compile_lite_startup.gd"),
           "--log-file", str(stage / "engine.log"), "--", str(request)]
    process = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=env)
    write(stage / "process.log", (process.stdout + process.stderr).encode())
    if process.returncode or "STARTUP_SIDECAR: PASS" not in process.stdout:
        raise RuntimeError(process.stdout + process.stderr)
    print((stage / "result.json").read_text())

def compiler_runtime():
    """Private portable executable COPY: avoid the installation's _sc_ state."""
    directory = SCOPE / "compiler-runtime-01"
    if not directory.exists():
        new_dir(directory)
        for name in (GODOT.name, "Godot_v4.7.2-stable_win64.exe"):
            data = (GODOT.parent / name).read_bytes()
            write(directory / name, data)
        write(directory / "_sc_", b"")
        settings = new_dir(directory / "editor_data")
        # Command-line exports do not need editor IPC. Non-local TEST-NET
        # bind addresses also prevent accidental listener startup if a plugin
        # attempts it; no DNS, SSH or preview service is involved.
        write(settings / "editor_settings-4.7.tres", b'[gd_resource type="EditorSettings" format=3]\n[resource]\nnetwork/language_server/remote_host="192.0.2.1"\nnetwork/debug_adapter/remote_host="192.0.2.1"\nnetwork/debug/remote_host="192.0.2.1"\nnetwork/debug_adapter/enabled=false\n')
    for name in (GODOT.name, "Godot_v4.7.2-stable_win64.exe"):
        if sha((directory / name).read_bytes()) != sha((GODOT.parent / name).read_bytes()):
            raise ValueError("Private compiler executable differs from pinned local engine")
    return directory / GODOT.name

def compile_single(output, source):
    """Stock tokenizer via a tiny offline export; no dependency payload exports."""
    stage, project, env = sandbox(output)
    scripts = new_dir(project / "scripts")
    write(scripts / "meadow_scene.gd", source)
    write(project / "export_presets.cfg", b'[preset.0]\nname="ScriptOnly"\nplatform="Web"\nrunnable=false\nexport_filter="all_resources"\ninclude_filter=""\nexclude_filter=""\nscript_export_mode=2\n[preset.0.options]\nvariant/thread_support=false\nvariant/extensions_support=false\nhtml/export_icon=false\n')
    target = stage / "script-only.pck"
    cmd = [str(compiler_runtime()), "--headless", "--recovery-mode", "--path", str(project),
           "--log-file", str(stage / "engine.log"), "--export-pack", "ScriptOnly", str(target)]
    process = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, env=env)
    log = process.stdout + process.stderr
    write(stage / "process.log", log.encode())
    if "language server started" in log or "Debug Adapter started" in log:
        raise RuntimeError("Unexpected editor listener; candidate rejected")
    if process.returncode or not target.is_file():
        raise RuntimeError(f"Tiny script export failed: {log[-6000:]}")
    entries = packed_entries(target)
    if len(entries) > 12 or sum(map(len, entries.values())) > 2_000_000 or SCRIPT_ENTRY not in entries:
        raise ValueError("Tiny export unexpectedly included dependencies / no compiled script")
    result = entries[SCRIPT_ENTRY]
    if result[:4] != b"GDSC":
        raise ValueError("Stock exporter did not produce GDScript binary tokens")
    write(stage / "meadow_scene.gdc", result)
    write_json(stage / "compilation.json", {"sourceSha256":sha(source), "outputSha256":sha(result),
              "outputBytes":len(result), "stockGodotTokenizer":True,
              "privateExportEntries":{k:{"bytes":len(v),"sha256":sha(v)} for k,v in entries.items()},
              "dependencyValidation": "Compile is tokenization only. Full validation must mount original PCK separately.",
              "compilerLog":str(stage / "process.log")})
    return result

def physics_function(source):
    text = source.decode("utf-8").replace("\r\n", "\n")
    begin = text.index("func _physics_process(delta: float) -> void:")
    return text[begin:text.index("\nfunc ", begin + 1)]

def source_functions(source):
    matches = list(re.finditer(rb"^func ([a-zA-Z_][a-zA-Z_0-9]*)\(", source, re.M))
    result = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        result[match[1].decode()] = source[match.start():end]
    return result

def verify_source_contract(original, patched):
    a, b = source_functions(original), source_functions(patched)
    if set(b) - set(a) != set(ADDED_METHODS) or set(a) - set(b):
        raise ValueError("Only the two main-owned startup gate/report helpers may be added")
    restored = patched
    for name in ADDED_METHODS:
        restored = restored.replace(b[name], b"", 1)
    restored = restored.replace(b["_physics_process"], a["_physics_process"], 1)
    if restored != original:
        raise ValueError("Source changed outside the main-owned startup gate/report patch")
    delimiter = b"\tif not scale_guide.visible:"
    if a["_physics_process"].split(delimiter, 1)[1] != b["_physics_process"].split(delimiter, 1)[1]:
        raise ValueError("Ordinary physics tail changed")
    prefix = b["_physics_process"].split(delimiter, 1)[0]
    if prefix.index(b"audit_complete = true") > prefix.index(b"_startup_audit_enabled()"):
        raise ValueError("Main-owned first-frame guard must precede all audit/gate/report work")
    unchanged = {k:sha(v) for k,v in a.items() if k != "_physics_process"}
    if any(b[k] != a[k] for k in unchanged):
        raise ValueError("Existing ordinary/audit methods changed")
    return {"addedMethods":ADDED_METHODS, "changedExistingMethods":["_physics_process"],
            "allOtherSourceRestoresOriginalByteExactly":True, "restoredSourceSha256":sha(restored),
            "ordinaryPhysicsTailByteExact":True, "unchangedFunctionSha256":unchanged,
            "mainOwnedPatchedSourceSha256":sha(patched)}

def protected_stats():
    # Main owns the live meadow_scene.gd edit. We never save that file; the
    # frozen original plus exact diff is the compiler input/source proof.
    result = {}
    for base in (ROOT / "godot", GODOT.parent):
        paths = [p for p in base.rglob("*") if p.is_file()]
        for p in paths:
            if base == ROOT / "godot" and (p.is_relative_to(base / "tools") or p == base / "scripts/meadow_scene.gd"):
                continue
            stat = p.stat()
            result[str(p.relative_to(ROOT))] = [stat.st_size, str(stat.st_mtime_ns)]
    return result

def validate_scripts(output, original_path, patched_path, original_source, patched_source):
    stage, project, env = sandbox(output)
    request = stage / "request.json"
    write_json(request, {"mode":"validate", "output":str(stage), "pack":str(PACK),
               "original":str(original_path), "patched":str(patched_path),
               "original_sha256":sha(Path(original_path).read_bytes()),
               "patched_sha256":sha(Path(patched_path).read_bytes()),
               "original_physics":physics_function(original_source), "patched_physics":physics_function(patched_source),
               "patched_helpers":"\n".join(source_functions(patched_source)[n].decode() for n in ADDED_METHODS),
               "added_methods":ADDED_METHODS})
    command = [str(GODOT), "--headless", "--path", str(project), "--script", str(ROOT / "godot/tools/compile_lite_startup.gd"),
               "--log-file", str(stage / "engine.log"), "--", str(request)]
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, env=env)
    log = process.stdout + process.stderr
    write(stage / "process.log", log.encode())
    if process.returncode or "STARTUP_SIDECAR: PASS" not in log or "ERROR:" in log or "SCRIPT ERROR" in log:
        raise RuntimeError(f"Full compiled-script validation failed: {log[-6000:]}")
    return json.loads((stage / "result.json").read_text(encoding="utf-8"))

def recover_compilation(path, source):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(SCOPE):
        raise ValueError("Compilation recovery scope violation")
    report = json.loads((path / "compilation.json").read_text())
    result = (path / "meadow_scene.gdc").read_bytes()
    if (path / "project/scripts/meadow_scene.gd").read_bytes() != source or sha(source) != report["sourceSha256"] or sha(result) != report["outputSha256"]:
        raise ValueError("Recovered compilation source/output fingerprint differs")
    entries = packed_entries(path / "script-only.pck")
    if entries[SCRIPT_ENTRY] != result or {k:{"bytes":len(v),"sha256":sha(v)} for k,v in entries.items()} != report["privateExportEntries"]:
        raise ValueError("Recovered stock compiler pack differs")
    return result

def build(output, patched_source, patched_sha, resume=False):
    original, entries = pin_original()
    patched_source = Path(patched_source).resolve(strict=True)
    if not patched_source.is_relative_to(SCOPE) or not re.fullmatch(r"[0-9a-f]{64}", patched_sha):
        raise ValueError("Explicit main-owned source freeze artifact and SHA are required")
    patched = patched_source.read_bytes()
    if sha(patched) != patched_sha:
        raise ValueError("Main-owned source freeze SHA differs from explicitly supplied pin")
    source_contract = verify_source_contract(original, patched)
    if resume:
        output = Path(output).resolve(strict=True)
        if not output.is_relative_to(SCOPE) or (output / "startup-replacements.v1.json").exists():
            raise ValueError("Only an incomplete startup artifact build can be resumed")
        frozen = json.loads((output / "protected-tree-before.json").read_text())
        if frozen != protected_stats() or (output / "meadow_scene.original.gd").read_bytes() != original or (output / "meadow_scene.lite.gd").read_bytes() != patched:
            raise ValueError("Frozen compilation input/protected tree changed before resume")
    else:
        frozen = protected_stats()
        output = new_dir(output)
        write_json(output / "protected-tree-before.json", frozen)
        write(output / "meadow_scene.original.gd", original)
        write(output / "meadow_scene.lite.gd", patched)
    diff = "".join(difflib.unified_diff(original.decode().splitlines(keepends=True), patched.decode().splitlines(keepends=True),
                                  fromfile="original/scripts/meadow_scene.gd", tofile="lite/scripts/meadow_scene.gd"))
    if resume:
        if (output / "startup.diff").read_bytes() != diff.encode():
            raise ValueError("Source diff evidence changed")
    else:
        write(output / "startup.diff", diff.encode())
    # Reproduce the original in this run too. Accept no hand-authored tokens,
    # version approximation, header patch or unexplained compiler discrepancy.
    compile_step = recover_compilation if resume else compile_single
    baseline = compile_step(output / "original-compile", original)
    if baseline != entries[SCRIPT_ENTRY]:
        raise ValueError("Original-source compiler output is not byte-exact original PCK .gdc")
    candidate = compile_step(output / "patched-compile", patched)
    # A second independent tiny project checks stock token output determinism.
    repeat = compile_step(output / "patched-repeat", patched)
    if repeat != candidate:
        raise ValueError("Patched compilation is not reproducible")
    if candidate == baseline:
        raise ValueError("Patched .gdc unexpectedly equals original")
    target = output / "meadow_scene.gdc"
    if resume:
        if target.read_bytes() != candidate:
            raise ValueError("Candidate output differs from original compiler output")
    else:
        write(target, candidate)
    validation_dir = output / ("validate-final" if resume else "validate")
    validation = validate_scripts(validation_dir, SOURCE.parent / "meadow_scene.original.gdc", target, original, patched)
    if protected_stats() != frozen or sha(PACK.read_bytes()) != PACK_SHA or sha(SOURCE.read_bytes()) != SOURCE_SHA:
        raise ValueError("Protected original tree, pack or frozen input changed")
    if verify_source_contract(original, patched) != source_contract:
        raise ValueError("Source proof changed")
    tests = subprocess.run([sys.executable, "-B", str(ROOT / "godot/tools/test_startup_audit.py"), "-v"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    tests_log = tests.stdout + tests.stderr
    write(output / "source-tests.log", tests_log.encode())
    test_count = re.search(r"Ran (\d+) tests", tests_log)
    if tests.returncode or not test_count or int(test_count[1]) < 16 or "OK" not in tests_log or "skipped=" in tests_log:
        raise RuntimeError("Main-owned source/Node VM regression tests did not all pass")
    if (ROOT / "godot/scripts/meadow_scene.gd").read_bytes() != patched:
        raise ValueError("Main-owned tests did not exercise the identical frozen compiler input")
    proof_path = output / "startup-proof.json"
    proof = {"schema":"lite-startup-compiler-proof-v115-1", "status":"passed",
             "originalSource":{"path":str(SOURCE),"sha256":SOURCE_SHA},
             "patchedSource":{"path":str(output / "meadow_scene.lite.gd"),"sha256":sha(patched),"owner":"01a08f81-b318-7d12-942b-0aab8c295b13"},
             "sourceContract":source_contract, "sourceDiff":str(output / "startup.diff"),
             "sourceTests":{"path":str(output / "source-tests.log"),"passed":int(test_count[1]),"nodeVmIncluded":True},
             "compilerReports":[str(output / sub / "compilation.json") for sub in ("original-compile","patched-compile","patched-repeat")],
             "originalCompilerMatchesPckGdcByteExactly":True, "patchedCompilerRepeatByteExactly":True,
             "originalPck":{"path":str(PACK),"sha256":PACK_SHA,"entry":SCRIPT_ENTRY,"entrySha256":SCRIPT_SHA},
             "candidateGdc":{"path":str(target),"sha256":sha(candidate),"bytes":len(candidate)},
             "stockCompilerExecutableSha256":sha((GODOT.parent / "Godot_v4.7.2-stable_win64.exe").read_bytes()),
             "compiledContractEvidence":str(validation_dir / "result.json"),"validation":validation,
             "originalPckUntouched":True,"protectedOriginalTreeStatUnchanged":True,
             "allOriginalEntryHashPins":str(SOURCE.parent / "pins.json")}
    write_json(proof_path, proof)
    manifest = {"schema":"lite-startup-replacements-v115-1", "status":"offline_validated_candidate",
        "sourcePck":str(PACK), "sourcePckSha256":PACK_SHA,
        "replacements":[{"path":SCRIPT_ENTRY, "file":str(target), "beforeSha256":SCRIPT_SHA, "afterSha256":sha(candidate),
            "proof":str(proof_path), "proofSha256":sha(proof_path.read_bytes()),
            "beforeBytes":len(baseline), "afterBytes":len(candidate),
            "beforeGzip9Bytes":len(gzip.compress(baseline, mtime=0)), "afterGzip9Bytes":len(gzip.compress(candidate, mtime=0)),
            "checks":{"stockGodot472Compiler":True, "originalSourceReproducesOriginalPckGdcExactly":True,
                      "patchedCompilationRepeatByteExact":True, "tinySourceDiff":str(output / "startup.diff"),
                      "frozenSourceSha256":SOURCE_SHA, "patchedSourceSha256":sha(patched),
                      "mainOwnedPhysicsStartupGateAndTelemetryOnly":True, "auditCompleteSetBeforeGateAndAudit":True,
                      "ordinaryGameplayAndExistingAuditQuerySourceExact":True,
                      "allOtherOriginalPckEntriesUntouched":True, "originalRemapUnchanged":True}}],
        "validation":validation, "originalSource":str(SOURCE), "patchedSource":str(output / "meadow_scene.lite.gd"),
        "protectedOriginalTreeStatUnchanged":True, "protectedOriginalTreeFiles":len(frozen),
        "liveSceneSourceOwnership":"Main-owned live meadow_scene.gd is excluded from stat assertion; never written by this tool. Compilation reads the pinned artifact, not concurrent source edits.",
        "compilerPath":"Stock script_export_mode=2, headless recovery-mode script-only --export-pack in private artifact projects. Token compiler needs no dependencies; emitted complete scripts are separately loaded against read-only original PCK dependencies.",
        "integration":"Replace ONLY scripts/meadow_scene.gdc in derived lite pack; retain its existing .gd.remap. Do not put script-only.pck, metadata/project.binary or source .gd into the real pack.",
        "scope":"No original project export/import/cache write; no gameplay scene startup, browser, service, SSH or Git. Geometry candidates frozen.",
        "limits":["Editor/debug engine cannot execute a true release OS.is_debug_build() result. Both exact extracted function branches are exercised with a test-only Boolean substitution; shipping .gdc retains the stock OS.is_debug_build() call.",
                  "Final release Web startup/performance and all selected-pack integration remain main-owned."]}
    write_json(output / "startup-replacements.v1.json", manifest)
    print(json.dumps({"manifest":str(output / "startup-replacements.v1.json"), "beforeSha256":SCRIPT_SHA,
                      "afterSha256":sha(candidate), "beforeBytes":len(baseline), "afterBytes":len(candidate)}))
    return manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin-only", action="store_true")
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--original-compile", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--patched-source", type=Path, help="Main-owned immutable patched-source artifact; required with --output")
    parser.add_argument("--patched-sha256", help="Explicit SHA provided by source owner; required with --output")
    parser.add_argument("--resume", action="store_true", help="Reuse fingerprint-verified stock compiler stages of an incomplete output; no token rebuilding")
    args = parser.parse_args()
    if args.pin_only:
        pin_original()
        print("Frozen original source and PCK script pinned")
    elif args.probe:
        run_probe(args.probe)
    elif args.original_compile:
        source, original = pin_original()
        result = compile_single(args.original_compile, source)
        print(json.dumps({"originalSourceReproducesPckGdc":result == original[SCRIPT_ENTRY],
                          "expectedSha256":SCRIPT_SHA, "actualSha256":sha(result)}))
    elif args.output:
        if not args.patched_source or not args.patched_sha256:
            parser.error("--output requires --patched-source and --patched-sha256; no stale default source")
        build(args.output, args.patched_source, args.patched_sha256, args.resume)
    else:
        parser.error("Use --pin-only or --probe NEW_ARTIFACT_DIR")
