"""Read-only v113 loading contract audit; stdout JSON, no engine/network/writes.

Input: standalone Godot PCK v4 (relative file-base, unencrypted), a Web export
directory containing index.pck, or an already-extracted res:// directory.
Use --baseline artifacts/v113 for conservative retention/change checks.
Exit 0: static checks passed; 1: broken contract; 2: unsupported input or
changed baseline payload needing review. This never certifies visual parity.
Binary scene dependencies and compiled GDScript are NOT semantically decoded;
baseline retention intentionally over-approximates the runtime dependency set.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
from urllib.parse import unquote, urlsplit

from inspect_web_pack import read_pack


MAX_BYTES = 512 * 1024 * 1024
# Approved six full logical material paths. --allow-texture may narrow this set.
# Escarpments has alpha; every decoded mip alpha must be preserved, not flattened.
LOSSY_ELIGIBLE = {
    "assets/materials/meadow-sward-v60.png",
    "assets/materials/ochre-trail-v39.png",
    "assets/materials/limestone-fractured-v61.png",
    "assets/materials/limestone-escarpments-v46.png",
    "assets/materials/riverbank-limestone-v68.png",
    "assets/materials/bridge-oak-v39.png",
}
LOSSLESS_CACHES = frozenset({
    "assets/baked/v77/detail.scn", "assets/baked/v77/brush.scn",
    "assets/baked/v77/foothill.scn", "assets/baked/v77/riverbank.scn",
    "assets/baked/v113/far-sward.scn",
})
TEXT_SUFFIXES = (".remap", ".import", ".gdshader", ".gdshaderinc", ".tscn", ".tres", ".gd")
RESOURCE_RE = re.compile(r'res://[A-Za-z0-9_./-]+')
CRITICAL = (
    "project.binary", "scenes/main.tscn", "scripts/meadow_scene.gd",
    "scripts/meadow_weather.gd", "scripts/meadow_wildlife.gd",
    "scripts/meadow_fauna_art.gd", "scripts/meadow_dragon_art.gd",
    "scripts/meadow_static_cache.gd", "scripts/meadow_ground_atmosphere.gd",
    "scripts/meadow_far_sward.gd", "scripts/meadow_mountain_atmosphere.gd",
    "scripts/meadow_architecture_fog.gd", "scripts/meadow_settlement_lights.gd",
    "scripts/meadow_road_lights.gd", "scripts/meadow_rock_occlusion.gd",
    "shaders/meadow_water.gdshader", "shaders/meadow_sky.gdshader",
    "shaders/meadow_focus.gdshader", "shaders/meadow_animal.gdshader",
    "shaders/meadow_dragon.gdshader", "shaders/meadow_spirit_aura.gdshader",
    "shaders/meadow_ground.gdshader", "shaders/meadow_ground_day.gdshader",
    "assets/creatures/leaf-hare-v54.png", "assets/creatures/bud-deer-v54.png",
    "assets/creatures/gold-fox-v54.png", "assets/creatures/moon-stag-v54.png",
    "assets/creatures/castle-dragon-turns-v57.png",
    "assets/materials/river-ripples-v37.png", "assets/materials/meadow-sward-v60.png",
    "assets/baked/v110/rock-occlusion.bin", "assets/baked/v113/far-sward.scn",
) + tuple(f"assets/baked/v77/{name}.scn" for name in ("terrain", "detail", "brush", "foothill", "riverbank"))


def safe_name(name):
    name = name.removeprefix("res://")
    if not name or "\\" in name or ":" in name or "\0" in name:
        raise ValueError(f"Unsafe resource path: {name!r}")
    if name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError(f"Unsafe resource path: {name!r}")
    return name


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_pck(blob):
    """Parse observed v4 layout, validate bounds/overlap/MD5, never extract."""
    if len(blob) < 112 or bytes(blob[:4]) != b"GDPC":
        raise ValueError("Not a standalone GDPC pack")
    version, major, minor, patch, flags = struct.unpack_from("<5I", blob, 4)
    if version != 4 or flags != 2:
        raise ValueError(f"Unsupported pack version/flags {version}/{flags}; expected v4 relative-base unencrypted")
    base, index = struct.unpack_from("<QQ", blob, 24)
    if not (112 <= base <= index <= len(blob) - 4):
        raise ValueError("Invalid PCK data/index boundary")
    count = struct.unpack_from("<I", blob, index)[0]
    if count > 100000:
        raise ValueError("Implausible entry count")
    cursor, entries, spans = index + 4, {}, []
    for _ in range(count):
        if cursor + 4 > len(blob):
            raise ValueError("Truncated index")
        length = struct.unpack_from("<I", blob, cursor)[0]
        cursor += 4
        if not 0 < length <= 16384 or cursor + length + 36 > len(blob):
            raise ValueError("Invalid/truncated path record")
        name = safe_name(bytes(blob[cursor:cursor + length]).rstrip(b"\0").decode("utf-8"))
        cursor += length
        offset, size = struct.unpack_from("<QQ", blob, cursor)
        digest = bytes(blob[cursor + 16:cursor + 32])
        entry_flags = struct.unpack_from("<I", blob, cursor + 32)[0]
        cursor += 36
        start = base + offset
        if name in entries or entry_flags or start < base or start + size > index:
            raise ValueError(f"Duplicate, flagged or out-of-bounds entry: {name}")
        data = memoryview(blob)[start:start + size]
        if hashlib.md5(data).digest() != digest:
            raise ValueError(f"PCK entry MD5 mismatch: {name}")
        entries[name] = data
        if size:
            spans.append((start, start + size, name))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError("Overlapping PCK payload entries")
    if cursor != len(blob):
        raise ValueError("Unexpected trailing PCK data; layout not audited")
    return entries, {"format": version, "engine": [major, minor, patch], "flags": flags,
                     "file_base": base, "index_offset": index, "entry_count": count}


class Package:
    def __init__(self, path):
        self.path = Path(path).resolve(strict=True)
        pack = self.path / "index.pck" if self.path.is_dir() else self.path
        self.web = self.path if self.path.is_dir() and pack.is_file() else None
        if pack.is_file():
            if pack.stat().st_size > MAX_BYTES:
                raise ValueError("PCK exceeds 512 MiB audit input limit")
            blob = pack.read_bytes()
            # Shared directory parser and ALL-entry MD5 checks owned by main.
            inventory = read_pack(pack, verify=True)
            self.entries = {safe_name(e["path"]): memoryview(blob)[e["offset"]:e["offset"] + e["bytes"]]
                            for e in inventory["entries"]}
            spans = sorted((e["offset"], e["offset"] + e["bytes"]) for e in inventory["entries"] if e["bytes"])
            if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
                raise ValueError("Overlapping PCK payload entries")
            # Detect input races between snapshot and shared-parser reads.
            for e in inventory["entries"]:
                if hashlib.md5(self.entries[safe_name(e["path"])]).hexdigest() != e["md5"]:
                    raise ValueError("PCK changed during audit")
            self.header = {"format": inventory["version"], "engine": inventory["engine"],
                           "entry_count": len(self.entries), "parser": "inspect_web_pack.read_pack"}
            self.header.update(bytes=len(blob), sha256=sha(blob))
        else:
            self.entries, total = {}, 0
            for file in sorted(self.path.rglob("*")):
                if file.is_symlink():
                    raise ValueError(f"Symlink input not supported: {file}")
                if file.is_file():
                    if not file.resolve().is_relative_to(self.path):
                        raise ValueError("File escapes input root")
                    total += file.stat().st_size
                    if total > MAX_BYTES:
                        raise ValueError("Extracted input exceeds 512 MiB")
                    self.entries[safe_name(file.relative_to(self.path).as_posix())] = file.read_bytes()
            self.header = {"format": "extracted", "bytes": total, "entry_count": len(self.entries)}
        self.maps = {}
        for name, data in self.entries.items():
            if name.endswith((".remap", ".import")):
                text = bytes(data).decode("utf-8").rstrip("\0")
                # All feature-specific targets must be present; resolution uses
                # the sole/default target. Multi-target variants fail closed.
                targets = re.findall(r'^path(?:\.[\w.]+)?\s*=\s*"(res://[^"\r\n]+)"', text, re.M)
                if len(targets) != 1:
                    raise ValueError(f"Unsupported missing/multiple remap targets: {name}")
                logical = name.rsplit(".", 1)[0]
                if logical in self.maps:
                    raise ValueError(f"Conflicting remaps: {logical}")
                self.maps[logical] = safe_name(targets[0])

    def resolve(self, name):
        name, seen = safe_name(name), set()
        while name in self.maps:
            if name in seen:
                raise ValueError(f"Remap cycle: {name}")
            seen.add(name)
            name = self.maps[name]
        return name if name in self.entries else None

    def logical(self):
        targets = set(self.maps.values())
        return set(self.maps) | {n for n in self.entries if n not in targets
                                 and not n.endswith((".import", ".remap"))}


def texture_shape(data):
    if bytes(data[:4]) == b"GST2" and len(data) >= 20:
        version, width, height, flags = struct.unpack_from("<4I", data, 4)
        return {"container": "GST2", "version": version, "width": width, "height": height, "flags": flags}
    if bytes(data[:8]) == b"\x89PNG\r\n\x1a\n" and len(data) >= 26:
        width, height = struct.unpack_from(">II", data, 16)
        return {"container": "PNG", "width": width, "height": height}
    return None


def check_package(pkg):
    errors, warnings = [], []
    for name in sorted(set(CRITICAL) | set(pkg.maps)):
        if pkg.resolve(name) is None:
            errors.append(f"Missing required resource/remap target: {name}")
    checked_refs = 0
    for name, data in pkg.entries.items():
        if not name.endswith(TEXT_SUFFIXES):
            continue
        text = bytes(data).decode("utf-8").rstrip("\0")
        # Strip full-line comments, but do not pretend to parse GDScript.
        text = "\n".join(line for line in text.splitlines()
                         if not line.lstrip().startswith(("//", "# ")))
        refs = set(RESOURCE_RE.findall(text))
        for include in re.findall(r'#include\s+"([^"\r\n]+)"', text):
            refs.add(include if include.startswith("res://") else str(PurePosixPath(name).parent / include))
        for ref in sorted(refs):
            # Directory prefixes/dynamic strings require manual contract roots.
            if ref.endswith("/"):
                continue
            checked_refs += 1
            if pkg.resolve(ref) is None:
                item = f"Unresolved textual reference: {name} -> {ref}"
                (warnings if ref.startswith("res://tools/") else errors).append(item)
    totals = {}
    for name, data in pkg.entries.items():
        category = "textures" if name.endswith(".ctex") else "baked" if name.startswith("assets/baked/") else "other"
        totals[category] = totals.get(category, 0) + len(data)
    return {"errors": errors, "warnings": warnings, "textual_references_checked": checked_refs,
            "payload_bytes_by_category": totals,
            "largest_entries": [{"path": n, "bytes": len(d)} for n, d in
                                sorted(pkg.entries.items(), key=lambda item: -len(item[1]))[:12]]}


def compare_packages(base, candidate):
    errors, changes, diagnostic_removed = [], [], []
    for logical in sorted(base.logical()):
        before, after = base.resolve(logical), candidate.resolve(logical)
        if after is None:
            if logical.startswith("tools/"):
                diagnostic_removed.append(logical)
            else:
                errors.append(f"Baseline resource removed (not proven unused): {logical}")
            continue
        a, b = base.entries[before], candidate.entries[after]
        if sha(a) != sha(b):
            change = {"resource": logical, "before_bytes": len(a), "after_bytes": len(b),
                      "before_sha256": sha(a), "after_sha256": sha(b)}
            ta, tb = texture_shape(a), texture_shape(b)
            if ta or tb:
                change.update(before_texture=ta, after_texture=tb)
                if not ta or not tb or (ta["width"], ta["height"]) != (tb["width"], tb["height"]):
                    errors.append(f"Texture dimensions/type changed; fixed atlas/alpha roots need revalidation: {logical}")
            changes.append(change)
    return {"errors": errors, "changed_payloads": changes,
            "removed_diagnostics": diagnostic_removed,
            "added_resources": sorted(candidate.logical() - base.logical())}


def file_digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_material_levels(before, after):
    """Decode every mip independently; preserve the entire CTEX header/alpha."""
    from PIL import Image

    def decode(blob):
        blob = bytes(blob)
        if len(blob) < 56 or blob[:4] != b"GST2" or struct.unpack_from("<I", blob, 4)[0] != 1:
            raise ValueError("Unsupported/truncated CTEX")
        kind, width, height, mips, image_format = struct.unpack_from("<IHHII", blob, 36)
        if kind != 2 or image_format not in (4, 5) or mips > 16 or not width or not height:
            raise ValueError("Expected WebP RGB(A) CTEX mip chain")
        if width * height > 16 * 1024 * 1024:
            raise ValueError("Texture exceeds audit pixel limit")
        levels, offset = [], 52
        for level in range(mips + 1):
            if offset + 4 > len(blob):
                raise ValueError("Missing CTEX mip length")
            size = struct.unpack_from("<I", blob, offset)[0]
            offset += 4
            if not size or offset + size > len(blob):
                raise ValueError("Truncated CTEX mip payload")
            with Image.open(io.BytesIO(blob[offset:offset + size])) as image:
                expected = (max(1, width >> level), max(1, height >> level))
                if image.format != "WEBP" or image.size != expected:
                    raise ValueError(f"Mip {level} codec/dimensions mismatch")
                rgba = image.convert("RGBA")
                alpha = rgba.getchannel("A")
                levels.append({"level": level, "size": list(expected),
                               "alpha": alpha.tobytes(), "alpha_range": list(alpha.getextrema()),
                               "rgba_sha256": sha(rgba.tobytes())})
            offset += size
        if offset != len(blob):
            raise ValueError("Unexpected CTEX trailing payload")
        return levels

    if bytes(before[:52]) != bytes(after[:52]):
        raise ValueError("CTEX header/metadata/dimensions/levels changed")
    a, b = decode(before), decode(after)
    if len(a) != len(b):
        raise ValueError("CTEX level count changed")
    result = []
    for x, y in zip(a, b):
        if x["size"] != y["size"] or x["alpha"] != y["alpha"]:
            raise ValueError("CTEX decoded dimensions/alpha changed")
        result.append({"level": x["level"], "size": x["size"], "alpha_exact": True,
                       "alpha_range": x["alpha_range"],
                       "rgba_equal": x["rgba_sha256"] == y["rgba_sha256"]})
    return result


def exact_entries(base, candidate, allowed=(), repack_caches=False, decode_materials=False):
    """Byte-identical entries except explicitly resolved texture payloads.

    Remaps, import metadata, all shaders/scripts, caches and project settings
    are intentionally NOT exempted, even for an approved texture.
    """
    errors, changed, cache_checks, material_checks = [], [], [], []
    if set(base.entries) != set(candidate.entries):
        errors.append("PCK entry set differs: " + json.dumps({
            "removed": sorted(set(base.entries) - set(candidate.entries)),
            "added": sorted(set(candidate.entries) - set(base.entries))}))
    for name in sorted(set(base.entries) & set(candidate.entries)):
        a, b = base.entries[name], candidate.entries[name]
        identical = sha(a) == sha(b)
        if not identical:
            changed.append(name)
        if repack_caches and name in LOSSLESS_CACHES:
            from repack_web_cache import _unpack
            try:
                raw_a, raw_b = _unpack(bytes(a)), _unpack(bytes(b))
                if raw_a != raw_b:
                    raise ValueError("decoded bytes differ (including resource metadata)")
                cache_checks.append({"path": name, "raw_bytes": len(raw_a),
                                     "raw_sha256": sha(raw_a), "raw_exact": True,
                                     "container_equal": identical})
            except ValueError as error:
                errors.append(f"Lossless cache check failed: {name}: {error}")
        elif name in allowed and decode_materials:
            try:
                material_checks.append({"path": name, "levels": verify_material_levels(a, b)})
            except (ValueError, OSError) as error:
                errors.append(f"Material mip/alpha check failed: {name}: {error}")
        elif identical:
            continue
        elif name not in allowed:
            errors.append(f"Non-allowlisted PCK entry changed: {name}")
        elif not name.endswith(".ctex") or bytes(a[:4]) != b"GST2" or bytes(b[:4]) != b"GST2":
            errors.append(f"Allowlisted payload is not a GST2 texture: {name}")
        elif texture_shape(a) != texture_shape(b):
            errors.append(f"Allowlisted texture dimensions/header flags changed: {name}")
    return {"errors": errors, "changed_entries": changed,
            "lossless_cache_checks": cache_checks, "material_checks": material_checks,
            "unchanged_entries": len(set(base.entries) & set(candidate.entries)) - len(changed)}


def check_quality_trace(trace, original, fast, wasm):
    """Validate externally captured evidence; never invent/run browser checks.

    JSON {runs:[{quality:'original'|'balanced', selectedQuality:..., ready:true,
    selectorOptions:['original','balanced'], selectionVia:'ui', engineStarts:1,
    mainPack:'index.pck', requests:[{url:'https://.../index.pck',status:200},
    {url:'https://.../index.wasm',status:200}]}]}. Requests must be a complete
    per-navigation trace through scene-ready, including preload/prefetch/cache.
    """
    errors, results = [], []
    # Preserve real source labels in output. fast is a legacy alias only;
    # callers do not need to rewrite actual DOM/network evidence.
    canonical = lambda value: "balanced" if value == "fast" else value
    expected = {"original": original, "balanced": fast}
    runs = trace.get("runs", [])
    if not isinstance(runs, list) or sorted(canonical(r.get("quality", "")) for r in runs) != ["balanced", "original"]:
        return {"errors": ["Trace must contain exactly one original and one balanced run (fast alias accepted)"]}
    def filename(url):
        return PurePosixPath(unquote(urlsplit(url).path)).name
    for run in runs:
        quality = canonical(run["quality"])
        if canonical(run.get("selectedQuality")) != quality or {canonical(v) for v in run.get("selectorOptions", [])} != set(expected):
            errors.append(f"{quality}: both UI qualities must be exposed and selected correctly")
        if run.get("selectionVia") != "ui" or run.get("ready") is not True or run.get("engineStarts") != 1:
            errors.append(f"{quality}: UI selection, scene-ready and exactly one engine start not established")
        if filename(run.get("mainPack", "")) != expected[quality]:
            errors.append(f"{quality}: wrong engine mainPack")
        requests = run.get("requests", [])
        packs = [r for r in requests if filename(r.get("url", "")).endswith(".pck")]
        engines = [r for r in requests if filename(r.get("url", "")).endswith(".wasm")]
        for label, rows, target in (("PCK", packs, expected[quality]), ("WASM", engines, wasm)):
            if len(rows) != 1 or filename(rows[0].get("url", "")) != target or rows[0].get("status") not in (200, 304):
                errors.append(f"{quality}: expected exactly one successful {label} request for {target}")
        results.append({"quality": run["quality"], "canonicalQuality": quality,
                        "pck_requests": len(packs), "wasm_requests": len(engines)})
    return {"errors": errors, "runs": results, "evidence_kind": "external_trace_consistency_only"}


def dual_quality(args):
    if not (args.original and args.fast and args.baseline) or (not args.core_only and not args.wasm):
        raise ValueError("Dual mode requires --original --fast --baseline, plus --wasm unless --core-only")
    names = {safe_name(n) for n in args.allow_texture} if args.allow_texture else set(LOSSY_ELIGIBLE)
    if not names or not names <= LOSSY_ELIGIBLE:
        raise ValueError("Use only the six exact material paths; no globs/water/foliage/animals")
    original, fast, baseline = Package(args.original), Package(args.fast), Package(args.baseline)
    if original.path == fast.path or original.path.name == fast.path.name:
        raise ValueError("Dual mode requires distinct standalone PCK filenames")
    if args.wasm and (not args.wasm.is_file() or args.wasm.read_bytes()[:8] != b"\0asm\x01\0\0\0"):
        raise ValueError("Missing/invalid shared WASM")
    errors, allowed = [], set()
    for pkg in (baseline, original, fast):
        errors.extend(check_package(pkg)["errors"])
    for name in sorted(names):
        before, after = original.resolve(name), fast.resolve(name)
        if not before or not after or before != after or not before.endswith(".ctex"):
            errors.append(f"Allowlist texture has absent/different import target: {name}")
        else:
            allowed.add(before)
    lossless = exact_entries(baseline, original, repack_caches=True)
    lossy = exact_entries(original, fast, allowed, repack_caches=True, decode_materials=True)
    errors.extend(lossless["errors"] + lossy["errors"])
    base_wasm = (baseline.web or baseline.path.parent) / "index.wasm"
    if args.wasm and (not base_wasm.is_file() or file_digest(base_wasm) != file_digest(args.wasm)):
        errors.append("Shared WASM differs from/missing in v113 baseline")
    core = {"status": "FAIL" if errors else "CORE_PACK_PASS", "errors": errors,
            "baseline": str(baseline.path), "baseline_sha256": baseline.header.get("sha256"),
            "allowlist": sorted(names), "original_vs_baseline": lossless, "fast_vs_original": lossy,
            "terrain_policy": "strict entry byte equality; no RSCC exception",
            "runtime": {"status": "NOT_RUN"},
            "limitations": ["Only five exact SCN paths allow container recompression; decoded metadata is NOT waived",
                            "Lossy image aesthetics and two-quality UI/loading require separate review",
                            "Equivalence is relative to the supplied baseline, not automatically to v113"]}
    if args.core_only:
        print(json.dumps(core, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    web_root = args.input.resolve() if args.input else original.path.parent
    html = web_root / "index.html"
    pending = []
    if html.is_file():
        for tag in re.findall(r'<link\b[^>]*>', html.read_text(encoding="utf-8"), re.I):
            if re.search(r'\brel=["\'](?:preload|prefetch)["\']', tag, re.I) and re.search(r'\.pck(?:[?"\'])', tag):
                errors.append("Unconditional HTML PCK preload/prefetch can download unselected quality")
    else:
        pending.append("Export index.html unavailable: preload audit pending")
    runtime = {"status": "NOT_RUN"}
    if args.quality_trace:
        runtime = check_quality_trace(json.loads(args.quality_trace.read_text(encoding="utf-8")),
                                      original.path.name, fast.path.name, args.wasm.name)
        errors.extend(runtime["errors"])
    else:
        pending.append("Need --quality-trace for both UI selections/single-pack runtime loading")
    status = "FAIL" if errors else "REVIEW_REQUIRED" if pending else "CONTRACT_PASS"
    result = {"status": status, "errors": errors, "pending": pending,
              "allowlist": sorted(names), "original_vs_baseline": lossless,
              "fast_vs_original": lossy, "shared_wasm_sha256": file_digest(args.wasm),
              "runtime": runtime,
              "limitations": ["No browser/engine/network run; external trace must be complete and trustworthy",
                              "Allowed lossy texture visual quality is not certified by this contract",
                              "Only five specified caches may differ as containers; decoded bytes must match"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 2 if pending else 0


def check_web(root):
    errors, warnings, checked = [], [], []
    def local(name):
        name = safe_name(name.split("?", 1)[0])
        file = root / name
        if not file.resolve().is_relative_to(root):
            raise ValueError(f"Web reference escapes input: {name}")
        return file
    required = ("index.html", "index.js", "index.wasm", "index.pck", "meadow-controls.js", "meadow-controls.css")
    for name in required:
        if not local(name).is_file():
            errors.append(f"Missing Web boot file: {name}")
    if errors:
        return {"errors": errors, "warnings": warnings}
    html = local("index.html").read_text(encoding="utf-8")
    match = re.search(r'meadowTimeUI\.start\((\{[^\n]+\})\)', html)
    if not match:
        errors.append("Cannot locate reviewed meadowTimeUI.start JSON config")
    else:
        config = json.loads(match[1])
        for name in ("index.pck", "index.wasm"):
            if config.get("fileSizes", {}).get(name) != local(name).stat().st_size:
                errors.append(f"Stale/missing HTML fileSizes: {name}")
        if config.get("executable") != "index":
            errors.append("Unexpected executable; review boot contract")
    for name in re.findall(r'(?:src|href)="([^"#]+)"', html):
        if not local(name).is_file():
            errors.append(f"Missing HTML dependency: {name}")
        elif "?v=" in name and name.startswith("meadow-controls."):
            if name.split("?v=", 1)[1] != file_digest(local(name))[:16]:
                errors.append(f"Stale control cache key: {name}")
    # Worklet filenames are dependencies named by the exported engine glue.
    glue = local("index.js").read_text(encoding="utf-8")
    for suffix in set(re.findall(r'[\w.]*worklet\.js', glue)):
        if suffix.startswith("godot."):
            # The exported glue's locateFile maps godot.* to loadPath=index.
            suffix = "index." + suffix.removeprefix("godot.")
        elif suffix.startswith("."):
            suffix = "index" + suffix
        if not local(suffix).is_file():
            errors.append(f"Missing engine worklet: {suffix}")
    manifest_file = local("web-payload.json")
    manifest = json.loads(manifest_file.read_text()) if manifest_file.is_file() else {}
    if not manifest:
        warnings.append("web-payload.json absent; no manifest consistency check")
    for name, entry in manifest.items():
        file = local(name)
        if not file.is_file() or entry.get("bytes") != file.stat().st_size or entry.get("sha256") != file_digest(file):
            errors.append(f"Stale/missing payload manifest entry: {name}")
        if entry.get("gzipBytes") is not None and not local(name + ".gz").is_file():
            errors.append(f"Manifest advertises missing gzip sibling: {name}")
    for file in sorted(root.glob("*.gz")):
        raw = local(file.name[:-3])
        if not raw.is_file():
            errors.append(f"Orphan gzip: {file.name}")
            continue
        h, count = hashlib.sha256(), 0
        with gzip.open(file, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                count += len(block)
                if count > raw.stat().st_size:
                    raise ValueError(f"gzip expands beyond raw file: {file.name}")
                h.update(block)
        if count != raw.stat().st_size or h.hexdigest() != file_digest(raw):
            errors.append(f"gzip decoded bytes differ from raw: {file.name}")
        if file.stat().st_mtime_ns < raw.stat().st_mtime_ns:
            warnings.append(f"Existing server will skip older gzip sibling: {file.name}")
        if raw.name in manifest and manifest[raw.name].get("gzipBytes") != file.stat().st_size:
            errors.append(f"Stale manifest gzipBytes: {file.name}")
        checked.append(file.name)
    return {"errors": errors, "warnings": warnings, "gzip_roundtrips_checked": checked,
            "unverified_brotli_sidecars": sorted(file.name for file in root.glob("*.br")),
            "http_headers_and_browser_startup": "NOT_RUN"}


def self_test():
    # Pure memory fixtures: no package/source files are written.
    payload = b"read-only-test"
    name = b"project.binary\0\0"
    index = 112 + len(payload)
    header = b"GDPC" + struct.pack("<5IQQ", 4, 4, 7, 2, 2, 112, index) + bytes(72)
    row = struct.pack("<I", len(name)) + name + struct.pack("<QQ", 0, len(payload)) + hashlib.md5(payload).digest() + bytes(4)
    blob = header + payload + struct.pack("<I", 1) + row
    entries, _ = parse_pck(blob)
    assert bytes(entries["project.binary"]) == payload
    tested = ["valid_v4", "gzip_roundtrip"]
    assert gzip.decompress(gzip.compress(payload, mtime=0)) == payload
    corruptions = {"truncation": blob[:-1], "bad_md5": blob[:112] + b"X" + blob[113:],
                   "unsupported_format": blob[:4] + struct.pack("<I", 99) + blob[8:],
                   "bad_index": blob[:32] + struct.pack("<Q", len(blob) + 1) + blob[40:]}
    for label, bad in corruptions.items():
        try:
            parse_pck(bad)
        except ValueError:
            tested.append(label)
        else:
            raise AssertionError(f"Did not reject {label}")
    for name in ("../escape", "/absolute", "C:/drive", "a/../b"):
        try:
            safe_name(name)
        except ValueError:
            continue
        raise AssertionError("Unsafe path accepted")
    tested.append("unsafe_paths")
    # Exercise resource resolution and comparison without disk fixtures.
    a, b = Package.__new__(Package), Package.__new__(Package)
    a.entries = {"scripts/x.gdc": b"same", "tools/test.gdc": b"diagnostic"}
    a.maps = {"scripts/x.gd": "scripts/x.gdc", "tools/test.gd": "tools/test.gdc"}
    b.entries, b.maps = {"scripts/x.gdc": b"same"}, {"scripts/x.gd": "scripts/x.gdc"}
    assert not compare_packages(a, b)["errors"]
    assert compare_packages(a, b)["removed_diagnostics"] == ["tools/test.gd"]
    b.entries = {}
    assert compare_packages(a, b)["errors"]
    b.entries = {"scripts/x.gdc": b"changed"}
    assert compare_packages(a, b)["changed_payloads"]
    b.maps = {"a": "b", "b": "a"}
    try:
        b.resolve("a")
    except ValueError:
        tested.append("remap_cycle")
    else:
        raise AssertionError("Cycle accepted")
    tested.extend(["remap_resolution", "missing_runtime", "diagnostic_removal", "changed_payload"])
    a.maps, b.maps = {}, {}
    a.entries = {"image.ctex": b"GST2" + struct.pack("<4I", 1, 100, 100, 0)}
    b.entries = {"image.ctex": b"GST2" + struct.pack("<4I", 1, 50, 50, 0)}
    assert compare_packages(a, b)["errors"]
    tested.append("texture_resize_rejected")
    # Dual-quality negative fixtures are entirely in memory.
    b.entries = dict(a.entries)
    b.entries["image.ctex"] += b"lossy"
    assert not exact_entries(a, b, {"image.ctex"})["errors"]
    assert exact_entries(a, b)["errors"]
    b.entries["shader.gdshader"] = b"unexpected"
    assert exact_entries(a, b, {"image.ctex"})["errors"]
    tested.extend(["dual_whitelist_only", "dual_original_exact", "dual_extra_entry_rejected"])
    runs = [{"quality": q, "selectedQuality": q, "ready": True, "selectionVia": "ui",
             "selectorOptions": ["original", "fast"], "engineStarts": 1,
             "mainPack": f"{q}.pck", "requests": [{"url": f"https://test/{q}.pck", "status": 200},
             {"url": "https://test/index.wasm", "status": 200}]} for q in ("original", "fast")]
    assert not check_quality_trace({"runs": runs}, "original.pck", "fast.pck", "index.wasm")["errors"]
    runs[1]["quality"] = runs[1]["selectedQuality"] = "balanced"
    for run in runs:
        run["selectorOptions"] = ["original", "balanced"]
    assert not check_quality_trace({"runs": runs}, "original.pck", "fast.pck", "index.wasm")["errors"]
    tested.append("native_balanced_label_accepted")
    runs[1]["requests"].append({"url": "https://test/original.pck", "status": 200})
    assert check_quality_trace({"runs": runs}, "original.pck", "fast.pck", "index.wasm")["errors"]
    runs[1]["requests"].pop()
    runs[1]["selectedQuality"] = "original"
    assert check_quality_trace({"runs": runs}, "original.pck", "fast.pck", "index.wasm")["errors"]
    tested.extend(["dual_both_ui_routes", "dual_extra_pack_rejected", "dual_unreachable_quality_rejected"])
    from repack_web_cache import _pack
    raw = b"geometry/collider/material metadata" * 500
    old_cache, new_cache = _pack(raw, 4096, 3), _pack(raw, 262144, 9)
    cache_name = "assets/baked/v77/detail.scn"
    a.entries, b.entries = {cache_name: old_cache}, {cache_name: new_cache}
    assert not exact_entries(a, b, repack_caches=True)["errors"]
    b.entries[cache_name] = _pack(raw + b"changed metadata", 262144, 9)
    assert exact_entries(a, b, repack_caches=True)["errors"]
    a.entries, b.entries = {"assets/baked/v77/terrain.scn": old_cache}, {"assets/baked/v77/terrain.scn": new_cache}
    assert exact_entries(a, b, repack_caches=True)["errors"]
    tested.extend(["five_cache_lossless_repack", "decoded_cache_metadata_rejected", "terrain_repack_rejected"])
    from PIL import Image
    def ctex_fixture(alpha=255, red=80):
        header = bytearray(52)
        struct.pack_into("<4s4I", header, 0, b"GST2", 1, 8, 8, 0)
        struct.pack_into("<IHHII", header, 36, 2, 8, 8, 3, 5)
        for level in range(4):
            output = io.BytesIO()
            image = Image.new("RGBA", (8 >> level, 8 >> level), (red, 100, 120, alpha))
            image.save(output, "WEBP", lossless=True)
            data = output.getvalue()
            header.extend(struct.pack("<I", len(data)) + data)
        return bytes(header)
    tex_a, tex_b = ctex_fixture(), ctex_fixture(red=90)
    assert len(verify_material_levels(tex_a, tex_b)) == 4
    assert len(verify_material_levels(ctex_fixture(alpha=120), ctex_fixture(alpha=120, red=90))) == 4
    for bad in (ctex_fixture(alpha=254), tex_b[:-1], tex_b + b"extra",
                tex_b[:48] + struct.pack("<I", 4) + tex_b[52:]):
        try:
            verify_material_levels(tex_a, bad)
        except (ValueError, OSError):
            continue
        raise AssertionError("Invalid material accepted")
    tested.extend(["all_mips_decoded", "alpha_change_rejected", "truncated_mip_rejected",
                   "ctex_trailing_data_rejected", "ctex_metadata_rejected", "existing_alpha_preserved"])
    return {"self_test": "PASS", "cases": tested}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--original", type=Path, help="Original PCK: baseline entry equality except five decoded-exact SCN containers")
    parser.add_argument("--fast", "--balanced", dest="fast", type=Path, help="Dual-quality balanced PCK (--fast retained as alias)")
    parser.add_argument("--wasm", type=Path, help="Shared WASM, byte-identical to v113")
    parser.add_argument("--allow-texture", action="append", default=[], help="Explicit logical texture path; repeat, no globs")
    parser.add_argument("--quality-trace", type=Path, help="Complete two-run UI/network evidence JSON; see check_quality_trace docstring")
    parser.add_argument("--core-only", action="store_true", help="Verify both PCKs now; no WASM/UI/trace claim, success is CORE_PACK_PASS")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if args.input is None and not (args.original or args.fast):
        parser.error("input is required unless --self-test")
    try:
        if args.original or args.fast:
            return dual_quality(args)
        candidate = Package(args.input)
        result = {"input": str(candidate.path), "pack": candidate.header, **check_package(candidate)}
        if candidate.web:
            result["web"] = check_web(candidate.web)
            result["errors"].extend(result["web"]["errors"])
        if args.baseline:
            base = candidate if args.baseline.resolve() == candidate.path else Package(args.baseline)
            baseline_checks = check_package(base)
            if baseline_checks["errors"]:
                raise ValueError("Baseline is incomplete: " + "; ".join(baseline_checks["errors"]))
            result["baseline"] = {"path": str(base.path), **base.header}
            result["comparison"] = compare_packages(base, candidate)
            result["errors"].extend(result["comparison"]["errors"])
            if base.web and candidate.web:
                result["web_changed_payloads"] = []
                for name in ("index.html", "index.js", "index.wasm", "meadow-controls.js", "meadow-controls.css",
                             "index.audio.worklet.js", "index.audio.position.worklet.js"):
                    before, after = base.web / name, candidate.web / name
                    if before.is_file() and not after.is_file():
                        result["errors"].append(f"Baseline Web dependency removed: {name}")
                    elif before.is_file() and file_digest(before) != file_digest(after):
                        result["web_changed_payloads"].append(name)
        changes = result.get("comparison", {}).get("changed_payloads", [])
        review = bool(changes or result.get("web_changed_payloads")
                      or result.get("web", {}).get("unverified_brotli_sidecars"))
        result["status"] = "FAIL" if result["errors"] else "REVIEW_REQUIRED" if review else "STATIC_PASS"
        result["limitations"] = ["Not visual/runtime acceptance; no engine, browser or network used",
                                 "RSCC scene internals/GDScript bytecode/UID graph not semantically decoded",
                                 "Texture header sizes are not decoded alpha/mipmap/pixel parity",
                                 "Baseline retention is conservative, not a proof that every entry is used",
                                 "Without --baseline, resource retention/change detection is incomplete"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 2 if review else 0
    except (ValueError, OSError, UnicodeError, struct.error, EOFError, ImportError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
