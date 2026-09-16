"""Bounded AO composition/paired-runtime guard; no native process or build.

--candidate checks the actual reviewed leaf -> preapplied pack and provenance.
The paired-runtime consumer is ready for the final native audit, but is NOT
satisfied by the builder's single raw-surface hash or synthetic tests.
"""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

from inspect_web_pack import read_pack
from test_dense_scene_containers_v126 import decode_rscc

ROOT = Path(__file__).resolve().parents[2]
LEAF = ROOT / "artifacts/startup-v128/leaf-lod/candidate-02/index-lite.pck"
CASE = ROOT / "artifacts/startup-v128/ready-ao/candidate-01"
BASE_SHA = "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"
LEAF_SHA = "48840869e6638addbb399b3226accae060a0e41f330b40bab611f367bec4648c"
AO_SHA = "1182ea711300b62fc4cd097acb1321840e75b53d02e884fbcdf02a2e15796460"
AO_SOURCE_SHA = "ec23d5c1a19b434610dcf73ea196dbeec051ba906e62e1111123bf2f64e889c3"
MAIN_SOURCE_SHA = "c8b80de0348f094fa43135cecbd57f971fd75afe022dc19727b95e5ff1edfd2d"
# Full fingerprints must be captured from actual objects, not source buffers.
# Resource IDs/paths of newly embedded resources may differ; resource names,
# storage properties, referenced textures/shader code and all uniforms may not.
FINGERPRINTS = (
    "rawSurfacesSha256", "allDecodedChannelsSha256", "meshPropertiesSha256",
    "fullMaterialStorageAndUniformsSha256", "rockSubtreeStorageAndMetadataSha256",
    "terrainMeshAndMaterialSha256", "colliderSetSha256",
)


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def pack(path, pin):
    blob = path.read_bytes()
    require(sha(blob) == pin, "Actual PCK pin")
    entries = read_pack(path)["entries"]
    require(len(entries) == 184, "Exact 184-entry inventory")
    return blob, {e["path"]: blob[e["offset"]:e["offset"] + e["bytes"]] for e in entries}


def runtime_gate(report, candidate_pin=AO_SHA):
    """Fail closed pending paired snapshots from the single final native run.

baselineAfterApply must come from normal apply on pinned unmarked v127 rock,
with the actual terrain present. candidateLoaded is captured BEFORE calling
apply on the preapplied cache; candidateAfterApply confirms idempotence. Leaf
LOD is checked separately: this gate never demands equality of changed leaves.
"""
    require(report.get("schemaVersion") == 1 and report.get("baselinePackSha256") == BASE_SHA
            and report.get("candidatePackSha256") == candidate_pin, "Paired runtime pack bindings")
    lifecycle = report.get("lifecycle", {})
    for key in ("allLoadedPackEntriesVerified", "baselineInitiallyUnmarked", "baselineNormalApplySucceeded",
                "baselineSupported", "candidateSupported", "candidateAppliedBeforeSceneAttach",
                "candidateApplySucceeded", "candidateMeshInstanceUnchanged", "candidateMaterialInstanceUnchanged"):
        require(lifecycle.get(key) is True, "Runtime lifecycle evidence: " + key)
    require(type(lifecycle.get("framesAdvancedDuringOffTreeComparison")) is int
            and lifecycle["framesAdvancedDuringOffTreeComparison"] == 0, "No draw before paired off-tree check")
    baseline = report.get("baselineAfterApply", {})
    for label in ("baselineAfterApply", "candidateLoaded", "candidateAfterApply"):
        row = report.get(label, {})
        require(set(row) == set(FINGERPRINTS) | {"prefixVertices", "appliedMarker"}, "Complete runtime fingerprint: " + label)
        require(type(row["prefixVertices"]) is int and row["prefixVertices"] == 317556
                and row["appliedMarker"] is True, "Actual enabled prefix and marker")
        for key in FINGERPRINTS:
            require(isinstance(row[key], str) and re.fullmatch(r"[0-9a-f]{64}", row[key]) is not None,
                    "Fingerprint hash: " + key)
        require(row == baseline, "Normal apply vs actual preapplied runtime differs: " + label)
    return {"aoRuntimeEquivalent": True, "gpuAcceptance": False, "startupPerformanceAccepted": False}


def audit_candidate():
    old_blob, old = pack(LEAF, LEAF_SHA)
    blob, candidate = pack(CASE / "index-lite.pck", AO_SHA)
    base_blob, base = pack(ROOT / "artifacts/v127/index-lite.pck", BASE_SHA)
    require(list(base) == list(old) == list(candidate), "PCK names/order exact")
    changed = [p for p in old if old[p] != candidate[p]]
    require(changed == ["assets/baked/v77/detail.scn"], "Only AO detail container differs from leaf candidate")
    for p in base:
        if p not in ("assets/baked/v77/detail.scn", "assets/baked/v77/foothill.scn", "assets/baked/v77/riverbank.scn"):
            require(base[p] == candidate[p], "Non-leaf resource remains v127 exact: " + p)
    proof_path = CASE / "proof.json"
    proof = json.loads(proof_path.read_text())
    native_path = CASE / "native-proof.json"
    native = json.loads(native_path.read_text())
    request = json.loads((CASE / "request.json").read_text())
    require(proof["schemaVersion"] == 1 and proof["sourceSha256"] == LEAF_SHA
            and proof["candidateSha256"] == AO_SHA and proof["native"] == native, "Provenance pins")
    require(Path(request["pack"]).resolve() == LEAF.resolve() and request["sha256"] == LEAF_SHA
            and Path(request["output"]).resolve() == CASE.resolve(), "Native builder request provenance")
    saved = (CASE / "detail.scn").read_bytes()
    require(sha(saved) == native["sceneSha256"], "Native proof is bound to actual saved scene")
    require(decode_rscc(saved)[0] == decode_rscc(candidate[changed[0]])[0], "Actual candidate decoded scene == native saved result")
    require(native["passed"] is True and native["prefixVertices"] == 317556
            and native["rawSurfaceSha256"] == "6fd50fe56e2b96cfffb77a3051d4319d7510413cf94de9ee3f8026193725e31b",
            "Reviewed builder AO result")
    gzip_bytes = len(gzip.compress(blob, compresslevel=6, mtime=0))
    require(proof["afterBytes"] == len(blob) and proof["afterGzip6Bytes"] == gzip_bytes, "Actual raw/offline-gzip sizes")
    source = ROOT / "godot/scripts/meadow_rock_occlusion.gd"
    main = ROOT / "godot/scripts/meadow_scene.gd"
    require(sha(source.read_bytes()) == AO_SOURCE_SHA and sha(main.read_bytes()) == MAIN_SOURCE_SHA,
            "Reviewed synchronous apply/ready source pins")
    require(LEAF.read_bytes() == old_blob and (CASE / "index-lite.pck").read_bytes() == blob
            and (ROOT / "artifacts/v127/index-lite.pck").read_bytes() == base_blob, "Inputs unchanged")
    return {"schemaVersion": 1, "status": "PASS_PACK_PROVENANCE_PENDING_INDEPENDENT_PAIRED_RUNTIME",
            "baseSha256": BASE_SHA, "leafSha256": LEAF_SHA, "candidateSha256": AO_SHA,
            "entries": 184, "byteExactVsLeaf": 183, "changedVsLeaf": changed,
            "byteExactVsV127": 181, "all32TexturesWaterScriptsShadersSettingsExact": True,
            "nativeSavedSceneDecodedBytesBoundToActualPack": True, "builderNativeEvidence": native,
            "candidateBytes": len(blob), "rawBytesAddedVsLeaf": len(blob) - len(old_blob),
            "offlineGzip6Bytes": gzip_bytes, "gzipPackOnly20MbpsFloorSeconds": gzip_bytes / 2500000,
            "proofSha256": sha(proof_path.read_bytes()), "nativeProofSha256": sha(native_path.read_bytes()),
            "sourcePins": {str(source.relative_to(ROOT)): AO_SOURCE_SHA, str(main.relative_to(ROOT)): MAIN_SOURCE_SHA},
            "checkerSha256": sha(Path(__file__).read_bytes()), "independentNativeRuns": 0,
            "limitations": ["Builder evidence was reviewed/rebound, not relabeled as an independent native run.",
                            "Paired final runtime must compare full derived rock/material/subtree/metadata and colliders, not just AO count/marker.",
                            "507ms native offline apply and 0ms rounded idempotent apply are not Web timing savings.",
                            "No GPU, custom mode-5 decoder or <=10s performance acceptance here."]}


def fixture():
    # Deliberately synthetic; never emitted as candidate proof.
    row = {key: sha(key.encode()) for key in FINGERPRINTS}
    row.update(prefixVertices=317556, appliedMarker=True)
    life = {key: True for key in ("allLoadedPackEntriesVerified", "baselineInitiallyUnmarked", "baselineNormalApplySucceeded",
                                  "baselineSupported", "candidateSupported", "candidateAppliedBeforeSceneAttach",
                                  "candidateApplySucceeded", "candidateMeshInstanceUnchanged", "candidateMaterialInstanceUnchanged")}
    life["framesAdvancedDuringOffTreeComparison"] = 0
    return {"schemaVersion": 1, "baselinePackSha256": BASE_SHA, "candidatePackSha256": AO_SHA, "lifecycle": life,
            **{key: copy.deepcopy(row) for key in ("baselineAfterApply", "candidateLoaded", "candidateAfterApply")}}


class PreappliedAOTests(unittest.TestCase):
    def test_complete_pair_is_not_gpu_or_performance_pass(self):
        self.assertEqual(runtime_gate(fixture()), {"aoRuntimeEquivalent": True, "gpuAcceptance": False, "startupPerformanceAccepted": False})

    def test_marker_and_single_surface_hash_are_insufficient(self):
        value = fixture()
        value["candidateLoaded"] = {"appliedMarker": True, "prefixVertices": 317556, "rawSurfacesSha256": "a" * 64}
        with self.assertRaises(AssertionError): runtime_gate(value)

    def test_every_protected_fingerprint_is_enforced(self):
        for phase in ("candidateLoaded", "candidateAfterApply"):
            for field in FINGERPRINTS:
                with self.subTest(phase=phase, field=field):
                    value = fixture()
                    value[phase][field] = "b" * 64
                    with self.assertRaises(AssertionError): runtime_gate(value)

    def test_false_marker_or_wrong_prefix_rejected(self):
        for field, changed in (("appliedMarker", False), ("prefixVertices", 0), ("prefixVertices", 317556.0)):
            value = fixture()
            value["candidateLoaded"][field] = changed
            with self.assertRaises(AssertionError): runtime_gate(value)

    def test_unsupported_or_rebuilt_resource_rejected(self):
        for field in fixture()["lifecycle"]:
            value = fixture()
            value["lifecycle"][field] = 1 if field == "framesAdvancedDuringOffTreeComparison" else False
            with self.assertRaises(AssertionError): runtime_gate(value)

    def test_missing_evidence_rejected(self):
        value = fixture()
        del value["candidateAfterApply"]
        with self.assertRaises(AssertionError): runtime_gate(value)

    def test_unknown_pack_is_not_self_authorized(self):
        value = fixture()
        value["candidatePackSha256"] = "0" * 64
        with self.assertRaises(AssertionError): runtime_gate(value)


if __name__ == "__main__":
    if sys.argv[1:] == ["--candidate"]:
        print(json.dumps(audit_candidate(), indent=2))
    else:
        unittest.main()
