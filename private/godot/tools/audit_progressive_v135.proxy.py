"""Pinned proxy-02 extension; the candidate-04 auditor stays byte-exact."""
from pathlib import Path
import argparse
import json
import sys
import unittest

sys.dont_write_bytecode = True
import audit_progressive_v135 as base

ROOT = base.ROOT
PROXY = ROOT / "artifacts/startup-v135/scenes/proxy-02"
MANIFEST_SHA = "7fde5df9fa7230ce112ce412d9763198ad2b6bc881da73cd58624193633a4210"
DUMP_SHA = "299c7df0b3b67f6e18a31ed20268c222f61b04118f9e7d316cac3c17cac7b16a"
MESH_ROOTS = ["ContinuousMeadow", "SolidLimestoneGeology"]
AO_RESTORE = {"SolidLimestoneGeology": {"rock_ao_vertex_count": 317556}}
ROOTS = {"MiddleMeadowBrush", "CastleFoothillWoodland", "RootedRiparianCover",
         "MeadowEdgeGrowth/CrownToTurfFringe", "MeadowEdgeGrowth/CrownTransitionBranchlets",
         "DistantMeadowSward", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"}
OLD_GUARD = '\tif not ROCK_OCCLUSION.apply(self):\n'
NEW_GUARD = ('\t# The temporary mesh retains its selected baked AO; the full cache is only valid for the full mesh.\n'
             '\tif not get_node("SolidLimestoneGeology").get_meta("progressive_visual_proxy", false) and not ROCK_OCCLUSION.apply(self):\n')


def validate_mesh_part(part):
    base.require(part.get("meshOnly") is True and part.get("rootScene", False) is False,
                 "Explicit mesh-only wrapped carrier required")
    base.require(part.get("parent", ".") == "." and part.get("roots") == MESH_ROOTS,
                 "Only the two pinned visual roots can be mesh-only")
    base.require(part.get("resource") == "res://progressive/details/world-visuals.scn", "Exact carrier resource")
    base.require(part.get("restoreShaderParameters") == AO_RESTORE, "Only exact AO prefix restore 317556")
    base.require(part.get("removeMetadata") == ["progressive_visual_proxy"], "Only proxy marker removed")


def validate_proxy_plan(plan):
    roots = base.validate_plan(plan)
    base.require(set(roots) == ROOTS, "All nine ordinary roots remain required")
    parts = [(g, p) for g in plan["detailPacks"] for p in g.get("scenes", []) if p.get("meshOnly", False)]
    base.require(len(parts) == 1, "One two-mesh restore group required")
    group, part = parts[0]
    validate_mesh_part(part)
    base.require(group["meshOnlyRoots"] == MESH_ROOTS and not group["roots"], "Separate mesh/root accounting")
    base.require(group["index"] < len(plan["detailPacks"]) - 1, "Water remains after all geometry")
    return roots


def build_contract():
    manifest_path = PROXY / "manifest.json"
    base.verify_pin({"file": manifest_path, "sha256": MANIFEST_SHA})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base.require(manifest["sourceNativePackSha256"] == base.NATIVE_SHA, "Pinned original source")
    base.verify_pin({"file": manifest["nativeProof"], "sha256": manifest["nativeProofSha256"]})
    dump_path = PROXY / "dump/native-proof.json"
    base.verify_pin({"file": dump_path, "sha256": DUMP_SHA})
    dump = json.loads(dump_path.read_text(encoding="utf-8"))
    references = []
    for label, target in (("terrain-core", MESH_ROOTS[0]), ("detail-core", MESH_ROOTS[1])):
        resource = manifest["resources"][label]
        info = resource["encodings"]["native"]
        base.verify_pin({"file": info["path"], "sha256": info["sha256"]})
        raw = next(row for row in dump["groups"] if row["mesh"] == target)
        refs = {key: {"file": value["path"], "sha256": value["sha256"]}
                for key, value in raw["buffers"].items()}
        references.append({"target": target, "entry": resource["entry"], **base.pin(info["path"]),
                           "originalBuffers": refs})
    return {"manifest": base.pin(manifest_path), "dumpProof": base.pin(dump_path),
            "references": references, "carrier": manifest["resources"]["world-visuals"],
            "proxyAoPrefix": 70386, "fullAoPrefix": 317556,
            "marker": "progressive_visual_proxy", "meshRoots": MESH_ROOTS}


def source_contract(core_path, pack, baseline):
    build = core_path.parent.parent
    proof_path = build / "script-proof.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    source_path = build / "meadow_scene.progressive.gd"
    source = source_path.read_bytes()
    previous_path = ROOT / "artifacts/startup-v135/build/candidate-04/meadow_scene.progressive.gd"
    base.verify_pin({"file": previous_path, "sha256": "c5f4457db0a377ed975d49325c11c8a507260b4e48a1b02745916443b5580e5e"})
    new_guard, old_guard = NEW_GUARD.encode(), OLD_GUARD.encode()
    base.require(source.count(new_guard) == 1, "One explicit short-circuit proxy AO branch")
    base.require(source.replace(new_guard, old_guard) == previous_path.read_bytes(),
                 "Only scoped AO branch changes candidate-04 main hook")
    base.require(base.sha(source) == proof["mainSourceSha256"], "Compiler source pin")
    base.require(base.sha(pack["scripts/meadow_scene.gdc"]) == proof["mainGdcSha256"], "Actual packed main GDC pin")
    base.require(base.sha(pack["scripts/meadow_progressive.gdc"]) == proof["controllerGdcSha256"], "Actual controller GDC pin")
    base.verify_pin({"file": ROOT / "godot/scripts/meadow_progressive.gd", "sha256": proof["controllerSourceSha256"]})
    base.verify_pin({"file": ROOT / "godot/scripts/meadow_scene.gd", "sha256": proof["originalSourceSha256"]})
    checked = []
    for path, value in baseline.items():
        if (path.endswith(".gdc") and path != "scripts/meadow_scene.gdc") or "rock-occlusion" in path:
            base.require(pack.get(path) == value, "Original logic/AO data unchanged: " + path)
            checked.append(path)
    return {"proof": base.pin(proof_path), "source": base.pin(source_path),
            "mainGdcSha256": proof["mainGdcSha256"], "controllerGdcSha256": proof["controllerGdcSha256"],
            "originalLogicEntriesExact": checked, "onlyExplicitProxyAoGuardAdded": True}


def make_plan(core_path, source_report, out):
    contract = build_contract()
    pack = base.entries(core_path)
    baseline = base.entries(base.NATIVE)
    contract["scriptContract"] = source_contract(core_path, pack, baseline)
    manifest = json.loads(pack["progressive/manifest.json"])
    base.require(manifest["version"] == 1, "Manifest version 1")
    groups = []
    for chunk in manifest["chunks"]:
        roots, meshes = [], []
        for part in chunk.get("scenes", []):
            target = meshes if part.get("meshOnly", False) else roots
            parent = part.get("parent", ".")
            target.extend(name if parent == "." else parent + "/" + name for name in part["roots"])
        group = {**chunk, "file": str((core_path.parent / chunk["file"]).resolve()),
                 "roots": roots, "meshOnlyRoots": meshes}
        base.verify_pin(group)
        if meshes:
            carrier = contract["carrier"]
            base.require(base.sha(base.entries(Path(group["file"]))[carrier["entry"]]) ==
                         carrier["encodings"]["native"]["sha256"], "Actual late carrier is pinned exact native resource")
        groups.append(group)
    for row in contract["references"]:
        base.require(base.sha(pack[row["entry"]]) == row["sha256"], "Actual initial proxy resource exact")
    base.require(not any("measurement-only" in path for path in pack), "Never ship measurement-only carrier")
    plan = {"corePack": base.pin(core_path), "detailPacks": groups, "controllerMethod": "apply_chunk",
            "controllerScript": "res://scripts/meadow_progressive.gd", "sourceReport": str(source_report.resolve()),
            "waterTextureProgression": "Original full water last, existing mip suffix before.",
            "baselinePathAliases": {}, "proxyContract": contract}
    validate_proxy_plan(plan)
    base.json_new(out, plan)
    print(json.dumps({"plan": str(out), "core": plan["corePack"], "rootReplacements": 9, "meshReplacements": 2}, indent=2))


def run(request, out, timeout):
    plan = json.loads(request.read_text(encoding="utf-8"))
    validate_proxy_plan(plan)
    current_contract = build_contract()
    base.require(plan["proxyContract"]["manifest"] == current_contract["manifest"], "Proxy contract unchanged")
    source_contract(Path(plan["corePack"]["file"]), base.entries(Path(plan["corePack"]["file"])), base.entries(base.NATIVE))
    base.PROBE = Path(__file__).with_suffix(".gd")
    base.native_audit(request, out, timeout)
    for row in plan["proxyContract"]["references"]:
        base.verify_pin(row)


class Tests(unittest.TestCase):
    def part(self):
        return {"meshOnly": True, "resource": "res://progressive/details/world-visuals.scn", "parent": ".",
                "roots": MESH_ROOTS, "restoreShaderParameters": AO_RESTORE,
                "removeMetadata": ["progressive_visual_proxy"]}

    def test_exact_contract(self):
        validate_mesh_part(self.part())

    def test_no_root_rename(self):
        row = self.part(); row["roots"] = ["ContinuousMeadow", "WrongRock"]
        with self.assertRaises(ValueError): validate_mesh_part(row)

    def test_no_extra_material_reset(self):
        row = self.part(); row["restoreShaderParameters"] = {"SolidLimestoneGeology": {"rock_ao_vertex_count": 317556, "night_blend": 0}}
        with self.assertRaises(ValueError): validate_mesh_part(row)

    def test_no_ao_marker_removal(self):
        row = self.part(); row["removeMetadata"] = ["progressive_visual_proxy", "rock_occlusion_applied"]
        with self.assertRaises(ValueError): validate_mesh_part(row)

    def test_no_double_wrapper(self):
        row = self.part(); row["rootScene"] = True
        with self.assertRaises(ValueError): validate_mesh_part(row)

    def test_proxy_inputs_pinned(self):
        self.assertEqual(build_contract()["proxyAoPrefix"], 70386)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--core", type=Path, required=True)
    p.add_argument("--source-report", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("native")
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=90)
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.mode == "plan": make_plan(args.core.resolve(), args.source_report.resolve(), args.out.resolve())
    elif args.mode == "native": run(args.request.resolve(), args.out.resolve(), args.timeout)
    else: unittest.main(argv=[sys.argv[0]], verbosity=2)
