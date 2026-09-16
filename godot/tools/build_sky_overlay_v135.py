"""Main-owned, single-use candidate11 composer. No compiler/native/browser calls.

Read-only preflight: python -B godot/tools/build_sky_overlay_v135.py --check
Main's one execution: python -B godot/tools/build_sky_overlay_v135.py --build

Writes NEW build/candidate-11 and build/boot-11 only. Existing core10, chunks,
bootstrap and sky overlay are pinned; any mismatch aborts before output creation.
The tests never invoke the PCK writer or create these output directories.
"""
from pathlib import Path
import argparse
import copy
import gzip
import hashlib
import json
import re
import sys

sys.dont_write_bytecode = True
from inspect_web_pack import read_pack
from build_web_quality import write_pack
from build_filtered_scene_pack_v128 import decode as decode_mode5
from repack_web_cache import _unpack

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "artifacts/startup-v135/build"
SOURCE = BUILD / "candidate-10"
OUTPUT = BUILD / "candidate-11"
BOOT_SOURCE = BUILD / "boot-10"
BOOT_OUTPUT = BUILD / "boot-11"
SKY = ROOT / "artifacts/startup-v135/sky-bound/candidate-01"
ENTRY = "shaders/meadow_sky.gdshader"
BEFORE_SHA = "374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b"
AFTER_SHA = "6a5df6affed4f91e7684ff4214fc6af9cd090ec150d7e889367294ce11d8d72c"
CORE_PINS = {
    "mode5": "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b",
    "native": "7622eb8f1c0f687a9c640ac0e2e0c818e005ad4ff6605fc353368849768d1988",
}
# The core-embedded manifests use compact JSON and intentionally identify
# different encoded chunks. Neither may change during this sky-only overlay.
EMBEDDED_MANIFEST_PINS = {
    "mode5": "9701ed7d4431c06c496113391cf5539ee8acab053505a97e881a4aa4d46d26b8",
    "native": "fe0a534353ed6110f2a7088ffd0defd46e0215a152f2e516d8e684b5ef70bb36",
}
SKY_MANIFEST_SHA = "e651da55ce6a2ab4a38c8e17a240ba9a438f5ed2a6832041906cf90f0675b2df"
PINS = {
    SOURCE / "mode5/index-lite.pck": CORE_PINS["mode5"],
    SOURCE / "native/index-lite.pck": CORE_PINS["native"],
    SOURCE / "mode5/progressive-manifest.json": "fe6b6f2e189a8d20e8fb89b2c72eda2766b277dbde9447d8d53df1a8a3879987",
    SOURCE / "native/progressive-manifest.json": "d01af3a6844bbf4ac8d2d18c27f415f026c7689cdccd7d50d116a59647674ab4",
    SOURCE / "mode5/proof.json": "00d57497b7f2cc0cb5784053545c1ad266e12e2feb9e332b7662f785e69f193a",
    SOURCE / "native/proof.json": "77cf776cbffec27677430db4f3ef5fad78b09e8483ba81bec71b9cc88d3ac3cb",
    SOURCE / "proof.json": "3dd9bc4e986a79391c14ae1b39ed5702b731730cee48bd9f7881152e3ce3a603",
    SOURCE / "script-proof.json": "3d40342877f707e9347e5f6e40a4220166756215e705bee5a1fc692e9db67eef",
    SOURCE / "water-proof.json": "5461f825b76420cd858eef7d04daa7142d42857a5fd9a9d9d7713466d4e9a775",
    SOURCE / "meadow_scene.progressive.gd": "94bca8a98f11c31688ecc8ce193df0adf4ad007d068143a0963517f5169bab73",
    BOOT_SOURCE / "bootstrap.pck": "fd5727057ca877d5d4efb6635495df5a80926a85195d4766d090a4f08c162885",
    BOOT_SOURCE / "bootstrap-manifest.json": "c9e0ff60d7b34f4ba42cdb137742ec1bfc4ead4191e97023a9d40b4566c5c540",
    SKY / "manifest.json": SKY_MANIFEST_SHA,
    SKY / "proof.json": "5d886d06ea75e2a90d27f86cd812b3dfa6f36eb85887adcb783c15ec33c9dab0",
    SKY / "entries" / ENTRY: AFTER_SHA,
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pinned(path, digest):
    data = path.read_bytes()
    require(sha(data) == digest, f"Frozen input SHA mismatch: {path}")
    return data


def logical(data):
    if data[:4] != b"RSCC":
        return data
    return decode_mode5(data) if int.from_bytes(data[4:8], "little") == 5 else _unpack(data)


def pack_entries(path, data):
    inventory = read_pack(path)
    require(inventory["version"] == 4 and inventory["engine"] == [4, 7, 2], "Pinned stock PCK v4/engine required")
    return inventory, {e["path"]: data[e["offset"]:e["offset"] + e["bytes"]] for e in inventory["entries"]}


def validate_overlay(manifest, replacement):
    require(manifest.get("schema") == "sky-bound-overlay-v1" and manifest.get("sourcePackSha256") == CORE_PINS["mode5"], "Pinned overlay core/schema")
    rows = manifest.get("entries")
    require(isinstance(rows, list) and len(rows) == 1, "Exactly one sky overlay entry")
    row = rows[0]
    require(row.get("entry") == ENTRY and row.get("beforeSha256") == BEFORE_SHA and row.get("sha256") == AFTER_SHA, "Only pinned sky entry/hash pair")
    require(Path(row["path"]).resolve() == (SKY / "entries" / ENTRY).resolve() and Path(row["proof"]).resolve() == (SKY / "proof.json").resolve(), "Pinned overlay paths only")
    require(sha(replacement) == AFTER_SHA and len(replacement) == row.get("bytes") == 7776, "Exact previously validated sky bytes")
    require(manifest.get("proofSha256") == PINS[SKY / "proof.json"], "Pinned sky proof")


def verify_sky_delta(before, after):
    require(sha(before) == BEFORE_SHA and sha(after) == AFTER_SHA, "Actual core must contain original sky")
    newline = b"\r\n" if b"\r\n" in before else b"\n"
    declaration = b"uniform int v118_cloud_loop_count = 48;" + newline
    bounded = b"for (int i = 0; i < min(v118_cloud_loop_count, 48); i++)"
    require(after.count(declaration) == 1 and after.count(bounded) == 1, "One default48 and one bound")
    require(after.replace(declaration, b"", 1).replace(bounded, b"for (int i = 0; i < 48; i++)", 1) == before, "Only the two approved sky edits")


def validate_chunks(manifest):
    rows = manifest.get("chunks")
    require(manifest.get("version") == 1 and isinstance(rows, list) and len(rows) == 12, "Exactly twelve original chunks")
    for index, row in enumerate(rows):
        digest = row.get("sha256", "")
        require(type(row.get("index")) is int and row["index"] == index, "Original ordered chunk indices")
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "Chunk SHA format")
        require(row.get("file") == f"detail-{index}-{digest[:12]}.pck", "Pinned flat chunk name; no traversal")
        require(type(row.get("bytes")) is int and row["bytes"] > 0, "Positive chunk byte count")
    return rows


def verify_entry_delta(before, after, expected):
    require(list(before) == list(after), "Every entry and its order must remain")
    require(ENTRY in before and expected != before[ENTRY], "One actual sky change required")
    changed = [name for name in before if before[name] != after[name]]
    require(changed == [ENTRY] and after[ENTRY] == expected, "Only sky may change; other entries must be byte exact")
    return [{"entry": name, "beforeSha256": sha(before[name]), "sha256": sha(after[name]),
             "byteExact": name != ENTRY} for name in before]


def verify_twins(native, mode5):
    require(list(native) == list(mode5), "Twin resource paths/order")
    for name in native:
        if name == "progressive/manifest.json":
            for kind, entries in (("native", native), ("mode5", mode5)):
                require(sha(entries[name]) == EMBEDDED_MANIFEST_PINS[kind], "Pinned twin transport manifest: " + kind)
            continue
        require(native[name] == mode5[name] or logical(native[name]) == logical(mode5[name]), "Twin logical bytes differ: " + name)


def preflight():
    """Read-only, including all source/chunk hashes. Does not call the writer."""
    data = {path: pinned(path, digest) for path, digest in PINS.items()}
    manifests, inventories, entries, chunks = {}, {}, {}, {}
    replacement = data[SKY / "entries" / ENTRY]
    validate_overlay(json.loads(data[SKY / "manifest.json"]), replacement)
    script = json.loads(data[SOURCE / "script-proof.json"])
    top = json.loads(data[SOURCE / "proof.json"])
    source_proofs = {}
    input_pins = dict(PINS)
    for kind in CORE_PINS:
        core = SOURCE / kind / "index-lite.pck"
        inventories[kind], entries[kind] = pack_entries(core, data[core])
        require(len(entries[kind]) == 222, "Frozen core10 entry count")
        verify_sky_delta(entries[kind][ENTRY], replacement)
        for name, key in (("meadow_scene", "mainGdcSha256"), ("meadow_progressive", "controllerGdcSha256")):
            require(sha(entries[kind][f"scripts/{name}.gdc"]) == script[key], "Inherited script GDC pin")
        path = SOURCE / kind / "progressive-manifest.json"
        manifests[kind] = json.loads(data[path])
        require(json.loads(entries[kind]["progressive/manifest.json"]) == manifests[kind], "Embedded/external chunk manifest consistency")
        chunks[kind] = validate_chunks(manifests[kind])
        source_proofs[kind] = json.loads(data[SOURCE / kind / "proof.json"])
        proof = source_proofs[kind]
        require(proof == top[kind] and proof["coreSha256"] == CORE_PINS[kind] and proof["coreBytes"] == len(data[core]), "Source proof/core consistency")
        require(proof["detailBytes"] == sum(r["bytes"] for r in chunks[kind]) and proof["chunks"] == 12, "Source proof chunk sizes")
        for row in chunks[kind]:
            path = SOURCE / kind / row["file"]
            payload = pinned(path, row["sha256"])
            require(len(payload) == row["bytes"], "Actual chunk length")
            _, chunk_entries = pack_entries(path, payload)
            require(ENTRY not in chunk_entries, "Deferred chunk must not overwrite sky")
            input_pins[path] = row["sha256"]
    verify_twins(entries["native"], entries["mode5"])
    require(sha(data[SOURCE / "meadow_scene.progressive.gd"]) == script["mainSourceSha256"], "Inherited main source pin")
    boot = json.loads(data[BOOT_SOURCE / "bootstrap-manifest.json"])
    boot_bytes = data[BOOT_SOURCE / "bootstrap.pck"]
    _, boot_entries = pack_entries(BOOT_SOURCE / "bootstrap.pck", boot_bytes)
    require(boot["coreSha256"] == CORE_PINS["mode5"] and boot["sha256"] == sha(boot_bytes) and boot["bytes"] == len(boot_bytes), "Bootstrap binding/payload pin")
    require(sha(boot_entries["scripts/meadow_boot.gdc"]) == boot["gdcSha256"], "Inherited bootstrap GDC pin")
    require(boot["reportsSceneReady"] is False and boot["sceneVisualsInBoot"] is False, "Bootstrap must not claim core readiness")
    return {"data": data, "replacement": replacement, "entries": entries, "inventories": inventories,
            "manifests": manifests, "chunks": chunks, "sourceProofs": source_proofs,
            "scriptProof": script, "bootManifest": boot, "inputPins": input_pins}


def overlay_metadata():
    return {"profile": "sky-only-uniform-bound", "entry": ENTRY, "beforeSha256": BEFORE_SHA,
            "sha256": AFTER_SHA, "sourceCoreSha256": dict(CORE_PINS),
            "manifest": (SKY / "manifest.json").as_posix(), "manifestSha256": SKY_MANIFEST_SHA,
            "cloudIterations": 48, "sourceAndGdcPinsReusedUnchanged": True,
            "readinessValidation": "pending", "nativeRuntimeValidation": "not-run", "webDayNightValidation": "pending"}


def variant_proof(source, digest, size, gzip_size, delta):
    result = copy.deepcopy(source)
    result.update(coreSha256=digest, coreBytes=size, coreGzipBytes=gzip_size,
                  coreGzipLevel=6, coreGzipMtime=0, visualAcceptance="pending", tenSecondTarget="unverified",
                  readinessValidation="pending", nativeRuntimeValidation="not-run", skyOverlay=overlay_metadata(),
                  sourceCoreSha256=source["coreSha256"], entryDelta=delta,
                  allOtherEntryBytesExact=True, chunksAndProgressiveManifestByteExact=True)
    return result


def script_proof(source):
    result = copy.deepcopy(source)
    result.update(skyOverlay=overlay_metadata(), sourceProof=(SOURCE / "script-proof.json").as_posix(),
                  sourceProofSha256=PINS[SOURCE / "script-proof.json"],
                  mainAndControllerGdcByteExactToCore10=True, recompiled=False, readinessValidation="pending")
    return result


def boot_manifest(source, mode5_sha):
    result = copy.deepcopy(source)
    result.update(coreSha256=mode5_sha, inheritedFrom=(BOOT_SOURCE / "bootstrap-manifest.json").as_posix(),
                  inheritedManifestSha256=PINS[BOOT_SOURCE / "bootstrap-manifest.json"],
                  bootstrapBytesExactToBoot10=True, sourceAndGdcPinsReusedUnchanged=True,
                  onlyOriginalFieldChanged="coreSha256", recompiled=False, readinessValidation="pending")
    return result


def ensure_fresh(output=OUTPUT, boot_output=BOOT_OUTPUT):
    require(output.absolute() == OUTPUT.absolute() and boot_output.absolute() == BOOT_OUTPUT.absolute(), "Only candidate-11 and boot-11 outputs")
    for path in (output, boot_output):
        require(path.resolve() == path.absolute() and path.parent.resolve() == BUILD.resolve(), "No redirected output paths")
        require(not path.exists() and not path.is_symlink(), "Refusing existing output: " + str(path))


def emit(path, data):
    require(any(path.resolve().is_relative_to(root) for root in (OUTPUT, BOOT_OUTPUT)), "Owned output files only")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def emit_json(path, data):
    emit(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())


def copy_exact(source, target, digest):
    data = pinned(source, digest)
    emit(target, data)
    require(target.read_bytes() == data, "Copy must be byte exact: " + str(target))


def build():
    ensure_fresh()
    inputs = preflight()  # All bad inputs fail before creating any output.
    ensure_fresh()
    OUTPUT.mkdir()
    BOOT_OUTPUT.mkdir()
    proofs, after_entries = {}, {}
    for kind in CORE_PINS:
        core = SOURCE / kind / "index-lite.pck"
        destination = OUTPUT / kind / "index-lite.pck"
        write_pack(core, inputs["inventories"][kind], destination, {ENTRY: inputs["replacement"]})
        candidate = destination.read_bytes()
        inventory, after_entries[kind] = pack_entries(destination, candidate)
        require(inventory["engine"] == inputs["inventories"][kind]["engine"], "Engine version unchanged")
        delta = verify_entry_delta(inputs["entries"][kind], after_entries[kind], inputs["replacement"])
        for row in inputs["chunks"][kind]:
            copy_exact(SOURCE / kind / row["file"], OUTPUT / kind / row["file"], row["sha256"])
        manifest_path = SOURCE / kind / "progressive-manifest.json"
        copy_exact(manifest_path, OUTPUT / kind / "progressive-manifest.json", PINS[manifest_path])
        proofs[kind] = variant_proof(inputs["sourceProofs"][kind], sha(candidate), len(candidate),
                                     len(gzip.compress(candidate, compresslevel=6, mtime=0)), delta)
    verify_twins(after_entries["native"], after_entries["mode5"])
    for name in ("meadow_scene.progressive.gd", "water-proof.json"):
        copy_exact(SOURCE / name, OUTPUT / name, PINS[SOURCE / name])
    emit_json(OUTPUT / "script-proof.json", script_proof(inputs["scriptProof"]))
    copy_exact(BOOT_SOURCE / "bootstrap.pck", BOOT_OUTPUT / "bootstrap.pck", PINS[BOOT_SOURCE / "bootstrap.pck"])
    emit_json(BOOT_OUTPUT / "bootstrap-manifest.json", boot_manifest(inputs["bootManifest"], proofs["mode5"]["coreSha256"]))
    for path, digest in inputs["inputPins"].items():
        pinned(path, digest)
    # Proof publication is last. Partial failures remain unsealed, never reused.
    for kind in CORE_PINS:
        emit_json(OUTPUT / kind / "proof.json", proofs[kind])
    emit_json(OUTPUT / "proof.json", proofs)
    completion = {"status": "PACK_BYTES_VERIFIED_RUNTIME_READINESS_PENDING", "coreHashes": {k: v["coreSha256"] for k, v in proofs.items()},
                  "overlay": overlay_metadata(), "entryCountPerCore": 222, "unchangedEntriesPerCore": 221,
                  "chunksCopiedByteExactPerVariant": 12, "allInputPinsRechecked": True,
                  "twinLogicalParityException": {"entry": "progressive/manifest.json", "reason": "Original encoding-specific chunk transport references", "unchangedEmbeddedSha256": dict(EMBEDDED_MANIFEST_PINS)},
                  "bootstrap": {"directory": BOOT_OUTPUT.as_posix(), "sha256": PINS[BOOT_SOURCE / "bootstrap.pck"]},
                  "compilerOrNativeOrBrowserInvoked": False,
                  "provenance": [{"path": p.as_posix(), "sha256": h} for p, h in inputs["inputPins"].items()]}
    emit_json(OUTPUT / "sky-overlay-proof.json", completion)
    return completion


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Read-only frozen-input verification; no outputs")
    mode.add_argument("--build", action="store_true", help="Main's sole execution; creates candidate11 and boot11")
    args = parser.parse_args(argv)
    if args.check:
        inputs = preflight()
        print(json.dumps({"status": "READ_ONLY_PREFLIGHT_PASS", "entryCountPerCore": len(inputs["entries"]["mode5"]),
                          "chunksPerVariant": 12, "outputsCreated": False}))
    else:
        result = build()
        print(json.dumps({"status": result["status"], "coreHashes": result["coreHashes"],
                          "candidate": OUTPUT.as_posix(), "bootstrap": BOOT_OUTPUT.as_posix()}, indent=2))


if __name__ == "__main__":
    main()
