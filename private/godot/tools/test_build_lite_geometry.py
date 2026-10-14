"""Offline numeric, corruption, source-freeze and delivered-artifact tests.

python -B godot/tools/test_build_lite_geometry.py [--manifest PATH]
No game startup, service, browser, import, export or source writes.
"""

import argparse
import gzip
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
parser.add_argument("--report", type=Path, help="Write a NEW test log below the geometry artifact directory")
options, remaining = parser.parse_known_args()


class QuantizationTests(unittest.TestCase):
    def test_absolute_bound_signed_zero_and_aabb(self):
        rng = np.random.default_rng(115)
        values = rng.uniform(-260, 260, (20000, 3)).astype("<f4")
        values[0] = [-0.0, 0.0, 1.0]
        for step in (1 / 128, 1 / 2048, 1 / 4096):
            actual = lite.quantize_values(values, step, clamp_bounds=True)
            self.assertLessEqual(np.abs(actual.astype(np.float64) - values).max(), step / 2)
            self.assertTrue((actual.min(axis=0) >= values.min(axis=0)).all())
            self.assertTrue((actual.max(axis=0) <= values.max(axis=0)).all())
            self.assertTrue(np.signbit(actual[0, 0]))
            self.assertFalse(np.signbit(actual[0, 1]))

    def test_invalid_step_and_nonfinite_input_fail_closed(self):
        for step in (0, -1, 0.003, .125, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                lite.validate_step(step)
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(ValueError):
                lite.quantize_values(np.array([[value, 0]], dtype="<f4"), 1 / 2048)

    def test_thin_triangle_protection_and_shared_position_seams(self):
        # First triangle would collapse on a 1/128 lattice. Vertex 3 is the
        # same coordinate as vertex 0 but could represent a separate UV seam.
        vertices = np.array([[.003, .002, .001], [.0031, .002, .001], [.003, .0021, .001],
                             [.003, .002, .001], [1.013, 0, .001], [1.013, 1.019, .001]], dtype="<f4")
        indices = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint32)
        actual, report = lite.quantize_positions(vertices, indices, 1 / 128)
        self.assertEqual(actual[:3].tobytes(), vertices[:3].tobytes())
        self.assertEqual(actual[0].tobytes(), actual[3].tobytes())
        self.assertEqual(report["new_degenerate_triangles"], 0)
        self.assertEqual(report["winding_reversals"], 0)
        self.assertEqual(report["unsafe_triangles"], 0)
        self.assertLessEqual(report["max_face_normal_delta_degrees"], 5)
        self.assertGreaterEqual(report["min_area_ratio"], .9)
        self.assertLessEqual(report["max_area_ratio"], 1.1)
        self.assertEqual(actual.shape, vertices.shape)

    def test_original_degenerate_triangle_is_neither_removed_nor_repaired(self):
        vertices = np.array([[.011, 0, 0], [.012, 0, 0], [.013, 0, 0]], dtype="<f4")
        actual, report = lite.quantize_positions(vertices, np.array([[0, 1, 2]]), 1 / 128)
        self.assertEqual(actual.tobytes(), vertices.tobytes())
        self.assertEqual(report["source_degenerate_triangles"], 1)
        self.assertEqual(report["triangles"], 1)

    def test_triangle_guard_detects_reverse_and_excess_area(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
        reversed_vertices = vertices[[0, 2, 1]].copy()
        bad, stats = lite.triangle_checks(vertices, reversed_vertices, np.array([[0, 1, 2]]))
        self.assertTrue(bad[0])
        self.assertEqual(stats["winding_reversals"], 1)
        bigger = vertices.copy()
        bigger[1] *= 2
        bad, stats = lite.triangle_checks(vertices, bigger, np.array([[0, 1, 2]]))
        self.assertTrue(bad[0])
        self.assertEqual(stats["max_area_ratio"], 2)

    def test_strided_patch_leaves_other_attributes_byte_exact(self):
        raw = bytearray(range(80))
        original = bytes(raw)
        view = lite.strided_floats(raw, 2, 4, 40, 2)
        view[:] = np.array([[1, 2], [3, 4]], dtype="<f4")
        allowed = set(range(4, 12)) | set(range(44, 52))
        self.assertTrue(all(a == b for i, (a, b) in enumerate(zip(original, raw)) if i not in allowed))
        with self.assertRaises(ValueError):
            lite.strided_floats(raw, 3, 4, 40, 2)


class PayloadTests(unittest.TestCase):
    def test_same_length_unique_patch_and_ambiguous_patch_rejection(self):
        patched, offset = lite.patch_unique(b"HEADabcdefghTAIL", b"abcdefgh", b"12345678")
        self.assertEqual(offset, 4)
        self.assertEqual(patched, b"HEAD12345678TAIL")
        for raw, before, after in ((b"xx", b"x", b"y"), (b"abc", b"z", b"x"),
                                   (b"abc", b"a", b"yy"), (b"abc", b"", b"")):
            with self.assertRaises(ValueError):
                lite.patch_unique(raw, before, after)

    def test_stock_rscc_roundtrip_and_corruption_rejection(self):
        raw = b"ABCD" * 20000 + bytes(range(256))
        packed, trials = lite.pack_best(raw)
        self.assertEqual(lite._unpack(packed), raw)
        self.assertEqual(len(gzip.compress(packed, compresslevel=9, mtime=0)), min(row["gzip9_bytes"] for row in trials))
        for broken in (packed[:-4], b"NOPE" + packed[4:], packed[:-4] + b"junkRSCC"):
            with self.assertRaises(ValueError):
                lite._unpack(broken)

    def test_writes_outside_authorized_artifacts_are_rejected(self):
        for path in (lite.ROOT / "new-copy", lite.GODOT_ROOT / "assets/new-copy",
                     lite.SCOPE / "../outside-geometry", Path(__file__)):
            with self.assertRaises(ValueError):
                lite.new_directory(path)
        for resource in ("res://scenes/main.tscn", "res://assets/baked/v77/../v77/detail.scn"):
            with self.assertRaises(ValueError):
                lite.source_path(resource)


@unittest.skipUnless(options.manifest, "Use --manifest to audit generated candidates")
class DeliveredCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(options.manifest.read_text(encoding="utf-8"))
        cls.directory = options.manifest.resolve().parent

    def test_original_caches_and_ao_remain_frozen(self):
        for resource, pin in lite.PINS.items():
            self.assertEqual(lite.sha(lite.source_path(resource).read_bytes()), pin)
        ao_original = lite.source_path(lite.AO_RESOURCE).read_bytes()
        ao_candidate = Path(self.manifest["replacements"][lite.AO_RESOURCE]).read_bytes()
        self.assertEqual(ao_original, ao_candidate)
        self.assertEqual(self.manifest["ao"]["patches"], [])

    def test_all_artifact_hashes_sizes_and_untouched_payload_regions(self):
        self.assertEqual(set(self.manifest["replacements"]), {*lite.PINS, lite.AO_RESOURCE})
        for resource, row in self.manifest["files"].items():
            candidate = Path(row["artifact_path"]).read_bytes()
            original = lite.source_path(resource).read_bytes()
            self.assertEqual(lite.size_record(candidate), row["after"])
            self.assertEqual(lite.size_record(original), row["before"])
            a, b = lite._unpack(original), lite._unpack(candidate)
            self.assertEqual(len(a), len(b))
            cursor = 0
            for span in sorted(row["changed_spans"], key=lambda item: item["offset"]):
                self.assertGreaterEqual(span["offset"], cursor)
                self.assertEqual(a[cursor:span["offset"]], b[cursor:span["offset"]])
                cursor = span["offset"] + span["length"]
            self.assertEqual(a[cursor:], b[cursor:])
            self.assertLess(row["after"]["gzip9_bytes"], row["before"]["gzip9_bytes"])

    def test_godot_reloaded_contract_and_original_ao_runtime(self):
        before = json.loads((self.directory / "before/inspection.json").read_text())
        after = json.loads((self.directory / "after/inspection.json").read_text())
        terrain_sha = self.manifest["files"][lite.TERRAIN]["after"]["sha256"]
        counts = lite.compare_inspections(before, after, self.manifest["files"], terrain_sha)
        self.assertEqual(counts, self.manifest["verified_counts"])
        self.assertEqual(counts["meshes"], 10)
        self.assertEqual(counts["collision_shapes"], 3)
        for resource, label in ((lite.TERRAIN, "ContinuousMeadow"), (lite.DETAIL, "SolidLimestoneGeology")):
            self.assertEqual(lite.mesh_signature(before, resource, label), lite.mesh_signature(after, resource, label))
        probe = self.manifest["ao"]["runtime_probe"]
        self.assertTrue(probe["applied"])
        self.assertTrue(probe["all_sample_indices_and_nonblue_attributes_exact"])
        self.assertGreater(probe["visibility_samples_checked"], 0)

    def test_every_position_uv_bound_and_triangle_guard(self):
        for file in self.manifest["files"].values():
            for surface in file["surfaces"]:
                for channel in surface["attributes"].values():
                    self.assertLessEqual(channel["measured_max_abs_error"], channel["absolute_error_bound_per_component"])
                topology = surface["topology"]
                self.assertEqual(topology["new_degenerate_triangles"], 0)
                self.assertEqual(topology["winding_reversals"], 0)
                self.assertEqual(topology["unsafe_triangles"], 0)
                self.assertLessEqual(topology["max_face_normal_delta_degrees"], 5)

    def test_pack_mapping_uses_actual_entry_sha_and_exact_approved_outputs(self):
        mapping = json.loads((self.directory / "pack-replacements.json").read_text(encoding="utf-8"))
        self.assertIsInstance(mapping["replacements"], list)
        self.assertEqual(len(mapping["replacements"]), 7)
        self.assertEqual(mapping["detailedManifestSha256"], lite.sha(options.manifest.read_bytes()))
        pack = Path(mapping["sourcePck"])
        self.assertEqual(lite.sha(pack.read_bytes()), mapping["sourcePckSha256"])
        inventory = lite.read_pack(pack, verify=True)
        entries = {entry["path"].removeprefix("res://"): entry for entry in inventory["entries"]}
        different_containers = []
        with pack.open("rb") as stream:
            for row in mapping["replacements"]:
                self.assertFalse(row["path"].startswith("res://"))
                resource = "res://" + row["path"]
                entry = entries[row["path"]]
                stream.seek(entry["offset"])
                original = stream.read(entry["bytes"])
                self.assertEqual(lite.sha(original), row["beforeSha256"])
                self.assertEqual(row["file"], self.manifest["replacements"][resource])
                self.assertEqual(lite.sha(Path(row["file"]).read_bytes()), row["afterSha256"])
                if row["pckContainerDiffersFromDisk"]:
                    different_containers.append(row["path"])
                    self.assertNotEqual(row["beforeSha256"], row["pinnedDiskSha256"])
                    self.assertEqual(lite._unpack(original), lite._unpack(lite.source_path(resource).read_bytes()))
        self.assertEqual(set(different_containers), {"assets/baked/v77/foothill.scn", "assets/baked/v113/far-sward.scn"})

    def test_original_project_art_scripts_shaders_and_import_cache_stat_inventory(self):
        frozen = json.loads((self.directory / "frozen-source-tree.json").read_text(encoding="utf-8"))
        self.assertEqual(frozen, lite.frozen_tree_stats())
        self.assertEqual(len(frozen), self.manifest["frozen_source_tree_files"])


if __name__ == "__main__":
    if options.report:
        capture = io.StringIO()
        program = unittest.main(argv=[sys.argv[0], *remaining], exit=False,
                                testRunner=unittest.TextTestRunner(stream=capture, verbosity=2))
        text = capture.getvalue()
        sys.stdout.write(text)
        lite.write_new(options.report, text.encode("utf-8"))
        raise SystemExit(0 if program.result.wasSuccessful() else 1)
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
