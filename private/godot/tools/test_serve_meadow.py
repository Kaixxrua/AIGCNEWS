import gzip
from contextlib import closing
from functools import partial
import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from serve_meadow import MeadowHandler


class QuietHandler(MeadowHandler):
    def log_message(self, *args):
        pass


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="meadow-http-test-")
        cls.root = Path(cls.temp.name)
        (cls.root / "v58").mkdir()
        cls.payload = b"\0asm" + b"test fixture" * 200
        (cls.root / "v58/index.wasm").write_bytes(cls.payload)
        (cls.root / "v58/index.wasm.gz").write_bytes(gzip.compress(cls.payload, mtime=0))
        (cls.root / "v58/private.log").write_text("not served")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path="/v58/index.wasm", method="GET", headers=None):
        with closing(http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)) as connection:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_gzip_and_mime(self):
        status, headers, body = self.request(headers={"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-type"], "application/wasm")
        self.assertEqual(headers["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(body), self.payload)

    def test_raw_and_q_zero(self):
        for headers in ({}, {"Accept-Encoding": "gzip;q=0"}):
            status, response, body = self.request(headers=headers)
            self.assertEqual(status, 200)
            self.assertNotIn("Content-Encoding", response)
            self.assertEqual(body, self.payload)

    def test_head(self):
        status, headers, body = self.request(method="HEAD", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_etag(self):
        _, first, _ = self.request()
        status, headers, body = self.request(headers={"If-None-Match": first["ETag"]})
        self.assertEqual(status, 304)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Vary"], "Accept-Encoding")

    def test_exports_only(self):
        for path in ("/", "/v58/", "/v58/private.log", "/v58/../AGENTS.md", "/v58/%2e%2e/private.js", "/v58/source/index.html"):
            self.assertEqual(self.request(path)[0], 404)


if __name__ == "__main__":
    unittest.main()
