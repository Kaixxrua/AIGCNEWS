"""Stage a new version using frozen original/engine files and the current UI.

No Godot re-export is needed for binary resource/settings-only variants. The
original and balanced packs are copied byte-for-byte, not rebuilt from source.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from prepare_web_build import prepare, select_verified_wasm_brotli
from mode5_engine_contract import ENGINE_NAMES, validate_pack_engine
from inspect_web_pack import read_pack


def stage(source, lite, destination, bootstrap=None, *, verified_wasm_br=None):
    source, lite = source.resolve(strict=True), lite.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or not re.fullmatch(r"v\d+", destination.name):
        raise ValueError("Use a NEW version directory")
    # Fail before creating a destination for bad explicit/approved sidecars.
    # Unknown raw engines retain prepare's existing quality6 behavior.
    wasm_br = select_verified_wasm_brotli(source / "index.wasm", verified_wasm_br)
    validate_pack_engine(lite, {name: (source / name).read_bytes() for name in ENGINE_NAMES})
    progressive_path = lite.with_name("progressive-manifest.json")
    progressive = json.loads(progressive_path.read_bytes()) if progressive_path.is_file() else None
    pack_entries = read_pack(lite, verify=True)['entries']
    embedded = next((row for row in pack_entries if row['path'] == 'progressive/manifest.json'), None)
    if bool(embedded) != bool(progressive):
        raise ValueError("Core pack and adjacent progressive manifest must be supplied together")
    if embedded:
        with lite.open('rb') as stream:
            stream.seek(embedded['offset'])
            packed_manifest = json.loads(stream.read(embedded['bytes']))
        if packed_manifest != progressive:
            raise ValueError("Adjacent progressive manifest does not match the selected core pack")
    if progressive:
        if progressive.get("version") != 1 or not 1 <= len(progressive.get("chunks", [])) <= 32:
            raise ValueError("Invalid progressive manifest")
        for index, chunk in enumerate(progressive["chunks"]):
            if chunk.get("index") != index or not re.fullmatch(r"detail-\d+-[a-f0-9]{12}\.pck", chunk.get("file", "")):
                raise ValueError("Unsafe progressive chunk")
            if chunk['file'] != f"detail-{index}-{chunk.get('sha256', '')[:12]}.pck":
                raise ValueError("Chunk filename must match its index and content identity")
            data = lite.with_name(chunk["file"]).read_bytes()
            if len(data) != chunk["bytes"] or hashlib.sha256(data).hexdigest() != chunk["sha256"]:
                raise ValueError("Progressive chunk does not match core manifest")
            validate_pack_engine(lite.with_name(chunk["file"]), {name: (source / name).read_bytes() for name in ENGINE_NAMES})
    if bootstrap:
        bootstrap = bootstrap.resolve(strict=True)
        boot = json.loads((bootstrap/'bootstrap-manifest.json').read_bytes())
        data = (bootstrap/'bootstrap.pck').read_bytes()
        if not progressive or boot['coreSha256'] != hashlib.sha256(lite.read_bytes()).hexdigest() or boot['sha256'] != hashlib.sha256(data).hexdigest():
            raise ValueError('Bootstrap does not match the selected progressive core')
        validate_pack_engine(bootstrap/'bootstrap.pck', {name:(source/name).read_bytes() for name in ENGINE_NAMES})
    original_html = (source / "index.html").read_text(encoding="utf-8")
    match = re.search(r"window\.meadowQuality\.mount\((\{[^\n]+\})\);", original_html)
    if not match:
        raise ValueError("Cannot identify original Godot engine config")
    config = json.loads(match.group(1))
    config.setdefault("fileSizes", {})["index-lite.pck"] = lite.stat().st_size
    shell_path = Path(__file__).resolve().parent.parent / "web" / "meadow-shell.html"
    shell = shell_path.read_text(encoding="utf-8")
    shell = shell.replace("$GODOT_PROJECT_NAME", "风起原野").replace("$GODOT_HEAD_INCLUDE", "")
    shell = shell.replace("$GODOT_URL", "index.js").replace("$GODOT_CONFIG", json.dumps(config, ensure_ascii=False))
    engine_stamp = re.search(r"window\.MEADOW_ENGINE_BUILD = (\{[^\n]+\});", original_html)
    if engine_stamp:
        stamp = json.loads(engine_stamp[1])
        shell = shell.replace("window.meadowQuality.mount(",
                              "window.MEADOW_ENGINE_BUILD = " + json.dumps(stamp) + ";\n    window.meadowQuality.mount(", 1)
    if "$GODOT_" in shell:
        raise ValueError("Unresolved export shell variable")
    destination.mkdir(parents=True)
    frozen = {}
    for name in ("index.pck", "index-balanced.pck", "index.wasm", "index.js",
                 "index.audio.worklet.js", "index.audio.position.worklet.js", "index.png"):
        before = hashlib.sha256((source / name).read_bytes()).hexdigest()
        shutil.copy2(source / name, destination / name)
        if hashlib.sha256((destination / name).read_bytes()).hexdigest() != before:
            raise ValueError(f"Frozen copy mismatch: {name}")
        frozen[name] = before
    if wasm_br is not None:
        if frozen["index.wasm"] != wasm_br["rawSha256"]:
            raise ValueError("Raw WASM changed after Brotli stage preflight")
        # Copy verified bytes only; source publication and its sidecar stay frozen.
        (destination / "index.wasm.br").write_bytes(wasm_br["data"])
    # Keep the provenance of a previously reviewed custom JS/WASM pair.
    if (source / "engine-build.json").is_file():
        shutil.copy2(source / "engine-build.json", destination / "engine-build.json")
    shutil.copy2(lite, destination / "index-lite.pck")
    if progressive:
        shutil.copy2(progressive_path, destination / progressive_path.name)
        for chunk in progressive["chunks"]:
            shutil.copy2(lite.with_name(chunk["file"]), destination / chunk["file"])
    if bootstrap:
        for name in ('bootstrap.pck', 'bootstrap-manifest.json'):
            shutil.copy2(bootstrap/name, destination/name)
    metadata = [lite.with_name(name) for name in ("lite-build.json", "shader-replacements.v1.json", "proof.json", "composition-proof.json", "final-proof.json")]
    if not any(path.is_file() for path in metadata):
        raise ValueError("Variant has no provenance manifest")
    for path in metadata:
        if path.is_file():
            shutil.copy2(path, destination / path.name)
    shutil.copy2(shell_path.with_name("meadow-controls.css"), destination / "meadow-controls.css")
    (destination / "index.html").write_text(shell, encoding="utf-8")
    sizes = prepare(destination, brotli=True, verified_wasm_br=verified_wasm_br)
    for name, checksum in frozen.items():
        if hashlib.sha256((destination / name).read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Preparation modified frozen original: {name}")
    (destination / "frozen-original.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    shared = sum(record["gzipBytes"] for name, record in sizes.items() if not name.endswith(".pck"))
    result = {name: {"gzipTotalBytes": shared + sizes[pack]["gzipBytes"] +
                    (sizes.get('bootstrap.pck', {}).get('gzipBytes', 0) if name == 'lite' else 0), "packBytes": sizes[pack]["bytes"]}
              for name, pack in (("original", "index.pck"), ("balanced", "index-balanced.pck"), ("lite", "index-lite.pck"))}
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("lite", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--bootstrap", type=Path)
    parser.add_argument("--verified-wasm-br", type=Path,
                        help="Optional location for the exact reviewed Brotli WASM sidecar")
    args = parser.parse_args()
    stage(args.source, args.lite, args.destination, args.bootstrap,
          verified_wasm_br=args.verified_wasm_br)
