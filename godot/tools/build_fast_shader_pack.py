"""Copy-only, pinned v117 shader isolation candidate. No exports or art edits.

Hoist the unchanged sunbreak cloud transmission from light() to fragment().
The fragment-to-light varying is NOT a vertex interpolation. The custom light
predicate and response stay byte-identical after reversing that one read.
This is a compiler-complexity experiment, not a measured performance claim.
The independent bounded-loops case instead retains 72/48 iterations as new
uniform defaults, and bounds the existing two 32 loops by their existing count
uniforms. It does NOT include the sunbreak hoist. Neither case changes water.
The bounded-material-loops profile is a separate three-include candidate:
two min(32,count) loops without redundant breaks, plus clamped default72
contact shadows. It preserves the entire sky shader and sunbreak include.
The combined profile explicitly transforms v117 -> hoist -> material loops.
Its overlapping ground/cutout entries therefore retain both changes; no sky.

Example (all output paths must be NEW and under the owned artifact scope):
  python -B godot/tools/build_fast_shader_pack.py --output \
    artifacts/startup-v118/godot-analysis/sunbreak-hoist-01 --validate-godot
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from inspect_web_pack import read_pack
from build_web_quality import write_pack
from repack_web_cache import _unpack as decode_rscc


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v118/godot-analysis"
SOURCE = ROOT / "artifacts/v117/index-lite.pck"
SOURCE_SHA = "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79"
GODOT = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe"
INCLUDE = "shaders/meadow_sunbreak.gdshaderinc"
CONSUMERS = (
    "shaders/meadow_ground_surface.gdshaderinc",
    "shaders/meadow_cutout_surface.gdshaderinc",
    "shaders/meadow_leaves.gdshader",
    "shaders/meadow_limestone.gdshader",
)
ALLOWED = {INCLUDE, *CONSUMERS}
VARYING = b"varying float sunbreak_fragment_transmission;"
EXPRESSION = b"sunbreak_transmission(sunbreak_position)"
ASSIGNMENT = b"    sunbreak_fragment_transmission = " + EXPRESSION + b";"
LOOP_RULES = {
    "shaders/meadow_ground_surface.gdshaderinc": (72, "v118_contact_shadow_loop_count", "uniform vec4 contact_shadows[72];", True),
    "shaders/meadow_sky.gdshader": (48, "v118_cloud_loop_count", "uniform vec3 cloud_radii[48];", True),
    "shaders/meadow_cutout_surface.gdshaderinc": (32, "window_count", None, False),
    "shaders/meadow_architecture.gdshaderinc": (32, "architecture_count", None, False),
}
ADDED_UNIFORMS = {
    "res://shaders/meadow_ground.gdshader": {"v118_contact_shadow_loop_count"},
    "res://shaders/meadow_ground_day.gdshader": {"v118_contact_shadow_loop_count"},
    "res://shaders/meadow_sky.gdshader": {"v118_cloud_loop_count"},
}
MATERIAL_LOOP_RULES = {
    "shaders/meadow_cutout_surface.gdshaderinc": ("window_count", 12),
    "shaders/meadow_architecture.gdshaderinc": ("architecture_count", 8),
}
MATERIAL_GROUND = "shaders/meadow_ground_surface.gdshaderinc"
MATERIAL_ALLOWED = {MATERIAL_GROUND, *MATERIAL_LOOP_RULES}
MATERIAL_NEW_UNIFORM = b"uniform int contact_shadow_iterations = 72;"
MATERIAL_ADDED_UNIFORMS = {
    "res://shaders/meadow_ground.gdshader": {"contact_shadow_iterations"},
    "res://shaders/meadow_ground_day.gdshader": {"contact_shadow_iterations"},
}
COMBINED_ALLOWED = ALLOWED | MATERIAL_ALLOWED


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def write_new(path, blob):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(blob)


def write_json(path, value):
    write_new(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def entry_blobs(path):
    inventory = read_pack(path)
    result = {}
    with path.open("rb") as stream:
        for row in inventory["entries"]:
            stream.seek(row["offset"])
            result[row["path"]] = stream.read(row["bytes"])
    return inventory, result


def once(blob, old, new):
    if blob.count(old) != 1:
        raise ValueError(f"Expected exactly one source anchor: {old!r}")
    return blob.replace(old, new, 1)


def function_body(blob, name):
    """Bounded original-source structural helper, not a shader compiler."""
    match = re.search(rb"\b(?:void|float) " + name.encode() + rb"\([^)]*\)\s*\{", blob)
    if not match:
        raise ValueError(f"Missing function {name}")
    depth, start = 1, match.end()
    for cursor in range(start, len(blob)):
        if blob[cursor] == ord("{"):
            depth += 1
        elif blob[cursor] == ord("}"):
            depth -= 1
            if not depth:
                return blob[start:cursor]
    raise ValueError(f"Unterminated function {name}")


def hoist(original):
    if not ALLOWED.issubset(original):
        raise ValueError("Missing sunbreak shader dependencies")
    replacement = {}
    shared = original[INCLUDE]
    nl = b"\r\n" if b"\r\n" in shared else b"\n"
    shared = once(shared, b"varying float sunbreak_specular;" + nl,
                  b"varying float sunbreak_specular;" + nl + VARYING + nl)
    shared = once(shared, b"transmission = " + EXPRESSION + b";",
                  b"transmission = sunbreak_fragment_transmission;")
    replacement[INCLUDE] = shared
    for path in CONSUMERS:
        blob = original[path]
        nl = b"\r\n" if b"\r\n" in blob else b"\n"
        anchor = b"    sunbreak_specular = SPECULAR;" + nl
        replacement[path] = once(blob, anchor, anchor + ASSIGNMENT + nl)
    verify_hoist(original, replacement)
    return replacement


def verify_hoist(original, replacement):
    if set(replacement) != ALLOWED:
        raise ValueError("Replacement allowlist must be exactly five shader entries")
    for path in ALLOWED:
        before, after = original[path], replacement[path]
        nl = b"\r\n" if b"\r\n" in before else b"\n"
        if path == INCLUDE:
            reverted = once(after, VARYING + nl, b"")
            reverted = once(reverted, b"transmission = sunbreak_fragment_transmission;",
                            b"transmission = " + EXPRESSION + b";")
            for name in ("sunbreak_hash", "sunbreak_noise", "sunbreak_scope", "sunbreak_transmission"):
                if function_body(before, name) != function_body(after, name):
                    raise ValueError(f"Cloud math changed: {name}")
            if EXPRESSION in function_body(after, "light"):
                raise ValueError("Cloud work remains inside light()")
        else:
            reverted = once(after, ASSIGNMENT + nl, b"")
            if function_body(after, "fragment").count(ASSIGNMENT) != 1:
                raise ValueError("New varying must be assigned directly in fragment()")
            if b"sunbreak_fragment_transmission" in function_body(after, "vertex"):
                raise ValueError("Must not approximate transmission by vertex interpolation")
        if reverted != before:
            raise ValueError(f"Unexplained shader change: {path}")
        # Uniform names/defaults, render modes, and conditional gates are exact.
        interface = rb"(?m)^\s*(?:global uniform|uniform|render_mode|#if|#else|#endif)[^\n]*"
        if re.findall(interface, before) != re.findall(interface, after):
            raise ValueError(f"Shader interface/control gates changed: {path}")
    transmission = function_body(original[INCLUDE], "sunbreak_transmission")
    if any(token in transmission for token in (b"LIGHT", b"NORMAL", b"VIEW", b"dFdx", b"dFdy", b"texture(")):
        raise ValueError("Transmission now depends on unsupported light/derivative/texture inputs")


def bounded_loops(original):
    """Keep every body/iteration at shipped defaults; make loop bound uniform."""
    replacement = {}
    for path, (count, name, anchor, new_uniform) in LOOP_RULES.items():
        blob = original[path]
        if new_uniform:
            if name.encode() in b"\n".join(original.values()):
                raise ValueError("Reserved loop uniform already occurs in source pack")
            nl = b"\r\n" if b"\r\n" in blob else b"\n"
            blob = once(blob, anchor.encode() + nl,
                        anchor.encode() + nl + f"uniform int {name} = {count};".encode() + nl)
        blob = once(blob, f"for (int i = 0; i < {count}; i++)".encode(),
                    f"for (int i = 0; i < min({name}, {count}); i++)".encode())
        replacement[path] = blob
    verify_bounded_loops(original, replacement)
    return replacement


def verify_bounded_loops(original, replacement):
    if set(replacement) != set(LOOP_RULES):
        raise ValueError("Bounded-loop case must change exactly its four shader entries")
    for path, (count, name, anchor, new_uniform) in LOOP_RULES.items():
        before, after = original[path], replacement[path]
        reverted = once(after, f"for (int i = 0; i < min({name}, {count}); i++)".encode(),
                        f"for (int i = 0; i < {count}; i++)".encode())
        if new_uniform:
            nl = b"\r\n" if b"\r\n" in before else b"\n"
            reverted = once(reverted, f"uniform int {name} = {count};".encode() + nl, b"")
        if reverted != before:
            raise ValueError(f"Loop arithmetic/body/defaults changed: {path}")
        if not new_uniform and f"if (i >= {name}) {{ break; }}".encode() not in after:
            raise ValueError("Existing count guard must remain exactly intact")


def bounded_material_loops(original):
    """Three exact material-loop changes only; no sky or hoist modification."""
    result = {}
    for path, (name, indent) in MATERIAL_LOOP_RULES.items():
        blob = original[path]
        nl = b"\r\n" if b"\r\n" in blob else b"\n"
        old = b"for (int i = 0; i < 32; i++) {" + nl
        old += b" " * indent + f"if (i >= {name}) {{ break; }}".encode() + nl
        new = f"for (int i = 0; i < min(32, {name}); i++) {{".encode() + nl
        result[path] = once(blob, old, new)
    blob = original[MATERIAL_GROUND]
    nl = b"\r\n" if b"\r\n" in blob else b"\n"
    anchor = b"uniform vec4 contact_shadows[72];" + nl
    blob = once(blob, anchor, anchor + MATERIAL_NEW_UNIFORM + nl)
    result[MATERIAL_GROUND] = once(blob, b"for (int i = 0; i < 72; i++)",
                                  b"for (int i = 0; i < clamp(contact_shadow_iterations, 0, 72); i++)")
    verify_material_loops(original, result)
    return result


def verify_material_loops(original, replacement):
    if set(replacement) != MATERIAL_ALLOWED:
        raise ValueError("Material-loop profile must replace exactly its three includes")
    for path, after in replacement.items():
        before = original[path]
        nl = b"\r\n" if b"\r\n" in before else b"\n"
        if path == MATERIAL_GROUND:
            reverted = once(after, MATERIAL_NEW_UNIFORM + nl, b"")
            reverted = once(reverted, b"for (int i = 0; i < clamp(contact_shadow_iterations, 0, 72); i++)",
                            b"for (int i = 0; i < 72; i++)")
        else:
            name, indent = MATERIAL_LOOP_RULES[path]
            new = f"for (int i = 0; i < min(32, {name}); i++) {{".encode() + nl
            old = b"for (int i = 0; i < 32; i++) {" + nl
            old += b" " * indent + f"if (i >= {name}) {{ break; }}".encode() + nl
            reverted = once(after, new, old)
            if f"if (i >= {name}) {{ break; }}".encode() in after:
                raise ValueError("The exact redundant break must be removed")
        if reverted != before:
            raise ValueError(f"Unexplained material-loop body/order/default change: {path}")
        declaration = rb"(?m)^[ \t]*(?:(?:global|instance)[ \t]+)?uniform\b[^;]*;"
        before_declarations = re.findall(declaration, before)
        after_declarations = re.findall(declaration, after)
        if path == MATERIAL_GROUND:
            if after_declarations.count(MATERIAL_NEW_UNIFORM) != 1:
                raise ValueError("New default must be exactly the integer literal72")
            after_declarations.remove(MATERIAL_NEW_UNIFORM)
        if before_declarations != after_declarations:
            raise ValueError("Existing uniform declarations/defaults changed")


def combined(original):
    """Compose transforms, not already-built overlapping replacement manifests."""
    stage_one = hoist(original)
    hoisted_resources = dict(original)
    hoisted_resources.update(stage_one)
    # Crucial: read the HOISTED ground/cutout inputs for the second transform.
    stage_two = bounded_material_loops(hoisted_resources)
    result = dict(stage_one)
    result.update(stage_two)
    verify_combined(original, result)
    return result


def verify_combined(original, replacement):
    if set(replacement) != COMBINED_ALLOWED or len(replacement) != 6:
        raise ValueError("Combined profile must change exactly six unique shader entries")
    hoisted_resources = dict(original)
    hoisted_resources.update(hoist(original))
    verify_material_loops(hoisted_resources, {path: replacement[path] for path in MATERIAL_ALLOWED})
    for path in ALLOWED - MATERIAL_ALLOWED:
        if replacement[path] != hoisted_resources[path]:
            raise ValueError(f"Combined profile lost/changed a hoist-only entry: {path}")
    for path in ALLOWED & MATERIAL_ALLOWED:
        if function_body(replacement[path], "fragment").count(ASSIGNMENT) != 1:
            raise ValueError(f"Combined profile lost/duplicated fragment hoist: {path}")
        if function_body(original[path], "vertex") != function_body(replacement[path], "vertex"):
            raise ValueError(f"Combined profile changed vertex behavior: {path}")


def composition_evidence(output, original, replacement):
    verify_combined(original, replacement)
    hoisted_resources = dict(original)
    hoisted_resources.update(hoist(original))
    rows, first_diff, second_diff = [], [], []
    for path in sorted(COMBINED_ALLOWED):
        baseline, intermediate, final = original[path], hoisted_resources[path], replacement[path]
        stage_file = output / "stage-01-hoist" / path
        write_new(stage_file, intermediate)
        rows.append({"path": path, "originalSha256": sha(baseline),
                     "afterHoistSha256": sha(intermediate), "afterMaterialLoopsSha256": sha(final),
                     "hoistedSourceFile": str(stage_file), "stageOneChanged": baseline != intermediate,
                     "stageTwoChanged": intermediate != final})
        if baseline != intermediate:
            first_diff.extend(difflib.unified_diff(baseline.decode().splitlines(keepends=True),
                intermediate.decode().splitlines(keepends=True), fromfile="v117/" + path, tofile="hoist/" + path))
        if intermediate != final:
            second_diff.extend(difflib.unified_diff(intermediate.decode().splitlines(keepends=True),
                final.decode().splitlines(keepends=True), fromfile="hoist/" + path, tofile="combined/" + path))
    write_new(output / "v117-to-hoist.diff", "".join(first_diff).encode())
    write_new(output / "hoist-to-combined.diff", "".join(second_diff).encode())
    evidence = {"orderedTransforms": ["original-v117", "sunbreak-hoist", "bounded-material-loops"],
                "stageOneChangedEntries": 5, "stageTwoChangedEntries": 3, "finalUniqueChangedEntries": 6,
                "overlappingEntries": sorted(ALLOWED & MATERIAL_ALLOWED),
                "secondStageConsumesHoistedSource": True, "reverseStageProofPassed": True,
                "noIntermediatePckBuilt": True, "entries": rows}
    write_json(output / "composition.json", evidence)
    return evidence


def verify_no_material_override(original):
    """Inspect even decoded RSCC string tables; no resource load or mutation."""
    name = "contact_shadow_iterations"
    needles = (name.encode(), name.encode("utf-16-le"))
    decoded = []
    for path, blob in original.items():
        raw = decode_rscc(blob) if blob.startswith(b"RSCC") else blob
        if any(needle in raw for needle in needles):
            raise ValueError(f"Original entry already contains new uniform name: {path}")
        if blob.startswith(b"RSCC"):
            decoded.append({"path": path, "decodedBytes": len(raw), "decodedSha256": sha(raw)})
    sources = []
    for path in sorted((ROOT / "godot/scripts").glob("*.gd")):
        raw = path.read_bytes()
        if any(needle in raw for needle in needles):
            raise ValueError(f"Existing runtime source sets/reserves new uniform: {path}")
        sources.append({"path": str(path), "sha256": sha(raw)})
    return {"newUniform": name, "default": 72, "bounds": [0, 72],
            "allOriginalEntryNamesAbsent": True, "decodedRsccEntries": decoded,
            "runtimeSourcesWithoutNewName": sources,
            "materialEntriesUnchanged": True, "runtimeSourceFilesUnchanged": True}


def protected_snapshot():
    result = {}
    # Read-only snapshots. Newly authored tools/artifacts are intentionally out.
    for name in ("godot/shaders", "godot/scripts", "godot/assets", "godot/.godot"):
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file():
                info = path.stat()
                row = {"bytes": info.st_size, "mtimeNs": info.st_mtime_ns}
                if name in ("godot/shaders", "godot/scripts"):
                    row["sha256"] = sha(path.read_bytes())
                result[path.relative_to(ROOT).as_posix()] = row
    result["godot/project.godot"] = {"sha256": sha((ROOT / "godot/project.godot").read_bytes())}
    return result


def validate_godot(directory, source, candidate, case):
    """ShaderLanguage/ShaderCompiler validation on dummy renderer, NOT GPU linking."""
    runtime = directory / "compiler-runtime"
    runtime.mkdir()
    copied = {}
    for executable in (GODOT, GODOT.with_name("Godot_v4.7.2-stable_win64.exe")):
        target = runtime / executable.name
        shutil.copyfile(executable, target)
        copied[executable.name] = sha(target.read_bytes())
        if copied[executable.name] != sha(executable.read_bytes()):
            raise ValueError("Private stock engine copy mismatch")
    write_new(runtime / "_sc_", b"")
    (runtime / "editor_data").mkdir()
    project = directory / "compiler-project"
    project.mkdir()
    write_new(project / "project.godot", b'config_version=5\n[application]\nconfig/name="OfflineSunbreakShaderCheck"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    validator = SCOPE / "validate_fast_shaders.gd"
    outputs = []
    for label, pack in (("baseline", source), ("candidate", candidate)):
        result_path = directory / f"{label}-shader-compile.json"
        command = [str(runtime / GODOT.name), "--headless", "--path", str(project),
                   "--script", str(validator), "--log-file", str(directory / f"{label}-engine.log"),
                   "--", str(pack), str(result_path)]
        proc = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        text = proc.stdout + "\n" + proc.stderr
        write_new(directory / f"{label}-console.log", text.encode())
        if proc.returncode or "ERROR:" in text or "SHADER ERROR" in text or not result_path.exists():
            raise ValueError(f"Godot language compilation failed: {label}; inspect console log")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("shaderCount") != 20 or not result.get("ok"):
            raise ValueError(f"Incomplete shader validation: {label}")
        outputs.append(result)
    before, after = outputs[0]["uniforms"], outputs[1]["uniforms"]
    filtered = {}
    added = {}
    for path, parameters in after.items():
        additions = (ADDED_UNIFORMS if case == "bounded-loops" else
                     MATERIAL_ADDED_UNIFORMS if case in ("bounded-material-loops", "combined") else {})
        allowed = additions.get(path, set())
        extra = [row for row in parameters if row["name"] in allowed]
        if {row["name"] for row in extra} != allowed or any(row["type"] != 2 for row in extra):
            raise ValueError("Missing or wrong-type bounded-loop uniform")
        if any(row["name"] in allowed for row in before[path]):
            raise ValueError("New loop name collides with an existing compiled uniform")
        filtered[path] = [row for row in parameters if row["name"] not in allowed]
        if extra:
            added[path] = extra
    if before != filtered:
        raise ValueError("Existing stock-compiled shader uniform interface changed")
    return {"engineCopySha256": copied, "baseline": outputs[0], "candidate": outputs[1],
            "uniformInterfacesExactlyEqual": before == after,
            "existingUniformInterfacesExactlyEqual": True, "addedUniforms": added,
            "shaderLanguageCompile": "passed",
            "gpuGlLinkValidation": "NOT_RUN; main owns ANGLE/Web validation"}


def build(output, validate=False, case="sunbreak-hoist"):
    output = output.resolve()
    if not output.is_relative_to(SCOPE.resolve()) or output == SCOPE.resolve() or output.exists():
        raise ValueError("Destination must be NEW, strictly under owned godot-analysis artifacts")
    if sha(SOURCE.read_bytes()) != SOURCE_SHA:
        raise ValueError("Source PCK differs from pinned measured v117")
    protected = protected_snapshot()
    inventory, original = entry_blobs(SOURCE)
    if inventory["version"] != 4 or inventory["engine"] != [4, 7, 2]:
        raise ValueError("Unsupported stock PCK/engine")
    if case == "sunbreak-hoist":
        replacement, allowed = hoist(original), ALLOWED
    elif case == "bounded-loops":
        replacement, allowed = bounded_loops(original), set(LOOP_RULES)
    elif case == "bounded-material-loops":
        replacement, allowed = bounded_material_loops(original), MATERIAL_ALLOWED
    elif case == "combined":
        replacement, allowed = combined(original), COMBINED_ALLOWED
    else:
        raise ValueError("Unknown isolation case")
    material_defaults = verify_no_material_override(original) if case in ("bounded-material-loops", "combined") else None
    output.mkdir(parents=True)
    write_json(output / "protected-before.json", protected)
    diff, rows = [], []
    for path in sorted(replacement):
        before, after = original[path], replacement[path]
        target = output / "replacement" / path
        write_new(output / "original" / path, before)
        write_new(target, after)
        diff.extend(difflib.unified_diff(before.decode().splitlines(keepends=True),
                                        after.decode().splitlines(keepends=True),
                                        fromfile="v117/" + path, tofile=case + "/" + path))
        rows.append({"path": path, "file": str(target), "beforeSha256": sha(before),
                     "afterSha256": sha(after), "beforeBytes": len(before), "afterBytes": len(after),
                     "proof": str(output / "proof.json")})
    write_new(output / "shader.diff", "".join(diff).encode())
    composition = composition_evidence(output, original, replacement) if case == "combined" else None
    pack = output / "index-lite.pck"
    write_pack(SOURCE, inventory, pack, replacement)
    after_inventory, after_entries = entry_blobs(pack)
    if set(after_entries) != set(original):
        raise ValueError("Pack object/resource count changed")
    changed = {path for path in original if original[path] != after_entries[path]}
    if changed != allowed or any(after_entries[path] != blob for path, blob in replacement.items()):
        raise ValueError("Pack differs beyond exact replacement contract")
    compilation = validate_godot(output, SOURCE, pack, case) if validate else {"shaderLanguageCompile": "NOT_RUN"}
    if protected_snapshot() != protected or sha(SOURCE.read_bytes()) != SOURCE_SHA:
        raise ValueError("Protected source/art/cache changed during build")
    proof = {"profile": case + "-only", "sourcePckSha256": SOURCE_SHA,
             "candidatePckSha256": sha(pack.read_bytes()), "entryCount": len(original),
             "changedEntries": sorted(changed), "unchangedEntries": len(original) - len(changed),
             "allOtherEntryBytesExact": True, "existingUniformsAndDefaultsExact": True,
             "uniformsAndDefaultsExact": case == "sunbreak-hoist",
             "proceduralFunctionBodiesByteExact": case in ("sunbreak-hoist", "combined"),
             "lightBodyOnlyExpressionReadReplaced": case in ("sunbreak-hoist", "combined"),
             "loopBodiesByteExact": case == "bounded-loops",
             "loopArithmeticBodiesExactApartFromRemovedRedundantCountBreak": case in ("bounded-material-loops", "combined"),
             "loopCountsAtShippedDefaultsExact": case in ("bounded-loops", "bounded-material-loops", "combined"),
             "perFragmentNotVertexInterpolated": True, "noSceneMaterialOrSettingChanges": True,
             "waterShaderAndMaterialsExact": True, "protectedSourceArtCacheUnchanged": True,
             "shaderLanguageValidation": compilation, "performance": "UNMEASURED candidate; not a claimed fix",
             "visualValidation": "Pending matched viewport/time/day-night Web acceptance by main",
             "fidelityContract": (
                 "Identical cloud function evaluated with identical per-fragment world input; same light predicate and downstream response. Floating point compiler reassociation still requires visual acceptance."
                 if case == "sunbreak-hoist" else (
                 "Exactly two 32 loops use min(32,existing_count) and remove only the immediately following redundant break. Ground uses clamp(contact_shadow_iterations,0,72), new integer default72; no sky changes, no hoist. All arithmetic and iteration order exact at default72. Existing uniform/default declarations byte-exact; stock language compiler/interface validation permits only new int contact_shadow_iterations on ground and ground_day. Headless dummy renderer does not expose local uniform default values, so default72 is independently proved by the exact compiled source declaration and absent material/runtime override, not a GPU default-upload measurement."
                 if case == "bounded-material-loops" else
                 "Every loop body and ordering exact. New int uniforms default to original 72/48 and are capped at array length. Existing 32 loops use min(existing count,32), retaining original break. No source/material sets the two new parameter names. Do not override their defaults in integration. Floating point driver optimization still requires visual acceptance.")),
             "scope": "No full export, scene startup, browser, service, Git, SSH, or installed engine/cache modification"}
    if material_defaults:
        proof["newUniformDefaultAndNoOverrideProof"] = material_defaults
        proof["skyEntryByteExact"] = original["shaders/meadow_sky.gdshader"] == after_entries["shaders/meadow_sky.gdshader"]
        proof["sunbreakIncludeByteExact"] = original[INCLUDE] == after_entries[INCLUDE]
    if composition:
        proof["composition"] = composition
        proof["fidelityContract"] = (
            "Explicit original-v117 -> sunbreak-hoist -> bounded-material-loops composition. "
            "Ground/cutout stage2 inputs are the stage1 hoisted sources; both changes survive. "
            "All original cloud math and light response preserved, and exact 32-count loop bodies/order "
            "preserved apart from removal of redundant breaks. New contact_shadow_iterations int default72 "
            "is clamped0..72, with no original material/runtime override; all other uniform declarations/defaults "
            "and compiled interfaces are exact. Sky/water/engine/settings/geometry/scripts unchanged. "
            "Default72 is proved by compiled source plus no-override scan, not a headless GPU readback. "
            "ANGLE link/visual acceptance and main-owned GL helper remain untested here.")
    write_json(output / "proof.json", proof)
    manifest = {"schema": "fast-shader-pack-v1", "profile": case + "-only",
                "sourcePck": str(SOURCE), "sourcePckSha256": SOURCE_SHA,
                "replacements": rows, "candidatePck": str(pack),
                "candidatePckSha256": proof["candidatePckSha256"], "candidateBytes": pack.stat().st_size,
                "proof": str(output / "proof.json"), "diff": str(output / "shader.diff")}
    if composition:
        manifest["compositionProof"] = str(output / "composition.json")
    write_json(output / "shader-replacements.v1.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case", "--profile", dest="case", choices=("sunbreak-hoist", "bounded-loops", "bounded-material-loops", "combined"), default="sunbreak-hoist")
    parser.add_argument("--validate-godot", action="store_true", help="Bounded headless shader-language compilation; no GPU claim")
    args = parser.parse_args()
    manifest = build(args.output, args.validate_godot, args.case)
    print(json.dumps({key: value for key, value in manifest.items() if key != "replacements"}, indent=2))
