"""Focused v135 offline contract tests; no engine launch or resource rewrite."""
from pathlib import Path
import hashlib
import json
import struct
import unittest

import build_progressive_scenes_v135 as tool


class PureTests(unittest.TestCase):
    def test_normalized_order_and_changed_data(self):
        before = {"b": [1, "raw-sha"], "a": {"material": "res://shader"}}
        reordered = {"a": {"material": "res://shader"}, "b": [1, "raw-sha"]}
        self.assertEqual(tool.normalized_hash(before), tool.normalized_hash(reordered))
        reordered["b"][1] = "changed-buffer"
        self.assertNotEqual(tool.normalized_hash(before), tool.normalized_hash(reordered))

    def test_unknown_pin_rejected(self):
        with self.assertRaises(ValueError):
            tool.pinned(Path(tool.__file__), "0" * 64)

    def test_writer_refuses_outside_scope_without_creating_file(self):
        target = tool.ROOT / "godot/assets/never-write-progressive-test.bin"
        before = target.exists()
        with self.assertRaises(ValueError):
            tool.write(target, b"forbidden")
        self.assertEqual(target.exists(), before)

    def test_exact_deferred_allowlist(self):
        self.assertEqual(list(tool.GROUPS), ["detail", "foothill", "riverbank", "brush", "crown-edge", "far-sward"])
        labels = [name for spec in tool.GROUPS.values() for name in spec["deferred"]]
        self.assertEqual(len(labels), 9)
        self.assertNotIn("SolidLimestoneGeology", labels)
        self.assertNotIn("EmbeddedRiverbankStrata", labels)
        self.assertNotIn("ContinuousMeadow", labels)


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tool.SCOPE / "candidate-02"
        cls.manifest = json.loads((cls.directory / "manifest.json").read_bytes())
        cls.proof = json.loads(tool.pinned(Path(cls.manifest["nativeProof"]), cls.manifest["nativeProofSha256"]))
        cls.hashes = json.loads((cls.directory / "normalized-hashes.json").read_bytes())["groups"]
        cls.rows = {row["group"]: row for row in cls.proof["groups"]}

    def test_source_packs_unchanged(self):
        tool.pinned(tool.SHIP, tool.SHIP_SHA)
        tool.pinned(tool.NATIVE, tool.NATIVE_SHA)
        self.assertEqual(self.manifest["sourceShippingPackSha256"], tool.SHIP_SHA)
        self.assertEqual(self.manifest["sourceNativePackSha256"], tool.NATIVE_SHA)

    def test_all_split_encodings_logically_identical(self):
        for group in self.manifest["groups"]:
            for kind in ("core", "deferred"):
                with self.subTest(group=group["group"], kind=kind):
                    part = group["variants"][kind]
                    decoded = []
                    for variant in ("native", "mode5"):
                        entry = part["encodings"][variant]
                        data = tool.pinned(Path(entry["path"]), entry["sha256"])
                        self.assertEqual(len(data), entry["bytes"])
                        decoded.append(tool.logical(data))
                    self.assertEqual(decoded[0], decoded[1])
                    self.assertEqual(tool.sha(decoded[0]), part["decodedSha256"])

    def test_restored_fingerprints_exact(self):
        self.assertEqual(self.proof["status"], "PASS")
        for group, row in self.rows.items():
            with self.subTest(group=group):
                self.assertTrue(row["reassembledExact"])
                self.assertTrue(row["packedResourceMetadataExact"])
                self.assertEqual(row["originalSnapshot"], row["reassembledSnapshot"])
                self.assertEqual(self.hashes[group]["original"], self.hashes[group]["restored"])
                self.assertEqual(self.hashes[group]["original"], tool.normalized_hash(row["originalSnapshot"]))

    def test_placeholders_keep_metadata_material_and_duplicable_empty_mesh(self):
        bool_true = [1, hashlib.sha256(struct.pack("<II", 1, 1)).hexdigest()]
        for group, row in self.rows.items():
            for label in tool.GROUPS[group]["deferred"]:
                key = "." if group == "far-sward" else label
                with self.subTest(group=group, node=key):
                    original = row["originalSnapshot"][key]
                    core = row["coreSnapshot"][key]
                    self.assertEqual(core["class"], original["class"])
                    self.assertEqual(core["properties"]["metadata/progressive_placeholder"], bool_true)
                    self.assertEqual(core["properties"]["mesh"][0], "ArrayMesh")
                    self.assertEqual(core["allDecodedMeshChannels"], [])
                    self.assertEqual(core["properties"]["material_override"], original["properties"]["material_override"])
                    for property_name, value in original["properties"].items():
                        if property_name.startswith("metadata/"):
                            self.assertEqual(core["properties"][property_name], value)
                    self.assertNotIn("metadata/progressive_placeholder", row["reassembledSnapshot"][key]["properties"])

    def test_all_target_collisions_in_core_exact(self):
        collider_count = 0
        for row in self.rows.values():
            self.assertEqual(row["core"]["collisionCount"], row["original"]["collisionCount"])
            self.assertEqual(row["deferred"]["collisionCount"], 0)
            for path, data in row["originalSnapshot"].items():
                if data["class"] in ("StaticBody3D", "CollisionShape3D"):
                    self.assertEqual(row["coreSnapshot"][path], data)
                    collider_count += data["class"] == "CollisionShape3D"
        self.assertEqual(collider_count, 2)  # Third cache collider is in untouched terrain.
        self.assertIn("assets/baked/v77/terrain.scn", self.manifest["coreAlwaysUnchanged"])

    def test_actual_controller_scene_specs_and_container_roots(self):
        for item in self.manifest["groups"]:
            group = item["group"]
            spec = item["sceneSpec"]
            self.assertEqual(spec["resource"], f"res://progressive/details/{group}.scn")
            self.assertEqual(spec["parent"], "MeadowEdgeGrowth" if group == "crown-edge" else ".")
            self.assertEqual(spec["roots"], tool.GROUPS[group]["deferred"])
            direct = [node["path"] for node in self.rows[group]["deferred"]["nodes"]
                      if node["path"] != "." and "/" not in node["path"]]
            self.assertEqual(direct, spec["roots"])
            self.assertEqual(item["variants"]["core"]["entry"], tool.GROUPS[group]["entry"])

    def test_far_sward_required_metadata_and_original_numeric_arrays(self):
        row = self.rows["far-sward"]
        for key in ("cache_revision", "source_sha256", "terrain_sha256", "ground_roots", "root_ranges"):
            field = "metadata/" + key
            self.assertEqual(row["coreSnapshot"]["."]["properties"][field], row["originalSnapshot"]["."]["properties"][field])
        self.assertEqual(self.rows["detail"]["core"]["meshBufferBytes"], 18736452)
        self.assertEqual(self.rows["detail"]["core"]["collisionBytes"], 5110236)


class ProxyArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tool.SCOPE / "proxy-02"
        cls.manifest = json.loads((cls.directory / "manifest.json").read_bytes())
        cls.proof = json.loads(tool.pinned(Path(cls.manifest["nativeProof"]), cls.manifest["nativeProofSha256"]))
        cls.dump = json.loads((cls.directory / "dump/native-proof.json").read_bytes())
        cls.request = json.loads((cls.directory / "assembly/request.json").read_bytes())

    def test_proxy_preserves_frozen_partition_and_originals(self):
        tool.pinned(Path(self.manifest["basePartitionManifest"]), self.manifest["basePartitionManifestSha256"])
        tool.pinned(tool.SHIP, tool.SHIP_SHA)
        tool.pinned(tool.NATIVE, tool.NATIVE_SHA)
        self.assertEqual(self.manifest["sourceShippingPackSha256"], tool.SHIP_SHA)

    def test_every_proxy_codec_pair_and_exact_late_mesh(self):
        for label, resource in self.manifest["resources"].items():
            with self.subTest(resource=label):
                decoded = []
                for variant in ("native", "mode5"):
                    item = resource["encodings"][variant]
                    decoded.append(tool.logical(tool.pinned(Path(item["path"]), item["sha256"])))
                self.assertEqual(decoded[0], decoded[1])
                self.assertEqual(tool.sha(decoded[0]), resource["decodedSha256"])
        for row in self.proof["groups"]:
            self.assertTrue(row["meshOnlyRestoredExact"])
            self.assertEqual(row["restoredSnapshot"], row["expectedCoreSnapshot"])

    def test_proxy_only_selects_original_whole_records(self):
        by_group = {row["group"]: row for row in self.request["groups"]}
        for saved in self.dump["groups"]:
            row = dict(saved)
            if row["group"] == "detail":
                path = self.directory / "buffers/detail-hybrid-source-indices.bin"
                data = path.read_bytes()
                row["lodIndices"] = {"path": str(path), "bytes": len(data), "sha256": tool.sha(data)}
            buffers, selected, corners, expected, prefix = tool.selected_proxy_buffers(row)
            spec = by_group[row["group"]]
            self.assertEqual(len(selected), spec["vertex_count"])
            self.assertEqual(len(corners), spec["index_count"])
            self.assertEqual(expected, spec["expected_channels"])
            self.assertEqual(prefix, spec["proxy_ao_prefix"])
            for key, value in buffers.items():
                self.assertEqual(value, tool.read_buffer(spec["buffers"][key]))

    def test_colliders_are_exact_and_instances_survive_mesh_upgrade(self):
        count = 0
        for row in self.proof["groups"]:
            self.assertTrue(row["collisionInstancesUnchangedDuringUpgrade"])
            self.assertTrue(row["allSelectedDecodedChannelsExact"])
            for path in row["colliderPaths"]:
                self.assertEqual(row["expectedCoreSnapshot"][path], row["proxyCoreSnapshot"][path])
                self.assertEqual(row["expectedCoreSnapshot"][path], row["restoredSnapshot"][path])
                count += row["expectedCoreSnapshot"][path]["class"] == "CollisionShape3D"
        self.assertEqual(count, 2)

    def test_hybrid_bounds_screen_and_ao_restore_contract(self):
        for row in self.manifest["parameters"]:
            self.assertTrue(row["screeningPassed"])
            self.assertLessEqual(row["coverage"]["lostFraction"], 0.02)
            self.assertTrue(row["coverage"]["notVisualAcceptance"])
        rock = next(row for row in self.manifest["parameters"] if row["group"] == "detail")
        self.assertTrue(rock["fullNonAoSuffixRetained"])
        self.assertEqual((rock["originalAoPrefix"], rock["proxyAoPrefix"]), (317556, 70386))
        self.assertEqual(self.manifest["sceneSpec"]["roots"], ["ContinuousMeadow", "SolidLimestoneGeology"])
        self.assertTrue(self.manifest["sceneSpec"]["meshOnly"])
        self.assertEqual(self.manifest["sceneSpec"]["restoreShaderParameters"]["SolidLimestoneGeology"]["rock_ao_vertex_count"], 317556)


if __name__ == "__main__":
    unittest.main()
