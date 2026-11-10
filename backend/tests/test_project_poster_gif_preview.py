from __future__ import annotations

import asyncio
import hashlib
import struct
import subprocess
import sys
import time
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from curl_cffi import CurlECode
from curl_cffi.requests.exceptions import RequestException
from langchain_core.messages import AIMessage
from PIL import Image, ImageChops, ImageDraw, ImageStat

from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog import game_poster_gif as gif, game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import ITEM, ORIGINAL, SOURCE, model_with, tool

GIF_URL = "https://cdn.example.com/discovered/gameplay.gif"


def animation(*, size=(192, 160), disposal=1):
    frames = [Image.new("RGB", size, "black"), Image.new("RGB", size, "white")]
    ImageDraw.Draw(frames[1]).rectangle((20, 20, 55, 50), fill="red")
    final = frames[1].copy()
    draw = ImageDraw.Draw(final)
    for x in range(0, size[0], 8):
        draw.rectangle((x, 60, x + 3, size[1] - 1), fill=(x % 256, 70, 160))
    frames.append(final)
    stream = BytesIO()
    frames[0].save(stream, format="GIF", save_all=True, append_images=frames[1:], duration=100,
                   loop=0, disposal=disposal, optimize=True, comment=b"untrusted-animation-metadata")
    return stream.getvalue()


def literal_gif(*, pixels=160 * 160, value=0, end=5, trailing=b""):
    # Repeated clear codes keep the width fixed at three bits, allowing exact
    # underflow/overflow/EOI and palette mutations without a test-only decoder.
    codes = [code for _ in range(pixels) for code in (4, value)] + [end]
    data = bytearray((len(codes) * 3 + 7) // 8)
    for i, code in enumerate(codes):
        byte, shift = divmod(i * 3, 8)
        data[byte] |= (code << shift) & 255
        if shift > 5:
            data[byte + 1] |= code >> (8 - shift)
    data.extend(trailing)
    blocks = b"".join(bytes([len(data[p:p + 255])]) + data[p:p + 255] for p in range(0, len(data), 255))
    return (b"GIF89a" + struct.pack("<HHBBB", 160, 160, 0x80, 0, 0)
            + b"\x00\x00\x00\xff\xff\xff" + b"," + struct.pack("<HHHHB", 0, 0, 160, 160, 0)
            + b"\x02" + blocks + b"\x00;")


def repeated_frames(count, *, size=(160, 160)):
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle((0, 0, 20, 20), fill="red")
    output = BytesIO()
    image.save(output, format="GIF", interlace=True)
    payload = output.getvalue()
    start = 13 + 3 * 2 ** ((payload[10] & 7) + 1)
    return payload[:start] + payload[start:-1] * count + b";"


def optimized_transparency(colors):
    first = Image.new("RGB", (176, 176), "black")
    draw = ImageDraw.Draw(first)
    palette = ["black", "white", "red", "green", "blue", "yellow", "cyan", "magenta"][:colors]
    for index, color in enumerate(palette):
        x, y = index % 4 * 44, index // 4 * 88
        draw.rectangle((x, y, x + 43, y + 87), fill=color)
    second = first.copy()
    draw = ImageDraw.Draw(second)
    draw.rectangle((1, 1, 10, 10), fill="white")
    draw.rectangle((160, 160, 170, 170), fill="red")
    output = BytesIO()
    first.save(output, format="GIF", save_all=True, append_images=[second], optimize=True,
               duration=30, loop=0, disposal=1)
    return output.getvalue()


class StrictGifTests(unittest.TestCase):
    def test_lzw_requires_eoi_exact_pixels_palette_and_no_hidden_codes(self):
        gif._frames(literal_gif(), partial=False)
        bad = [literal_gif(end=4), literal_gif(pixels=25599), literal_gif(pixels=25601),
               literal_gif(value=3), literal_gif(trailing=b"\x00")]
        # Pillow's normal strict loader accepts this missing-EOI raster.
        with Image.open(BytesIO(bad[0])) as decoded:
            decoded.load()
        for payload in bad:
            with self.subTest(sha=hashlib.sha256(payload).hexdigest()), self.assertRaisesRegex(gif.GifPreviewError, "invalid_image"):
                gif._frames(payload, partial=False)

    def test_only_explicit_prefix_discards_an_incomplete_trailing_frame(self):
        payload = animation()
        _, _, all_frames = gif._frames(payload, partial=False)
        cut = payload[:all_frames[-2].end + 12]
        self.assertEqual(len(gif._frames(cut, partial=True)[2]), 2)
        with self.assertRaises(gif.GifPreviewError):
            gif._frames(cut, partial=False)
        # Known malformed data is never excused by the partial-range flag.
        with self.assertRaises(gif.GifPreviewError):
            gif._frames(payload[:all_frames[0].end] + b"\x7f", partial=True)
        with self.assertRaises(gif.GifPreviewError):
            gif._frames(payload[:20], partial=True)
        with self.assertRaises(gif.GifPreviewError):
            gif._frames(literal_gif()[:-2] + b";", partial=True)  # Missing sub-block terminator.

    def test_canvas_frames_and_total_composited_pixels_are_separate_bounds(self):
        self.assertEqual((gif.GIF_BYTES, gif.GIF_PIXELS, gif.GIF_TOTAL_PIXELS, gif.GIF_FRAMES),
                         (8 * 1024 * 1024, 16_000_000, 64_000_000, 120))
        self.assertEqual(len(gif._frames(repeated_frames(125), partial=False)[2]), 120)
        width, height, frames = gif._frames(repeated_frames(70, size=(1024, 1024)), partial=False)
        self.assertEqual(len(frames), 61)
        self.assertLessEqual(width * height * len(frames), 64_000_000)
        for claimed in ((65535, 65535), (160, 159), (0, 160)):
            payload = bytearray(literal_gif())
            payload[6:10] = struct.pack("<HH", *claimed)
            with self.subTest(claimed=claimed), self.assertRaises(gif.GifPreviewError):
                gif._frames(bytes(payload), partial=False)
        with self.assertRaisesRegex(gif.GifPreviewError, "image_too_large"):
            gif._frames(b"x" * (gif.GIF_BYTES + 1), partial=True)

    def test_unknown_rendering_and_out_of_canvas_rectangles_are_rejected(self):
        payload = literal_gif()
        for extension in (b"!\x01\x0c" + bytes(12) + b"\x00", b"!\xff\x01x\x00", b"!\xf9\x04\x10\x00\x00\x00\x00"):
            with self.subTest(extension=extension), self.assertRaises(gif.GifPreviewError):
                gif._frames(payload[:19] + extension + payload[19:], partial=False)
        broken = bytearray(payload)
        broken[20:22] = struct.pack("<H", 159)
        with self.assertRaises(gif.GifPreviewError):
            gif._frames(bytes(broken), partial=False)

    def test_only_the_declared_transparent_symbol_can_exceed_the_palette(self):
        payload = literal_gif(value=3)  # Only palette entries 0 and 1 exist.
        transparent = b"!\xf9\x04\x01\x00\x00\x03\x00"
        declared = payload[:19] + transparent + payload[19:]
        self.assertEqual(len(gif._frames(declared, partial=False)[2]), 1)
        for changed in (b"!\xf9\x04\x00\x00\x00\x03\x00",  # Flag is unset.
                        b"!\xf9\x04\x01\x00\x00\x02\x00",  # Another symbol is declared.
                        b""):
            with self.subTest(control=changed), self.assertRaises(gif.GifPreviewError):
                gif._frames(payload[:19] + changed + payload[19:], partial=False)
        # The preceding frame's declaration must not leak into the next one.
        with self.assertRaises(gif.GifPreviewError):
            gif._frames(declared[:-1] + payload[19:], partial=False)

    def test_pillow_optimized_transparency_beyond_palette_composites_correctly(self):
        for colors in (4, 8):
            payload = optimized_transparency(colors)
            self.assertIn(b"!\xf9\x04\x05\x03\x00" + bytes([colors]) + b"\x00", payload)
            jpeg, evidence = gif.preview_gif_sync(payload)
            self.assertEqual(evidence["framesValidated"], 2)
            with Image.open(BytesIO(payload)) as original, Image.open(BytesIO(jpeg)) as actual:
                original.seek(evidence["frameIndex"])
                difference = ImageStat.Stat(ImageChops.difference(original.convert("RGB"), actual.convert("RGB")))
                self.assertLess(max(difference.mean), 8)

    def test_valid_delta_frames_and_disposal_match_the_actual_composited_frame(self):
        for disposal in (1, 2, 3):
            payload = animation(disposal=disposal)
            jpeg, evidence = gif.preview_gif_sync(payload)
            self.assertEqual(evidence["frameIndex"], 2)
            self.assertEqual(evidence["framesValidated"], 3)
            if disposal == 1:
                frames = gif._frames(payload, partial=False)[2]
                self.assertTrue(any(frame.height < 160 for frame in frames))
            with Image.open(BytesIO(payload)) as original, Image.open(BytesIO(jpeg)) as result:
                original.seek(evidence["frameIndex"])
                expected = original.convert("RGB")
                difference = ImageStat.Stat(ImageChops.difference(expected, result.convert("RGB")))
                self.assertLess(max(difference.mean), 8)
                self.assertEqual(result.format, "JPEG")
                self.assertNotIn("comment", result.info)
                self.assertNotIn("duration", result.info)
            self.assertEqual(evidence["sourcePrefixSha256"], hashlib.sha256(payload).hexdigest())

    def test_black_or_uniform_animation_produces_no_preview(self):
        output = BytesIO()
        Image.new("RGB", (160, 160), "black").save(output, format="GIF")
        with self.assertRaises(gif.GifPreviewError):
            gif.preview_gif_sync(output.getvalue())


class GifWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_is_isolated_and_async_result_is_one_clean_frame(self):
        real_popen = subprocess.Popen
        with patch.object(gif.subprocess, "Popen", wraps=real_popen) as start:
            jpeg, evidence = await gif.preview_gif(animation())
        self.assertEqual(start.call_args.kwargs["env"], {"LANG": "C.UTF-8"})
        self.assertIn("-I", start.call_args.args[0])
        self.assertTrue(jpeg.startswith(b"\xff\xd8\xff"))
        self.assertEqual(evidence["frameIndex"], 2)

    async def test_hard_deadline_and_cancellation_kill_and_reap_the_worker(self):
        for cancel in (False, True):
            processes = []
            entered = asyncio.Event()

            def blocked():
                process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                processes.append(process)
                entered.set()
                return process

            started = time.monotonic()
            with patch.object(gif, "_start_worker", blocked), patch.object(gif, "GIF_SECONDS", 0.06):
                task = asyncio.create_task(gif.preview_gif(animation()))
                await entered.wait()
                if cancel:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                else:
                    with self.assertRaisesRegex(gif.GifPreviewError, "image_preview_timeout"):
                        await task
            self.assertIsNotNone(processes[0].poll())
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(processes[0].stdin.closed and processes[0].stdout.closed)

    async def test_worker_start_failure_is_a_stable_non_secret_code(self):
        with patch.object(gif.subprocess, "Popen", side_effect=OSError("private host path")):
            with self.assertRaisesRegex(gif.GifPreviewError, "^image_preview_unavailable$"):
                await gif.preview_gif(animation())


class GifRangeTransportTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def public(url, **kwargs):
        return pin_http_target(url, resolver=lambda _: ["93.184.216.34"], **kwargs)

    def session(self, responses, seen):
        responses = iter(responses)

        class Session:
            def __init__(self, **options):
                self.options = options

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                seen.append({"closed": True})

            async def get(self, url, *, allow_redirects, timeout, content_callback):
                assert not allow_redirects and self.options["verify"]
                if "Range" in self.options["headers"]:
                    assert self.options["headers"].get("Accept-Encoding") == "identity"
                seen.append({"url": url, "options": self.options})
                response = next(responses)
                if content_callback(response.body) == resources.CURL_WRITEFUNC_ERROR:
                    raise RuntimeError("bounded-body-aborted")
                if getattr(response, "error", None) is not None:
                    raise response.error
                return response
        return Session

    @staticmethod
    def response(body, status=206, content_type="application/octet-stream", **headers):
        return SimpleNamespace(status_code=status, body=body, headers={"content-type": content_type,
                               "content-range": f"bytes 0-{len(body) - 1}/{len(body) + 10000000}", **headers})

    async def fetch(self, response, *, url=GIF_URL):
        seen = []
        with patch.object(resources, "pin_http_target", self.public), patch.object(resources, "AsyncSession", self.session([response], seen)):
            return await resources.fetch_poster_resource(url, image=True), seen

    async def test_strict_gif_prefix_binary_mime_becomes_jpeg_with_source_evidence(self):
        payload = animation()
        frames = gif._frames(payload, partial=False)[2]
        prefix = payload[:frames[1].end + 12]
        result, seen = await self.fetch(self.response(prefix))
        self.assertEqual(result.url, GIF_URL)
        self.assertEqual(result.content_type, "image/jpeg")
        self.assertEqual(result.preview["frameIndex"], 1)
        self.assertTrue(result.preview["partial"])
        self.assertEqual(result.preview["downloadedBytes"], len(prefix))
        self.assertEqual(result.preview["transferBytes"], len(prefix))
        self.assertEqual(result.preview["sourceBytes"], len(prefix) + 10000000)
        self.assertEqual(seen[0]["options"]["headers"]["Range"], f"bytes=0-{resources.IMAGE_BYTES - 1}")
        self.assertEqual(seen[0]["options"]["curl_options"][resources.CurlOpt.MAXFILESIZE_LARGE], resources.IMAGE_BYTES)

    async def test_invalid_ranges_mime_and_signature_only_binary_stay_rejected(self):
        payload = animation()
        cases = [self.response(b"GIF89a"), self.response(b"not a GIF"), self.response(payload, content_type="text/html"),
                 self.response(payload, **{"content-range": "bytes 10-20/100"}),
                 self.response(payload, **{"content-range": "bytes 0-4/*"}),
                 self.response(payload, **{"content-range": f"bytes 0-{len(payload) - 1}/{len(payload) - 1}"}),
                 self.response(payload, **{"content-length": "12"}),
                 self.response(payload, **{"content-encoding": "gzip"}),
                 self.response(payload, status=404)]
        for response in cases:
            with self.subTest(headers=response.headers), self.assertRaises(resources.PosterResourceError):
                await self.fetch(response)
        # The binary exception is not a generic image-sniffing fallback.
        with patch.object(resources, "preview_gif", new_callable=AsyncMock) as decoder, \
                self.assertRaisesRegex(resources.PosterResourceError, "^invalid_image$"):
            await self.fetch(self.response(payload, status=200), url="https://cdn.example.com/download.bin")
        decoder.assert_not_awaited()

    async def test_ignored_range_must_be_complete_and_within_the_same_byte_limit(self):
        result, _ = await self.fetch(self.response(animation(), status=200, content_type="image/gif"))
        self.assertFalse(result.preview["partial"])
        with self.assertRaises(resources.PosterResourceError):
            await self.fetch(self.response(animation()[:-6], status=200, content_type="image/gif"))
        with patch.object(resources, "IMAGE_BYTES", 32), self.assertRaisesRegex(resources.PosterResourceError, "image_too_large"):
            await self.fetch(self.response(b"x" * 33, status=200))

    async def test_redirect_bytes_share_budget_and_private_redirect_is_never_fetched(self):
        payload, seen = animation(), []
        redirect = self.response(b"redirect-body", status=302, location=GIF_URL + "?resolved=1")
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([redirect, self.response(payload)], seen)):
            result = await resources.fetch_poster_resource(GIF_URL, image=True)
        requests = [entry for entry in seen if "url" in entry]
        self.assertEqual(requests[1]["options"]["curl_options"][resources.CurlOpt.MAXFILESIZE_LARGE],
                         resources.IMAGE_BYTES - len(redirect.body))
        self.assertEqual(result.preview["transferBytes"], len(payload) + len(redirect.body))
        seen.clear()
        redirect.headers["location"] = "https://127.0.0.1/private.gif"
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([redirect], seen)), self.assertRaises(resources.PosterResourceError):
            await resources.fetch_poster_resource(GIF_URL, image=True)
        self.assertEqual(len([entry for entry in seen if "url" in entry]), 1)

    async def test_retry_cannot_reset_download_budget_or_reuse_partial_frames(self):
        payload, seen = animation(), []
        failed = self.response(payload[:100])
        failed.error = RequestException("private response", code=CurlECode.RECV_ERROR, response=SimpleNamespace(status_code=206))
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([failed, self.response(payload)], seen)):
            result = await resources.fetch_poster_resource(GIF_URL, image=True)
        requests = [entry for entry in seen if "url" in entry]
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["options"]["headers"]["Range"], f"bytes=0-{resources.IMAGE_BYTES - 101}")
        self.assertEqual(result.preview["downloadedBytes"], len(payload))
        self.assertEqual(result.preview["sourcePrefixSha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result.preview["transferBytes"], len(payload) + 100)

    async def test_one_candidate_still_uses_exactly_one_vision_review_and_cache(self):
        payload, seen = animation(), []
        html = f'<h1>{ORIGINAL}</h1><img src="{GIF_URL}">'.encode()

        async def fetch(url, *, image=False):
            return await resources.fetch_poster_resource(url, image=True) if image else resources.PosterResource(SOURCE, html, "text/html")

        model = model_with(tool("search_web", {"query": ORIGINAL + " gameplay"}), tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}), AIMessage(content='{"candidateId":"image-1"}'))
        review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        cache = AsyncMock(return_value=cached_image())
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}), fetch=fetch, review=review, cache=cache)
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([self.response(payload)], seen)):
            result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], SOURCE)
        self.assertEqual(result["posterTrace"][-1]["imageUrl"], GIF_URL)
        evidence = result["posterTrace"][-1]["imagePreview"]
        self.assertEqual((evidence["type"], evidence["frameIndex"], evidence["framesValidated"]), ("gif_frame", 2, 3))
        self.assertEqual(evidence["sourcePrefixSha256"], hashlib.sha256(payload).hexdigest())
        review.assert_awaited_once()
        cache.assert_awaited_once()
        self.assertTrue(review.await_args.args[0].startswith(b"\xff\xd8\xff"))
        self.assertEqual(review.await_args.args[0], cache.await_args.args[0])
        self.assertEqual(agent.counts["verify_image"], 1)
