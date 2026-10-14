"""Tiny transport fixtures only. No real staging, engine, browser or service."""
from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import prepare_web_build as web
import stage_lite_web as stage


def digest(data):
    return hashlib.sha256(data).hexdigest()


class VerifiedBrotliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="meadow-verified-br-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.directory = self.root / "v999"
        self.directory.mkdir()
        self.raw = b"\0asm\x01\0\0\0" + b"tiny exact fixture\0" * 20
        self.codec = web.brotli_module()
        if self.codec is None:
            self.skipTest("Tiny real decode fixture requires installed Brotli")
        self.encoded = self.codec.compress(self.raw, quality=11, lgwin=24)
        self.sidecar = self.root / "reviewed.br"
        self.sidecar.write_bytes(self.encoded)
        self.proof_path = self.root / "proof.json"
        self.proof_path.write_text(json.dumps({"status": "PASS", "source": {"sha256": digest(self.raw)},
            "candidate": {"sha256": digest(self.encoded), "bytes": len(self.encoded)},
            "parameters": {"quality": 11, "lgwin": 24}}), encoding="utf-8")
        self.contract = {"rawBytes": len(self.raw), "bytes": len(self.encoded),
                         "sha256": digest(self.encoded), "proofSha256": web.sha256(self.proof_path),
                         "sidecar": self.sidecar, "proof": self.proof_path}
        for name, data in {"index.wasm": self.raw, "meadow-controls.js": b"// controls",
                           "meadow-controls.css": b"/* controls */", "index.js": b"// engine"}.items():
            (self.directory / name).write_bytes(data)
        (self.directory / "index.html").write_text(
            '<script src="index.js"></script><script>window.meadowQuality.mount({"executable":"index"});</script>', encoding="utf-8")
        for hook in (patch.dict(web.PINNED_WASM_BROTLI, {digest(self.raw): self.contract}, clear=True),
                     patch.object(web, "PAYLOADS", ("index.wasm",)),
                     patch.object(web, "OPTIONAL_PAYLOADS", ()),
                     patch.object(web, "HELPER_SOURCES", {})):
            hook.start()
            self.addCleanup(hook.stop)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}

    def prepare(self, **kwargs):
        return web.prepare(self.directory, brotli=True, **kwargs)["index.wasm"]

    def test_adopts_exact_pinned_bytes_without_encoder(self):
        proxy = Mock(decompress=self.codec.decompress, Compressor=Mock(side_effect=AssertionError("No encoder")))
        with patch.object(web, "brotli_module", return_value=proxy):
            row = self.prepare()
        self.assertEqual((self.directory / "index.wasm.br").read_bytes(), self.encoded)
        self.assertEqual(row["encodings"]["br"]["policy"], "pinned-verified-brotli")
        self.assertEqual(row["encodings"]["br"]["selection"], "pinned-artifact")
        self.assertTrue(row["encodings"]["br"]["decodedByteExact"])
        self.assertEqual(row["encodings"]["br"]["proofSha256"], self.contract["proofSha256"])
        self.assertEqual(gzip.decompress((self.directory / "index.wasm.gz").read_bytes()), self.raw)
        proxy.Compressor.assert_not_called()

    def test_repeat_keeps_sidecar_mtime_and_metadata_sizes(self):
        first = self.prepare(immutable=True)
        sidecar = self.directory / "index.wasm.br"
        before = (sidecar.read_bytes(), sidecar.stat().st_mtime_ns)
        # A verified local copy remains usable even if its original candidate is moved.
        self.contract["sidecar"] = self.root / "not-present.br"
        second = self.prepare(immutable=True)
        self.assertEqual((sidecar.read_bytes(), sidecar.stat().st_mtime_ns), before)
        self.assertEqual(second["encodings"]["br"]["selection"], "existing-sidecar")
        self.assertEqual(first["brotliBytes"], len(self.encoded))
        self.assertEqual(second["brotliBytes"], len(self.encoded))
        self.assertEqual(json.loads((self.directory / "web-payload.json").read_text())["index.wasm"], second)
        html = (self.directory / "index.html").read_text()
        shared = json.loads(html.split("window.MEADOW_QUALITY_SHARED = ", 1)[1].split(";", 1)[0])
        self.assertEqual(shared["index.wasm"]["brBytes"], len(self.encoded))
        self.assertEqual((self.directory / (first["immutableUrl"] + ".br")).read_bytes(), self.encoded)

    def test_changed_raw_uses_real_q6_and_never_old_strong_bytes(self):
        self.prepare()
        changed = self.raw + b"different engine"
        (self.directory / "index.wasm").write_bytes(changed)
        row = self.prepare()
        self.assertEqual(row["encodings"]["br"]["quality"], 6)
        self.assertEqual(row["encodings"]["br"]["policy"], "quality6-unpinned-wasm")
        actual = (self.directory / "index.wasm.br").read_bytes()
        self.assertNotEqual(actual, self.encoded)
        self.assertEqual(self.codec.decompress(actual), changed)

    def test_explicit_bad_sidecar_rejected_before_any_output(self):
        bad = self.root / "bad.br"
        bad.write_bytes(b"bad")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "sidecar bytes/SHA256"):
            self.prepare(verified_wasm_br=bad)
        self.assertEqual(self.snapshot(), before)

    def test_explicit_unapproved_raw_is_rejected_not_silently_ignored(self):
        (self.directory / "index.wasm").write_bytes(b"foreign")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "no approved raw"):
            self.prepare(verified_wasm_br=self.sidecar)
        self.assertEqual(self.snapshot(), before)

    def test_proof_pass_label_without_pinned_hash_is_not_trusted(self):
        self.proof_path.write_text('{"status":"PASS"}')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "proof SHA256"):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_pinned_hashes_still_require_actual_decode_equal(self):
        # The lookup is already a trusted fixture: a bad decoder/result cannot
        # become successful merely because the proof says PASS.
        before = self.snapshot()
        for result in (b"different", self.raw[:-1]):
            codec = Mock(decompress=Mock(return_value=result))
            with self.subTest(result=result), patch.object(web, "brotli_module", return_value=codec):
                with self.assertRaisesRegex(ValueError, "decoded bytes"):
                    self.prepare()
            self.assertEqual(self.snapshot(), before)

    def test_decode_exception_and_missing_codec_fail_closed(self):
        before = self.snapshot()
        for codec in (None, Mock(decompress=Mock(side_effect=RuntimeError("bad stream")))):
            with self.subTest(codec=codec), patch.object(web, "brotli_module", return_value=codec):
                with self.assertRaises(ValueError):
                    self.prepare()
            self.assertEqual(self.snapshot(), before)

    def test_corrupt_default_artifact_is_not_downgraded_to_q6(self):
        self.sidecar.write_bytes(b"bad default")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "sidecar bytes/SHA256"):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_existing_unverified_sidecar_is_replaced_from_verified_artifact(self):
        (self.directory / "index.wasm.br").write_bytes(b"untrusted old sidecar")
        self.prepare()
        self.assertEqual((self.directory / "index.wasm.br").read_bytes(), self.encoded)

    def test_preflight_captures_bytes_instead_of_trusting_mutable_path(self):
        selection = web.select_verified_wasm_brotli(self.directory / "index.wasm")
        self.sidecar.write_bytes(b"changed later")
        self.assertEqual(selection["data"], self.encoded)

    def test_explicit_sidecar_requires_brotli_mode(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            web.prepare(self.directory, verified_wasm_br=self.sidecar)
        self.assertEqual(self.snapshot(), before)

    def test_stage_bad_provided_br_fails_before_destination_or_pack_validation(self):
        bad, lite, destination = self.root / "bad.br", self.root / "lite.pck", self.root / "v1000"
        bad.write_bytes(b"bad")
        lite.write_bytes(b"unused tiny pack")
        before = self.snapshot()
        with patch.object(stage, "validate_pack_engine") as validator, patch.object(stage, "prepare") as prepare:
            with self.assertRaisesRegex(ValueError, "sidecar bytes/SHA256"):
                stage.stage(self.directory, lite, destination, verified_wasm_br=bad)
        validator.assert_not_called()
        prepare.assert_not_called()
        self.assertFalse(destination.exists())
        self.assertEqual(self.snapshot(), before)

    def test_stage_copies_verified_bytes_and_passes_option_on_tiny_mock_fixture(self):
        source = self.directory
        for name in ("index.pck", "index-balanced.pck", "index.audio.worklet.js",
                     "index.audio.position.worklet.js", "index.png"):
            (source / name).write_bytes(b"tiny " + name.encode())
        lite = self.root / "lite.pck"
        lite.write_bytes(b"tiny unused parser fixture")
        # The adjacent proof is provenance only; never used as trust authority.
        destination = self.root / "v1001"
        before = self.snapshot()
        def prepared(directory, **options):
            self.assertEqual(options, {"brotli": True, "verified_wasm_br": self.sidecar})
            self.assertEqual((directory / "index.wasm.br").read_bytes(), self.encoded)
            return {name: {"bytes": 1, "gzipBytes": 1} for name in (
                "index.wasm", "index.pck", "index-balanced.pck", "index-lite.pck")}
        with patch.object(stage, "validate_pack_engine"), \
                patch.object(stage, "read_pack", return_value={"entries": []}), \
                patch.object(stage, "prepare", side_effect=prepared) as prepare, \
                redirect_stdout(io.StringIO()):
            stage.stage(source, lite, destination, verified_wasm_br=self.sidecar)
        prepare.assert_called_once()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((destination / "index.wasm").read_bytes(), self.raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
