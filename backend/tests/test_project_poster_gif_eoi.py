from __future__ import annotations

import struct
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from PIL import Image, ImageChops, ImageStat

from backend.app.services.project_catalog import game_poster_gif as gif, game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent
from backend.app.services.project_catalog.game_poster_resources import PosterResource
from backend.tests.test_project_web_posters import ITEM, ORIGINAL, SOURCE, model_with, tool


def padded_gif(*, tail=b"\x00", align=True, pixels=160 * 160, end=5):
    # Clear before each literal keeps the code width fixed at 3. Seven leading
    # clear codes align EOI exactly without changing a pixel. A striped raster
    # proves the isolated worker composes content, not an all-black fixture.
    codes = [4] * (7 if align else 0)
    codes += [code for index in range(pixels) for code in (4, (index // 160 // 8) % 2)]
    codes.append(end)
    data = bytearray((len(codes) * 3 + 7) // 8)
    for index, code in enumerate(codes):
        byte, shift = divmod(index * 3, 8)
        data[byte] |= (code << shift) & 255
        if shift > 5:
            data[byte + 1] |= code >> (8 - shift)
    data.extend(tail)
    blocks = b"".join(bytes([len(data[offset:offset + 255])]) + data[offset:offset + 255]
                      for offset in range(0, len(data), 255))
    return (b"GIF89a" + struct.pack("<HHBBB", 160, 160, 0x80, 0, 0)
            + b"\x00\x00\x00\xff\xff\xff" + b"," + struct.pack("<HHHHB", 0, 0, 160, 160, 0)
            + b"\x02" + blocks + b"\x00;")


class GifEoiCompatibilityTests(unittest.TestCase):
    def test_only_one_zero_flush_after_aligned_eoi_preserves_the_raster(self):
        standard, compatible = padded_gif(tail=b""), padded_gif()
        for payload in (standard, compatible):
            self.assertEqual(gif._frames(payload, partial=False)[:2], (160, 160))
            self.assertEqual(len(gif._frames(payload, partial=False)[2]), 1)
        jpeg, evidence = gif.preview_gif_sync(compatible)
        with Image.open(BytesIO(standard)) as expected, Image.open(BytesIO(jpeg)) as actual:
            difference = ImageStat.Stat(ImageChops.difference(expected.convert("RGB"), actual.convert("RGB")))
            self.assertLess(max(difference.mean), 2)
        self.assertEqual(evidence["frameIndex"], 0)
        self.assertEqual(evidence["decodedPixels"], 160 * 160)
        self.assertEqual(evidence["framesValidated"], 1)

    def test_nonzero_multiple_zero_and_unaligned_whole_byte_tails_still_fail(self):
        for tail, align in [(b"\x01", True), (b"\xff", True), (b"\x00\x00", True),
                            (b"\x00\x05", True), (b"\x00", False), (b"\xff", False)]:
            for partial in (False, True):
                with self.subTest(tail=tail, align=align, partial=partial), self.assertRaisesRegex(gif.GifPreviewError, "^invalid_image$"):
                    gif._frames(padded_gif(tail=tail, align=align), partial=partial)

    def test_padding_never_supplies_a_missing_eoi_or_missing_or_excess_pixels(self):
        # Four literals change the stream by 24 bits, keeping EOI aligned:
        # the exact raster count must reject these independently of tail shape.
        for payload in (padded_gif(end=4), padded_gif(end=0),
                        padded_gif(pixels=160 * 160 - 1), padded_gif(pixels=160 * 160 + 1),
                        padded_gif(pixels=160 * 160 - 4), padded_gif(pixels=160 * 160 + 4)):
            with self.subTest(payload=len(payload)), self.assertRaisesRegex(gif.GifPreviewError, "^invalid_image$"):
                gif._frames(payload, partial=False)

    def test_subblock_terminator_trailer_and_canvas_still_validate(self):
        payload = padded_gif()
        outside = bytearray(payload)
        outside[20:22] = struct.pack("<H", 1)  # The 160px frame would exceed its 160px canvas.
        for broken in (payload[:-1], payload[:-2] + b";", payload[:-2] + b"\x00X",
                       payload[:35], bytes(outside)):
            with self.subTest(length=len(broken)), self.assertRaisesRegex(gif.GifPreviewError, "^invalid_image$"):
                gif._frames(broken, partial=False)

    def test_compatibility_does_not_change_the_resource_or_worker_limits(self):
        self.assertEqual((gif.GIF_BYTES, gif.GIF_PIXELS, gif.GIF_TOTAL_PIXELS, gif.GIF_FRAMES, gif.GIF_SECONDS),
                         (8 * 1024 * 1024, 16_000_000, 64_000_000, 120, 3.0))
        self.assertEqual((resources.IMAGE_BYTES, resources.IMAGE_PIXELS, resources.IMAGE_RESOURCE_SECONDS),
                         (8 * 1024 * 1024, 16_000_000, 30))
        with self.assertRaisesRegex(gif.GifPreviewError, "image_too_large"):
            gif._frames(padded_gif() + bytes(gif.GIF_BYTES), partial=True)


class GifEoiPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_isolated_worker_accepts_the_same_single_frame(self):
        real_start = gif._start_worker
        workers = []

        def start():
            worker = real_start()
            workers.append(worker)
            return worker

        with patch.object(gif, "_start_worker", start):
            jpeg, evidence = await gif.preview_gif(padded_gif())
        self.assertEqual(len(workers), 1)
        self.assertIsNotNone(workers[0].poll())
        self.assertTrue(jpeg.startswith(b"\xff\xd8\xff"))
        self.assertEqual(evidence["framesValidated"], 1)

    async def test_decodable_gif_still_requires_image_review_and_cannot_bypass_it(self):
        address = "https://example.com/actual-discovered.gif"
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":""}'), AIMessage(content='{"candidateId":""}'))
        jpeg, evidence = await gif.preview_gif(padded_gif())
        fetch = AsyncMock(side_effect=[
            PosterResource(SOURCE, f'<title>{ORIGINAL}</title><img src="{address}">'.encode(), "text/html"),
            PosterResource(address, jpeg, "image/jpeg", evidence),
        ])
        review = AsyncMock(return_value={"matches": False, "kind": "screenshot", "reason": "uncertain"})
        cache = AsyncMock()
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                      fetch=fetch, review=review, cache=cache).run(ITEM)
        review.assert_awaited_once()
        cache.assert_not_awaited()
        self.assertNotEqual(result["posterStatus"], "ready")
        self.assertTrue(any(row.get("error") == "image_content_mismatch" for row in result["posterTrace"]))


if __name__ == "__main__":
    unittest.main()
