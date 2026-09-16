"""Prepare lossless Web representations; optional Brotli and immutable asset URLs.

Existing filenames/manifest fields and control-query versioning remain compatible.
Updates the three meadow JS helpers only for shells referencing loader/quality;
legacy shells keep their existing controls. Versions existing HTML references.
Injects size/pack choices before the quality mount; does not change engine config
or preload policy. Missing packs are never advertised.
immutableUrl is opt-in loader input; all quality packs share one manifest/WASM.
The quality catalog includes lite only when index-lite.pck is present. Shared
download sizes cover WASM, engine JS and the shell's referenced scripts/styles;
encoding metadata describes prepared files, not a live server's capabilities.
"""
import argparse
from contextlib import contextmanager
import gzip
import hashlib
from html.parser import HTMLParser
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import warnings


PAYLOADS = ("index.wasm", "index.pck", "index.js", "meadow-controls.js", "meadow-controls.css")
# Keep historical exports valid; never manufacture a missing quality pack.
OPTIONAL_PAYLOADS = ("meadow-loader.js", "meadow-quality.js", "meadow-startup-trace.js", "meadow-webgl-compile.js", "meadow-progressive.js", "meadow-stream.js", "meadow-boot.js", "meadow-progressive.css", "index-balanced.pck", "index-lite.pck", "bootstrap.pck")
HELPER_SOURCES = {name: Path(__file__).resolve().parent.parent / "web" / name
                  for name in ("meadow-controls.js", "meadow-loader.js", "meadow-quality.js", "meadow-startup-trace.js", "meadow-webgl-compile.js", "meadow-progressive.js", "meadow-stream.js", "meadow-boot.js", "meadow-progressive.css")}
QUALITY_BEGIN = "/* MEADOW_QUALITY_MANIFEST_BEGIN */"
QUALITY_END = "/* MEADOW_QUALITY_MANIFEST_END */"
CHUNK = 1024 * 1024
# Reviewed transport bytes, not a JSON-supplied permission to trust arbitrary br.
# Paths are relocatable; every use checks all three pins AND actual decoded bytes.
_STRONG_BR_ROOT = Path(__file__).resolve().parents[2] / "artifacts/startup-v135/transfer-br/candidate-01"
PINNED_WASM_BROTLI = {
    "1bf0d192b97645d76e31fbb7582e3c112981a1e420d5d976ae71757866ee92e1": {
        "rawBytes": 26609403,
        "bytes": 4448037,
        "sha256": "d04c9aede11842cce88dca647a15812d2514037858e8a02727fc0d068e0d089e",
        "proofSha256": "d081a04af27ea401a906f3f13854ee75ca4b89a1ffd3eaaf5d5e2d33bf0158c8",
        "sidecar": _STRONG_BR_ROOT / "wasm.br",
        "proof": _STRONG_BR_ROOT / "proof.json",
    },
}
# The independent combined-01 native/source audit proves this exact pack has
# four directional/nine omni and zero spot/area lights, also through day/night.
# A different future pack receives NO contract: new game lights must be audited.
SCENE_RENDER_CONTRACTS = {
    "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79":
        {"spotLights": 0, "areaLights": 0},
    "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c":
        {"spotLights": 0, "areaLights": 0},
    # v126 independent runtime + byte/decoded-scene proof: dense-q60-01.
    "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf":
        {"spotLights": 0, "areaLights": 0},
    # v128 independent seven-phase native audit, real preapplied AO + leaf LOD.
    "1182ea711300b62fc4cd097acb1321840e75b53d02e884fbcdf02a2e15796460":
        {"spotLights": 0, "areaLights": 0},
    # Same decoded scene/script/texture bytes; matching-engine mode-5 wrapper.
    "dfae7b33bbf28a12a456610abb7dd80da36bd5158b5b5cfc8f1527c5150cadfc":
        {"spotLights": 0, "areaLights": 0},
    # Combined-01: all185 payloads + native seven-phase light/route/cache audit.
    "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3":
        {"spotLights": 0, "areaLights": 0},
    # Candidate-05: actual core/eight chunks/day/night/transition keep 4 dir,
    # 9 omni and zero spot/area. Proxy visuals do not add light sources.
    "699c08aac4201b9c507d964b6a857247af6f718ebab203da085e5937de0052db":
        {"spotLights": 0, "areaLights": 0},
    # Candidate-06: twelve actual phases, 30 in-place textures, exact support.
    "2850c2eebd3382b57866b77aba6dbfe5e4209190c478c502c637bce660fefff4":
        {"spotLights": 0, "areaLights": 0},
    # Candidate-07: actual native core/twelve chunks, day/night and transitions;
    # CPU predicate planes preserve derived geometry and all thirteen lights.
    "78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5":
        {"spotLights": 0, "areaLights": 0},
    # Candidate-10 actual 12-chunk native/twin audit; 17+50 exact caches,
    # unchanged thirteen day/night lights and complete final restoration.
    "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b":
        {"spotLights": 0, "areaLights": 0},
    # Actual15 native: 18 observed phases, all twelve chunks, 4 directional +
    # 9 omni throughout. This proves ONLY absence of Spot/Area. The separate
    # strict floating-point scene comparison remains FAIL, not relabelled PASS.
    "4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c":
        {"spotLights": 0, "areaLights": 0},
}


class HelperReferences(HTMLParser):
    """Only real script tags opt in; comments/inline JS strings do not."""
    def __init__(self, html):
        super().__init__()
        self.names = set()
        self.assets = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        source = attributes.get("src") if tag == "script" else (
            attributes.get("href") if tag == "link" and "stylesheet" in (attributes.get("rel") or "").lower().split() else None)
        asset = re.fullmatch(r"(?:\./)?([\w.-]+\.(?:js|css))(?:[?#].*)?", source or "")
        if asset:
            self.assets.add(asset[1])
        if tag == "script":
            match = re.fullmatch(r"(?:\./)?(meadow-(?:controls|loader|quality|startup-trace|webgl-compile|progressive|stream|boot)\.js)(?:[?#].*)?", source or "")
            if match:
                self.names.add(match[1])
        if tag == "link" and asset and asset[1] == "meadow-progressive.css":
            self.names.add(asset[1])


def brotli_module():
    for name in ("brotli", "brotlicffi"):
        try:
            return importlib.import_module(name)
        except (ImportError, OSError):
            continue
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_verified_wasm_brotli(source: Path, provided: Path | None = None, *, codec=None):
    """Read-only preflight. Unknown raw defaults to q6; explicit bad input fails.

    Return verified bytes, not an unchecked path that can change before copying.
    Missing/corrupt approved artifacts fail closed for the pinned raw; never
    silently downgrade an engine whose strong sidecar has already been selected.
    """
    source = Path(source)
    digest = sha256(source)
    contract = PINNED_WASM_BROTLI.get(digest)
    if contract is None:
        if provided is not None:
            raise ValueError("Provided Brotli sidecar has no approved raw WASM contract")
        return None
    proof_data = Path(contract["proof"]).read_bytes()
    if hashlib.sha256(proof_data).hexdigest() != contract["proofSha256"]:
        raise ValueError("Pinned Brotli proof SHA256 mismatch")
    proof = json.loads(proof_data)
    if (proof.get("status") != "PASS" or proof.get("source", {}).get("sha256") != digest
            or proof.get("candidate", {}).get("sha256") != contract["sha256"]
            or proof.get("candidate", {}).get("bytes") != contract["bytes"]
            or proof.get("parameters", {}).get("quality") != 11
            or proof.get("parameters", {}).get("lgwin") != 24):
        raise ValueError("Pinned Brotli proof contract mismatch")
    existing = source.with_name(source.name + ".br")
    if provided is not None:
        selected, selection = Path(provided), "provided-sidecar"
    elif (existing.is_file() and existing.stat().st_size == contract["bytes"]
          and sha256(existing) == contract["sha256"]):
        selected, selection = existing, "existing-sidecar"
    else:
        selected, selection = Path(contract["sidecar"]), "pinned-artifact"
    encoded = selected.read_bytes()
    if len(encoded) != contract["bytes"] or hashlib.sha256(encoded).hexdigest() != contract["sha256"]:
        raise ValueError("Pinned Brotli sidecar bytes/SHA256 mismatch")
    raw = source.read_bytes()
    if len(raw) != contract["rawBytes"] or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Raw WASM changed during Brotli preflight")
    codec = codec if codec is not None else brotli_module()
    if codec is None:
        raise ValueError("Brotli decoder required to verify pinned sidecar")
    try:
        decoded = codec.decompress(encoded)
    except Exception as error:
        raise ValueError("Pinned Brotli sidecar cannot be decoded") from error
    if decoded != raw or hashlib.sha256(decoded).hexdigest() != digest:
        raise ValueError("Pinned Brotli decoded bytes do not equal raw WASM")
    return {"data": encoded, "rawSha256": digest, "rawBytes": len(raw),
            "metadata": {"bytes": len(encoded), "sha256": contract["sha256"],
                         "policy": "pinned-verified-brotli", "selection": selection,
                         "quality": 11, "lgwin": 24, "rawSha256": digest,
                         "proofSha256": contract["proofSha256"], "decodedByteExact": True}}


@contextmanager
def atomic_output(path: Path):
    """Do not expose a partially compressed file/manifest to a running reader."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".web-", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        yield temporary
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def immutable_copy(source: Path, target: Path, digest: str) -> None:
    # Never hard-link to mutable aliases: an export could truncate both names.
    if target.exists():
        if sha256(target) != digest:
            raise ValueError(f"Refusing to overwrite immutable asset: {target.name}")
        return
    with atomic_output(target) as temporary:
        shutil.copyfile(source, temporary)
        if sha256(temporary) != digest:
            raise ValueError(f"Asset changed while copying: {source.name}")


def fingerprint(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def quality_html(html: str, sizes: dict) -> str:
    """Only advertise files actually prepared. Bare pack paths are also FS paths."""
    mount = "window.meadowQuality.mount("
    if mount not in html:
        return html  # Historical shell: no UI or preload changes.
    if html.count(mount) != 1:
        raise ValueError("Expected exactly one quality mount")
    def size_fields(record):
        fields = {"bytes": record["bytes"], "gzipBytes": record["gzipBytes"]}
        if "brotliBytes" in record:
            fields["brBytes"] = record["brotliBytes"]
        return fields

    choices = {}
    for quality, name in (("original", "index.pck"), ("balanced", "index-balanced.pck"), ("lite", "index-lite.pck")):
        if name not in sizes:
            continue
        choices[quality] = {"pack": name, **size_fields(sizes[name])}
    details = [record for name, record in sizes.items() if re.fullmatch(r"detail-\d+-[a-f0-9]{12}\.pck", name)]
    if details and "lite" in choices:
        choices["lite"]["details"] = {key: sum(record[key] for record in details) for key in ("bytes", "gzipBytes")}
        if all("brotliBytes" in record for record in details):
            choices["lite"]["details"]["brBytes"] = sum(record["brotliBytes"] for record in details)
    if 'bootstrap.pck' in sizes and 'lite' in choices:
        choices['lite']['bootstrap'] = {'file':'bootstrap.pck', **size_fields(sizes['bootstrap.pck']),
                                         'sha256':sizes['bootstrap.pck']['sha256'],
                                         'coreSha256':sizes['index-lite.pck']['sha256']}
    shared_names = {"index.wasm", "index.js"} | HelperReferences(html).assets
    shared = {name: size_fields(sizes[name]) for name in sorted(shared_names) if name in sizes}
    render_contracts = {name: {"packSha256": record["sha256"], **SCENE_RENDER_CONTRACTS[record["sha256"]]}
                        for name, record in sizes.items()
                        if name.endswith(".pck") and record.get("sha256") in SCENE_RENDER_CONTRACTS}
    block = (QUALITY_BEGIN + "\nwindow.MEADOW_QUALITY_SHARED = " + json.dumps(shared) + ";\n"
             + "window.MEADOW_RENDER_CONTRACTS = " + json.dumps(render_contracts) + ";\n"
             + "window.MEADOW_QUALITY = " + json.dumps(choices) + ";\n" + QUALITY_END)
    if QUALITY_BEGIN in html or QUALITY_END in html:
        if html.count(QUALITY_BEGIN) != 1 or html.count(QUALITY_END) != 1:
            raise ValueError("Ambiguous quality manifest markers")
        pattern = re.escape(QUALITY_BEGIN) + r".*?" + re.escape(QUALITY_END)
        html, count = re.subn(pattern, lambda _match: block, html, flags=re.DOTALL)
        if count != 1 or html.index(QUALITY_END) > html.index(mount):
            raise ValueError("Quality manifest must precede mount")
        return html
    return html.replace(mount, block + "\n" + mount, 1)


def prepare(directory: Path, *, brotli: bool = False, immutable: bool = False,
            verified_wasm_br: Path | None = None) -> dict:
    directory = directory.resolve(strict=True)
    if not re.fullmatch(r"v\d+", directory.name):
        raise ValueError("Expected a versioned Web artifact directory")
    if verified_wasm_br is not None and not brotli:
        raise ValueError("Provided verified WASM sidecar requires brotli=True")
    compressor_module = brotli_module() if brotli else None
    # Before copying helpers, creating gzip files, or changing any metadata.
    wasm_br = (select_verified_wasm_brotli(directory / "index.wasm", verified_wasm_br,
                                         codec=compressor_module) if brotli else None)
    html_path = directory / "index.html"
    html = html_path.read_text(encoding="utf-8")
    referenced = HelperReferences(html).names
    modern_shell = bool(referenced & {"meadow-loader.js", "meadow-quality.js"})
    if modern_shell:
        for name, helper_source in HELPER_SOURCES.items():
            if helper_source.is_file():
                data = helper_source.read_bytes()
                target = directory / name
                if not target.is_file() or target.read_bytes() != data:
                    with atomic_output(target) as temporary:
                        temporary.write_bytes(data)
    payloads = list(PAYLOADS)
    progressive_path = directory / "progressive-manifest.json"
    if progressive_path.is_file():
        progressive = json.loads(progressive_path.read_bytes())
        if progressive.get("version") != 1 or not 1 <= len(progressive.get("chunks", [])) <= 32:
            raise ValueError("Invalid progressive export manifest")
        for index, chunk in enumerate(progressive["chunks"]):
            name = chunk.get("file", "")
            if chunk.get("index") != index or not re.fullmatch(r"detail-\d+-[a-f0-9]{12}\.pck", name) or name in payloads:
                raise ValueError("Unsafe or duplicate progressive file")
            source = directory / name
            if source.stat().st_size != chunk["bytes"] or sha256(source) != chunk["sha256"]:
                raise ValueError("Progressive file changed before preparation")
            payloads.append(name)
    for name in OPTIONAL_PAYLOADS:
        if (directory / name).is_file():
            payloads.append(name)
        elif name in referenced:
            raise ValueError(f"HTML references missing export helper: {name}")
    references = ["meadow-controls.js", "meadow-controls.css"]
    references.extend(name for name in ("meadow-loader.js", "meadow-quality.js", "meadow-startup-trace.js", "meadow-webgl-compile.js", "meadow-progressive.js", "meadow-progressive.css", "meadow-stream.js") if name in payloads)
    for name in references:
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if name in ("meadow-controls.js", "meadow-controls.css"):
            digest = digest[:16]  # Preserve existing control-query URLs.
        html = re.sub(r'(["\'])(?:\./)?' + re.escape(name) + r'(?:\?[^"\']*)?(["\'])',
                      lambda match: f'{match[1]}{name}?v={digest}{match[2]}', html)
    if brotli and compressor_module is None:
        warnings.warn("Brotli unavailable; publishing gzip only", RuntimeWarning)
    sizes = {}
    inputs = {}
    for name in payloads:
        source = directory / name
        before = fingerprint(source)
        inputs[source] = before
        digest = sha256(source)
        if name == "index.wasm" and wasm_br is not None and digest != wasm_br["rawSha256"]:
            raise ValueError("Raw WASM changed after Brotli preflight")
        target = source.with_name(source.name + ".gz")
        with atomic_output(target) as temporary:
            with source.open("rb") as reader, temporary.open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as writer:
                    shutil.copyfileobj(reader, writer, length=CHUNK)
        encodings = {"gzip": {"bytes": target.stat().st_size, "sha256": sha256(target)}}
        if name == "index.wasm" and wasm_br is not None:
            br_path = source.with_name(source.name + ".br")
            # Keep the already-verified file itself on repeat prepare, including
            # its mtime. Otherwise publish only the preflight-verified bytes.
            if not br_path.is_file() or sha256(br_path) != wasm_br["metadata"]["sha256"]:
                with atomic_output(br_path) as temporary:
                    temporary.write_bytes(wasm_br["data"])
            encodings["br"] = dict(wasm_br["metadata"])
        elif compressor_module is not None:
            br_path = source.with_name(source.name + ".br")
            try:
                with atomic_output(br_path) as temporary:
                    compressor = compressor_module.Compressor(quality=6)
                    with source.open("rb") as reader, temporary.open("wb") as writer:
                        for chunk in iter(lambda: reader.read(CHUNK), b""):
                            writer.write(compressor.process(chunk))
                        writer.write(compressor.finish())
                encodings["br"] = {"bytes": br_path.stat().st_size, "sha256": sha256(br_path),
                                   "quality": 6, "policy": ("quality6-unpinned-wasm" if name == "index.wasm"
                                                             else "quality6-default")}
            except Exception as error:
                # Optional codec failure must not break otherwise valid gzip publication.
                warnings.warn(f"Brotli failed for {name}; using gzip: {error}", RuntimeWarning)
        if fingerprint(source) != before:
            raise ValueError(f"Source changed during preparation: {name}")
        record = {"bytes": source.stat().st_size, "gzipBytes": target.stat().st_size,
                  "sha256": digest, "encodings": encodings}
        if "br" in encodings:
            record["brotliBytes"] = encodings["br"]["bytes"]
        if immutable:
            versioned = source.with_name(f"{source.stem}.{digest}{source.suffix}")
            immutable_copy(source, versioned, digest)
            for coding, metadata in encodings.items():
                suffix = ".gz" if coding == "gzip" else ".br"
                immutable_copy(source.with_name(name + suffix),
                               versioned.with_name(versioned.name + suffix), metadata["sha256"])
            record["immutableUrl"] = versioned.name
        sizes[name] = record
    if any(fingerprint(path) != stamp for path, stamp in inputs.items()):
        raise ValueError("Sources changed before manifest publication")
    html = quality_html(html, sizes)
    # Publish payload metadata first, HTML last. This is not a multi-file atomic
    # deployment: use a completed version directory when switching live previews.
    with atomic_output(directory / "web-payload.json") as temporary:
        temporary.write_text(json.dumps(sizes, indent=2), encoding="utf-8")
    if html != html_path.read_text(encoding="utf-8"):
        with atomic_output(html_path) as temporary:
            temporary.write_text(html, encoding="utf-8", newline="\n")
    return sizes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--brotli", action="store_true", help="Optional .br siblings; missing codec safely falls back to gzip")
    parser.add_argument("--immutable", action="store_true", help="Retained SHA256-named assets; immutableUrl fields for loader integration")
    parser.add_argument("--verified-wasm-br", type=Path,
                        help="Optional sidecar location; must match the built-in reviewed raw/br/proof pins")
    args = parser.parse_args()
    result = prepare(args.directory, brotli=args.brotli, immutable=args.immutable,
                     verified_wasm_br=args.verified_wasm_br)
    print(json.dumps(result, indent=2))
