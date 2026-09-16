"""Bounded engine-only staging contracts: synthetic ZIP/PCKs, fake prepare.

No real export, compression build, browser, socket or native engine is used.
Run: E:/Anaconda3/python.exe -B godot/tools/test_stage_engine_web.py -v
"""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import socket
import struct
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import prepare_web_build as web
import stage_engine_web as stage
import mode5_engine_contract as mode5


def minimal_pack(payload=b"fixture", entry_path="assets/baked/fixture.scn"):
    name = entry_path.encode("utf-8")
    name += b"\0" * (-len(name) % 4)
    header = b"GDPC" + struct.pack("<5IQ", 2, 4, 7, 2, 0, 0) + bytes(64) + struct.pack("<I", 1)
    offset = len(header) + 4 + len(name) + 36
    entry = struct.pack("<I", len(name)) + name + struct.pack("<QQ", offset, len(payload)) + hashlib.md5(payload).digest() + struct.pack("<I", 0)
    return header + entry + payload


class EngineStageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="meadow-engine-stage-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "v125"
        self.source.mkdir()
        self.destination = self.root / "v126"
        self.archive = self.root / "template.zip"
        self.members = {
            "godot.js": b"// synthetic replacement engine, not an executable Godot build\n",
            "godot.wasm": b"\0asm\x01\0\0\0fixture",
            "godot.audio.worklet.js": b"// replacement worklet\n",
            "godot.audio.position.worklet.js": b"// replacement position worklet\n",
        }
        for name in stage.FROZEN:
            (self.source / name).write_bytes(minimal_pack() if name.endswith(".pck") else b"unchanged synthetic " + name.encode())
        for name in stage.ENGINE_MEMBERS.values():
            (self.source / name).write_bytes(b"old engine " + name.encode())
        self.helpers = {}
        helper_root = self.root / "helpers"
        helper_root.mkdir()
        for name in web.HELPER_SOURCES:
            blob = b"// frozen host " + name.encode() + b"\n"
            (self.source / name).write_bytes(blob)
            self.helpers[name] = helper_root / name
            self.helpers[name].write_bytes(blob)
        (self.source / "meadow-controls.css").write_bytes(b"/* frozen CSS */\n")
        for name in ("lite-build.json", "proof.json", "shader-replacements.v1.json"):
            (self.source / name).write_text('{"fixture":true}\n', encoding="utf-8")
        self.config = {"executable": "index", "args": ["--", "--fixture=keep"],
                       "fileSizes": {"index.pck": 999, "index.wasm": 111},
                       "focusCanvas": False, "canvasResizePolicy": 2,
                       "gdextensionLibs": []}
        self.set_html()
        self.write_zip()
        self.prepare_hook = None
        self.prepare_records_hook = None
        self.progressive_payload_names = ()
        self.prepared_records = None
        guards = [patch.object(stage, "prepare", side_effect=self.fake_prepare),
                  patch.object(stage, "HELPER_SOURCES", self.helpers, create=True),
                  patch.object(socket, "socket", side_effect=AssertionError("No sockets")),
                  patch.object(socket, "create_connection", side_effect=AssertionError("No network"))]
        self.prepare_mock = guards[0].start()
        self.addCleanup(guards[0].stop)
        for guard in guards[1:]:
            guard.start()
            self.addCleanup(guard.stop)

    def set_html(self, suffix=""):
        scripts = "".join(f'<script src="{name}"></script>\n' for name in self.helpers)
        html = ('<!doctype html>\n<!-- FROZEN SOURCE SHELL: must survive engine-only AB -->\n'
                '<link rel="stylesheet" href="meadow-controls.css">\n' + scripts +
                '<script src="index.js"></script>\n<script>\nwindow.meadowQuality.mount(' +
                json.dumps(self.config) + ');\n</script>\n' + suffix)
        (self.source / "index.html").write_text(html, encoding="utf-8")

    def write_zip(self, members=None, extras=()):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_STORED) as archive:
                for name, blob in (members or self.members).items():
                    archive.writestr(name, blob)
                for name, blob in extras:
                    archive.writestr(name, blob)
        self.sha = stage.digest(self.archive.read_bytes())

    def fake_prepare(self, directory, **options):
        self.assertEqual(options, {"brotli": True})
        self.assertEqual(directory, self.destination.resolve())
        if self.prepare_hook:
            self.prepare_hook(directory)
        records = {}
        for name in dict.fromkeys((*web.PAYLOADS, *web.OPTIONAL_PAYLOADS,
                                   *self.progressive_payload_names)):
            path = directory / name
            if path.is_file():
                blob = path.read_bytes()
                # Deliberately fake encoded size: no real compression/staging run.
                records[name] = {"bytes": len(blob), "sha256": stage.digest(blob),
                                 "gzipBytes": len(blob) // 2 + 1}
        if self.prepare_records_hook:
            self.prepare_records_hook(records)
        html = directory / "index.html"
        html.write_text(web.quality_html(html.read_text(encoding="utf-8"), records), encoding="utf-8")
        (directory / "web-payload.json").write_text(json.dumps(records), encoding="utf-8")
        self.prepared_records = records
        return records

    def run_stage(self, expected_sha=None):
        with redirect_stdout(io.StringIO()):
            return stage.stage(self.source, self.archive, expected_sha or self.sha, self.destination)

    def snapshot(self, directory):
        return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}

    def staged_config(self):
        html = (self.destination / "index.html").read_text(encoding="utf-8")
        return json.loads(re.findall(r"window\.meadowQuality\.mount\((\{[^\n]+\})\);", html)[0])

    def write_progressive(self, manifest, *, external=None):
        """Real PCK envelope/MD5; contents are synthetic, not a runnable scene."""
        encoded = json.dumps(manifest, sort_keys=True).encode()
        core = minimal_pack(encoded, "progressive/manifest.json")
        (self.source / "index-lite.pck").write_bytes(core)
        (self.source / "progressive-manifest.json").write_text(
            json.dumps(manifest if external is None else external, indent=2), encoding="utf-8")
        boot = (self.source / "bootstrap.pck").read_bytes()
        (self.source / "bootstrap-manifest.json").write_text(json.dumps({
            "file": "bootstrap.pck", "bytes": len(boot), "sha256": stage.digest(boot),
            "coreSha256": stage.digest(core)}), encoding="utf-8")
        self.progressive_payload_names = tuple(chunk["file"] for chunk in manifest["chunks"])

    def install_progressive(self, *, private=None):
        chunks = []
        private_header = b"RSCC" + struct.pack("<III", 5, 1048576, 0)
        for index in range(12):
            payload = f"synthetic detail {index}".encode()
            if private in ("detail", "both") and index == 11:
                payload = private_header + payload
            data = minimal_pack(payload)
            sha = stage.digest(data)
            name = f"detail-{index}-{sha[:12]}.pck"
            (self.source / name).write_bytes(data)
            chunks.append({"index": index, "file": name, "bytes": len(data), "sha256": sha})
        boot = (private_header if private in ("bootstrap", "both") else b"") + b"synthetic boot"
        (self.source / "bootstrap.pck").write_bytes(minimal_pack(boot))
        manifest = {"version": 1, "chunks": chunks}
        self.write_progressive(manifest)
        return manifest

    def synthetic_engine_pair(self):
        # Only the allowlist is replaced. The actual parser and four-file pairing
        # validator still run, including for mode-5 entries in the last chunk.
        return {stage.digest(self.members["godot.wasm"]): tuple(
            stage.digest(self.members[name]) for name in (
                "godot.js", "godot.audio.worklet.js", "godot.audio.position.worklet.js"))}

    def assert_preflight_refused(self, pattern=None):
        before = self.snapshot(self.source)
        with self.assertRaises((ValueError, FileNotFoundError)) as caught:
            self.run_stage()
        if pattern:
            self.assertRegex(str(caught.exception), pattern)
        self.assertEqual(self.snapshot(self.source), before)
        self.assertFalse(self.destination.exists())
        self.prepare_mock.assert_not_called()

    def test_success_freezes_all_three_packs_icon_host_and_old_directory(self):
        before = self.snapshot(self.source)
        result = self.run_stage()
        self.assertEqual(self.snapshot(self.source), before)
        for name in (*stage.FROZEN, *self.helpers, "meadow-controls.css", "proof.json",
                     "lite-build.json", "shader-replacements.v1.json"):
            self.assertEqual((self.destination / name).read_bytes(), before[name], name)
        for archive_name, target in stage.ENGINE_MEMBERS.items():
            self.assertEqual((self.destination / target).read_bytes(), self.members[archive_name])
        self.assertIn("FROZEN SOURCE SHELL", (self.destination / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(result["engineWasmBytes"], len(self.members["godot.wasm"]))
        self.assertEqual(result["engineSha256"], stage.digest(self.members["godot.wasm"]))
        self.prepare_mock.assert_called_once()

    def test_private_mode5_pack_refuses_unreviewed_engine_before_writing(self):
        payload = b"RSCC" + struct.pack("<III", 5, 1048576, 0) + b"fixture"
        (self.source / "index-lite.pck").write_bytes(minimal_pack(payload))
        with self.assertRaisesRegex(ValueError, "Private mode-5"):
            self.run_stage()
        self.assertFalse(self.destination.exists())
        self.prepare_mock.assert_not_called()

    def test_config_sizes_cover_four_new_engine_files_and_three_frozen_packs(self):
        before = deepcopy(self.config)
        self.run_stage()
        after = self.staged_config()
        self.assertEqual({k: v for k, v in after.items() if k != "fileSizes"},
                         {k: v for k, v in before.items() if k != "fileSizes"})
        for name in (*stage.ENGINE_MEMBERS.values(), *stage.FROZEN[:3]):
            self.assertEqual(after["fileSizes"][name], (self.destination / name).stat().st_size, name)

    def test_absent_file_sizes_are_populated(self):
        del self.config["fileSizes"]
        self.set_html()
        self.run_stage()
        self.assertEqual(self.staged_config()["fileSizes"]["index.wasm"], len(self.members["godot.wasm"]))

    def test_provenance_and_shared_catalog_bind_exact_engine_once(self):
        result = self.run_stage()
        metadata = json.loads((self.destination / "engine-build.json").read_text())
        self.assertEqual(metadata["templateSha256"], self.sha)
        self.assertEqual(set(metadata["engine"]), set(stage.ENGINE_MEMBERS.values()))
        for source, target in stage.ENGINE_MEMBERS.items():
            self.assertEqual(metadata["engine"][target],
                             {"bytes": len(self.members[source]), "sha256": stage.digest(self.members[source])})
        frozen = json.loads((self.destination / "frozen-original.json").read_text())
        self.assertEqual(set(frozen), set(stage.FROZEN))
        html = (self.destination / "index.html").read_text(encoding="utf-8")
        shared = json.loads(re.search(r"window\.MEADOW_QUALITY_SHARED = (.*?);\n", html)[1])
        choices = json.loads(re.search(r"window\.MEADOW_QUALITY = (.*?);\n", html)[1])
        self.assertEqual(set(choices), {"original", "balanced", "lite"})
        self.assertEqual(shared["index.wasm"]["bytes"], len(self.members["godot.wasm"]))
        self.assertEqual([n for n in shared if n.endswith(".wasm")], ["index.wasm"])
        self.assertEqual(html.count('<script src="index.js">'), 1)
        self.assertNotIn("preload", html)
        self.assertEqual(result["liteGzipTotalBytes"],
                         sum(r["gzipBytes"] for n, r in self.prepared_records.items() if not n.endswith(".pck")) +
                         self.prepared_records["index-lite.pck"]["gzipBytes"])

    def test_only_four_exact_root_members_consumed_no_extraction(self):
        self.write_zip(extras=[("../outside.js", b"outside"), ("/absolute.js", b"outside"),
                               ("nested/godot.js", b"nested"), ("godot.html", b"\xff"),
                               ("godot.service.worker.js", b"ignored service worker")])
        actual_read = zipfile.ZipFile.read
        consumed = []
        def read(archive, name, *args, **kwargs):
            consumed.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
            return actual_read(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "read", read), \
                patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("No extraction")), \
                patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("No extraction")):
            self.run_stage()
        self.assertEqual(consumed, list(stage.ENGINE_MEMBERS))
        self.assertFalse((self.root / "outside.js").exists())
        self.assertFalse((self.destination / "nested").exists())
        self.assertFalse((self.destination / "godot.service.worker.js").exists())

    def test_duplicate_consumed_or_ignored_member_rejected(self):
        for extras in ([("godot.js", b"duplicate")], [("ignored", b"x"), ("ignored", b"y")]):
            with self.subTest(extras=extras):
                self.write_zip(extras=extras)
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    self.run_stage()
                self.assertFalse(self.destination.exists())

    def test_wrong_or_malformed_hash_rejected_before_destination(self):
        for expected in ("f" * 64, self.sha.upper(), "x", self.sha + " "):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.run_stage(expected)
        self.assertFalse(self.destination.exists())
        self.prepare_mock.assert_not_called()

    def test_oversize_member_is_not_read(self):
        members = {**self.members, "godot.wasm": b"\0asm\x01\0\0\0" + b"x" * 256}
        self.write_zip(members)
        actual_read = zipfile.ZipFile.read
        def read(archive, member, *args, **kwargs):
            self.assertNotEqual(member.filename, "godot.wasm", "Oversize member must be rejected before reading")
            return actual_read(archive, member, *args, **kwargs)
        with patch.object(stage, "MAX_MEMBER_BYTES", 128), patch.object(zipfile.ZipFile, "read", read), \
                self.assertRaises(ValueError):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_oversize_archive_rejected_before_zip_parser(self):
        with patch.object(stage, "MAX_ARCHIVE_BYTES", self.archive.stat().st_size - 1), \
                patch.object(zipfile, "ZipFile", side_effect=AssertionError("Archive must not be parsed")), \
                self.assertRaisesRegex(ValueError, "archive"):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_zip_consumes_the_hashed_snapshot_not_a_reopened_path(self):
        replacement = io.BytesIO()
        actual_zip = zipfile.ZipFile
        with actual_zip(replacement, "w") as archive:
            for name, blob in self.members.items():
                archive.writestr(name, b"// UNREVIEWED replacement" if name == "godot.js" else blob)
        def swapped_open(file, *args, **kwargs):
            self.archive.write_bytes(replacement.getvalue())
            return actual_zip(file, *args, **kwargs)
        with patch.object(zipfile, "ZipFile", side_effect=swapped_open):
            result = stage.read_template(self.archive, self.sha)
        self.assertEqual(result["index.js"], self.members["godot.js"])
        self.assertNotEqual(stage.digest(self.archive.read_bytes()), self.sha)

    def test_empty_member_and_bad_utf8_rejected(self):
        for bad in (b"", b"\xff\xfe"):
            self.write_zip({**self.members, "godot.js": bad})
            with self.subTest(bad=bad), self.assertRaises((ValueError, UnicodeError)):
                self.run_stage()
            self.assertFalse(self.destination.exists())

    def test_wasm_magic_version_and_truncated_header_rejected(self):
        for bad in (b"\0asm\x02\0\0\0", b"notwasm!", b"\0asm\x01"):
            self.write_zip({**self.members, "godot.wasm": bad})
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "WebAssembly"):
                self.run_stage()
            self.assertFalse(self.destination.exists())

    def test_missing_root_member_is_not_satisfied_by_nested_name(self):
        members = dict(self.members)
        members["nested/godot.wasm"] = members.pop("godot.wasm")
        self.write_zip(members)
        with self.assertRaises((ValueError, KeyError)):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_thread_or_dynamic_link_template_rejected(self):
        for name in ("godot.worker.js", "godot.side.wasm"):
            self.write_zip(extras=[(name, b"unsupported")])
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "nothreads"):
                self.run_stage()
            self.assertFalse(self.destination.exists())

    def test_non_index_configuration_rejected(self):
        self.config["executable"] = "renamed"
        self.set_html()
        with self.assertRaisesRegex(ValueError, "index"):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_invalid_file_sizes_or_mount_rejected_before_output(self):
        for bad in (None, [], 42):
            self.config["fileSizes"] = bad
            self.set_html()
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.run_stage()
            self.assertFalse(self.destination.exists())
        (self.source / "index.html").write_text("no config")
        with self.assertRaises(ValueError):
            self.run_stage()
        self.set_html(suffix='window.meadowQuality.mount({"executable":"index"});')
        with self.assertRaises(ValueError):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_existing_file_or_directory_is_never_overwritten(self):
        self.destination.write_bytes(b"existing target")
        with self.assertRaises(ValueError):
            self.run_stage()
        self.assertEqual(self.destination.read_bytes(), b"existing target")
        self.destination = self.source
        before = self.snapshot(self.source)
        with self.assertRaises(ValueError):
            self.run_stage()
        self.assertEqual(self.snapshot(self.source), before)
        self.prepare_mock.assert_not_called()

    def test_destination_inside_old_version_is_rejected(self):
        self.destination = self.source / "v126"
        before = self.snapshot(self.source)
        with self.assertRaisesRegex(ValueError, "source|inside|old"):
            self.run_stage()
        self.assertEqual(self.snapshot(self.source), before)

    def test_unversioned_destination_is_rejected(self):
        self.destination = self.root / "latest"
        with self.assertRaises(ValueError):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_missing_frozen_input_rejected_before_output(self):
        (self.source / "index-balanced.pck").unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_live_host_drift_is_not_silently_bundled(self):
        self.helpers["meadow-loader.js"].write_bytes(b"// unrelated NEW host behavior")
        with self.assertRaisesRegex(ValueError, "host|helper|engine-only"):
            self.run_stage()
        self.assertFalse(self.destination.exists())

    def test_prepare_mutation_of_pack_engine_or_host_is_rejected(self):
        for index, name in enumerate(("index-lite.pck", "index.wasm", "meadow-controls.js")):
            self.destination = self.root / f"v{200 + index}"
            self.prepare_hook = lambda directory, name=name: (directory / name).write_bytes(b"unexpected mutation")
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_stage()
            self.assertFalse((self.destination / "engine-build.json").exists())

    def test_prepare_failure_never_claims_success_and_source_stays_unchanged(self):
        before = self.snapshot(self.source)
        def fail(_directory):
            raise RuntimeError("synthetic preparation failure")
        self.prepare_hook = fail
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            self.run_stage()
        self.assertFalse((self.destination / "engine-build.json").exists())
        self.assertEqual(self.snapshot(self.source), before)

    def test_progressive_keeps_all_twelve_chunks_bootstrap_and_catalog(self):
        manifest = self.install_progressive()
        before = self.snapshot(self.source)
        names = [chunk["file"] for chunk in manifest["chunks"]]
        with patch.object(stage, "validate_pack_engine", wraps=stage.validate_pack_engine) as validate:
            self.run_stage()
        self.assertEqual([call.args[0].name for call in validate.call_args_list],
                         ["index-lite.pck", *names, "bootstrap.pck"])
        self.assertEqual(self.snapshot(self.source), before)
        for name in (*stage.FROZEN, *names, "progressive-manifest.json",
                     "bootstrap.pck", "bootstrap-manifest.json"):
            self.assertEqual((self.destination / name).read_bytes(), before[name], name)
        self.assertEqual({path.name for path in self.destination.glob("*.pck")},
                         {*stage.FROZEN[:3], *names, "bootstrap.pck"})
        for name in (*names, "bootstrap.pck"):
            self.assertEqual(self.prepared_records[name]["bytes"], len(before[name]))
            self.assertEqual(self.prepared_records[name]["sha256"], stage.digest(before[name]))
        html = (self.destination / "index.html").read_text(encoding="utf-8")
        choices = json.loads(re.search(r"window\.MEADOW_QUALITY = (.*?);\n", html)[1])
        self.assertEqual(choices["lite"]["details"], {
            key: sum(self.prepared_records[name][key] for name in names)
            for key in ("bytes", "gzipBytes")})
        self.assertEqual(choices["lite"]["bootstrap"], {
            "file": "bootstrap.pck", **self.prepared_records["bootstrap.pck"],
            "coreSha256": stage.digest(before["index-lite.pck"])})
        for quality in ("original", "balanced"):
            self.assertNotIn("bootstrap", choices[quality])
            self.assertNotIn("details", choices[quality])
        self.prepare_mock.assert_called_once()

    def test_progressive_inner_outer_manifest_pair_is_required(self):
        for missing in ("embedded", "external"):
            with self.subTest(missing=missing):
                self.install_progressive()
                if missing == "embedded":
                    (self.source / "index-lite.pck").write_bytes(minimal_pack())
                else:
                    (self.source / "progressive-manifest.json").unlink()
                self.assert_preflight_refused("matching embedded/adjacent")

    def test_progressive_manifest_mismatch_version_and_count_rejected(self):
        for defect in ("mismatch", "version", "empty", "too-many"):
            with self.subTest(defect=defect):
                manifest = self.install_progressive()
                if defect == "mismatch":
                    self.write_progressive(manifest, external={**manifest, "unexpected": True})
                else:
                    if defect == "version":
                        manifest["version"] = 2
                    else:
                        manifest["chunks"] = [] if defect == "empty" else [manifest["chunks"][0]] * 33
                    self.write_progressive(manifest)
                self.assert_preflight_refused("manifest mismatch|detail count")

    def test_progressive_chunk_index_name_hash_and_length_rejected(self):
        mutations = (("index", 0), ("file", "../outside.pck"),
                     ("file", "detail-11-000000000000.pck"), ("sha256", "not-a-sha"),
                     ("sha256", "A" * 64), ("bytes", 1))
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                manifest = self.install_progressive()
                manifest["chunks"][-1][field] = value
                self.write_progressive(manifest)
                self.assert_preflight_refused("Invalid detail identity|Detail bytes")

    def test_progressive_missing_corrupt_or_wrong_hash_last_chunk_rejected(self):
        for defect in ("missing", "same-length-corruption", "wrong-pinned-hash"):
            with self.subTest(defect=defect):
                manifest = self.install_progressive()
                chunk = manifest["chunks"][-1]
                path = self.source / chunk["file"]
                if defect == "missing":
                    path.unlink()
                elif defect == "same-length-corruption":
                    data = path.read_bytes()
                    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
                else:
                    chunk["sha256"] = "f" * 64
                    chunk["file"] = "detail-11-ffffffffffff.pck"
                    (self.source / chunk["file"]).write_bytes(path.read_bytes())
                    self.write_progressive(manifest)
                self.assert_preflight_refused()

    def test_bootstrap_pair_required_in_both_directions(self):
        for missing in ("bootstrap.pck", "bootstrap-manifest.json"):
            with self.subTest(missing=missing):
                self.install_progressive()
                (self.source / missing).unlink()
                self.assert_preflight_refused("supplied together")

    def test_bootstrap_core_file_hash_and_length_rejected(self):
        for field, value in (("coreSha256", "f" * 64), ("file", "index.pck"),
                             ("sha256", "f" * 64), ("bytes", 1)):
            with self.subTest(field=field):
                self.install_progressive()
                path = self.source / "bootstrap-manifest.json"
                spec = json.loads(path.read_bytes())
                spec[field] = value
                path.write_text(json.dumps(spec), encoding="utf-8")
                self.assert_preflight_refused("Bootstrap does not match")

    def test_bootstrap_cannot_attach_to_nonprogressive_core_even_with_exact_pin(self):
        self.install_progressive()
        core = minimal_pack()
        (self.source / "index-lite.pck").write_bytes(core)
        (self.source / "progressive-manifest.json").unlink()
        path = self.source / "bootstrap-manifest.json"
        spec = json.loads(path.read_bytes())
        spec["coreSha256"] = stage.digest(core)
        path.write_text(json.dumps(spec), encoding="utf-8")
        self.assert_preflight_refused("Bootstrap does not match")

    def test_progressive_mode5_in_detail_or_bootstrap_refuses_unreviewed_engine(self):
        for location in ("detail", "bootstrap"):
            with self.subTest(location=location):
                self.install_progressive(private=location)
                self.assert_preflight_refused("Private mode-5")

    def test_progressive_mode5_exact_four_file_pair_is_accepted(self):
        self.install_progressive(private="both")
        before = self.snapshot(self.source)
        with patch.dict(mode5.MODE5_ENGINES, self.synthetic_engine_pair(), clear=True):
            self.run_stage()
        self.assertEqual(self.snapshot(self.source), before)
        for name in (*self.progressive_payload_names, "bootstrap.pck"):
            self.assertEqual((self.destination / name).read_bytes(), before[name])

    def test_progressive_mode5_mixed_js_wasm_or_either_worklet_rejected(self):
        self.install_progressive(private="both")
        with patch.dict(mode5.MODE5_ENGINES, self.synthetic_engine_pair(), clear=True):
            for name in self.members:
                with self.subTest(mixed_member=name):
                    self.write_zip({**self.members, name: self.members[name] + b"unreviewed"})
                    self.assert_preflight_refused("Private mode-5")

    def test_prepare_progressive_copy_or_manifest_drift_never_claims_success(self):
        manifest = self.install_progressive()
        before = self.snapshot(self.source)
        names = (manifest["chunks"][-1]["file"], "bootstrap.pck",
                 "progressive-manifest.json", "bootstrap-manifest.json")
        for index, name in enumerate(names):
            with self.subTest(name=name):
                self.destination = self.root / f"v{300 + index}"
                self.prepare_hook = lambda directory, name=name: (directory / name).write_bytes(b"changed by prepare")
                with self.assertRaisesRegex(ValueError, "Frozen copy/host mismatch"):
                    self.run_stage()
                for marker in ("engine-build.json", "frozen-original.json"):
                    self.assertFalse((self.destination / marker).exists())
                self.assertEqual(self.snapshot(self.source), before)

    def test_prepare_progressive_source_drift_never_claims_success(self):
        manifest = self.install_progressive()
        name = manifest["chunks"][-1]["file"]
        self.prepare_hook = lambda _directory: (self.source / name).write_bytes(b"simulated concurrent source edit")
        with self.assertRaisesRegex(ValueError, "Frozen source mismatch"):
            self.run_stage()
        for marker in ("engine-build.json", "frozen-original.json"):
            self.assertFalse((self.destination / marker).exists())

    def test_prepare_progressive_metadata_drift_must_not_claim_success(self):
        manifest = self.install_progressive()
        before = self.snapshot(self.source)
        # Core is the existing guard's control; boot/detail need the same gate.
        names = ("index-lite.pck", manifest["chunks"][-1]["file"], "bootstrap.pck")
        for index, name in enumerate(names):
            for field_index, field in enumerate(("bytes", "sha256", "missing")):
                with self.subTest(name=name, field=field):
                    self.destination = self.root / f"v{400 + index * 3 + field_index}"
                    def corrupt(records, name=name, field=field):
                        if field == "missing":
                            del records[name]
                        else:
                            records[name][field] = 1 if field == "bytes" else "f" * 64
                    self.prepare_records_hook = corrupt
                    with self.assertRaises((ValueError, KeyError), msg=f"prepare drift accepted: {name}/{field}"):
                        self.run_stage()
                    for marker in ("engine-build.json", "frozen-original.json"):
                        self.assertFalse((self.destination / marker).exists())
                    self.assertEqual(self.snapshot(self.source), before)


if __name__ == "__main__":
    unittest.main()
