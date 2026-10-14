"""Independent numeric/structural audit of strong geometry COPY artifacts.

python -B godot/tools/test_lite_geometry_strong.py --manifest PATH --report NEW_LOG
No scene runtime, browser, service, export, import, or original resource writes.
"""

import argparse
import copy
import io
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
import numpy as np
import build_lite_geometry as lite

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--manifest", type=Path)
parser.add_argument("--report", type=Path)
options, remaining = parser.parse_known_args()


class StrongNumericTests(unittest.TestCase):
    def test_canonical_uv_all_three_categories_and_interpolation(self):
        uv = np.array([[.1, .2], [.3, .7], [.9, .9], [-999, 1], [-1000, 0], [-1001, .5],
                       [-2000, .1], [-2001, .2], [-2050, .3]], dtype="<f4")
        indices = np.arange(9).reshape(-1, 3)
        target = lite.canonical_leaf_uv(uv, indices)
        np.testing.assert_array_equal(lite.leaf_classes(uv), lite.leaf_classes(target))
        rng = np.random.default_rng(115)
        weights = rng.uniform(0, 1, (100, 3))
        weights /= weights.sum(axis=1)[:, None]
        for w in weights:
            a = (uv[indices] * w[None, :, None]).sum(axis=1)
            b = (target[indices] * w[None, :, None]).sum(axis=1)
            np.testing.assert_array_equal(lite.leaf_classes(a), lite.leaf_classes(b))

    def test_mixed_uv_triangle_fails_closed(self):
        uv = np.array([[0, 0], [-999, 0], [-2000, 0]], dtype="<f4")
        with self.assertRaises(ValueError):
            lite.canonical_leaf_uv(uv, np.array([[0, 1, 2]]))

    def test_canonical_native_normals_cover_sphere_and_poles(self):
        rng = np.random.default_rng(4_7_2)
        n = rng.normal(0, 1, (100000, 3))
        n /= np.linalg.norm(n, axis=1)[:, None]
        n = np.vstack((n, np.eye(3), -np.eye(3))).astype("<f4")
        axes, angle, predicted = lite.canonical_normal_encoding(n)
        self.assertEqual(axes.shape, (len(n), 2))
        self.assertGreaterEqual(angle.min(), 32768)
        self.assertLessEqual(lite.normal_angles(n, predicted).max(), .25)
        self.assertLess(np.abs(np.linalg.norm(predicted, axis=1) - 1).max(), 1e-6)
        self.assertEqual(axes.tobytes(), lite.canonical_normal_encoding(n.copy())[0].tobytes())
        with self.assertRaises(ValueError):
            lite.canonical_normal_encoding(np.zeros((3, 3), dtype="<f4"))

    def test_32_level_rgb_maximum_error_preserves_alpha_policy(self):
        source = np.arange(256)
        result = np.rint(np.rint(source * 31 / 255) * 255 / 31)
        self.assertLessEqual(np.abs(source - result).max(), 4)
        self.assertEqual(len(np.unique(result)), 32)
        self.assertEqual(result[0], 0)
        self.assertEqual(result[-1], 255)

    def test_native_uv_range_and_same_length_span_guards(self):
        surface = dict(vertex_count=3, attribute_stride=12, format=lite.NATIVE_FLAG,
                       offsets={"4": 4}, uv_scale_values=[0, 0, 0, 0])
        output = bytearray(36)
        lite.write_uv_storage(output, surface, 4, np.array([[0, 0], [.5, .5], [1, 1]], dtype="<f4"))
        with self.assertRaises(ValueError):
            lite.write_uv_storage(output, surface, 4, np.full((3, 2), 2, dtype="<f4"))
        lite.verify_declared_spans(b"head1234tail", b"head5678tail", [dict(offset=4, length=4)])
        for changed in (b"head5678oops", b"head56789tail"):
            with self.assertRaises(ValueError):
                lite.verify_declared_spans(b"head1234tail", changed, [dict(offset=4, length=4)])


@unittest.skipUnless(options.manifest, "Use --manifest for full delivered-artifact audit")
class StrongCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = options.manifest.resolve().parent
        cls.manifest = json.loads(options.manifest.read_text(encoding="utf-8"))
        cls.before = json.loads((cls.directory / "before/inspection.json").read_text(encoding="utf-8"))
        cls.after = json.loads((cls.directory / "after/inspection.json").read_text(encoding="utf-8"))

    def test_original_pack_caches_AO_tree_and_shaders_frozen(self):
        for resource, pin in lite.PINS.items():
            self.assertEqual(lite.sha(lite.source_path(resource).read_bytes()), pin)
        self.assertEqual(lite.sha(lite.source_path(lite.AO_RESOURCE).read_bytes()), lite.AO_PIN)
        pack = Path(self.manifest["reference_pack"]["path"])
        self.assertEqual(lite.sha(pack.read_bytes()), self.manifest["reference_pack"]["sha256"])
        self.assertEqual(lite.frozen_tree_stats(), json.loads((self.directory / "frozen-source-tree.json").read_text()))
        self.assertEqual(lite.verify_leaf_shader_contract(pack), self.manifest["shader_contract"])

    def test_independent_engine_decoded_bounds_topology_and_collision_audit(self):
        expected = copy.deepcopy(self.manifest["files"])
        counts = lite.compare_strong_inspections(self.before, self.after, expected,
                                                 self.manifest["files"][lite.TERRAIN]["after"]["sha256"])
        self.assertEqual(counts, self.manifest["verified_counts"])
        self.assertEqual(expected, self.manifest["files"])
        self.assertEqual(counts, dict(nodes=21, meshes=10, surfaces=10, collision_shapes=3,
                                     collision_corners=1006005, vertices=2436986, triangles=1312182))
        for row in expected.values():
            for surface in row["surfaces"]:
                self.assertEqual(surface["topology"]["new_degenerate_triangles"], 0)
                self.assertEqual(surface["topology"]["winding_reversals"], 0)
                self.assertLessEqual(surface["position_max_vector_error"], .004)
                self.assertLessEqual(surface["normal_max_angle_degrees"], .25)

    def test_AO_rebinding_only_and_exact_full_prefix_correspondence(self):
        original = lite.source_path(lite.AO_RESOURCE).read_bytes()
        candidate = Path(self.manifest["replacements"][lite.AO_RESOURCE]).read_bytes()
        patches = self.manifest["ao"]["patches"]
        self.assertEqual(len(patches), 1)
        patch = patches[0]
        self.assertEqual(patch["field"], "mesh_signature")
        self.assertEqual(patch["length"], 64)
        self.assertEqual(patch["before"], lite.mesh_signature(self.before, lite.DETAIL, "SolidLimestoneGeology"))
        self.assertEqual(patch["after"], lite.mesh_signature(self.after, lite.DETAIL, "SolidLimestoneGeology"))
        actual, offset = lite.patch_unique(original, patch["before"].encode(), patch["after"].encode())
        self.assertEqual(offset, patch["offset"])
        self.assertEqual(bytes(actual), candidate)
        self.assertEqual(lite.size_record(candidate), self.manifest["ao"]["after"])
        expected_ao = copy.deepcopy(self.before["ao"])
        expected_ao["mesh_signature"] = patch["after"]
        probe = json.loads((self.directory / "ao-verify/inspection.json").read_text())
        self.assertEqual(probe["ao"], expected_ao)
        self.assertTrue(probe["runtime_probe"]["applied"])
        self.assertTrue(probe["runtime_probe"]["all_sample_indices_and_nonblue_attributes_exact"])
        self.assertFalse(self.manifest["ao"]["signature_bypass"])
        self.assertEqual(probe["runtime_probe"], self.manifest["ao"]["runtime_probe"])
        for resource, name in ((lite.DETAIL, "SolidLimestoneGeology"), (lite.TERRAIN, "ContinuousMeadow")):
            a = next(m for m in self.before["files"][resource]["meshes"] if m["label"] == name)["surfaces"][0]
            b = next(m for m in self.after["files"][resource]["meshes"] if m["label"] == name)["surfaces"][0]
            for channel in (0, 1, 2, 3, 12):
                self.assertEqual(a["channel_hashes"][str(channel)], b["channel_hashes"][str(channel)])
            if name == "SolidLimestoneGeology":
                indices = lite.triangle_indices(a).ravel()
                corners, vertices = self.before["ao"]["prefix_corners"], self.before["ao"]["prefix_vertices"]
                np.testing.assert_array_equal(np.unique(indices[:corners]), np.arange(vertices))
                self.assertTrue((indices[corners:] >= vertices).all())
                self.assertEqual(vertices, 317556)
                self.assertEqual(corners, 317580)

    def test_candidate_gzip_buffer_reduction_and_exact_patch_base_regions(self):
        before_gpu = after_gpu = 0
        for resource, row in self.manifest["files"].items():
            candidate = Path(row["artifact_path"]).read_bytes()
            base = Path(row["patch_base_path"]).read_bytes()
            self.assertEqual(lite.size_record(candidate), row["after"])
            self.assertEqual(lite.sha(base), row["patch_base_sha256"])
            lite.verify_declared_spans(lite._unpack(base), lite._unpack(candidate), row["changed_spans"])
            for surface in row["surfaces"]:
                before_gpu += surface["original_gpu_buffer_bytes"]
                after_gpu += surface["candidate_gpu_buffer_bytes"]
        self.assertEqual(before_gpu, self.manifest["totals"]["original_gpu_buffer_bytes"])
        self.assertEqual(after_gpu, self.manifest["totals"]["candidate_gpu_buffer_bytes"])
        self.assertLess(after_gpu, before_gpu)
        self.assertLess(self.manifest["totals"]["after_individual_gzip9_bytes"], 43151686)

    def test_pack_schema_actual_PCK_hashes_not_disk_container_hashes(self):
        path = self.directory / "pack-replacements.v1.json"
        mapping = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(mapping["replacements"]), 7)
        self.assertEqual(mapping["detailedManifestSha256"], lite.sha(options.manifest.read_bytes()))
        entries = {e["path"].removeprefix("res://"): e for e in lite.read_pack(Path(mapping["sourcePck"]), verify=True)["entries"]}
        different = []
        with Path(mapping["sourcePck"]).open("rb") as stream:
            for row in mapping["replacements"]:
                entry = entries[row["path"]]
                stream.seek(entry["offset"])
                self.assertEqual(lite.sha(stream.read(entry["bytes"])), row["beforeSha256"])
                self.assertEqual(lite.sha(Path(row["file"]).read_bytes()), row["afterSha256"])
                self.assertEqual(row["file"], self.manifest["replacements"]["res://" + row["path"]])
                if row["pckContainerDiffersFromDisk"]:
                    different.append(row["path"])
                    self.assertNotEqual(row["beforeSha256"], row["pinnedDiskSha256"])
        self.assertEqual(set(different), {"assets/baked/v77/foothill.scn", "assets/baked/v113/far-sward.scn"})

    def test_tampered_topology_and_nodes_are_rejected(self):
        changed = copy.deepcopy(self.after)
        changed["files"][lite.TERRAIN]["node_count"] -= 1
        with self.assertRaises(ValueError):
            lite.compare_strong_inspections(self.before, changed, copy.deepcopy(self.manifest["files"]),
                                             self.manifest["files"][lite.TERRAIN]["after"]["sha256"])
        changed = copy.deepcopy(self.after)
        changed["files"][lite.TERRAIN]["meshes"][0]["surfaces"][0]["index_count"] -= 3
        with self.assertRaises(ValueError):
            lite.compare_strong_inspections(self.before, changed, copy.deepcopy(self.manifest["files"]),
                                             self.manifest["files"][lite.TERRAIN]["after"]["sha256"])


if __name__ == "__main__":
    if options.report:
        capture = io.StringIO()
        program = unittest.main(argv=[sys.argv[0], *remaining], exit=False,
                                testRunner=unittest.TextTestRunner(stream=capture, verbosity=2))
        log = capture.getvalue()
        sys.stdout.write(log)
        lite.write_new(options.report, log.encode("utf-8"))
        raise SystemExit(0 if program.result.wasSuccessful() else 1)
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
