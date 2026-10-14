"""Float boundaries, fail-closed consumer guards and every real CPU mask pixel."""
import io
import json
from pathlib import Path
import struct
import unittest

from PIL import Image

import build_progressive_alpha_predicates_v135 as tool


class PredicateTests(unittest.TestCase):
    def test_float32_not_naive_double_or_float32_threshold(self):
        self.assertFalse(153 / 255.0 > 0.6)
        self.assertEqual(tool.godot_alpha(153), 0.6000000238418579)
        self.assertTrue(tool.godot_alpha(153) > 0.6)
        self.assertFalse(tool.godot_alpha(153) > struct.unpack("<f", struct.pack("<f", 0.6))[0])
        self.assertEqual(tool.predicate_bits(153), 1)

    def test_all_256_values_and_three_boundary_pairs(self):
        lut, rows = tool.build_lut()
        self.assertEqual(len(rows), 256)
        self.assertEqual(lut, bytes([0]) * 153 + bytes([204]) * 77 + bytes([236]) * 13 + bytes([255]) * 13)
        for value in range(256):
            self.assertEqual(tool.predicate_bits(value), tool.predicate_bits(lut[value]))
        for value, expected in ((152, 0), (153, 1), (229, 1), (230, 3), (242, 3), (243, 7)):
            self.assertEqual(tool.predicate_bits(value), expected)

    def test_exact_four_value_mapping_and_identity_proof_reject_bad_mask(self):
        original = bytes(range(256))
        lut, _ = tool.build_lut()
        mapped = original.translate(lut)
        proof = tool.verify_semantics(original, mapped)
        self.assertEqual(proof["predicateMismatchCount"], 0)
        self.assertFalse(proof["alphaBytesExact"])
        bad = bytearray(mapped)
        bad[153] = 0
        with self.assertRaises(ValueError):
            tool.verify_semantics(original, bytes(bad))
        with self.assertRaises(ValueError):
            tool.verify_semantics(original, mapped[:-1])

    def test_threshold_operator_rgb_new_use_and_source_drift_fail_closed(self):
        name = "meadow_city_builder.gd"
        line = tool.EXPECTED_PIXEL_LINES[name][0]
        self.assertEqual(tool.validate_consumer_text(name, line), [line])
        mutations = [line.replace("0.60", "0.61"), line.replace(">", ">="), line.replace(".a", ".r"),
                     line + "\nvar extra = source.get_pixel(1, 1).a", line.replace("get_pixel", "get_pixelv")]
        for text in mutations:
            with self.assertRaises(ValueError):
                tool.validate_consumer_text(name, text)
        with self.assertRaises(ValueError):
            tool.validate_consumer_text(name, line + "\nvar x = source.get_data()", tool.sha(line.encode()))
        with self.assertRaises(ValueError):
            tool.validate_consumer_text("future_consumer.gd", line)

    def test_engine_pin_drift_fails_and_outside_output_rejected(self):
        with self.assertRaises(ValueError):
            tool.validate_engine(pins={"core/io/image.cpp": "0" * 64})
        with self.assertRaises(ValueError):
            tool.generate(tool.ROOT / "outside-predicate-scope")


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tool.SCOPE / "alpha-predicates-01"
        if not (cls.directory / "manifest.json").exists():
            raise unittest.SkipTest("Predicate overlay not generated")
        cls.overlay = json.loads((cls.directory / "manifest.json").read_text(encoding="utf-8"))
        cls.proof = json.loads((cls.directory / "proof.json").read_text(encoding="utf-8"))
        cls.source = tool.exact.textures.pinned_entries(tool.exact.SOURCE, tool.exact.SOURCE_SHA)

    def test_every_original_pixel_matches_three_double_predicates_independently(self):
        compared = 0
        for row in self.overlay["textures"]:
            parsed, original, _ = tool.exact.top_alpha(self.source[row["sourceCtexEntry"]])
            png = Path(row["path"]).read_bytes()
            with Image.open(io.BytesIO(png)) as image:
                self.assertEqual(image.mode, "LA")
                self.assertEqual(image.size, parsed["physical"])
                mapped = image.getchannel("A").tobytes()
                self.assertEqual(image.getchannel("L").getextrema(), (255, 255))
            self.assertLessEqual(set(mapped), {0, 204, 236, 255})
            # Independent scalar tables, then byte translations check every pixel.
            for threshold in (0.60, 0.9, 0.95):
                table = bytes(int(struct.unpack("<f", struct.pack("<f", a / 255.0))[0] > threshold) for a in range(256))
                self.assertEqual(original.translate(table), mapped.translate(table))
            self.assertEqual(tool.verify_semantics(original, mapped), row["proof"])
            compared += len(original)
        self.assertEqual(compared, 12581980)
        self.assertEqual(self.overlay["totalPredicateChecks"], compared * 3)

    def test_runtime_external_schema_hashes_and_semantics_only(self):
        self.assertTrue(self.overlay["semanticsOnly"])
        runtime = json.loads((self.directory / "alpha-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(runtime), {"textures", "semanticsOnly"})
        self.assertTrue(runtime["semanticsOnly"])
        self.assertEqual(len(self.overlay["entries"]), 9)
        for entry in self.overlay["entries"]:
            self.assertEqual(set(entry), {"entry", "path", "sha256"})
            self.assertEqual(tool.sha(Path(entry["path"]).read_bytes()), entry["sha256"])
        for row in self.overlay["textures"]:
            mapping = runtime["textures"][row["sourceTexture"]]
            self.assertEqual(set(mapping), {"resource", "width", "height", "alphaSha256"})
            self.assertEqual(mapping["alphaSha256"], row["proof"]["mappedAlphaSha256"])
            self.assertFalse(row["mayBindToVisibleMaterial"])
            self.assertTrue(row["semanticsOnly"])
        self.assertEqual(tool.sha((self.directory / "manifest.json").read_bytes()), self.proof["overlaySha256"])

    def test_frozen_exact_alpha_ctex_and_consumers_still_unchanged(self):
        self.assertEqual(tool.snapshot_directory(tool.EXACT_DIRECTORY), self.overlay["existingExactAlphaFileHashes"])
        self.assertEqual(tool.exact.snapshot_candidates(), self.overlay["existingTextureCandidateFileHashes"])
        exact_overlay = json.loads((tool.EXACT_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(tool.validate_consumers(exact_overlay), self.overlay["pinnedCurrentConsumers"])
        self.assertEqual(tool.validate_engine(), self.overlay["enginePrecisionContract"])
        self.assertFalse(list(self.directory.rglob("*.pck")))
        self.assertFalse(list(self.directory.rglob("*.ctex")))

    def test_budget_includes_all_pngs_and_runtime_manifest(self):
        budget = self.overlay["budget"]
        size = sum(Path(row["path"]).stat().st_size for row in self.overlay["entries"])
        self.assertEqual(size + 1171130, budget["combinedCtexMasksAndRuntimeManifestBytes"])
        self.assertEqual(sum(row["pngBytes"] for row in self.overlay["textures"]), budget["predicatePngBytes"])
        self.assertGreater(budget["additionalRawSavingsVsExactAlphaOverlay"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
