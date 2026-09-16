"""Lossless transport contracts. Temporary fixtures + ephemeral loopback only."""
from contextlib import contextmanager
from functools import partial
import gzip
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

import prepare_web_build as build
from serve_meadow import MeadowHandler


class QuietHandler(MeadowHandler):
    def log_message(self, *_args):
        pass


class QualityCatalogTests(unittest.TestCase):
    """Pure manifest/shell checks; no artifact preparation or HTTP service."""
    shell = ('<script src="index.js"></script>'
             '<script src="meadow-quality.js"></script>'
             '<link rel="stylesheet" href="./meadow-controls.css?v=old">'
             '<!-- <script src="unused.js"></script> -->'
             '<script>window.meadowQuality.mount({executable:"index",args:["--seed=3"]});</script>')

    def manifest(self, html, name="MEADOW_QUALITY"):
        return json.loads(re.search(r"window\." + name + r" = (.*?);\n", html)[1])

    def records(self, *extra_packs):
        names = ("index.pck", "index.wasm", "index.js", "meadow-quality.js", "meadow-controls.css", "unused.js", *extra_packs)
        return {name: {"bytes": 10_000 + index, "gzipBytes": 1_000 + index,
                       "sha256": "a" * 64, "immutableUrl": name + ".immutable"}
                for index, name in enumerate(names)}

    def test_catalog_only_advertises_prepared_original_balanced_and_lite(self):
        for extras in ((), ("index-balanced.pck",), ("index-lite.pck",), ("index-balanced.pck", "index-lite.pck")):
            with self.subTest(extras=extras):
                records = self.records(*extras)
                before = json.dumps(records, sort_keys=True)
                html = build.quality_html(self.shell, records)
                choices = self.manifest(html)
                self.assertEqual({choice["pack"] for choice in choices.values()}, {"index.pck", *extras})
                for mode, name in (("original", "index.pck"), ("balanced", "index-balanced.pck"), ("lite", "index-lite.pck")):
                    self.assertEqual(mode in choices, name in records)
                    if name in records:
                        self.assertEqual(choices[mode], {"pack": name, "bytes": records[name]["bytes"],
                                                         "gzipBytes": records[name]["gzipBytes"]})
                self.assertEqual(json.dumps(records, sort_keys=True), before)
                self.assertIn('mount({executable:"index",args:["--seed=3"]})', html)
                self.assertNotIn("preload", html)
                self.assertEqual(build.quality_html(html, records), html)

    def test_shared_metadata_counts_one_wasm_and_only_referenced_interface_assets(self):
        records = self.records("index-balanced.pck", "index-lite.pck")
        html = build.quality_html(self.shell, records)
        shared = self.manifest(html, "MEADOW_QUALITY_SHARED")
        self.assertEqual(set(shared), {"index.wasm", "index.js", "meadow-quality.js", "meadow-controls.css"})
        for name, record in shared.items():
            self.assertEqual(record, {"bytes": records[name]["bytes"], "gzipBytes": records[name]["gzipBytes"]})
        self.assertEqual(html.count(build.QUALITY_BEGIN), 1)
        self.assertLess(html.index("window.MEADOW_QUALITY_SHARED = "), html.index("window.meadowQuality.mount("))

    def test_replacement_drops_missing_modes_and_stale_codec_metadata(self):
        records = self.records("index-balanced.pck", "index-lite.pck")
        for record in records.values():
            record["brotliBytes"] = 800
        first = build.quality_html(self.shell, records)
        self.assertEqual(self.manifest(first)["lite"]["brBytes"], 800)
        self.assertEqual(self.manifest(first, "MEADOW_QUALITY_SHARED")["index.wasm"]["brBytes"], 800)
        revised = build.quality_html(first, self.records())
        self.assertEqual(set(self.manifest(revised)), {"original"})
        self.assertNotIn("index-lite", revised)
        self.assertNotIn("index-balanced", revised)
        self.assertNotIn("brBytes", revised)
        self.assertEqual(revised.count(build.QUALITY_BEGIN), 1)
        self.assertEqual(revised.count("window.MEADOW_QUALITY_SHARED = "), 1)

    def test_legacy_shell_is_unchanged_even_with_all_three_packs(self):
        shell = '<script>window.meadowTimeUI.start({executable:"index"});</script>'
        self.assertEqual(build.quality_html(shell, self.records("index-balanced.pck", "index-lite.pck")), shell)

    def test_ambiguous_mount_or_markers_are_rejected(self):
        for shell in (self.shell + self.shell, self.shell + build.QUALITY_BEGIN,
                      self.shell + build.QUALITY_BEGIN + build.QUALITY_END):
            with self.subTest(shell=shell), self.assertRaises(ValueError):
                build.quality_html(shell, self.records())


@contextmanager
def preview(directory):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive(), "Temporary HTTP server did not stop"


class WebTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "v123"
        self.directory.mkdir()
        self.loader_source = self.root / "loader-source.js"
        self.helper_sources = {"meadow-loader.js": self.loader_source,
            "meadow-controls.js": self.root / "controls-source.js",
            "meadow-quality.js": self.root / "quality-source.js"}
        source_patch = patch.object(build, "HELPER_SOURCES", self.helper_sources)
        source_patch.start()
        self.addCleanup(source_patch.stop)
        self.payloads = {name: (name.encode() + b"\x00lossless data\xff" * 500) for name in build.PAYLOADS}
        for name, data in self.payloads.items():
            (self.directory / name).write_bytes(data)
        (self.directory / "index.html").write_text(
            '<script src="index.js"></script><script src="meadow-controls.js"></script>'
            '<link href="meadow-controls.css">', encoding="utf-8")
        self.port = None

    def request(self, path="index.wasm", encoding="identity", method="GET", headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            values = {} if encoding is None else {"Accept-Encoding": encoding}
            values.update(headers or {})
            connection.request(method, "/v123/" + path, headers=values)
            response = connection.getresponse()
            return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
        finally:
            connection.close()

    def test_prepare_deterministic_lossless_and_opt_in(self):
        first = build.prepare(self.directory, immutable=True)
        encoded = (self.directory / "index.wasm.gz").read_bytes()
        self.assertEqual(first, build.prepare(self.directory, immutable=True))
        self.assertEqual(encoded, (self.directory / "index.wasm.gz").read_bytes())
        for name, raw in self.payloads.items():
            self.assertEqual((self.directory / name).read_bytes(), raw)
            self.assertEqual(gzip.decompress((self.directory / (name + ".gz")).read_bytes()), raw)
            record = first[name]
            self.assertIn(hashlib.sha256(raw).hexdigest(), record["immutableUrl"])
            self.assertEqual((self.directory / record["immutableUrl"]).read_bytes(), raw)
        html = (self.directory / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="index.js"', html)
        self.assertIn("meadow-controls.js?v=", html)
        self.assertNotIn(first["index.wasm"]["immutableUrl"], html)
        self.assertEqual(json.loads((self.directory / "web-payload.json").read_text()), first)

    def test_optional_brotli_missing_or_failed_falls_back(self):
        for module in (None, unittest.mock.Mock(Compressor=unittest.mock.Mock(side_effect=RuntimeError("codec failed")))):
            with self.subTest(module=module), patch.object(build, "brotli_module", return_value=module):
                with self.assertWarns(RuntimeWarning):
                    records = build.prepare(self.directory, brotli=True)
            for record in records.values():
                self.assertEqual(set(record["encodings"]), {"gzip"})
                self.assertNotIn("brotliBytes", record)

    def test_new_loader_copied_and_versioned_without_config_rewrite(self):
        name = "meadow-loader.js"
        raw = b"window.MeadowLoader = {fixture: true};\n" * 100
        self.loader_source.write_bytes(raw)
        html_path = self.directory / "index.html"
        # Finish the pre-existing control-query rewrite before testing new wiring.
        build.prepare(self.directory)
        html = html_path.read_text(encoding="utf-8") + (
            '<script src="meadow-loader.js"></script>'
            '<script>const config={executable:"index",mainPack:"index.pck"};</script>')
        html_path.write_text(html, encoding="utf-8")
        codec = build.brotli_module()
        records = build.prepare(self.directory, brotli=codec is not None, immutable=True)
        self.assertEqual(set(records), set(build.PAYLOADS) | {name})
        expected = html.replace('src="meadow-loader.js"', 'src="meadow-loader.js?v=' + records[name]["sha256"] + '"')
        self.assertEqual(html_path.read_text(encoding="utf-8"), expected)
        self.assertEqual((self.directory / name).read_bytes(), raw)
        self.assertEqual(gzip.decompress((self.directory / (name + ".gz")).read_bytes()), raw)
        if codec is not None:
            self.assertEqual(codec.decompress((self.directory / (name + ".br")).read_bytes()), raw)
        with preview(self.root) as self.port:
            for filename, record in records.items():
                status, headers, body = self.request(record["immutableUrl"], "gzip")
                self.assertEqual(status, 200)
                self.assertIn("immutable", headers["cache-control"])
                self.assertEqual(hashlib.sha256(gzip.decompress(body)).hexdigest(), record["sha256"])
                legacy = self.request(filename)[1]
                self.assertIn("must-revalidate", legacy["cache-control"])
                self.assertNotIn("immutable", legacy["cache-control"])
                query = self.request(filename + "?v=" + record["sha256"])
                self.assertEqual(query[0], 200)
                self.assertNotIn("immutable", query[1]["cache-control"])

    def test_dual_packs_independent_lossless_no_preload_insertion(self):
        balanced = b"balanced pack distinct bytes\x00" * 120
        (self.directory / "index-balanced.pck").write_bytes(balanced)
        self.loader_source.write_bytes(b"// fixture loader v1\n")
        html_path = self.directory / "index.html"
        html_path.write_text('<link rel="preload" href="index.wasm" as="fetch">'
            '<script src="meadow-loader.js"></script>', encoding="utf-8")
        codec = build.brotli_module()
        records = build.prepare(self.directory, brotli=codec is not None, immutable=True)
        self.assertEqual(set(records), set(build.PAYLOADS) | {"meadow-loader.js", "index-balanced.pck"})
        self.assertEqual([name for name in records if name.endswith(".wasm")], ["index.wasm"])
        self.assertNotEqual(records["index.pck"]["immutableUrl"], records["index-balanced.pck"]["immutableUrl"])
        with preview(self.root) as self.port:
            for name, data in (("index.pck", self.payloads["index.pck"]), ("index-balanced.pck", balanced)):
                record = records[name]
                self.assertEqual(record["bytes"], len(data))
                self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
                status, headers, body = self.request(record["immutableUrl"], "gzip")
                self.assertEqual((status, headers["content-type"]), (200, "application/octet-stream"))
                self.assertEqual(gzip.decompress(body), data)
                if codec is not None:
                    status, headers, body = self.request(name, "br")
                    self.assertEqual((status, headers["content-encoding"]), (200, "br"))
                    self.assertEqual(codec.decompress(body), data)
        html = html_path.read_text(encoding="utf-8")
        self.assertIn('href="index.wasm"', html)
        self.assertNotIn(".pck", html)
        # A new helper revision replaces only the mutable alias; old hash copy remains.
        old = records["meadow-loader.js"]
        self.loader_source.write_bytes(b"// fixture loader v2\n")
        updated = build.prepare(self.directory, immutable=True)
        self.assertNotEqual(old["sha256"], updated["meadow-loader.js"]["sha256"])
        self.assertEqual((self.directory / old["immutableUrl"]).read_bytes(), b"// fixture loader v1\n")
        self.assertIn(updated["meadow-loader.js"]["sha256"], html_path.read_text(encoding="utf-8"))

    def test_three_helpers_and_quality_manifest_before_mount(self):
        for name, path in self.helper_sources.items():
            path.write_bytes(("// copied " + name + "\n").encode())
        (self.directory / "index-balanced.pck").write_bytes(b"balanced bytes" * 55)
        (self.directory / "index-lite.pck").write_bytes(b"complete scene lite bytes" * 20)
        html_path = self.directory / "index.html"
        shell = '<link rel="stylesheet" href="meadow-controls.css"><script src="index.js"></script>'
        shell += ''.join('<script src="' + name + '"></script>' for name in self.helper_sources)
        shell += '<script>window.meadowQuality.mount({executable:"index",fileSizes:{}});</script>'
        html_path.write_text(shell, encoding="utf-8")
        codec = build.brotli_module()
        records = build.prepare(self.directory, brotli=codec is not None, immutable=True)
        html = html_path.read_text(encoding="utf-8")
        self.assertEqual(html.count(build.QUALITY_BEGIN), 1)
        self.assertLess(html.index(build.QUALITY_END), html.index("window.meadowQuality.mount("))
        encoded = html.split("window.MEADOW_QUALITY = ", 1)[1].split(";\n" + build.QUALITY_END, 1)[0]
        choices = json.loads(encoded)
        self.assertEqual(set(choices), {"original", "balanced", "lite"})
        for quality, name in (("original", "index.pck"), ("balanced", "index-balanced.pck"), ("lite", "index-lite.pck")):
            choice = choices[quality]
            self.assertEqual(choice["pack"], name)
            self.assertEqual(choice["bytes"], records[name]["bytes"])
            self.assertEqual(choice["gzipBytes"], records[name]["gzipBytes"])
            self.assertEqual(choice.get("brBytes"), records[name].get("brotliBytes"))
            self.assertIn(records[name]["sha256"], records[name]["immutableUrl"])
            self.assertEqual((self.directory / records[name]["immutableUrl"]).read_bytes(),
                             (self.directory / name).read_bytes())
        shared = json.loads(html.split("window.MEADOW_QUALITY_SHARED = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(set(shared), {"index.wasm", "index.js", "meadow-controls.css"} | set(self.helper_sources))
        self.assertEqual([name for name in shared if name.endswith(".wasm")], ["index.wasm"])
        for name, record in shared.items():
            self.assertEqual(record["bytes"], records[name]["bytes"])
            self.assertEqual(record["gzipBytes"], records[name]["gzipBytes"])
            self.assertEqual(record.get("brBytes"), records[name].get("brotliBytes"))
        for name, source in self.helper_sources.items():
            self.assertEqual((self.directory / name).read_bytes(), source.read_bytes())
            digest = records[name]["sha256"][:16] if name == "meadow-controls.js" else records[name]["sha256"]
            self.assertIn(name + "?v=" + digest, html)
            self.assertEqual(gzip.decompress((self.directory / (name + ".gz")).read_bytes()), source.read_bytes())
            if codec is not None:
                self.assertEqual(codec.decompress((self.directory / (name + ".br")).read_bytes()), source.read_bytes())
        self.assertNotIn("preload", html)
        self.assertIn('mount({executable:"index",fileSizes:{}})', html)
        build.prepare(self.directory, brotli=codec is not None, immutable=True)
        self.assertEqual(html, html_path.read_text(encoding="utf-8"))
        # A stale immutable copy or compression sibling cannot advertise lite.
        old_lite = records["index-lite.pck"]["immutableUrl"]
        (self.directory / "index-lite.pck").unlink()
        revised_records = build.prepare(self.directory, immutable=True)
        revised = html_path.read_text(encoding="utf-8")
        choices = json.loads(revised.split("window.MEADOW_QUALITY = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(set(choices), {"original", "balanced"})
        self.assertNotIn("index-lite.pck", revised_records)
        self.assertNotIn("index-lite", revised)
        self.assertTrue((self.directory / old_lite).is_file())
        self.assertTrue((self.directory / "index-lite.pck.gz").is_file())
        # Revisions replace the block; absent qualities/codecs are not advertised.
        (self.directory / "index-balanced.pck").unlink()
        with patch.object(build, "brotli_module", return_value=None), self.assertWarns(RuntimeWarning):
            build.prepare(self.directory, brotli=True)
        revised = html_path.read_text(encoding="utf-8")
        self.assertEqual(revised.count(build.QUALITY_BEGIN), 1)
        encoded = revised.split("window.MEADOW_QUALITY = ", 1)[1].split(";\n" + build.QUALITY_END, 1)[0]
        choices = json.loads(encoded)
        self.assertEqual(set(choices), {"original"})
        self.assertNotIn("brBytes", choices["original"])
        self.assertNotIn("brBytes", revised)
        self.assertEqual(revised.count("window.MEADOW_QUALITY_SHARED = "), 1)

    def test_lite_revisions_preserve_old_immutable_files_without_preloading(self):
        lite = self.directory / "index-lite.pck"
        original = b"complete scene lite revision one" * 20
        lite.write_bytes(original)
        first = build.prepare(self.directory, immutable=True)
        before_html = (self.directory / "index.html").read_text(encoding="utf-8")
        old = first["index-lite.pck"]
        self.assertEqual(gzip.decompress((self.directory / (old["immutableUrl"] + ".gz")).read_bytes()), original)
        replacement = b"complete scene lite revision two" * 22
        lite.write_bytes(replacement)
        second = build.prepare(self.directory, immutable=True)
        new = second["index-lite.pck"]
        self.assertNotEqual(new["immutableUrl"], old["immutableUrl"])
        self.assertEqual((self.directory / old["immutableUrl"]).read_bytes(), original)
        self.assertEqual((self.directory / new["immutableUrl"]).read_bytes(), replacement)
        self.assertEqual(gzip.decompress((self.directory / (new["immutableUrl"] + ".gz")).read_bytes()), replacement)
        self.assertEqual(first["index.wasm"], second["index.wasm"])
        self.assertEqual(before_html, (self.directory / "index.html").read_text(encoding="utf-8"))
        self.assertNotIn("MEADOW_QUALITY", before_html)
        self.assertNotIn(".pck", before_html)

    def test_old_export_without_loader_and_missing_referenced_loader(self):
        self.assertNotIn("meadow-loader.js", build.prepare(self.directory))
        html = self.directory / "index.html"
        html.write_text('<script src="./meadow-loader.js?v=123"></script>', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing export helper"):
            build.prepare(self.directory)

    def test_legacy_shell_keeps_existing_controls_despite_new_helper_sources(self):
        old_controls = b"window.meadowTimeUI={start:function(){return 'legacy';}};\n"
        controls = self.directory / "meadow-controls.js"
        controls.write_bytes(old_controls)
        for name, source in self.helper_sources.items():
            source.write_bytes(b"// newer helper depends on meadowLoader: " + name.encode())
        html_path = self.directory / "index.html"
        html_path.write_text('<script src="meadow-controls.js"></script>'
            '<!-- future: <script src="meadow-loader.js"></script> -->'
            '<script>window.meadowTimeUI.start({executable:"index"});</script>', encoding="utf-8")
        for _ in range(2):
            records = build.prepare(self.directory)
            self.assertEqual(controls.read_bytes(), old_controls)
            self.assertEqual(gzip.decompress((self.directory / "meadow-controls.js.gz").read_bytes()), old_controls)
            self.assertEqual(records["meadow-controls.js"]["sha256"], hashlib.sha256(old_controls).hexdigest())
            for name in ("meadow-loader.js", "meadow-quality.js"):
                self.assertNotIn(name, records)
                self.assertFalse((self.directory / name).exists())
            html = html_path.read_text(encoding="utf-8")
            self.assertEqual(build.HelperReferences(html).names, {"meadow-controls.js"})
            self.assertIn('window.meadowTimeUI.start({executable:"index"})', html)
            self.assertNotIn("MEADOW_QUALITY", html)

    def test_real_brotli_negotiation_and_head(self):
        codec = build.brotli_module()
        if codec is None:
            self.skipTest("Optional Brotli not installed; missing-codec fallback tested separately")
        records = build.prepare(self.directory, brotli=True, immutable=True)
        with preview(self.root) as self.port:
            cases = [("br, gzip", "br"), ("gzip;q=1, br;q=0.5", "gzip"),
                     ("br;q=0, *;q=1", "gzip"), ("GZIP;q=0.500, BR;q=0.800", "br"),
                     ("br;q=0, gzip;q=0", None), ("br;q=bogus,gzip;q=1", "gzip"),
                     ("br;q=1.1,gzip;q=0", None), ("identity;q=1,br;q=0.5", None),
                     ("identity;q=0,br;q=0.5", "br"), ("*;q=0,br;q=1", "br")]
            for accepted, expected in cases:
                with self.subTest(accepted=accepted):
                    status, headers, body = self.request(encoding=accepted)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers.get("content-encoding"), expected)
                    decoded = codec.decompress(body) if expected == "br" else gzip.decompress(body) if expected == "gzip" else body
                    self.assertEqual(decoded, self.payloads["index.wasm"])
            for encoding in ("identity", "gzip", "br"):
                status, headers, body = self.request(encoding=encoding)
                head_status, head_headers, head_body = self.request(encoding=encoding, method="HEAD")
                self.assertEqual((head_status, head_body), (200, b""))
                for key in ("content-length", "content-type", "etag", "vary", "cache-control"):
                    self.assertEqual(headers[key], head_headers[key])
                self.assertEqual(int(headers["content-length"]), len(body))
                self.assertEqual(headers["content-type"], "application/wasm")
            self.assertEqual(self.request(encoding="*;q=0")[0], 406)
            self.assertEqual(self.request(encoding="br;q=0,gzip;q=0,identity;q=0")[0], 406)
            url = records["index.pck"]["immutableUrl"]
            self.assertIn("immutable", self.request(url, "br")[1]["cache-control"])

    def test_conditional_requests_and_representation_identity(self):
        build.prepare(self.directory)
        with preview(self.root) as self.port:
            _, headers, _ = self.request(encoding="gzip")
            etag = headers["etag"]
            for tag in (etag, "W/" + etag, '"unrelated", W/' + etag, "*"):
                status, cached, body = self.request(encoding="gzip", headers={"If-None-Match": tag})
                self.assertEqual((status, body), (304, b""))
                self.assertEqual(cached["vary"], "Accept-Encoding")
                self.assertEqual(cached["etag"], etag)
            self.assertEqual(self.request(headers={"If-None-Match": etag})[0], 200)
            self.assertEqual(self.request(encoding="gzip", headers={"If-Modified-Since": headers["last-modified"]})[0], 304)
            self.assertEqual(self.request(headers={"If-Modified-Since": "garbage"})[0], 200)
            self.assertEqual(self.request(headers={"If-None-Match": '"different"',
                "If-Modified-Since": "Wed, 01 Jan 2098 00:00:00 GMT"})[0], 200)
            self.assertNotIn("immutable", self.request("index.html")[1]["cache-control"])
            self.assertIn("must-revalidate", self.request()[1]["cache-control"])

    def test_old_immutable_url_retained_and_wrong_query_fails_closed(self):
        records = build.prepare(self.directory, immutable=True)
        old_url = records["index.wasm"]["immutableUrl"]
        old_hash = records["index.wasm"]["sha256"]
        (self.directory / "index.wasm").write_bytes(b"new content")
        build.prepare(self.directory, immutable=True)
        with preview(self.root) as self.port:
            status, headers, body = self.request(old_url, "gzip")
            self.assertEqual(status, 200)
            self.assertEqual(gzip.decompress(body), self.payloads["index.wasm"])
            self.assertIn("immutable", headers["cache-control"])
            self.assertEqual(self.request()[2], b"new content")
            self.assertEqual(self.request("index.wasm?v=" + old_hash[:16])[0], 404)
            (self.directory / old_url).write_bytes(b"incorrect immutable bytes")
            self.assertEqual(self.request(old_url)[0], 404)
        with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
            build.immutable_copy(self.directory / "index.wasm", self.directory / old_url, "0" * 64)

    def test_stale_corrupt_compression_never_serves_wrong_bytes(self):
        build.prepare(self.directory, brotli=build.brotli_module() is not None)
        with preview(self.root) as self.port:
            old_etag = self.request()[1]["etag"]
            replacement = b"X" * len(self.payloads["index.wasm"])
            (self.directory / "index.wasm").write_bytes(replacement)
            for encoding in ("gzip", "br,gzip"):
                status, headers, body = self.request(encoding=encoding)
                self.assertEqual((status, body), (200, replacement))
                self.assertNotIn("content-encoding", headers)
                self.assertNotEqual(old_etag, headers["etag"])
            self.assertEqual(self.request(encoding="gzip,identity;q=0")[0], 406)
            (self.directory / "index.wasm.gz").write_bytes(b"not gzip")
            self.assertEqual(self.request(encoding="gzip")[2], replacement)
            # Valid gzip header, invalid DEFLATE payload: zlib.error, not BadGzipFile.
            (self.directory / "index.wasm.gz").write_bytes(bytes.fromhex("1f8b0800000000000003ff0000000000000000"))
            self.assertEqual(self.request(encoding="gzip")[2], replacement)

    def test_corrupt_brotli_falls_back_to_valid_gzip(self):
        if build.brotli_module() is None:
            self.skipTest("Optional Brotli not installed")
        build.prepare(self.directory, brotli=True)
        (self.directory / "index.wasm.br").write_bytes(b"corrupt Brotli")
        with preview(self.root) as self.port:
            status, headers, body = self.request(encoding="br,gzip")
            self.assertEqual((status, headers["content-encoding"]), (200, "gzip"))
            self.assertEqual(gzip.decompress(body), self.payloads["index.wasm"])

    def test_compressed_symlink_outside_root_is_ignored(self):
        # Use a sibling outside the allowed root, not merely a different route.
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "private.gz"
            outside.write_bytes(gzip.compress(self.payloads["index.wasm"]))
            try:
                (self.directory / "index.wasm.gz").symlink_to(outside)
            except OSError:
                self.skipTest("Windows symlink privilege unavailable")
            with preview(self.root) as self.port:
                status, headers, body = self.request(encoding="gzip")
                self.assertEqual((status, body), (200, self.payloads["index.wasm"]))
                self.assertNotIn("content-encoding", headers)

    def test_routes_and_mime(self):
        build.prepare(self.directory)
        with preview(self.root) as self.port:
            for route in ("../private.log", "%2e%2e/private.log", "index.wasm.gz", "index.wasm.br",
                          "web-payload.json", "", "nested/index.js"):
                self.assertEqual(self.request(route)[0], 404, route)
            for name, mime in (("index.pck", "application/octet-stream"), ("index.js", "text/javascript; charset=utf-8"),
                               ("meadow-controls.css", "text/css; charset=utf-8")):
                self.assertEqual(self.request(name, "gzip")[1]["content-type"], mime)


if __name__ == "__main__":
    unittest.main()
