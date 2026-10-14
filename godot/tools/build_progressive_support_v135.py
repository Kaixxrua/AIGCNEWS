"""Bounded stock-tokenized eleven-script support overlay; source pack is frozen."""
from pathlib import Path
import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

sys.dont_write_bytecode = True
from inspect_web_pack import read_pack
from build_progressive_web_v135 import pack as make_pack

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/startup-v135/support/candidate-01"
BASE = ROOT / "artifacts/v134/index-lite.pck"
BASE_SHA = "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3"
GODOT = ROOT / ".tools/godot-4.7.2"
HELPER = "scripts/meadow_progressive_support.gd"
CALL = 'preload("res://' + HELPER + '")'
SOURCES = {
    "meadow_city_builder": [("terrain.mesh.generate_triangle_mesh()", f"{CALL}.surface(terrain)"), ("texture.get_image()", f"{CALL}.image(texture)")],
    "meadow_village_builder": [("terrain.mesh.generate_triangle_mesh()", f"{CALL}.surface(terrain)"), ("texture.get_image()", f"{CALL}.image(texture)")],
    "meadow_mountain_relief": [("ground_node.mesh.generate_triangle_mesh()", f"{CALL}.surface(ground_node)"), ("texture.get_image()", f"{CALL}.image(texture)")],
    "meadow_mountain_groves": [('scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()', f'{CALL}.surface(scene.get_node("ContinuousMeadow"))'), ("atlas.get_image()", f"{CALL}.image(atlas)")],
    "meadow_mountain_woodland": [("land.mesh.generate_triangle_mesh()", f"{CALL}.surface(land)")],
    "meadow_scrub_modules": [('scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()', f'{CALL}.surface(scene.get_node("ContinuousMeadow"))'), ("TEXTURE.get_image()", f"{CALL}.image(TEXTURE)")],
    "meadow_ledge_breakup": [("surface.mesh.generate_triangle_mesh()", f"{CALL}.surface(surface)")],
    "meadow_wildlife": [('scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()', f'{CALL}.surface(scene.get_node("ContinuousMeadow"))'), ('scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()', f'{CALL}.surface(scene.get_node("SolidLimestoneGeology"))')],
    "meadow_herb_modules": [("TEXTURE.get_image()", f"{CALL}.image(TEXTURE)")],
    "meadow_road_lights": [("ATLAS.get_image()", f"{CALL}.image(ATLAS)")],
    "meadow_settlement_lights": [("texture.get_image()", f"{CALL}.image(texture)")],
}


def require(value, message):
    if not value: raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data):
    path = Path(path).resolve()
    require(path.is_relative_to(OUT) and not path.exists(), "Fresh owned artifact required: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream: stream.write(data)


def write_json(path, value):
    write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def entries(path):
    data = Path(path).read_bytes()
    return {r["path"]: data[r["offset"]:r["offset"] + r["bytes"]] for r in read_pack(Path(path), verify=True)["entries"]}


def patch_source(name, source):
    patched = source
    for before, after in SOURCES[name]:
        require(patched.count(before.encode()) == 1, "Unique observed call site: " + name + "/" + before)
        patched = patched.replace(before.encode(), after.encode(), 1)
    reverse = patched
    for before, after in reversed(SOURCES[name]): reverse = reverse.replace(after.encode(), before.encode(), 1)
    require(reverse == source, "Only precise query/image call substitutions")
    if name == "meadow_ledge_breakup":
        require(patched.count(b"stones.mesh.generate_triangle_mesh()") == 1, "Local stone query untouched")
    return patched


def private_runtime():
    target = OUT / "compiler-runtime"
    require(not target.exists(), "Fresh private compiler runtime")
    target.mkdir(parents=True)
    for name in ("Godot_v4.7.2-stable_win64_console.exe", "Godot_v4.7.2-stable_win64.exe"):
        shutil.copyfile(GODOT / name, target / name)
        require(sha((target / name).read_bytes()) == sha((GODOT / name).read_bytes()), "Stock executable copy exact")
    write(target / "_sc_", b"")
    write(target / "editor_data/editor_settings-4.7.tres", b'[gd_resource type="EditorSettings" format=3]\n[resource]\nnetwork/language_server/remote_host="192.0.2.1"\nnetwork/debug_adapter/remote_host="192.0.2.1"\nnetwork/debug/remote_host="192.0.2.1"\nnetwork/debug_adapter/enabled=false\n')
    return target / "Godot_v4.7.2-stable_win64_console.exe"


def compile_batch(label, sources, executable):
    stage = OUT / label
    project = stage / "project"
    project.mkdir(parents=True)
    write(project / "project.godot", b'config_version=5\n[application]\nconfig/name="OfflineProgressiveSupportCompiler"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    write(project / "export_presets.cfg", b'[preset.0]\nname="ScriptOnly"\nplatform="Web"\nrunnable=false\nexport_filter="all_resources"\ninclude_filter=""\nexclude_filter=""\nscript_export_mode=2\n[preset.0.options]\nvariant/thread_support=false\nvariant/extensions_support=false\nhtml/export_icon=false\n')
    for path, data in sources.items(): write(project / path, data)
    env = os.environ.copy()
    for name in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = stage / name.lower(); directory.mkdir()
        env[name] = str(directory)
    target = stage / "scripts-only.pck"
    command = [str(executable), "--headless", "--recovery-mode", "--path", str(project),
               "--log-file", str(stage / "engine.log"), "--export-pack", "ScriptOnly", str(target)]
    started = time.monotonic()
    process = subprocess.run(command, capture_output=True, env=env, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    log = process.stdout + process.stderr
    write(stage / "process.log", log)
    write_json(stage / "invocation.json", {"command": command, "exitCode": process.returncode,
               "wallSeconds": round(time.monotonic() - started, 3), "compilerSha256": sha(executable.read_bytes()),
               "tokenizationOnly": True, "dependenciesValidatedSeparately": True})
    require(b"language server started" not in log and b"Debug Adapter started" not in log, "No editor services")
    require(process.returncode == 0 and target.exists(), "Tiny stock script export failed; inspect preserved log")
    packed = entries(target)
    require(len(packed) <= 80 and sum(map(len, packed.values())) < 2_000_000, "No dependency/full export")
    for path in sources:
        gdc = path[:-3] + ".gdc"
        require(gdc in packed and packed[gdc].startswith(b"GDSC"), "Actual stock GDC required: " + gdc)
    return packed


def build():
    require(not OUT.exists(), "Never overwrite earlier candidate output")
    require(sha(BASE.read_bytes()) == BASE_SHA, "Pinned v134 source pack")
    baseline = entries(BASE)
    originals = {"scripts/" + name + ".gd": (ROOT / "godot/scripts" / (name + ".gd")).read_bytes() for name in SOURCES}
    helper = (ROOT / "godot" / HELPER).read_bytes()
    frozen = {path: sha(data) for path, data in originals.items()}
    frozen[HELPER] = sha(helper)
    write_json(OUT / "source-pins.json", {"sourcePackSha256": BASE_SHA, "sources": frozen})
    for path, data in originals.items(): write(OUT / "frozen" / path, data)
    write(OUT / "frozen" / HELPER, helper)
    compiler = private_runtime()
    actual = compile_batch("original-compile", originals, compiler)
    checks = []
    for path, source in originals.items():
        gdc = path[:-3] + ".gdc"
        checks.append({"entry": gdc, "sourceSha256": sha(source), "beforeSha256": sha(baseline[gdc]),
                       "stockCompiledSha256": sha(actual[gdc]), "byteExact": actual[gdc] == baseline[gdc]})
    write_json(OUT / "baseline-compiler-proof.json", {"scripts": checks, "allExact": all(x["byteExact"] for x in checks)})
    mismatches = [x["entry"] for x in checks if not x["byteExact"]]
    require(not mismatches, "BASELINE GDC NOT EXACT; no patched output emitted: " + repr(mismatches))
    print("All eleven original sources reproduce their actual v134 GDC byte-exactly.", flush=True)
    changed = {"scripts/" + name + ".gd": patch_source(name, originals["scripts/" + name + ".gd"]) for name in SOURCES}
    changed[HELPER] = helper
    for path, value in changed.items():
        if path in originals:
            diff = "".join(difflib.unified_diff(originals[path].decode().splitlines(True), value.decode().splitlines(True), fromfile=path, tofile="private/" + path))
            write(OUT / "diffs" / (Path(path).stem + ".diff"), diff.encode())
    compiled = compile_batch("patched-compile", changed, compiler)
    overlay, manifest = {}, []
    for path in changed:
        gdc = path[:-3] + ".gdc"
        for entry in (gdc, path + ".remap"):
            data = compiled[entry]
            output = OUT / "entries" / entry
            write(output, data)
            overlay[entry] = data
            manifest.append({"entry": entry, "path": str(output), "sha256": sha(data),
                             "beforeSha256": sha(baseline[entry]) if entry in baseline else None})
    require(len(overlay) == 24 and not any(p.endswith(".gd") for p in overlay), "Eleven private GDCs plus helper and remaps only")
    write(OUT / "support-overlay.pck", make_pack(BASE.read_bytes()[:112], overlay))
    require(entries(OUT / "support-overlay.pck") == overlay, "Overlay pack readback exact")
    for path, expected in frozen.items(): require(sha((ROOT / "godot" / path).read_bytes()) == expected, "Source remained frozen: " + path)
    require(sha(BASE.read_bytes()) == BASE_SHA, "Original pack remained frozen")
    write_json(OUT / "manifest.json", {"schema": "progressive-support-overlay-v1", "sourcePackSha256": BASE_SHA,
               "entries": manifest, "baselineCompilerAllExact": True, "privatePatchedSourceOnly": True,
               "sourceConsumerCount": 11, "originalQuerySubstitutions": 9, "cpuImageSubstitutions": 8,
               "runtimeValidation": "PENDING separate actual native overlay audit", "alphaMapping": "res://progressive/alpha-manifest.json"})
    print(json.dumps({"manifest": str(OUT / "manifest.json"), "entries": len(manifest), "overlayBytes": (OUT / "support-overlay.pck").stat().st_size}, indent=2), flush=True)


class Tests(unittest.TestCase):
    def test_exact_scope(self):
        self.assertEqual(len(SOURCES), 11)
        self.assertNotIn("meadow_edge_growth", SOURCES)
        self.assertNotIn("meadow_scene", SOURCES)
        self.assertNotIn("meadow_progressive", SOURCES)

    def test_reversible_actual_sources(self):
        for name in SOURCES: patch_source(name, (ROOT / "godot/scripts" / (name + ".gd")).read_bytes())

    def test_ambiguous_call_rejected(self):
        with self.assertRaises(ValueError): patch_source("meadow_mountain_woodland", b"land.mesh.generate_triangle_mesh()\n" * 2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test: unittest.main(argv=[sys.argv[0]], verbosity=2)
    elif args.build: build()
    else: parser.error("Choose --build or --self-test")
