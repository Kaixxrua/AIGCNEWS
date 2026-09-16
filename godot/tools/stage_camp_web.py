"""Assemble a NEW public Web scene with a pinned optional camp presentation.

No scene export, texture edits or backend input. Frozen v153 engine/core/detail
bytes are copied exactly. Only shared entry helpers change. Every executable
script is external for a scoped CSP. PNG artwork remains inside selected-actor
PCK shards, never preloaded with the scene. This is staging, not deployment.

Usage:
  python -B godot/tools/stage_camp_web.py --bindings artifacts/camp-bootstrap/NAME/selected-pack-bindings.json --presentation artifacts/camp-presentation/NAME/presentation-pack.json --output artifacts/v154
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import brotli

sys.dont_write_bytecode = True
from build_camp_bootstrap import PINS

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "artifacts/v153"
HELPERS = ROOT / "godot/web"
UPDATED = ("meadow-boot.js", "meadow-loader.js", "meadow-controls.js",
           "meadow-controls.css", "meadow-quality.js", "meadow-camp-bridge.js",
           "meadow-camp-integration.js")
ENGINE_PINS = {
    "index.js": "96a4fbc94381a8e0c12362f7379f2febc775cf016175e2632820c5f6311195be",
    "index.wasm": "1bf0d192b97645d76e31fbb7582e3c112981a1e420d5d976ae71757866ee92e1",
}
RUNTIME = re.compile(r"(?:index(?:\.audio(?:\.position)?\.worklet)?\.(?:js|wasm|png)|index(?:-balanced|-lite)?\.pck|bootstrap\.pck|detail-\d+-[a-f0-9]{12}\.pck|meadow-[a-z-]+\.(?:js|css))(?:\.(?:br|gz))?\Z")

def require(value, message):
    if not value:
        raise ValueError(message)

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def regular_input(path):
    info = path.lstat()
    # Resolving a path cannot reveal another hardlink outside the public tree.
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not (getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
            "Unlinked regular input required: " + path.name)
    return info

def pin(directory, spec):
    name = spec["file"]
    require(isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9_.-]+", name), "Local pinned file only")
    source = directory / name
    try:
        info = regular_input(source)
    except FileNotFoundError:
        raise ValueError("Pinned file mismatch: " + name) from None
    require(info.st_size == spec["bytes"] and digest(source) == spec["sha256"],
            "Pinned file mismatch: " + name)
    return source

def write(path, value):
    with path.open("xb") as stream:
        stream.write(value if isinstance(value, bytes) else value.encode("utf-8"))

def compress(path):
    data = path.read_bytes()
    for suffix, encoded in ((".br", brotli.compress(data, quality=6)), (".gz", gzip.compress(data, mtime=0))):
        target = path.with_name(path.name + suffix)
        # Only newly assembled helper outputs are replaced, never source files.
        target.write_bytes(encoded)

def sizes(path):
    return {"bytes": path.stat().st_size, "gzipBytes": path.with_name(path.name+".gz").stat().st_size,
            "brBytes": path.with_name(path.name+".br").stat().st_size}

def assignment(html, name):
    found = re.search(r"window\." + re.escape(name) + r"\s*=\s*(\{[^\n]+\});", html)
    require(found is not None, "Missing source assignment: " + name)
    return json.loads(found.group(1))

def stage(binding_path, presentation_path, output):
    binding_path, presentation_path = binding_path.resolve(strict=True), presentation_path.resolve(strict=True)
    output = output.resolve()
    require(binding_path.is_relative_to(ROOT/"artifacts/camp-bootstrap"), "Public wrapper input only")
    require(presentation_path.is_relative_to(ROOT/"artifacts/camp-presentation"), "Public presentation input only")
    require(output.parent == ROOT/"artifacts" and re.fullmatch(r"v\d+(?:-[a-z0-9-]+)?", output.name)
            and not output.exists(), "New versioned artifact directory required")
    config = json.loads(binding_path.read_bytes())
    art = json.loads(presentation_path.read_bytes())
    require(config["version"] == 1 and config["source"] == "frozen-v153" and art["version"] == 2, "Sharded frozen binding required")
    require(config["optionalPack"] == art["pack"] and config.get("actorShards") == art["actorShards"]
            and config["assetIds"] == art["assetIds"], "Wrapper and actor library must agree")
    for tier, expected in PINS.items():
        if tier == "bootstrap":
            continue
        selected = config["bindings"][tier]["selectedPack"]
        require(selected == expected, "Frozen selected scene pin changed")
        pin(FROZEN, selected)
    for name, expected in ENGINE_PINS.items():
        require(digest(FROZEN/name) == expected, "Frozen engine changed")
    sources = [p for p in FROZEN.iterdir() if p.is_file() and RUNTIME.fullmatch(p.name)]
    frozen_hashes = {p.name: digest(p) for p in sources}
    packs = [(presentation_path.parent, config["optionalPack"])]
    packs.extend((presentation_path.parent, shard["pack"]) for shard in config["actorShards"])
    unique_boots = {}
    for entry in config["bindings"].values():
        spec = entry["bootstrap"]
        name = spec["file"]
        require(name not in unique_boots or unique_boots[name] == spec, "Conflicting bootstrap pin: " + str(name))
        unique_boots[name] = spec
    packs.extend((binding_path.parent, spec) for spec in unique_boots.values())
    # One flat output namespace, including sidecars and generated entry files.
    # Case-folding also prevents aliases on the supported Windows filesystem.
    destinations = {p.name.casefold() for p in sources} | {"index.html", "camp-web-manifest.json"}
    compressible = {p.name for p in sources if p.suffix in (".js", ".css", ".wasm", ".pck")}
    for name in compressible | set(UPDATED) | {"meadow-engine-preload.js", "meadow-camp-entry.js"}:
        destinations.update((name + suffix).casefold() for suffix in ("", ".br", ".gz"))
    for directory, spec in packs:
        source = pin(directory, spec)
        for suffix in ("", ".br", ".gz"):
            name = (source.name + suffix).casefold()
            require(name not in destinations, "Conflicting pack output filename: " + source.name + suffix)
            destinations.add(name)
        raw = source.read_bytes()
        for suffix, decode, message in ((".gz", gzip.decompress, "gzip integrity"), (".br", brotli.decompress, "brotli integrity")):
            sidecar = source.with_name(source.name + suffix)
            regular_input(sidecar)
            require(decode(sidecar.read_bytes()) == raw, message)
    html = (FROZEN/"index.html").read_text("utf-8")
    engine_build = assignment(html, "MEADOW_ENGINE_BUILD")
    quality = assignment(html, "MEADOW_QUALITY")
    contracts = assignment(html, "MEADOW_RENDER_CONTRACTS")
    mount = re.search(r"window\.meadowQuality\.mount\((\{[^\n]+\})\);", html)
    require(mount is not None, "Frozen mount config required")
    engine_config = json.loads(mount.group(1))
    output.mkdir()
    for source in sources:
        shutil.copyfile(source, output/source.name)
    for directory, spec in packs:
        for suffix in ("", ".br", ".gz"):
            shutil.copyfile(directory/(spec["file"]+suffix), output/(spec["file"]+suffix))
    for name in UPDATED:
        shutil.copyfile(HELPERS/name, output/name)
        compress(output/name)
    # Worklet files may not have had compressed sidecars in the old artifact.
    for path in output.iterdir():
        if path.suffix in (".js", ".css", ".wasm", ".pck") and not path.with_name(path.name+".br").exists():
            compress(path)
    # Externalize source inline scripts, not by relaxing the main site's CSP.
    inline = list(re.finditer(r"<script([^>]*)>([\s\S]*?)</script>", html))
    require(len([m for m in inline if not re.search(r"\bsrc=", m.group(1))]) == 2, "Exactly two inline source scripts expected")
    preload = next(m for m in inline if "data-meadow-engine-preload" in m.group(1))
    write(output/"meadow-engine-preload.js", preload.group(2))
    compress(output/"meadow-engine-preload.js")
    html = html.replace(preload.group(0), '<script src="meadow-engine-preload.js"></script>')
    last_inline = next(m for m in inline if "window.MEADOW_ENGINE_BUILD" in m.group(2))
    html = html.replace(last_inline.group(0), '<script src="meadow-camp-entry.js"></script>')
    html = html.replace('  <script src="index.js"></script>',
        '  <script src="meadow-camp-bridge.js"></script>\n  <script src="meadow-camp-integration.js"></script>\n  <script src="index.js"></script>')
    html = html.replace('    <button id="quality-control"', '    <button id="camp-assets-retry" type="button" hidden>重试伙伴下载</button>\n    <button id="quality-control"')
    html = html.replace('中央保留未来行走和 Boss 战区域。', '中央为伙伴与守卫的战斗演出区；账户进度与奖励由网站服务器确认。')
    html = html.replace('不含 HTML 和响应头。', '不含 HTML、响应头和随后按需下载的出场伙伴。')
    shared_names = set(re.findall(r'(?:src|href)="([^"?#]+\.(?:js|css))', html)) | {"index.wasm"}
    shared_names.discard("meadow-camp-entry.js")
    shared = {name: sizes(output/name) for name in sorted(shared_names)}
    # Before loading any pack the quality chooser also counts its own wrapper.
    wrapper_sizes = {}
    for tier, choice in quality.items():
        binding = config["bindings"][tier]
        wrapper_sizes[tier] = {**binding["bootstrap"], **sizes(output/binding["bootstrap"]["file"])}
    entry = "\n".join([
        "window.MEADOW_ENGINE_BUILD = " + json.dumps(engine_build) + ";",
        "window.MEADOW_QUALITY_SHARED = " + json.dumps(shared) + ";",
        "window.MEADOW_RENDER_CONTRACTS = " + json.dumps(contracts) + ";",
        "window.MEADOW_QUALITY = " + json.dumps(quality) + ";",
        "const campEnabled = window.meadowCampIntegration.initialize(" + json.dumps(config) + ");",
        "if (campEnabled) for (const [tier, boot] of Object.entries(" + json.dumps(wrapper_sizes) + ")) window.MEADOW_QUALITY[tier].bootstrap = boot;",
        "document.getElementById('camp-assets-retry').addEventListener('click', () => window.meadowCampIntegration.retryActors());",
        "window.meadowQuality.mount(" + json.dumps(engine_config) + ");",
    ]) + "\n"
    write(output/"meadow-camp-entry.js", entry)
    compress(output/"meadow-camp-entry.js")
    # Content-based helper cache keys; no page-global script injection.
    html = re.sub(r'((?:src|href)=")([^"?#]+\.(?:js|css))(?:\?[^"]*)?"',
        lambda match: match[1]+match[2]+"?v="+digest(output/match[2])[:16]+'"', html)
    require(not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "Inline scripts are prohibited")
    write(output/"index.html", html)
    for name in frozen_hashes:
        require(digest(FROZEN/name) == frozen_hashes[name], "Source v153 changed during staging")
    preserved = {name: expected for name, expected in frozen_hashes.items()
                 if name.split(".br")[0].split(".gz")[0] not in UPDATED}
    require(all(digest(output/name) == expected for name, expected in preserved.items()), "Frozen payload changed")
    payload = {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in output.iterdir() if p.is_file()}
    report = {"version": 1, "source": "frozen-v153", "preserved": preserved, "updatedHelpers": list(UPDATED),
              "bindings": config, "files": payload, "initialArtworkDownloads": 0,
              "scope": "Presentation only; no backend, account, timer or reward data.",
              "acceptance": "Staging integrity only; Web readiness, network and QHD checks are separate."}
    write(output/"camp-web-manifest.json", json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"output":str(output),"files":len(payload),"actorShards":len(config["actorShards"]),
                     "frozenFilesPreserved":len(preserved),"optionalRuntimeBytes":config["optionalPack"]["bytes"]}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", required=True, type=Path)
    parser.add_argument("--presentation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    stage(args.bindings, args.presentation, args.output)
