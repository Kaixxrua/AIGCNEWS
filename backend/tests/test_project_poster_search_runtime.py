"""Search remains usable and cancellable after a server child-watcher failure."""
from __future__ import annotations

import asyncio
import json
import os
import random
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image, PngImagePlugin

from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog import game_poster_resources as resources


class SearchWorkerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def worker(self, directory: str, code: str):
        root = Path(directory)
        (root / "game_poster_search.py").write_text(code)
        return patch.object(resources, "__file__", str(root / "game_poster_resources.py"))

    async def test_search_does_not_use_child_watchers_or_leak_environment(self):
        code = '''import json, os, sys
data = json.load(sys.stdin)
assert len(sys.argv) == 1
assert 'PORTSHELF_TEST_SECRET' not in os.environ
assert data['query'] == 'Diablo cover'
print(json.dumps({'engine': 'test', 'results': [{'title': data['query']}]}))
'''
        with tempfile.TemporaryDirectory() as directory, self.worker(directory, code), \
                patch.dict(os.environ, {"PORTSHELF_TEST_SECRET": "do-not-inherit"}), \
                patch.object(resources.asyncio, "create_subprocess_exec", AsyncMock(side_effect=RuntimeError("child watcher failed"))):
            result = await resources.search_public_web("Diablo cover")
        self.assertEqual(result["results"], [{"title": "Diablo cover"}])
        self.assertEqual(result["workerTransport"], "direct_child")

    async def blocked_worker(self, timeout: bool, artwork: bool = False):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pid"
            code = "import os, time\nfrom pathlib import Path\nPath(" + repr(str(pidfile)) + ").write_text(str(os.getpid()))\ntime.sleep(60)\n"
            with self.worker(directory, code), \
                    patch.object(resources, "SEARCH_WORKER_SECONDS", 0.2 if timeout else 22), \
                    patch.object(resources.asyncio, "create_subprocess_exec", AsyncMock(side_effect=RuntimeError("child watcher failed"))):
                search = resources.search_public_artwork if artwork else resources.search_public_web
                task = asyncio.create_task(search("A Game screenshot"))
                async with asyncio.timeout(3):
                    while not pidfile.exists():
                        await asyncio.sleep(0.01)
                pid = int(pidfile.read_text())
                if not timeout:
                    task.cancel()
                with self.assertRaises(resources.PosterResourceError if timeout else asyncio.CancelledError):
                    await asyncio.wait_for(task, 3)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    async def test_worker_cancellation_kills_and_reaps_real_child(self):
        await self.blocked_worker(False)

    async def test_worker_timeout_kills_and_reaps_real_child(self):
        await self.blocked_worker(True)

    async def test_artwork_worker_cancellation_and_timeout_keep_the_same_kill_boundary(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                await self.blocked_worker(timeout, artwork=True)

    async def test_worker_bad_output_is_a_stable_nonsecret_failure(self):
        for output in ["not-json", json.dumps({"unavailable": True, "results": []})]:
            with tempfile.TemporaryDirectory() as directory, self.worker(directory, "print(" + repr(output) + ")"), \
                    patch.object(resources.asyncio, "create_subprocess_exec", AsyncMock(side_effect=RuntimeError("child watcher failed"))):
                with self.assertRaisesRegex(resources.PosterResourceError, "^search_unavailable$"):
                    await resources.search_public_web("Diablo cover")

    async def test_repeated_parallel_searches_survive_a_failed_loop_process_watcher(self):
        code = "import json, sys\ndata=json.load(sys.stdin)\nprint(json.dumps({'results':[{'title':data['query']}]}))\n"
        with tempfile.TemporaryDirectory() as directory, self.worker(directory, code), \
                patch.object(resources.asyncio, "create_subprocess_exec", AsyncMock(side_effect=RuntimeError("unusable loop watcher"))), \
                patch.object(resources.asyncio, "to_thread", AsyncMock(side_effect=RuntimeError("unusable default executor"))):
            for batch in range(4):
                results = await asyncio.gather(*(resources.search_public_web(f"game {batch}-{i} cover") for i in range(4)))
                self.assertEqual([r["results"][0]["title"] for r in results], [f"game {batch}-{i} cover" for i in range(4)])

    async def test_worker_output_limit_kills_instead_of_reading_unbounded_data(self):
        code = "import sys, time\nsys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(60)\n"
        with tempfile.TemporaryDirectory() as directory, self.worker(directory, code):
            with self.assertRaisesRegex(resources.PosterResourceError, "search_output_too_large"):
                await asyncio.wait_for(resources.search_public_web("game cover"), 3)

    async def test_artwork_search_uses_images_except_for_explicit_game_database_query(self):
        cases = [
            ("A Game screenshots", ["bing_images", "yahoo"]),
            ("人生重开模拟器 游戏截图", ["bing_images", "yahoo"]),
            ("A Game cover site:gamesdb.launchbox-app.com", ["google", "yahoo"]),
            ("site:GAMESDB.LAUNCHBOX-APP.COM A Game", ["google", "yahoo"]),
            ("A Game site:gamesdb.launchbox-app.com.evil.example", ["bing_images", "yahoo"]),
        ]
        worker = AsyncMock(return_value=json.dumps({"results": []}).encode())
        with patch.object(resources, "_search_worker", worker):
            for query, engines in cases:
                with self.subTest(query=query):
                    await resources.search_public_artwork(query)
                    self.assertEqual(json.loads(worker.await_args.args[0])["engines"], engines)
            await resources.search_public_web("A Game screenshots")
            self.assertEqual(json.loads(worker.await_args.args[0])["engines"], ["google", "yahoo"])

    async def test_parent_validates_source_and_image_as_one_pair_and_strips_extra_fields(self):
        source, image = "https://games.example/game", "https://cdn.example/game.png"
        rows = [
            {"url": source + "#top", "imageUrl": image + "#full", "title": "A" * 400, "snippet": "B" * 700, "private": "do-not-trust"},
            {"url": source, "imageUrl": "https://127.0.0.1/private.png"},
            {"url": "https://user:password@games.example/game", "imageUrl": image},
            {"url": source, "imageUrl": "https://cdn.example/%252e%252e/private"},
            {"url": "https://private.local/game", "imageUrl": image},
            {"url": source, "imageUrl": "https://cdn.example/second.png"},
        ]
        result = {"engine": "bing_images", "results": rows, "attempts": [
            {"engine": "bing_images", "status": "succeeded", "resultCount": 6, "elapsedMs": 900,
             "errorMessage": "private-provider-response"},
        ]}
        with patch.object(resources, "_search_worker", AsyncMock(return_value=json.dumps(result).encode())):
            data = await resources.search_public_artwork("A Game screenshots")
        self.assertEqual(data["results"], [
            {"url": source, "imageUrl": image, "title": "A" * 300, "snippet": "B" * 600},
            {"url": source, "imageUrl": "https://cdn.example/second.png", "title": "", "snippet": ""},
        ])
        self.assertEqual(data["attempts"], [{"engine": "bing_images", "status": "succeeded", "resultCount": 6, "elapsedMs": 900}])
        self.assertNotIn("private-provider", json.dumps(data))
        self.assertNotIn("do-not-trust", json.dumps(data))


class PosterImageTransportLimitsTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def public(url, **kwargs):
        return pin_http_target(url, resolver=lambda _: ["93.184.216.34"], **kwargs)

    def session(self, *, chunks=(), error=None, response=None, seen=None, block=None):
        class Session:
            def __init__(self, **kwargs):
                self.options = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                if seen is not None:
                    seen.append("closed")

            async def get(self, url, *, allow_redirects, timeout, content_callback):
                assert not allow_redirects and timeout <= 12
                assert self.options["verify"] is True
                assert self.options["curl_options"][resources.CurlOpt.MAXFILESIZE_LARGE] == resources.IMAGE_BYTES
                target = resources.ffi.string(self.options["curl_options"][resources.CurlOpt.CONNECT_TO].data).decode()
                if seen is not None:
                    seen.append((url, target))
                if block is not None:
                    block.set()
                    await asyncio.Event().wait()
                if error is not None:
                    raise error
                for chunk in chunks:
                    if content_callback(chunk) == resources.CURL_WRITEFUNC_ERROR:
                        raise RuntimeError("transport-body-with-private-details")
                return response or SimpleNamespace(status_code=200, headers={"content-type": "image/png"})
        return Session

    async def test_chunked_body_limit_accepts_exact_boundary_and_reports_oversize(self):
        for chunks, allowed in [([b"x" * 4, b"y" * 4], True), ([b"x" * 4, b"y" * 5], False)]:
            with self.subTest(allowed=allowed), patch.object(resources, "IMAGE_BYTES", 8), \
                    patch.object(resources, "pin_http_target", self.public), \
                    patch.object(resources, "AsyncSession", self.session(chunks=chunks)):
                if allowed:
                    resource = await resources.fetch_poster_resource("https://cdn.example/full.png", image=True)
                    self.assertEqual(resource.body, b"xxxxyyyy")
                else:
                    with self.assertRaisesRegex(resources.PosterResourceError, "^image_too_large$"):
                        await resources.fetch_poster_resource("https://cdn.example/full.png", image=True)

    async def test_content_length_limit_is_not_misreported_as_network_failure(self):
        error = RuntimeError("private-response-and-proxy-credentials")
        error.code = resources.CurlECode.FILESIZE_EXCEEDED
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session(error=error)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^image_too_large$") as raised:
                await resources.fetch_poster_resource("https://cdn.example/full.png", image=True)
        self.assertIsNone(raised.exception.__cause__)

    async def test_image_redirect_rejects_private_target_and_mixed_dns_before_connect(self):
        seen = []
        response = SimpleNamespace(status_code=302, headers={"location": "https://127.0.0.1/private.png"})
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session(response=response, seen=seen)):
            with self.assertRaises(resources.PosterResourceError):
                await resources.fetch_poster_resource("https://cdn.example/full.png", image=True)
        self.assertEqual(seen, [("https://cdn.example/full.png", "cdn.example:443:93.184.216.34:443"), "closed"])

        def mixed(url, **kwargs):
            return pin_http_target(url, resolver=lambda _: ["93.184.216.34", "127.0.0.1"], **kwargs)
        with patch.object(resources, "pin_http_target", mixed), patch.object(resources, "AsyncSession") as session:
            with self.assertRaises(resources.PosterResourceError):
                await resources.fetch_poster_resource("https://cdn.example/full.png", image=True)
        session.assert_not_called()

    async def test_image_download_cancellation_closes_session_without_becoming_network_error(self):
        entered, seen = asyncio.Event(), []
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session(block=entered, seen=seen)):
            task = asyncio.create_task(resources.fetch_poster_resource("https://cdn.example/full.png", image=True))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        self.assertEqual(seen[-1], "closed")

    def test_real_raster_between_four_and_eight_megabytes_is_cleaned_with_existing_output_limits(self):
        source = Image.frombytes("RGB", (1800, 1300), random.Random(42).randbytes(1800 * 1300 * 3))
        output = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("untrusted", "discard-this-source-metadata")
        source.save(output, format="PNG", pnginfo=metadata)
        payload = output.getvalue()
        self.assertGreater(len(payload), 4 * 1024 * 1024)
        self.assertLess(len(payload), resources.IMAGE_BYTES)
        self.assertEqual(resources.IMAGE_BYTES, 8 * 1024 * 1024)
        self.assertEqual(resources.IMAGE_PIXELS, 16_000_000)
        jpeg, width, height = resources.clean_poster_jpeg(payload)
        self.assertLessEqual(max(width, height), 1200)
        self.assertLess(len(jpeg), 1024 * 1024)
        with Image.open(BytesIO(jpeg)) as clean:
            self.assertEqual(clean.format, "JPEG")
            self.assertNotIn("untrusted", clean.info)
            self.assertNotIn("exif", clean.info)
        with self.assertRaisesRegex(resources.PosterResourceError, "^image_too_large$"):
            resources.clean_poster_jpeg(b"x" * (resources.IMAGE_BYTES + 1))

    def test_pixel_budget_is_not_relaxed_for_compressed_images(self):
        output = BytesIO()
        Image.new("RGB", (4001, 4000), "red").save(output, format="PNG")
        with self.assertRaisesRegex(resources.PosterResourceError, "^invalid_image$"):
            resources.clean_poster_jpeg(output.getvalue())
