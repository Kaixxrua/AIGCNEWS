"""CPU alpha data only: no native, engine, browser, or scene execution."""
import io
import json
from pathlib import Path
import unittest

from PIL import Image

import build_progressive_alpha_v135 as tool


class AlphaEncodingTests(unittest.TestCase):
    def test_every_eight_bit_alpha_value_survives_in_la8(self):
        alpha = bytes(range(256))
        png = tool.encode_alpha(alpha, 16, 16)
        proof = tool.verify_alpha(png, alpha, 16, 16)
        self.assertEqual(proof["alphaSha256"], tool.sha(alpha))
        self.assertEqual(proof["rawLA8Bytes"], 512)

    def test_odd_size_edges_and_fully_transparent_rgb_independent(self):
        alpha = bytes((0, 255, 1, 127, 128, 254)) * 5
        png = tool.encode_alpha(alpha, 5, 6)
        self.assertTrue(tool.verify_alpha(png, alpha, 5, 6)["allAlphaPixelsExact"])
        with Image.open(io.BytesIO(png)) as image:
            self.assertEqual(image.getchannel("L").tobytes(), bytes([255]) * 30)

    def test_changed_alpha_luminance_or_size_rejected(self):
        alpha = bytes((0, 128, 255, 10))
        png = tool.encode_alpha(alpha, 2, 2)
        with self.assertRaises(ValueError):
            tool.verify_alpha(png, bytes((0, 127, 255, 10)), 2, 2)
        with self.assertRaises(ValueError):
            tool.verify_alpha(png, alpha, 1, 4)
        stream = io.BytesIO()
        Image.new("LA", (2, 2), (254, 0)).save(stream, format="PNG")
        with self.assertRaises(ValueError):
            tool.verify_alpha(stream.getvalue(), bytes(4), 2, 2)

    def test_invalid_input_and_outside_output_rejected(self):
        for width, height in ((True, 1), (0, 1), (-1, 1), (1.5, 1)):
            with self.assertRaises(ValueError):
                tool.encode_alpha(b"x", width, height)
        with self.assertRaises(ValueError):
            tool.encode_alpha(b"x", 2, 2)
        with self.assertRaises(ValueError):
            tool.generate(tool.ROOT / "outside-alpha-scope")


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tool.SCOPE / "alpha-data-01"
        if not (cls.directory / "manifest.json").exists():
            raise unittest.SkipTest("Alpha overlay not generated")
        cls.overlay = json.loads((cls.directory / "manifest.json").read_text(encoding="utf-8"))
        cls.proof = json.loads((cls.directory / "proof.json").read_text(encoding="utf-8"))
        cls.source = tool.textures.pinned_entries(tool.SOURCE, tool.SOURCE_SHA)

    def test_exact_main_builder_and_support_schemas_and_hashes(self):
        self.assertEqual(len(self.overlay["entries"]), 9)
        runtime = json.loads((self.directory / "alpha-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(runtime), {"textures"})
        self.assertEqual(len(runtime["textures"]), 8)
        for entry in self.overlay["entries"]:
            self.assertEqual(set(entry), {"entry", "path", "sha256"})
            self.assertEqual(tool.sha(Path(entry["path"]).read_bytes()), entry["sha256"])
        self.assertEqual(tool.sha((self.directory / "manifest.json").read_bytes()), self.proof["overlaySha256"])
        for row in self.overlay["textures"]:
            mapping = runtime["textures"][row["sourceTexture"]]
            self.assertEqual(set(mapping), {"resource", "width", "height", "alphaSha256"})
            self.assertEqual(mapping["resource"], "res://" + row["entry"])
            self.assertEqual(mapping["alphaSha256"], row["proof"]["alphaSha256"])

    def test_every_original_top_mip_alpha_pixel_and_la8_dimension_exact(self):
        self.assertEqual({r["name"] for r in self.overlay["textures"]}, set(tool.TARGETS))
        for row in self.overlay["textures"]:
            ctex = self.source[row["sourceCtexEntry"]]
            parsed, alpha, mip_sha = tool.top_alpha(ctex)
            self.assertEqual(tool.sha(ctex), row["sourceCtexSha256"])
            self.assertEqual(mip_sha, row["sourceTopEncodedMipSha256"])
            self.assertEqual(parsed["physical"], (row["width"], row["height"]))
            self.assertEqual(tool.verify_alpha(Path(row["path"]).read_bytes(), alpha, row["width"], row["height"]), row["proof"])
            self.assertTrue(row["cpuOnly"])
            self.assertFalse(row["mayBindToVisibleMaterial"])

    def test_all_existing_candidates_frozen_dragon_water_not_encoded(self):
        self.assertEqual(tool.snapshot_candidates(), self.overlay["existingCandidateFileHashes"])
        names = {r["name"] for r in self.overlay["textures"]}
        self.assertNotIn("castle-dragon-turns-v57", names)
        self.assertNotIn("river-ripples-v37", names)
        self.assertFalse(list(self.directory.rglob("*.ctex")))
        self.assertFalse(list(self.directory.rglob("*.pck")))

    def test_budget_counts_alpha_and_runtime_manifest_overhead(self):
        budget = self.overlay["budget"]
        self.assertEqual(sum(r["pngBytes"] for r in self.overlay["textures"]), budget["alphaPngBytes"])
        actual_entries = sum(Path(row["path"]).stat().st_size for row in self.overlay["entries"])
        self.assertEqual(actual_entries + budget["bootstrap256CtexBytesWithOriginalDragonAndExistingWater"],
                         budget["combinedCtexAlphaAndRuntimeManifestBytes"])
        self.assertEqual(budget["bootstrap256CtexBytesWithOriginalDragonAndExistingWater"], 1171130)
        self.assertEqual(self.overlay["integration"]["visibleTextureReplacementCount"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
