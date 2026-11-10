from __future__ import annotations

import asyncio
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from PIL import GifImagePlugin, Image, ImageDraw

from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog import game_poster_resources as resources


def gif_bytes(*, size=(256, 256), animated=True):
    first = Image.new("RGB", size, "red")
    ImageDraw.Draw(first).rectangle((0, 0, size[0] // 4, size[1] // 2), fill="yellow")
    output = BytesIO()
    first.save(output, format="GIF", save_all=animated,
               append_images=[Image.new("RGB", size, "blue")] if animated else [],
               duration=100, loop=0, comment=b"untrusted-source-metadata")
    return output.getvalue()


class GifPosterDecodeTests(unittest.TestCase):
    def test_preview_is_static_and_animation_metadata_is_removed(self):
        jpeg, width, height = resources.clean_poster_jpeg(gif_bytes())
        self.assertEqual((width, height), (256, 256))
        with Image.open(BytesIO(jpeg)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertFalse(getattr(image, "is_animated", False))
            red, green, blue = image.getpixel((128, 128))
            self.assertGreater(red, 240)
            self.assertLess(max(green, blue), 15)
            for key in ("comment", "duration", "loop", "transparency", "exif"):
                self.assertNotIn(key, image.info)

    def test_static_gif_keeps_the_existing_thumbnail_bound(self):
        jpeg, width, height = resources.clean_poster_jpeg(gif_bytes(size=(1800, 2400), animated=False))
        self.assertEqual((width, height), (900, 1200))
        self.assertLess(len(jpeg), resources.IMAGE_BYTES)

    def test_small_corrupt_svg_and_html_inputs_still_fail(self):
        for payload in (gif_bytes(size=(159, 256)), gif_bytes()[:40], b"<svg></svg>", b"<html>not an image</html>"):
            with self.subTest(prefix=payload[:10]), self.assertRaisesRegex(resources.PosterResourceError, "^invalid_image$"):
                resources.clean_poster_jpeg(payload)

    def test_byte_and_logical_canvas_limits_apply_before_frame_decode(self):
        payload = gif_bytes()
        self.assertEqual(resources.IMAGE_BYTES, 8 * 1024 * 1024)
        self.assertEqual(resources.IMAGE_PIXELS, 16_000_000)
        with self.assertRaisesRegex(resources.PosterResourceError, "^image_too_large$"):
            resources.clean_poster_jpeg(payload + b"x" * (resources.IMAGE_BYTES + 1 - len(payload)))
        # A tiny compressed frame can claim a much larger logical GIF canvas.
        # Reject that canvas before load() allocates a decompressed raster.
        oversized = bytearray(payload)
        oversized[6:10] = (5000).to_bytes(2, "little") * 2
        with patch.object(GifImagePlugin.GifImageFile, "load", side_effect=AssertionError("must_not_decode")) as decode, \
                self.assertRaisesRegex(resources.PosterResourceError, "^invalid_image$"):
            resources.clean_poster_jpeg(bytes(oversized))
        decode.assert_not_called()


class GifPosterTransportTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def public(url, **kwargs):
        return pin_http_target(url, resolver=lambda _: ["93.184.216.34"], **kwargs)

    def session(self, response, *, seen, entered=None):
        class Session:
            def __init__(self, **kwargs):
                self.options = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                seen.append("closed")

            async def get(self, url, *, allow_redirects, timeout, content_callback):
                assert not allow_redirects and 0 < timeout <= resources.IMAGE_REQUEST_SECONDS
                assert self.options["verify"] is True
                assert "image/gif" in self.options["headers"]["Accept"]
                assert self.options["curl_options"][resources.CurlOpt.MAXFILESIZE_LARGE] == resources.IMAGE_BYTES
                pin = resources.ffi.string(self.options["curl_options"][resources.CurlOpt.CONNECT_TO].data).decode()
                seen.append((url, pin))
                if entered is not None:
                    entered.set()
                    await asyncio.Event().wait()
                if content_callback(response.content) == resources.CURL_WRITEFUNC_ERROR:
                    raise RuntimeError("bounded-body-aborted")
                return response
        return Session

    async def test_gif_http_body_is_accepted_but_html_svg_and_stale_404_are_rejected(self):
        for status, content_type, body, allowed in [
            (200, "image/gif", gif_bytes(), True),
            (200, "image/svg+xml", b"<svg/>", False),
            (200, "text/html", b"<html/>", False),
            (404, "text/html", b"<html>missing image</html>", False),
            (404, "image/gif", gif_bytes(), False),
        ]:
            response = SimpleNamespace(status_code=status, headers={"content-type": content_type}, content=body)
            seen = []
            with self.subTest(status=status, content_type=content_type), patch.object(resources, "pin_http_target", self.public), \
                    patch.object(resources, "AsyncSession", self.session(response, seen=seen)):
                if allowed:
                    result = await resources.fetch_poster_resource("https://games.example/animation.gif", image=True)
                    self.assertEqual(result.content_type, "image/jpeg")
                    self.assertTrue(result.body.startswith(b"\xff\xd8\xff"))
                    self.assertEqual(result.preview["type"], "gif_frame")
                else:
                    with self.assertRaisesRegex(resources.PosterResourceError, "^invalid_image$"):
                        await resources.fetch_poster_resource("https://games.example/animation.gif", image=True)
            self.assertEqual(seen, [("https://games.example/animation.gif", "games.example:443:93.184.216.34:443"), "closed"])

    async def test_gif_redirect_and_mixed_dns_keep_the_same_private_network_boundary(self):
        response = SimpleNamespace(status_code=302, headers={"location": "https://127.0.0.1/private.gif"}, content=b"")
        seen = []
        with patch.object(resources, "pin_http_target", self.public), patch.object(resources, "AsyncSession", self.session(response, seen=seen)):
            with self.assertRaises(resources.PosterResourceError):
                await resources.fetch_poster_resource("https://games.example/animation.gif", image=True)
        self.assertEqual(len([entry for entry in seen if isinstance(entry, tuple)]), 1)

        def mixed(url, **kwargs):
            return pin_http_target(url, resolver=lambda _: ["93.184.216.34", "127.0.0.1"], **kwargs)
        with patch.object(resources, "pin_http_target", mixed), patch.object(resources, "AsyncSession") as session:
            with self.assertRaises(resources.PosterResourceError):
                await resources.fetch_poster_resource("https://games.example/animation.gif", image=True)
        session.assert_not_called()

    async def test_gif_download_cancellation_is_preserved_and_closes_the_connection(self):
        entered, seen = asyncio.Event(), []
        response = SimpleNamespace(status_code=200, headers={"content-type": "image/gif"}, content=b"")
        with patch.object(resources, "pin_http_target", self.public), patch.object(resources, "AsyncSession", self.session(response, seen=seen, entered=entered)):
            task = asyncio.create_task(resources.fetch_poster_resource("https://games.example/animation.gif", image=True))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        self.assertEqual(seen[-1], "closed")


if __name__ == "__main__":
    unittest.main()
