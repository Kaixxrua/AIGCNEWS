"""Regression contract for the contact meadow's broad cloud lighting."""

from pathlib import Path
import unittest


PALETTE = Path(__file__).resolve().parents[1] / "shaders" / "meadow_palette.gdshaderinc"


class CloudLightingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PALETTE.read_text(encoding="utf-8")

    def test_cloud_octaves_do_not_share_the_axis_aligned_noise_grid(self):
        self.assertIn("vec2 broad_uv = mat2", self.source)
        self.assertIn("vec2 detail_uv = mat2", self.source)
        self.assertIn("vec2 breakup_uv = mat2", self.source)
        self.assertIn(
            "broad * 0.66 + detail * 0.24 + breakup * 0.10", self.source
        )
        self.assertNotIn("meadow_noise(p * 0.036", self.source)

    def test_day_cloud_shade_cannot_create_a_deep_rectangular_patch(self):
        self.assertIn("mix(0.89, 1.0, cloud)", self.source)
        self.assertIn("mix(0.97, 1.0, cloud)", self.source)


if __name__ == "__main__":
    unittest.main()
