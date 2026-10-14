"""Run only the pure travel helper's isolated native tests; no world/build/art.

Uses the already available portable Godot. A tiny temporary project holds just
the helper and its existing five-site layout dependency; it is removed on exit.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "godot/scripts"
TEST = ROOT / "godot/tools/test_camp_travel_path.gd"
ENGINE = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64.exe"


def main():
    names = ("camp_travel_path.gd", "camp_spawn_layout.gd")
    sources = {name: (SCRIPTS / name).read_bytes() for name in names}
    helper = sources[names[0]]
    assert not re.search(rb"\b(?:FileAccess|DirAccess|Time|OS|JavaScriptBridge|HTTPRequest|HTTPClient|Timer|Tween|RandomNumberGenerator)\s*[.(]|func\s+_process\s*\(|\b(?:randf|randi|randomize|seed)\s*\(", helper)
    assert b"extends RefCounted" in helper
    assert ENGINE.is_file()
    with tempfile.TemporaryDirectory(prefix="camp-travel-path-native-") as temporary:
        stage = Path(temporary).resolve()
        module = stage / "camp_presentation"
        module.mkdir()
        for name in names:
            shutil.copyfile(SCRIPTS / name, module / name)
        (stage / "project.godot").write_text(
            'config_version=5\n[application]\nconfig/name="CampTravelPathTestOnly"\n'
            '[debug]\nfile_logging/enable_file_logging=false\n'
            '[rendering]\nrenderer/rendering_method="gl_compatibility"\n', encoding="utf-8")
        env = dict(os.environ)
        for name in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
            isolated = stage / name.lower()
            isolated.mkdir()
            env[name] = str(isolated)
        result = subprocess.run(
            [str(ENGINE), "--headless", "--path", str(stage), "--log-file", str(stage / "native.log"), "--script", str(TEST)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log = result.stdout + result.stderr
        print(log.strip())
        assert result.returncode == 0 and "CAMP_TRAVEL_PATH_TEST: PASS" in log and "ERROR:" not in log, "Isolated travel helper test failed"
        for name, original in sources.items():
            assert (SCRIPTS / name).read_bytes() == original, "Source changed during isolated test: " + name
        print("TRAVEL_SOURCE_SHA256: " + hashlib.sha256(helper).hexdigest())


if __name__ == "__main__":
    main()
