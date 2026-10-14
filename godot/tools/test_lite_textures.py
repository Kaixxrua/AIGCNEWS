import io
import struct
import unittest

import numpy as np
from PIL import Image

from build_lite_pack import compress_ctex, decode_ctex


def fixture(size=(32, 16), opaque=False):
    blob = bytearray(52)
    struct.pack_into("<9I", blob, 0, 844387143, 1, *size, 226492416, 4294967295, 0, 0, 0)
    count = max(size).bit_length() - 1
    struct.pack_into("<IHHII", blob, 36, 2, *size, count, 4 if opaque else 5)
    for level in range(count + 1):
        w, h = max(1, size[0] >> level), max(1, size[1] >> level)
        pixels = np.zeros((h, w, 4), dtype=np.uint8)
        pixels[:, :, :3] = [48, 120, 64]
        pixels[:, :, 3] = 255 if opaque else np.arange(w, dtype=np.uint8) * (255 // max(1, w - 1))
        image = Image.fromarray(pixels).convert("RGB" if opaque else "RGBA")
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", lossless=True, exact=True)
        data = buffer.getvalue()
        blob += struct.pack("<I", len(data)) + data
    return bytes(blob)


class LiteTextureTests(unittest.TestCase):
    def test_half_size_preserves_logical_frame_coordinates_and_mip_alpha(self):
        before = fixture()
        after, report = compress_ctex(before, "bud-deer-v54")
        self.assertEqual(report["physicalAfter"], [16, 8])
        logical, _, levels = decode_ctex(after)
        original = decode_ctex(before)[2]
        self.assertEqual(logical, (32, 16))
        for index, (_, image) in enumerate(levels):
            np.testing.assert_array_equal(np.asarray(image)[:, :, 3], np.asarray(original[index + 1][1])[:, :, 3])

    def test_material_quarter_dimensions_and_complete_chain(self):
        after, report = compress_ctex(fixture(opaque=True), "meadow-sward-v60")
        self.assertEqual(report["physicalAfter"], [8, 4])
        self.assertEqual(decode_ctex(after)[2][-1][1].size, (1, 1))

    def test_dragon_pixel_contract_keeps_physical_size(self):
        _, report = compress_ctex(fixture(), "castle-dragon-turns-v57")
        self.assertEqual(report["mipDrop"], 0)
        self.assertEqual(report["physicalAfter"], [32, 16])

    def test_reject_corruption(self):
        for data in (b"", fixture()[:-1], fixture() + b"trailing"):
            with self.assertRaises(ValueError):
                decode_ctex(data)


if __name__ == "__main__":
    unittest.main()
