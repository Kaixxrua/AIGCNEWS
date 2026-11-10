"""Search remains usable and cancellable after a server child-watcher failure."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.app.services.project_catalog import game_poster_resources as resources


class SearchWorkerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def worker(self, directory: str, code: str):
        root = Path(directory)
        (root / "game_poster_search.py").write_text(code)
        return patch.object(resources, "__file__", str(root / "game_poster_resources.py"))

    async def test_child_watcher_failure_still_searches_without_leaking_environment(self):
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

    async def blocked_worker(self, timeout: bool):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pid"
            code = "import os, time\nfrom pathlib import Path\nPath(" + repr(str(pidfile)) + ").write_text(str(os.getpid()))\ntime.sleep(60)\n"
            with self.worker(directory, code), \
                    patch.object(resources, "SEARCH_WORKER_SECONDS", 0.2 if timeout else 22), \
                    patch.object(resources.asyncio, "create_subprocess_exec", AsyncMock(side_effect=RuntimeError("child watcher failed"))):
                task = asyncio.create_task(resources.search_public_web("Diablo cover"))
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

    async def test_fallback_cancellation_kills_and_reaps_real_child(self):
        await self.blocked_worker(False)

    async def test_fallback_timeout_kills_and_reaps_real_child(self):
        await self.blocked_worker(True)

    async def test_fallback_bad_output_is_a_stable_nonsecret_failure(self):
        for output in ["not-json", json.dumps({"unavailable": True, "results": []})]:
            with tempfile.TemporaryDirectory() as directory, self.worker(directory, "print(" + repr(output) + ")"), \
                    patch.object(resources.asyncio, "create_subprocess_exec", AsyncMock(side_effect=RuntimeError("child watcher failed"))):
                with self.assertRaisesRegex(resources.PosterResourceError, "^search_unavailable$"):
                    await resources.search_public_web("Diablo cover")
