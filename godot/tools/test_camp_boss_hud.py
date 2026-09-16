"""Run ONLY the new HUD's isolated native contracts; no world/build/art inputs.

python -B godot/tools/test_camp_boss_hud.py --font godot/assets/camp/ui/camp_ui_zh.ttf
Uses the existing read-only portable Godot and an automatically removed tiny
temporary project. Source/runtime files and the accepted artifacts stay intact.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HUD = ROOT / "godot/scripts/camp_boss_hud.gd"
TEST = ROOT / "godot/tools/test_camp_boss_hud.gd"
ENGINE = ROOT / ".tools/godot-4.7.2/Godot_v4.7.2-stable_win64.exe"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--font', type=Path, default=ROOT / 'godot/assets/camp/ui/camp_ui_zh.ttf', help='Approved open-source TTF subset; copied read-only into the tiny test project')
    args = parser.parse_args()
    font = args.font.resolve(strict=True)
    font_bytes = font.read_bytes()
    assert 4 < len(font_bytes) <= 98304 and font_bytes[:4] == b'\x00\x01\x00\x00', 'Expected bounded packaged TrueType subset'
    original = HUD.read_bytes()
    assert not re.search(rb"\b(?:Time|JavaScriptBridge|HTTPRequest|HTTPClient|Timer|Tween)\s*[.(]|func\s+_process\s*\(", original)
    assert b"extends CanvasLayer" in original
    assert ENGINE.is_file()
    with tempfile.TemporaryDirectory(prefix="camp-boss-hud-native-") as temporary:
        stage = Path(temporary).resolve()
        module = stage / "camp_presentation/camp_boss_hud.gd"
        module.parent.mkdir()
        shutil.copyfile(HUD, module)
        (module.parent / 'fonts').mkdir()
        shutil.copyfile(font, module.parent / 'fonts/camp_ui_zh.ttf')
        (stage / "project.godot").write_text(
            'config_version=5\n[application]\nconfig/name="CampBossHudTestOnly"\n'
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
            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log = result.stdout + result.stderr
        print(log.strip())
        assert result.returncode == 0 and "CAMP_BOSS_HUD_TEST: PASS" in log and "ERROR:" not in log, "Isolated HUD test failed"
        assert HUD.read_bytes() == original, "Source HUD changed during the test"
        assert font.read_bytes() == font_bytes, 'Test must not modify the approved font'
        print("HUD_SOURCE_SHA256: " + hashlib.sha256(original).hexdigest())
        print("CAST_FONT_SHA256: " + hashlib.sha256(font_bytes).hexdigest())


if __name__ == "__main__":
    main()
