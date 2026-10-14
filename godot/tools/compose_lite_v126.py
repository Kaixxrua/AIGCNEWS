"""Combine the two reviewed, disjoint v126 pack candidates without re-export.

The texture candidate changes only CTEX entries; dense-scenes changes only
lossless RSCC containers. Neither may mutate an input, shader, setting or object.
This is a pinned composition recipe, not a general purpose patch injector.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from build_web_quality import write_pack
from inspect_web_pack import read_pack
from repack_web_cache import CACHE_ENTRIES, _unpack


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v126/composed"
INPUTS = {
    "base": (ROOT / "artifacts/v125/index-lite.pck",
             "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"),
    "dense": (ROOT / "artifacts/startup-v126/dense-scenes/candidate-01/index-lite.pck",
              "1486269c29086c476a18550d6b2baf59be970cb1ca7a323899f9c4a2f945210c"),
    "texture": (ROOT / "artifacts/startup-v126/textures/mip2-q60/index-lite.pck",
                "a55f331daee2cda8594f9f784482dd580cb331fcda1962f4e1adc69df40228a4"),
}


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def entries(path, blob):
    inventory = read_pack(path)
    return inventory, {row["path"]: blob[row["offset"]:row["offset"] + row["bytes"]]
                       for row in inventory["entries"]}


def build(output):
    if output.exists() or output.is_symlink():
        raise ValueError("Use a new owned composition directory")
    output = output.resolve()
    if SCOPE.resolve() != SCOPE or output == SCOPE or not output.is_relative_to(SCOPE):
        raise ValueError("Output must stay under the owned composition directory")
    blobs, maps, inventories = {}, {}, {}
    for label, (path, checksum) in INPUTS.items():
        blobs[label] = path.read_bytes()
        if sha(blobs[label]) != checksum:
            raise ValueError(f"Unreviewed input: {label}")
        inventories[label], maps[label] = entries(path, blobs[label])
    base = maps["base"]
    if len(base) != 184 or any(list(m) != list(base) for m in maps.values()):
        raise ValueError("Candidate inventories changed")
    replacements, changes = {}, []
    for label in ("dense", "texture"):
        changed = {name: data for name, data in maps[label].items() if data != base[name]}
        if label == "dense":
            if set(changed) != CACHE_ENTRIES:
                raise ValueError("Unexpected dense-container scope")
            if any(_unpack(data) != _unpack(base[name]) for name, data in changed.items()):
                raise ValueError("Dense container changed decoded scene")
        elif len(changed) != 22 or any(not name.endswith(".ctex") for name in changed):
            raise ValueError("Unexpected texture scope")
        if set(changed) & replacements.keys():
            raise ValueError("Overlapping candidates require an explicit new integration")
        replacements.update(changed)
        changes.extend({"path": name, "candidate": label, "beforeSha256": sha(base[name]),
                        "afterSha256": sha(data), "bytes": len(data)}
                       for name, data in changed.items())
    output.mkdir(parents=True)
    target = output / "index-lite.pck"
    write_pack(INPUTS["base"][0], inventories["base"], target, replacements)
    after = target.read_bytes()
    _, actual = entries(target, after)
    if list(actual) != list(base) or any(actual[name] != replacements.get(name, data)
                                        for name, data in base.items()):
        raise ValueError("Unexpected composed resource mutation")
    for label, (path, _) in INPUTS.items():
        if path.read_bytes() != blobs[label]:
            raise ValueError("Input mutated during composition")
    proof = {"schemaVersion": 1, "profile": "v126-dense-scenes-mip2-q60",
             "inputs": {label: {"path": str(path), "sha256": checksum}
                        for label, (path, checksum) in INPUTS.items()},
             "packSha256": sha(after), "bytes": len(after),
             "offlineGzip6Bytes": len(gzip.compress(after, compresslevel=6, mtime=0)),
             "offlineGzip9Bytes": len(gzip.compress(after, compresslevel=9, mtime=0)),
             "entryCount": 184, "exactEntries": 184 - len(changes), "changes": changes,
             "allDecodedScenesExact": True, "scriptsShadersSettingsExact": True,
             "inputsExact": True, "visualAcceptance": "pending QHD day/night review",
             "textureProof": str(INPUTS["texture"][0].with_name("lite-build.json")),
             "denseProof": str(INPUTS["dense"][0].with_name("proof.json")),
             "note": "No startup or production-performance claim; scene contract must bind this new hash."}
    (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in proof.items() if k != "changes"}, indent=2))
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output)
