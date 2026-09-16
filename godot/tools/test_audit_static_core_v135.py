"""Bounded synthetic/static tests only. No Godot, sockets, capture or builds."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import audit_static_core_v135 as audit


def observation():
    contract = {"nodes": [{"path": "ContinuousRiver", "material": {"resource": "river/material"}, "transformBits": "exact"}],
                "resources": {"river/material": {"shaderObject": "canonical/water", "textureRidAlias": "water", "ctexSha256": "alpha-exact"}},
                "members": {"windmills": ["VillageRotor_0", "VillageRotor_1"], "weatherPools": list(range(7)),
                            "bossGuideVertices": 65, "edgeReady": True, "shaderGlobalObservable": False},
                "lights": audit.LIGHTS.copy(), "colliders": list(range(5)),
                "controller": {"completed": True}}
    return {"schema": "static-core-observation-v1", "status": "OBSERVED_CPU_ONLY", "errors": [],
            "packBinding": {"allLoadedEntryMd5Match": True, "entryCount": 222, "matchedLoadedEntries": 222},
            "corePack": {"sha256": "source"}, "startup": {"clock": 0, "motion": True},
            "timing": {"probeEnteredUs": 500, "loadBeginUs": 1000, "loadEndUs": 4000, "instantiateEndUs": 5000,
                       "readyEndUs": 10000, "firstObservationUs": 10001, "loadMainMs": 3.0, "instantiateMs": 1.0,
                       "readyCallMs": 5.0, "cpuLoadThroughReadyMs": 9.0, "offlineCaptureIncluded": False,
                       "probePreloadsWorld": False, "packMountIncluded": False, "renderReadyClaim": False},
            "snapshots": [{"contract": {**copy.deepcopy(contract), "label": label},
                           "cacheDiagnosticsNotCompared": {"hits": 50}} for label in audit.LABELS],
            "routes": [{"pauseExact": True, "invalidSampledPoints": 0, "seed": seed} for seed in [1150901, 1150902]],
            "chunks": [{"index": i, "sha256": str(i), "applyAwaitMs": i + 1} for i in range(12)],
            "inputChecks": [{"key": key, "before": False, "after": True} for key in [68, 71, 67]]}


THIN = '''[gd_scene load_steps=3 format=3]
[ext_resource type="Script" path="res://scripts/meadow_scene.gd" id="1_main"]
[ext_resource type="Script" path="res://scripts/meadow_edge_growth.gd" id="2_edge"]
[node name="MeadowPlain" type="Node3D"]
script = ExtResource("1_main")
[node name="Camera3D" type="Camera3D" parent="."]
[node name="MeadowEdgeGrowth" type="Node3D" parent="."]
script = ExtResource("2_edge")
'''


class StaticCoreTests(unittest.TestCase):
    def test_native_runner_refuses_unbounded_limits_without_launching(self):
        with mock.patch.object(audit.subprocess, "run") as launch:
            for value in [0, 91, 90.1, True]:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    audit.invoke_bounded(["unused.exe"], audit.SCOPE, value)
            launch.assert_not_called()

    def test_native_runner_timeout_records_failure_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "source"
            directory.mkdir()
            engine = root / "Godot.exe"
            engine.write_bytes(b"fake executable: no process is launched by this test")
            with mock.patch.object(audit, "SCOPE", root), mock.patch.object(audit.subprocess, "run") as launch:
                launch.side_effect = subprocess.TimeoutExpired([str(engine)], 90)
                result = audit.invoke_bounded([str(engine), "--headless"], directory, 90)
                self.assertEqual(result["status"], "TIMEOUT_KILLED")
                self.assertIsNone(result["exitCode"])
                kwargs = launch.call_args.kwargs
                self.assertEqual(kwargs["timeout"], 90)
                self.assertIs(kwargs["shell"], False)
                self.assertTrue(all(Path(kwargs["env"][key]).is_relative_to(directory) for key in result["freshEnvironment"]))
                self.assertNotEqual(launch.call_args.args[0][0], str(engine))
                self.assertEqual(audit.pin(launch.call_args.args[0][0])["sha256"], audit.pin(engine)["sha256"])
                before = (directory / "process.json").read_bytes()
                with self.assertRaises(ValueError):
                    audit.invoke_bounded([str(engine)], directory, 90)
                self.assertEqual(launch.call_count, 1)
                self.assertEqual((directory / "process.json").read_bytes(), before)

    def test_exact_contract_is_not_web_performance_pass(self):
        left, right = observation(), observation()
        right["corePack"]["sha256"] = "candidate"
        right["snapshots"][0]["cacheDiagnosticsNotCompared"] = {"hits": 0}
        right["chunks"][0]["applyAwaitMs"] = 99.0
        result = audit.compare_reports(left, right)
        self.assertEqual(result["status"], "PASS_NATIVE_EXACT_STATIC_CORE_CONTRACT")
        self.assertTrue(any("10s" in text for text in result["limits"]))

    def test_tiny_transform_changes_are_not_rounded_away(self):
        left, right = observation(), observation()
        right["snapshots"][0]["contract"]["nodes"][0]["transformBits"] = "3.576e-7-different"
        self.assertEqual(audit.compare_reports(left, right)["status"], "FAIL")

    def test_equal_shader_bytes_do_not_excuse_broken_object_or_rid_alias(self):
        for field in ["shaderObject", "textureRidAlias", "ctexSha256"]:
            with self.subTest(field=field):
                left, right = observation(), observation()
                right["snapshots"][0]["contract"]["resources"]["river/material"][field] = "copy"
                self.assertEqual(audit.compare_reports(left, right)["status"], "FAIL")

    def test_dynamic_reconstruction_omissions_fail(self):
        mutations = {"windmills": [], "weatherPools": list(range(6)), "bossGuideVertices": 0, "edgeReady": False}
        for key, value in mutations.items():
            with self.subTest(key=key):
                left, right = observation(), observation()
                right["snapshots"][0]["contract"]["members"][key] = value
                self.assertEqual(audit.compare_reports(left, right)["status"], "FAIL")

    def test_duplicate_nodes_input_loss_and_changed_routes_fail(self):
        for target in ["duplicate", "input", "route"]:
            with self.subTest(target=target):
                left, right = observation(), observation()
                if target == "duplicate":
                    right["snapshots"][0]["contract"]["nodes"].append({"path": "CrownToTurfFringe2"})
                elif target == "input":
                    right["inputChecks"][0]["after"] = False
                else:
                    right["routes"][0]["seed"] = 999
                if target == "input":
                    with self.assertRaises(ValueError):
                        audit.compare_reports(left, right)
                else:
                    self.assertEqual(audit.compare_reports(left, right)["status"], "FAIL")

    def test_missing_snapshot_chunk_or_failed_native_refused(self):
        for field in ["snapshots", "chunks", "errors"]:
            with self.subTest(field=field):
                report = observation()
                report[field].pop() if field != "errors" else report[field].append("stale WeakRef")
                with self.assertRaises(ValueError):
                    audit.compare_reports(observation(), report)

    def test_changed_light_shape_and_unbound_pack_refused(self):
        for kind in ["light", "shape", "binding"]:
            with self.subTest(kind=kind):
                report = observation()
                if kind == "binding":
                    report["packBinding"]["matchedLoadedEntries"] -= 1
                elif kind == "light":
                    report["snapshots"][0]["contract"]["lights"]["SpotLight3D"] = 1
                else:
                    report["snapshots"][0]["contract"]["colliders"].pop()
                with self.assertRaises(ValueError):
                    audit.compare_reports(observation(), report)

    def test_cpu_timer_must_include_resource_load_not_just_attach(self):
        timing = observation()["timing"]
        audit.check_timing(timing)
        for key, value in [("cpuLoadThroughReadyMs", 5.0), ("loadBeginUs", 9000), ("firstObservationUs", 9999),
                           ("probePreloadsWorld", True), ("offlineCaptureIncluded", True), ("renderReadyClaim", True),
                           ("loadMainMs", float("nan"))]:
            with self.subTest(key=key):
                changed = {**timing, key: value}
                with self.assertRaises(ValueError):
                    audit.check_timing(changed)

    def test_all_old_entries_are_frozen_except_two_explicit_entries(self):
        old = {"scripts/meadow_scene.gdc": {"sha256": "old", "bytes": 1},
               "scenes/main.tscn.remap": {"sha256": "heavy", "bytes": 2},
               "water.ctex": {"sha256": "water", "bytes": 3}}
        new = {**old, "scripts/meadow_scene.gdc": {"sha256": "new", "bytes": 5},
               "scenes/main.tscn.remap": {"sha256": "thin", "bytes": 1},
               "progressive/static-core/world.scn": {"sha256": "scene", "bytes": 9}}
        removals = audit.approved_removals()
        self.assertEqual(len(removals), 26)
        old.update({name: {"sha256": digest, "bytes": 99} for name, digest in removals.items()})
        changes = [{"path": key, "beforeSha256": old.get(key, {}).get("sha256"), "afterSha256": new[key]["sha256"]}
                   for key in new if new[key] != old.get(key)]
        self.assertEqual(audit.check_changes(old, new, changes)["unchangedEntries"], 1)
        explicit = changes + [{"path": name, "beforeSha256": digest, "afterSha256": None} for name, digest in removals.items()]
        self.assertGreater(len(explicit), 16)
        self.assertEqual(audit.check_changes(old, new, explicit)["removedEntries"], removals)
        for kind in ["undeclared", "declared-water", "duplicate", "missing", "wrong-pin", "new-script", "no-thin-entry", "missing-removal", "wrong-deleted-pin", "wildcard"]:
            with self.subTest(kind=kind):
                source, candidate, allowed = copy.deepcopy(old), copy.deepcopy(new), copy.deepcopy(explicit)
                if kind in ["undeclared", "declared-water"]:
                    candidate["water.ctex"]["sha256"] = "changed-alpha"
                    if kind == "declared-water":
                        allowed.append({"path": "water.ctex", "beforeSha256": "water", "afterSha256": "changed-alpha"})
                elif kind == "duplicate":
                    allowed.append(allowed[0])
                elif kind == "missing":
                    del candidate["water.ctex"]
                elif kind == "wrong-pin":
                    allowed[0]["afterSha256"] = "wrong"
                elif kind == "new-script":
                    candidate["new.gdc"] = {"sha256": "extra", "bytes": 2}
                    allowed.append({"path": "new.gdc", "beforeSha256": None, "afterSha256": "extra"})
                elif kind == "missing-removal":
                    key = next(iter(removals))
                    candidate[key] = source[key]
                elif kind == "wrong-deleted-pin":
                    source[next(iter(removals))]["sha256"] = "changed"
                elif kind == "wildcard":
                    allowed[-1]["path"] = "progressive/static-cache/*"
                else:
                    candidate["scenes/main.tscn.remap"] = old["scenes/main.tscn.remap"]
                    allowed = [r for r in allowed if r["path"] != "scenes/main.tscn.remap"]
                with self.assertRaises(ValueError):
                    audit.check_changes(source, candidate, allowed)

    def test_wrong_final_deletion_authority_is_refused(self):
        with mock.patch.object(audit, "FINAL_OVERLAY_SHA", "0" * 64):
            with self.assertRaises(ValueError):
                audit.approved_removals()

    def test_actual_pretty_and_compact_manifests_are_separately_pinned(self):
        external = (audit.SOURCE.parent / "progressive-manifest.json").read_bytes()
        embedded = audit.entry_bytes(audit.SOURCE, "progressive/manifest.json")
        self.assertNotEqual(external, embedded)
        self.assertEqual(len(audit.check_progressive_manifests(external, embedded)["chunks"]), 12)
        for outer, inner in [(embedded, external), (external + b" ", embedded), (external, embedded + b" "),
                             (external, embedded.replace(b'"index":0', b'"index":1', 1))]:
            with self.subTest(outer_length=len(outer), inner_length=len(inner)):
                with self.assertRaises(ValueError):
                    audit.check_progressive_manifests(outer, inner)

    def test_thin_entry_must_not_load_heavy_world_twice(self):
        self.assertTrue(audit.check_thin_entry(THIN, THIN)["thinEntry"])
        for modified in [THIN.replace('type="Script"', 'type="PackedScene"'),
                         THIN + '\n[ext_resource type="PackedScene" path="res://terrain.scn" id="2"]\n',
                         THIN.replace('name="MeadowPlain"', 'name="Other"'),
                         THIN + 'mesh = SubResource("heavy")\n',
                         THIN.replace('script = ExtResource("1_main")', 'script = ExtResource("unknown")'),
                         THIN.replace('script = ExtResource("1_main")', 'position = Vector3(1, 0, 0)\nscript = ExtResource("1_main")'),
                         THIN.replace('[node name="MeadowEdgeGrowth" type="Node3D" parent="."]\nscript = ExtResource("2_edge")\n', '')]:
            with self.subTest(text=modified):
                with self.assertRaises(ValueError):
                    audit.check_thin_entry(modified, THIN)

    def test_actual_source_remap_cannot_be_shadowed_by_adding_text_scene(self):
        self.assertEqual(audit.thin_target('[remap]\npath="res://progressive/static-core/entry.tscn"'), "progressive/static-core/entry.tscn")
        for target in [".godot/exported/133200997/export-3ad5c15c4f3250da0cc7c1af1770d85f-main.scn",
                       "scenes/main.tscn", "progressive/static-core/../heavy.tscn", "assets/baked/terrain.scn"]:
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    audit.thin_target('[remap]\npath="res://' + target + '"')

    def test_probe_static_scope_timing_and_live_guards(self):
        text = audit.PROBE.read_text(encoding="utf-8")
        run = text[text.index("func _run()") : text.index("func _finish_static()")]
        markers = ["var load_begin", "var packed := load", "var load_end", "packed.instantiate()", "var instantiate_end",
                   "root.add_child(scene)", "var ready_end", "_bind_pack()", '_snapshot("core")']
        locations = [run.index(marker) for marker in markers]
        self.assertEqual(locations, sorted(locations))
        for forbidden in ["preload(", "ResourceSaver", "PackedScene.new", "load_resource_pack(", "sceneReady(",
                          "frame_post_draw.emit", "_build_landscape\"", "restoreWorld\""]:
            self.assertNotIn(forbidden, text)
        for required in ["get_cached_ref", "canonical == value", "canonical.get_rid() == rid", 'get("rotors")',
                         "pools.size() == 7", 'get("ready_complete")', "is_connected", 'key == owner_node.get_instance_id()',
                         "item.surface == wildlife.get(target)", "size() == 65", "KEY_D, KEY_G, KEY_C", '"_physics_process", 0.125']:
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
