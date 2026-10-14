"""Settings audit fixtures; --web-transport runs existing transport tests in memory.

The optional transport runner replaces only the socket/listener plumbing. The
existing HTTP handler, HTTP response parser, fixture preparation and assertions
run unchanged. No TCP service is opened; this is not live-server verification.
"""
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import audit_lite_settings as audit


def integer(value, wide=False):
    return struct.pack("<Iq" if wide else "<Ii", 2 | (0x10000 if wide else 0), value)


def floating(value, wide=False):
    return struct.pack("<Id" if wide else "<If", 3 | (0x10000 if wide else 0), value)


def string_body(value):
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw + bytes(-len(raw) % 4)


def string(value):
    return struct.pack("<I", 4) + string_body(value)


def strings(values):
    return struct.pack("<II", 34, len(values)) + b"".join(string_body(value + "\0") for value in values)


def ecfg(records):
    items = list(records.items()) if isinstance(records, dict) else records
    blob = struct.pack("<4sI", b"ECFG", len(items))
    for key, raw in items:
        name = key.encode("utf-8")
        blob += struct.pack("<I", len(name)) + name + struct.pack("<I", len(raw)) + raw
    return blob


def fixture_pack(payload):
    """One unencrypted v4 entry, built only inside temporary test fixtures."""
    name = b"project.binary\0\0"
    header = bytearray(112)
    struct.pack_into("<4s5IQQ", header, 0, b"GDPC", 4, 4, 7, 0, 2, 112, 112 + len(payload))
    index = struct.pack("<II", 1, len(name)) + name
    index += struct.pack("<QQ", 0, len(payload)) + hashlib.md5(payload).digest() + struct.pack("<I", 0)
    return bytes(header) + payload + index


class LiteSettingsTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            "application/config/name": string("风起原野"),
            "application/config/features": strings(["4.7"]),
            "application/run/main_scene": string("res://scenes/main.tscn"),
            "display/window/size/viewport_width": integer(1280),
            "display/window/size/viewport_height": integer(800),
            "display/window/stretch/mode": string("canvas_items"),
            "rendering/renderer/rendering_method": string("gl_compatibility"),
            "rendering/anti_aliasing/quality/msaa_3d": integer(2),
            "shader_globals/opaque_fixture": struct.pack("<I", 1000) + b"unchanged opaque bytes",
        }
        self.good = {**self.before, "rendering/scaling_3d/scale": floating(0.5),
                     "rendering/lights_and_shadows/directional_shadow/size": integer(2048),
                     "rendering/anti_aliasing/quality/msaa_3d": integer(1)}

    def compare(self, after=None, before=None):
        return audit.compare_settings(ecfg(self.before if before is None else before), ecfg(self.good if after is None else after))

    def test_expected_three_differences_explain_size_increase_exactly(self):
        report = self.compare()
        self.assertTrue(report["passed"])
        self.assertTrue(report["all_other_variant_bytes_exact"])
        self.assertEqual(len(report["differences"]), 3)
        self.assertEqual(report["candidate_records"] - report["original_records"], 2)
        self.assertEqual(report["bytes_delta"], 110)
        self.assertEqual(sum(row["record_bytes_delta"] for row in report["differences"]), 110)
        self.assertEqual(report["minimal_patch_proposal"], [])
        self.assertEqual(report["protected_settings"]["display_layout"]["status"], "exact")
        self.assertEqual(report["protected_settings"]["export_features"]["status"], "exact")
        self.assertEqual(report["protected_settings"]["camera_settings"]["status"], "not_stored_in_ecfg")

    def test_mode_omission_is_distinct_from_explicit_zero_and_requires_original_omission(self):
        omitted = self.compare()["approved_settings"][audit.MODE]
        self.assertEqual(omitted["status"], "omitted_in_both")
        self.assertFalse(omitted["actual"]["present"])
        self.assertIn("not explicitly encoded", omitted["note"])
        explicit = self.compare({**self.good, audit.MODE: integer(0)})
        self.assertTrue(explicit["passed"])
        self.assertEqual(explicit["approved_settings"][audit.MODE]["status"], "matches")
        removed = self.compare(before={**self.before, audit.MODE: integer(0)})
        self.assertFalse(removed["passed"])
        self.assertEqual(removed["approved_settings"][audit.MODE]["status"], "invalid")

    def test_wrong_values_wrong_numeric_types_and_missing_approved_values_fail(self):
        for key, (kind, expected) in audit.ALLOWED.items():
            bad = [integer(7), floating(expected) if kind == 2 else integer(0),
                   floating(float("nan")), floating(float("inf")), struct.pack("<II", 1, 1),
                   struct.pack("<I", kind), floating(expected) + b"trailing"]
            for value in bad:
                with self.subTest(key=key, raw=value):
                    report = self.compare({**self.good, key: value})
                    self.assertFalse(report["passed"])
                    self.assertTrue(any(key in error for error in report["errors"]))
            if key != audit.MODE:
                missing = {name: value for name, value in self.good.items() if name != key}
                self.assertFalse(self.compare(missing)["passed"])

    def test_correct_64_bit_numeric_variants_are_supported(self):
        good = {**self.good, **{key: floating(expected, True) if kind == 3 else integer(expected, True)
                               for key, (kind, expected) in audit.ALLOWED.items()}}
        self.assertTrue(self.compare(good)["passed"])

    def test_any_unapproved_add_change_or_removal_fails_even_default_values(self):
        cases = [
            {**self.good, "custom_features": string("web,debug")},
            {**self.good, "application/config/features": strings(["4.7", "web"])},
            {**self.good, "display/window/size/viewport_width": integer(640)},
            {**self.good, "display/window/stretch/aspect": string("keep")},
            {**self.good, "display/window/size/resizable": struct.pack("<II", 1, 1)},
            {**self.good, "input/toggle_night": struct.pack("<I", 0)},
            {**self.good, "meadow/fixed_camera/zoom": floating(2)},
            {**self.good, "rendering/scaling_3d/scale.web": floating(0.5)},
            {key: raw for key, raw in self.good.items() if key != "application/config/features"},
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                report = self.compare(candidate)
                self.assertFalse(report["passed"])
                self.assertFalse(report["all_other_variant_bytes_exact"])
                self.assertTrue(report["minimal_patch_proposal"])

    def test_equal_decoded_values_do_not_hide_raw_variant_changes(self):
        candidate = {**self.good, "display/window/size/viewport_width": integer(1280, wide=True)}
        self.assertFalse(self.compare(candidate)["passed"])
        before = {**self.before, "meadow/test_value": floating(0.0)}
        candidate = {**self.good, "meadow/test_value": floating(-0.0)}
        self.assertFalse(self.compare(candidate, before)["passed"])

    def test_opaque_settings_are_checked_without_instantiating_godot_objects(self):
        self.assertTrue(self.compare()["passed"])
        candidate = {**self.good, "shader_globals/opaque_fixture": struct.pack("<I", 1000) + b"changed opaque bytes"}
        self.assertFalse(self.compare(candidate)["passed"])

    def test_ecfg_rejects_malformed_headers_lengths_counts_duplicates_and_trailing_data(self):
        good = ecfg({"key": integer(1)})
        cases = [b"", b"ECFG", b"NOPE" + good[4:], good[:-1], good + b"\0",
                 b"ECFG" + struct.pack("<I", 10001), ecfg([("key", integer(1)), ("key", integer(2))]),
                 ecfg({"": integer(1)}), ecfg({"bad\0key": integer(1)}), ecfg({"key": b"x"}),
                 good[:8] + struct.pack("<I", 0xffffffff) + good[12:],
                 good[:12] + b"\xff" + good[13:]]
        for blob in cases:
            with self.subTest(blob=blob), self.assertRaises(ValueError):
                audit.parse_ecfg(blob)

    def test_feature_string_diagnostics_and_unknown_types_are_readable(self):
        self.assertEqual(audit.describe_variant(strings(["4.7", "web"]))["value"], ["4.7", "web"])
        self.assertEqual(audit.describe_variant(string("风起原野"))["value"], "风起原野")
        opaque = audit.describe_variant(struct.pack("<I", 1000))
        self.assertIn("opaque", opaque["encoding"])
        malformed = audit.describe_variant(struct.pack("<II", 34, 0xffffffff))
        self.assertIn("decode_error", malformed)

    def test_pck_entry_and_cli_are_read_only_and_reject_checksum_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, candidate = root / "index.pck", root / "project.binary"
            packed, proposed = fixture_pack(ecfg(self.before)), ecfg(self.good)
            pack.write_bytes(packed)
            candidate.write_bytes(proposed)
            args = ["--original-pack", str(pack), "--candidate", str(candidate), "--json"]
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(audit.main(args), 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report["passed"])
            self.assertEqual(report["source_pack"]["engine"], [4, 7, 0])
            self.assertEqual(pack.read_bytes(), packed)
            self.assertEqual(candidate.read_bytes(), proposed)
            self.assertEqual({path.name for path in root.iterdir()}, {"index.pck", "project.binary"})
            candidate.write_bytes(ecfg({**self.good, "custom_features": string("changed")}))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(args), 1)
            pack.write_bytes(packed[:120] + bytes([packed[120] ^ 1]) + packed[121:])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(args), 2)


def run_web_transport_without_listener():
    """Run ALL existing transport cases with real handlers over in-memory HTTP."""
    from http.client import HTTPResponse
    from types import SimpleNamespace
    import test_web_transport as web

    class MemorySocket:
        def __init__(self, incoming=b""):
            self.incoming, self.outgoing = incoming, bytearray()

        def makefile(self, *_args):
            return io.BytesIO(self.incoming)

        def sendall(self, data):
            self.outgoing.extend(data)

    class MemoryConnection:
        def __init__(self, _host, port, **_options):
            self.directory = port

        def request(self, method, path, headers):
            self.method = method
            lines = [f"{method} {path} HTTP/1.1", "Host: in-memory", "Connection: close"]
            lines.extend(f"{name}: {value}" for name, value in headers.items())
            channel = MemorySocket(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
            web.QuietHandler(channel, ("127.0.0.1", 0), SimpleNamespace(server_name="in-memory", server_port=0),
                             directory=str(self.directory))
            self.response = HTTPResponse(MemorySocket(bytes(channel.outgoing)), method=method)
            self.response.begin()

        def getresponse(self):
            return self.response

        def close(self):
            if hasattr(self, "response"):
                self.response.close()

    @contextmanager
    def memory_preview(directory):
        yield directory

    def no_network(*_args, **_kwargs):
        raise AssertionError("This regression run must not open sockets or start a service")

    print("Full existing transport suite: in-memory HTTP only; no listener or live-service verification.", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromModule(web)
    with patch.object(web, "preview", memory_preview), patch.object(web, "HTTPConnection", MemoryConnection), \
            patch.object(web, "ThreadingHTTPServer", no_network), patch("socket.socket", no_network), \
            patch("socket.create_connection", no_network):
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--web-transport"]:
        sys.exit(run_web_transport_without_listener())
    unittest.main()
