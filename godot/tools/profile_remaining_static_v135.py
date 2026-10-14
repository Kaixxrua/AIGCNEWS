"""One actual09 native startup with test-only inherited timing overrides.

The packed main/controller and all 17 cache dependencies remain byte-identical.
Generated source copies are diagnostic only, never shipping overlays.
"""
from pathlib import Path
import difflib
import json
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
from build_progressive_support_v135 import sha, entries

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/startup-v135/static-cache/remaining-profile-01"
CORE = ROOT / "artifacts/startup-v135/build/candidate-09/native/index-lite.pck"
SOURCE = CORE.parents[1] / "meadow_scene.progressive.gd"
CITY = ROOT / "artifacts/startup-v135/support/candidate-01/patched-compile/project/scripts/meadow_city_builder.gd"
ENGINE = ROOT / "artifacts/startup-v135/static-cache/candidate-01/compiler-runtime/Godot_v4.7.2-stable_win64.exe"


def write(path, data):
    path = Path(path).resolve()
    assert path.is_relative_to(OUT) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def json_write(path, value):
    write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def function(source, name):
    start = source.index("func " + name + "(")
    end = source.find("\nfunc ", start + 1)
    static_end = source.find("\nstatic func ", start + 1)
    end = min(x for x in (end, static_end, len(source)) if x >= 0)
    return source[start:end].rstrip() + "\n"


def timed_body(body, prefix):
    result = []
    for line in body.splitlines():
        if re.fullmatch(r"\t(?:[A-Za-z_][\w.]*(?:\.new\(\))?\([^\n]*\))", line) and not line.startswith(("\tprint(", "\tassert(")):
            result.extend(["\t_profile_clock = Time.get_ticks_usec()", line,
                "\t_profile_record(" + json.dumps(prefix + line.strip()) + ", _profile_clock)"])
        else:
            result.append(line)
    result.insert(1, "\tvar _profile_clock: int = 0")
    return "\n".join(result) + "\n"


def main():
    assert not OUT.exists(), "Fresh bounded diagnostic only"
    assert sha(CORE.read_bytes()) == "9472167e7e416eca07e9a217eba189b1ddeecb149faa86b121f9c0a097fe3e93"
    assert sha(SOURCE.read_bytes()) == "a29aef468e6f0b5e333577ef2b4e34db06632c767ada9454ce08e2ca03f1b30d"
    source = SOURCE.read_text(encoding="utf-8")
    city_original = CITY.read_text(encoding="utf-8")
    city = city_original
    # Separate first full-collider BVH construction: it remains necessary for wildlife.
    for line in [
        '\tvar source := preload("res://scripts/meadow_progressive_support.gd").image(texture)',
        '\tvar surface: TriangleMesh = preload("res://scripts/meadow_progressive_support.gd").surface(terrain)',
    ]:
        label = "city/alpha_image" if "image(texture)" in line else "city/full_collider_bvh"
        assert city.count(line) == 1
        city = city.replace(line, '\tvar _' + label.split("/")[-1] + ': int = Time.get_ticks_usec()\n' + line +
            '\n\tmeadow._profile_record("' + label + '", _' + label.split("/")[-1] + ')')
    line = '\tvar columns: Array[float] = []'
    city = city.replace(line, '\tvar _geometry: int = Time.get_ticks_usec()\n' + line, 1)
    line = '\tcity.set_meta("max_foundation_shift", max_shift)'
    city = city.replace(line, line + '\n\tmeadow._profile_record("city/geometry_after_query", _geometry)', 1)
    write(OUT / "profile-city.gd", city.encode())
    ready = timed_body(function(source, "_ready"), "ready/")
    layers = timed_body(function(source, "_build_art_layers"), "layers/")
    layers = layers.replace('CITY_BUILDER.new().build(self, CASTLE_HILL, CASTLE_PEAK_UV)',
        'load("' + (OUT / "profile-city.gd").as_posix() + '").new().build(self, CASTLE_HILL, CASTLE_PEAK_UV)', 1)
    derived = '''extends "res://scripts/meadow_scene.gd"
var profile_rows: Array = []
var profile_root_meshes: Dictionary = {}
func _profile_record(label: String, started: int) -> void:
\tprofile_rows.append({"label": label, "usec": Time.get_ticks_usec() - started})

func _conform_root_line(instance: MeshInstance3D, follow_whole_column: bool = false) -> void:
\tvar before: PackedByteArray = preload("res://scripts/meadow_static_geometry_cache.gd").context(self, instance, [follow_whole_column])
\tvar started := Time.get_ticks_usec()
\tsuper._conform_root_line(instance, follow_whole_column)
\t_profile_record("root_conform/" + str(instance.name), started)
\tprofile_root_meshes[str(instance.name)] = {"context": before, "mesh": instance.mesh, "wholeColumn": follow_whole_column}

func _art(label: String, texture: Texture2D, foot: Vector2, width: float,
\t\tanchor: Vector2, sink: float = 0.0, tint: Color = Color.WHITE, billboard: bool = true,
\t\tregion: Rect2 = Rect2(0, 0, 1, 1)) -> MeshInstance3D:
\tvar started := Time.get_ticks_usec()
\tvar result := super._art(label, texture, foot, width, anchor, sink, tint, billboard, region)
\t_profile_record("art/" + label, started)
\treturn result

'''
    derived += ready + "\n" + layers
    write(OUT / "profile-main.gd", derived.encode())
    json_write(OUT / "source-proof.json", {
        "coreSha256": sha(CORE.read_bytes()), "packedMainSha256": sha(entries(CORE)["scripts/meadow_scene.gdc"]),
        "mainSourceSha256": sha(SOURCE.read_bytes()), "privateDerivedSha256": sha(derived.encode()),
        "citySourceSha256": sha(CITY.read_bytes()),
        "cityTimingOnlyDiff": ''.join(difflib.unified_diff(city_original.splitlines(True), city.splitlines(True))),
        "contract": "Test-only inherited ready/art-layer copies with timers; super original _art/root-conform; no packed entry replacement or cache dependency change."})
    request = {"core": CORE.as_posix(), "derived": (OUT / "profile-main.gd").as_posix(),
        "report": (OUT / "profile.json").as_posix(), "rootResource": (OUT / "root-results.res").as_posix()}
    json_write(OUT / "request.json", request)
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = OUT / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    runtime = OUT / "runtime"
    runtime.mkdir()
    command = [str(ENGINE), "--headless", "--path", str(runtime), "--main-pack", str(CORE),
        "--log-file", str(OUT / "engine.log"), "--script", str(ROOT / "godot/tools/profile_remaining_static_v135.gd"),
        "--", str(OUT / "request.json")]
    started = time.monotonic()
    result = subprocess.run(command, env=env, capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    log = result.stdout + result.stderr
    write(OUT / "process.log", log)
    json_write(OUT / "invocation.json", {"command": command, "exitCode": result.returncode,
        "wallSeconds": time.monotonic() - started, "engineSha256": sha(ENGINE.read_bytes())})
    assert result.returncode == 0 and b"SCRIPT ERROR" not in log and b"Parse Error" not in log, log[-8000:].decode(errors="replace")
    report = json.loads((OUT / "profile.json").read_bytes())
    totals = {}
    for row in report["rows"]:
        group = row["label"].split("/")[0]
        if group in ("art", "root_conform"):
            totals[group] = totals.get(group, 0) + row["usec"] / 1000
    print(json.dumps({"readyMs": report["readyMs"], "cacheHits": len(report["cache"]["hits"]),
        "totalsMs": totals, "top": sorted(report["rows"], key=lambda r: -r["usec"])[:18]}, indent=2))


if __name__ == "__main__":
    main()
