"""Build only the fixed combat vocabulary, not a full CJK font download.

Source: google/fonts ofl/notosanssc/NotoSansSC[wght].ttf (SIL OFL 1.1).
The downloaded original stays in ignored artifacts; redistribute the subset
with its original copyright/license and a distinct primary family name.
"""
from pathlib import Path
import hashlib
import json
import re

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts/camp-ui-font/NotoSansSC-variable.ttf"
LICENSE = ROOT / "artifacts/camp-ui-font/OFL.txt"
DESTINATION = ROOT / "godot/assets/camp/ui"


def build():
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da":
        raise ValueError("Original Google Fonts source changed; review before regenerating")
    if hashlib.sha256(LICENSE.read_bytes()).hexdigest() != "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9":
        raise ValueError("Original font license changed")
    code = (ROOT / "godot/scripts/camp_presentation.gd").read_text(encoding="utf-8")
    characters = set(re.findall(r"[\u4e00-\u9fff\uff01]", code))
    characters.update(chr(value) for value in range(32, 127))
    characters.update("−×…守卫暂停同步击破奥义")
    font = TTFont(SOURCE, recalcTimestamp=False)
    instantiateVariableFont(font, {"wght": 600}, inplace=True)
    options = subset.Options()
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17]
    options.name_legacy = True
    options.name_languages = [0x409]
    options.recalc_timestamp = False
    worker = subset.Subsetter(options=options)
    worker.populate(text="".join(sorted(characters)))
    worker.subset(font)
    names = {1: "Camp UI Zh", 2: "Semibold", 3: "CampUIZh-Semibold-1.0",
             4: "Camp UI Zh Semibold", 6: "CampUIZh-Semibold", 16: "Camp UI Zh", 17: "Semibold"}
    for row in font["name"].names:
        if row.nameID in names:
            row.string = names[row.nameID].encode(row.getEncoding())
    for identity, value in names.items():
        font["name"].setName(value, identity, 3, 1, 0x409)
    missing = {ord(value) for value in characters} - font.getBestCmap().keys()
    if missing:
        raise ValueError(f"Missing required glyphs: {sorted(missing)}")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    output = DESTINATION / "camp_ui_zh.ttf"
    font.save(output)
    (DESTINATION / "OFL.txt").write_bytes(LICENSE.read_bytes())
    if output.stat().st_size > 96 * 1024:
        raise ValueError("Combat subset exceeds the bounded 96 KiB budget")
    print(json.dumps({"characters": len(characters), "bytes": output.stat().st_size,
                      "sourceSha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                      "subsetSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    build()
