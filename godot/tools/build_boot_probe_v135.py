"""Compile ONLY the opt-in observer, plus a tiny no-scene validation harness.

Emits two additive entries; never edits boot/main/cache, stages Web, or runs the
main scene. Stock compiler runtime, generated files and logs stay in NEW output.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
import compile_lite_startup as compiler

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "artifacts/startup-v135/build"
SOURCE = ROOT / "godot/scripts/meadow_boot_probe.gd"
CORE = BUILD / "candidate-10/native/index-lite.pck"
CORE_SHA = "7622eb8f1c0f687a9c640ac0e2e0c818e005ad4ff6605fc353368849768d1988"
ENTRY = "scripts/meadow_boot_probe.gdc"

HARNESS = '''extends SceneTree
func _initialize() -> void:
    run.call_deferred()
func run() -> void:
    var script := load(OS.get_cmdline_user_args()[0]) as Script
    assert(script != null and script.can_instantiate())
    var probe := Node.new()
    probe.set_script(script)
    assert(probe.get_script() == script)
    var a: Array = []
    for i in range(21): a.append(0.0)
    a[1] = Transform3D.IDENTITY
    a[13] = Rect2(0, 0, 2560, 1440)
    var b := a.duplicate(true)
    b[6] = 0.0000000000001
    b[13] = Rect2(0, 0, 2560, 1439)
    var rows: Array = probe._compare_fields(a, b, ["inputs"])
    assert(rows.size() == 21)
    assert(rows[1].exactBytes)
    assert(not rows[6].exactBytes and rows[6].absoluteError > 0.0)
    assert(rows[13].absoluteError == [[0.0, 0.0], [0.0, 1.0]])
    assert(rows[20].actualOrigin == "record-replay")
    # Public load/set_script against the actual core, without loading its scene.
    var scene_script := GDScript.new()
    scene_script.source_code = "extends Node3D\\nvar camera: Camera3D\\n"
    assert(scene_script.reload() == OK)
    var scene := Node3D.new()
    scene.set_script(scene_script)
    root.add_child(scene)
    scene.camera = Camera3D.new()
    scene.add_child(scene.camera)
    var target := MeshInstance3D.new()
    target.name = "ReadOnlyFixture"
    target.mesh = QuadMesh.new()
    target.mesh.size = Vector2(2, 3)
    target.mesh.center_offset = Vector3(-0.5, 0.75, 0)
    target.set_meta("art_width", 2.0)
    target.set_meta("art_height", 3.0)
    target.set_meta("art_anchor", Vector2(0.75, 0.75))
    target.material_override = ShaderMaterial.new()
    var shader := Shader.new()
    shader.code = "shader_type spatial; uniform sampler2D asset_texture; uniform vec4 uv_region;"
    target.material_override.shader = shader
    var texture := GradientTexture2D.new()
    target.material_override.set_shader_parameter("asset_texture", texture)
    target.material_override.set_shader_parameter("uv_region", Vector4(0, 0, 1, 1))
    scene.add_child(target)
    var contract := load("res://scripts/meadow_static_geometry_cache.gd") as Script
    var context: PackedByteArray = contract.context(scene, target, [false])
    assert(not context.is_empty())
    var state := {"valid": true, "records": {"ReadOnlyFixture": {"context": context, "wholeColumn": false}},
        "hits": [], "misses": ["ReadOnlyFixture"]}
    scene.set_meta("_meadow_root_conform_cache_v135", state)
    target.mesh = ArrayMesh.new() # Model the ORIGINAL fallback, before observing.
    var before_mesh := target.mesh
    var before_material := target.material_override
    var before_state := var_to_bytes(state)
    scene.camera.fov += 0.125
    var report: Dictionary = probe._inspect(scene)
    assert(report.firstFailure.available and report.firstFailure.liveContextBytes == 0)
    assert(report.firstFailure.fields[6].absoluteError == 0.125)
    assert(report.firstFailure.fields[14].actualOrigin == "derive-from-live-original-metadata")
    assert(report.firstFailure.fields[14].exactBytes and report.firstFailure.fields[15].exactBytes)
    # An altered recorded size must NOT be injected into the actual comparison.
    var wrong: Array = bytes_to_var(context)
    wrong[14] = Vector2(4, 3)
    state.records.ReadOnlyFixture.context = var_to_bytes(wrong)
    var changed: Dictionary = probe._inspect(scene)
    assert(changed.firstFailure.fields[14].absoluteError == [2.0, 0.0])
    state.records.ReadOnlyFixture.context = context
    assert(target.mesh == before_mesh and target.material_override == before_material)
    assert(var_to_bytes(state) == before_state and scene.get_child_count() == 2)
    state.misses.clear()
    state.hits.append("ReadOnlyFixture")
    assert(probe._inspect(scene).firstFailure == null)
    state.valid = false
    state.misses.append("NoSuchRecord")
    assert(not probe._inspect(scene).firstFailure.available)
    # Native/default-OFF attachment must remove only the observer.
    root.add_child(probe)
    await process_frame
    await process_frame
    assert(not is_instance_valid(probe) and is_instance_valid(scene))
    scene.free()
    print("BOOT_PROBE_VALIDATION: PASS; public set_script; field errors; detached replay; read-only; default OFF")
    quit()
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def build(output):
    output = output.resolve()
    require(output.parent == BUILD.resolve() and re.fullmatch(r"probe-[0-9]+", output.name)
            and not output.exists(), "Require a NEW build/probe-N directory; never overwrite")
    source = SOURCE.read_bytes()
    require(len(source) < 24000 and b'const CONTRACT = preload' not in source,
            "Small observer must not preload missing core dependencies in bootstrap")
    require(sha(CORE.read_bytes()) == CORE_SHA, "Pinned read-only validation core changed")
    compiler.SCOPE = output
    compiler.new_dir(output / "input")
    compiler.write(output / "input/meadow_boot_probe.gd", source)
    gdc = compiler.compile_single(output / "compile", source)
    require(gdc.startswith(b"GDSC") and len(gdc) < 60000, "Bounded stock GDC required")
    entries = {ENTRY: gdc, "scripts/meadow_boot_probe.gd.remap":
               b'[remap]\n\npath="res://scripts/meadow_boot_probe.gdc"\n'}
    rows = []
    for entry, data in entries.items():
        target = output / "entries" / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        compiler.write(target, data)
        rows.append({"entry": entry, "path": target.as_posix(), "bytes": len(data), "sha256": sha(data)})
    validation = compiler.new_dir(output / "validation")
    compiler.write(validation / "check.gd", HARNESS.encode())
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        env[key] = str(compiler.new_dir(validation / key.lower()))
    executable = output / "compiler-runtime-01/Godot_v4.7.2-stable_win64.exe"
    command = [str(executable), "--headless", "--path", str(validation), "--main-pack", str(CORE),
               "--log-file", str(validation / "engine.log"), "--script", str(validation / "check.gd"),
               "--", str(output / "entries" / ENTRY)]
    result = subprocess.run(command, env=env, capture_output=True, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log = result.stdout + result.stderr
    compiler.write(validation / "process.log", log)
    compiler.write_json(validation / "invocation.json", {"command": command, "exitCode": result.returncode})
    require(result.returncode == 0 and b"BOOT_PROBE_VALIDATION: PASS" in log
            and b"SCRIPT ERROR" not in log and b"ERROR:" not in log,
            "Bounded observer validation failed; preserved validation/process.log")
    require(SOURCE.read_bytes() == source and sha(CORE.read_bytes()) == CORE_SHA, "Inputs changed during compilation")
    manifest = {"schema": "meadow-boot-probe-entries-v135-1", "status": "PASS_BOUNDED_NATIVE_FIXTURE",
                "sourceSha256": sha(source), "builderSha256": sha(Path(__file__).read_bytes()),
                "compiler": (output / "compile/compilation.json").as_posix(),
                "validationCoreSha256": CORE_SHA, "entries": rows,
                "integration": "Add ONLY these two entries to bootstrap. For explicit root_cache_probe=1, "
                "use Node.new(), set_script(load('res://scripts/meadow_boot_probe.gd')), "
                "then get_tree().root.add_child(node). Do not parent to the replaceable boot scene.",
                "limits": ["No actual main scene, Web/browser or timing audit was run.",
                           "Post-ready observation; Quad dimensions derive from live original art metadata, never expected values. Original call inputs are labeled record-replay.",
                           "No main/controller/cache/boot source or readiness change; default OFF, one JSON then queue_free."]}
    compiler.write_json(output / "probe-entries.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BUILD / "probe-01")
    build(parser.parse_args().output)
