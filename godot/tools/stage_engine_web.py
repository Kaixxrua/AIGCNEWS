"""Stage a new, isolated Web engine A/B with every PCK byte unchanged.

Only four members of a locally built Godot template are consumed; HTML, service
workers and archive paths are never extracted. The explicit archive digest binds
this staging operation to the reviewed build, not to an arbitrary latest binary.
This is a build/provenance tool, not proof of engine correctness or performance.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import zipfile

from prepare_web_build import HELPER_SOURCES, HelperReferences, prepare
from mode5_engine_contract import validate_pack_engine
from inspect_web_pack import read_pack


ENGINE_MEMBERS = {
    "godot.js": "index.js",
    "godot.wasm": "index.wasm",
    "godot.audio.worklet.js": "index.audio.worklet.js",
    "godot.audio.position.worklet.js": "index.audio.position.worklet.js",
}
FROZEN = ("index.pck", "index-balanced.pck", "index-lite.pck", "index.png")
COMMIT = "ed1daf0bf001b61586d9930840f2f1394092c079"
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 4 * MAX_MEMBER_BYTES + 16 * 1024 * 1024


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def read_template(path, expected_sha):
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("An exact lower-case SHA256 of the reviewed template is required")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Engine template archive exceeds the bounded input size")
    # Hash and consume the same snapshot; never reopen a potentially replaced ZIP.
    archive_bytes = path.read_bytes()
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ValueError("Engine template archive exceeds the bounded input size")
    if digest(archive_bytes) != expected_sha:
        raise ValueError("Engine template digest does not match the reviewed build")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate template members")
        if any("side.wasm" in name or "worker.js" in name and "service.worker.js" not in name
               for name in names):
            raise ValueError("Only the reviewed nothreads/non-dlink template is supported")
        result = {}
        for source, target in ENGINE_MEMBERS.items():
            try:
                member = archive.getinfo(source)
            except KeyError as error:
                raise ValueError(f"Missing root engine member: {source}") from error
            if not 0 < member.file_size <= MAX_MEMBER_BYTES or member.flag_bits & 1:
                raise ValueError("Invalid engine member size or encryption")
            blob = archive.read(member)
            if len(blob) != member.file_size:
                raise ValueError("Engine member length disagrees with ZIP metadata")
            if target.endswith(".wasm"):
                if blob[:8] != b"\0asm\x01\0\0\0":
                    raise ValueError("Expected WebAssembly v1 module")
            else:
                blob.decode("utf-8")
            result[target] = blob
        return result


def progressive_files(source, engine):
    """Retain the entire pinned stream when changing only its engine."""
    core = source / 'index-lite.pck'
    external = source / 'progressive-manifest.json'
    entry = next((row for row in read_pack(core, verify=True)['entries']
                  if row['path'] == 'progressive/manifest.json'), None)
    if bool(entry) != external.is_file():
        raise ValueError('Engine A/B requires matching embedded/adjacent detail manifests')
    result = {}
    if entry:
        with core.open('rb') as stream:
            stream.seek(entry['offset'])
            manifest = json.loads(stream.read(entry['bytes']))
        if manifest != json.loads(external.read_bytes()) or manifest.get('version') != 1:
            raise ValueError('Progressive manifest mismatch')
        chunks = manifest.get('chunks', [])
        if not 1 <= len(chunks) <= 32:
            raise ValueError('Invalid detail count')
        result[external.name] = digest(external.read_bytes())
        for index, chunk in enumerate(chunks):
            sha = chunk.get('sha256', '')
            name = chunk.get('file', '')
            if (chunk.get('index') != index or not re.fullmatch(r'[a-f0-9]{64}', sha)
                    or name != f'detail-{index}-{sha[:12]}.pck'):
                raise ValueError('Invalid detail identity')
            path = source / name
            data = path.read_bytes()
            if len(data) != chunk.get('bytes') or digest(data) != sha:
                raise ValueError('Detail bytes do not match the actual core')
            validate_pack_engine(path, engine)
            result[name] = sha
    boot_path, boot_manifest = source/'bootstrap.pck', source/'bootstrap-manifest.json'
    if boot_path.is_file() != boot_manifest.is_file():
        raise ValueError('Bootstrap and its manifest must be supplied together')
    if boot_path.is_file():
        spec = json.loads(boot_manifest.read_bytes())
        data = boot_path.read_bytes()
        if (not entry or spec.get('file') != boot_path.name or spec.get('bytes') != len(data)
                or spec.get('sha256') != digest(data) or spec.get('coreSha256') != digest(core.read_bytes())):
            raise ValueError('Bootstrap does not match the selected core')
        validate_pack_engine(boot_path, engine)
        result.update({boot_path.name:digest(data), boot_manifest.name:digest(boot_manifest.read_bytes())})
    return result


def stage(source, template, expected_sha, destination, variant="lazy-web-v126"):
    source = source.resolve(strict=True)
    template = template.resolve(strict=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Use a NEW vNNN artifact directory")
    destination = destination.resolve()
    if destination.exists() or not re.fullmatch(r"v\d+", destination.name):
        raise ValueError("Use a NEW vNNN artifact directory")
    if destination.is_relative_to(source):
        raise ValueError("Destination must not be inside the old source version")
    engine = read_template(template, expected_sha)
    validate_pack_engine(source / "index-lite.pck", engine)
    progressive = progressive_files(source, engine)
    html_bytes = (source / "index.html").read_bytes()
    original_html = html_bytes.decode("utf-8")
    matches = list(re.finditer(r"window\.meadowQuality\.mount\((\{[^\n]+\})\);", original_html))
    if len(matches) != 1 or original_html.count("window.meadowQuality.mount(") != 1:
        raise ValueError("Expected one source engine configuration")
    config = json.loads(matches[0][1])
    if config.get("executable") != "index":
        raise ValueError("Expected the reviewed index executable")
    if config.get("mainPack") not in (None, "", *FROZEN[:3]) or config.get("gdextensionLibs", []):
        raise ValueError("Expected an index pack and no dynamic-link extensions")
    if not isinstance(config.setdefault("fileSizes", {}), dict):
        raise ValueError("Expected an object for engine fileSizes")
    # Validate every input before creating the new output directory.
    frozen = {name: digest((source / name).read_bytes()) for name in FROZEN}
    previous_engine = {name: digest((source / name).read_bytes()) for name in engine}
    host_names = (HelperReferences(original_html).assets - set(engine)) | set(HELPER_SOURCES)
    host = {name: digest((source / name).read_bytes()) for name in sorted(host_names)}
    # prepare() refreshes helpers from the worktree. Reject drift rather than
    # silently adding a second variable to the engine-only A/B.
    for name, path in HELPER_SOURCES.items():
        if digest(path.read_bytes()) != host[name]:
            raise ValueError(f"Worktree helper differs from engine-only source host: {name}")
    provenance_names = [name for name in ("lite-build.json", "proof.json", "shader-replacements.v1.json", "composition-proof.json", "final-proof.json")
                        if (source / name).is_file()]
    copied = {**frozen, **host, **progressive,
              **{name: digest((source / name).read_bytes()) for name in provenance_names}}
    source_hashes = {**copied, **previous_engine, "index.html": digest(html_bytes)}
    for name, blob in engine.items():
        config["fileSizes"][name] = len(blob)
    for name in FROZEN[:3]:
        config["fileSizes"][name] = (source / name).stat().st_size
    start, end = matches[0].span(1)
    shell = original_html[:start] + json.dumps(config, ensure_ascii=False) + original_html[end:]
    metadata = {"schemaVersion": 1, "kind": "web-engine-only-ab", "sourceVersion": str(source),
                "template": str(template), "templateSha256": expected_sha,
                "sourceCommit": COMMIT, "sourceFrozenFiles": frozen,
                "sourceHostFiles": host, "sourceHtmlSha256": digest(html_bytes),
                "previousEngine": previous_engine,
                "engine": {name: {"bytes": len(blob), "sha256": digest(blob)} for name, blob in engine.items()},
                "note": "Stage provenance only; reviewed build, Web correctness and visual acceptance are separate."}
    if not re.fullmatch(r"[a-z0-9-]{1,80}", variant):
        raise ValueError("Invalid engine variant label")
    metadata["variant"] = variant
    stamp = {"sourceCommit": COMMIT, "templateSha256": expected_sha, "variant": variant}
    # Replace the old stamp, not a growing chain of contradictory assignments.
    shell = re.sub(r"window\.MEADOW_ENGINE_BUILD = \{[^\n]+\};\s*", "", shell)
    shell = shell.replace("window.meadowQuality.mount(",
                          "window.MEADOW_ENGINE_BUILD = " + json.dumps(stamp) + ";\n    window.meadowQuality.mount(", 1)
    destination.mkdir(parents=True)
    for name in copied:
        shutil.copy2(source / name, destination / name)
    for name, blob in engine.items():
        (destination / name).write_bytes(blob)
    (destination / "index.html").write_text(shell, encoding="utf-8")
    sizes = prepare(destination, brotli=True)
    for name, before in source_hashes.items():
        if digest((source / name).read_bytes()) != before:
            raise ValueError(f"Frozen source mismatch: {name}")
    for name, before in copied.items():
        if digest((destination / name).read_bytes()) != before:
            raise ValueError(f"Frozen copy/host mismatch: {name}")
    for name, blob in engine.items():
        if digest((destination / name).read_bytes()) != digest(blob):
            raise ValueError(f"Staged engine mismatch: {name}")
    for name in ("index.js", "index.wasm", *FROZEN[:3],
                 *(name for name in progressive if name.endswith('.pck'))):
        path = destination / name
        record = sizes.get(name, {})
        if record.get("bytes") != path.stat().st_size or record.get("sha256") != digest(path.read_bytes()):
            raise ValueError(f"Prepared size/hash mismatch: {name}")
    (destination / "engine-build.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (destination / "frozen-original.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    total = sum(item["gzipBytes"] for name, item in sizes.items() if not name.endswith(".pck"))
    total += sizes["index-lite.pck"]["gzipBytes"]
    result = {"destination": str(destination), "liteGzipTotalBytes": total,
              "engineWasmBytes": sizes["index.wasm"]["bytes"], "engineSha256": sizes["index.wasm"]["sha256"]}
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--variant", default="lazy-web-v126")
    args = parser.parse_args()
    stage(args.source, args.template, args.engine_sha256, args.destination, args.variant)
