"""Pure/mock checks plus read-only frozen pins; never creates or repacks a PCK."""
import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import build_sky_overlay_v135 as tool


class PureTests(unittest.TestCase):
    def setUp(self):
        self.before = {"a": b"scene", tool.ENTRY: b"old", "script.gdc": b"script"}
        self.after = dict(self.before, **{tool.ENTRY: b"new"})

    def test_single_sky_delta(self):
        proof = tool.verify_entry_delta(self.before, self.after, b"new")
        self.assertEqual(sum(not r["byteExact"] for r in proof), 1)

    def test_other_entry_change_rejected(self):
        self.after["script.gdc"] = b"other"
        with self.assertRaisesRegex(ValueError, "Only sky"):
            tool.verify_entry_delta(self.before, self.after, b"new")

    def test_twin_other_resource_change_rejected(self):
        tool.verify_twins(self.before, self.before)
        wrong = dict(self.before, **{"script.gdc": b"different"})
        with self.assertRaisesRegex(ValueError, "Twin logical bytes differ"):
            tool.verify_twins(self.before, wrong)

    def test_twin_manifest_is_not_a_blanket_exception(self):
        both = {"progressive/manifest.json": b'{}'}
        with self.assertRaisesRegex(ValueError, "Pinned twin transport manifest"):
            tool.verify_twins(both, both)

    def test_missing_added_reordered_or_noop_rejected(self):
        cases = [dict(self.after, extra=b"x"), {k:v for k,v in self.after.items() if k != "a"},
                 dict(reversed(list(self.after.items()))), self.before]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                tool.verify_entry_delta(self.before, case, b"new")

    def test_chunk_paths_counts_and_indices_fail_closed(self):
        rows = [{"index":i, "file":f"detail-{i}-{'a'*12}.pck", "sha256":"a"*64, "bytes":10} for i in range(12)]
        valid = {"version":1, "chunks":rows}
        self.assertEqual(tool.validate_chunks(valid), rows)
        for field, value in (("file", "../other.pck"), ("index", 2), ("sha256", "wrong"), ("bytes", True)):
            wrong = copy.deepcopy(valid); wrong["chunks"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                tool.validate_chunks(wrong)
        with self.assertRaises(ValueError):
            tool.validate_chunks({"version":1, "chunks":rows[:-1]})

    def test_overlay_rejects_extra_entries_and_other_source(self):
        m = json.loads((tool.SKY / "manifest.json").read_bytes())
        data = (tool.SKY / "entries" / tool.ENTRY).read_bytes()
        tool.validate_overlay(m, data)
        for field, value in (("entries", m["entries"] * 2), ("sourcePackSha256", "0"*64)):
            wrong = copy.deepcopy(m); wrong[field] = value
            with self.assertRaises(ValueError): tool.validate_overlay(wrong, data)
        wrong = copy.deepcopy(m); wrong["entries"][0]["entry"] = "shaders/meadow_water.gdshader"
        with self.assertRaises(ValueError): tool.validate_overlay(wrong, data)
        with self.assertRaises(ValueError): tool.validate_overlay(m, data + b" ")

    def test_two_edits_default48_and_body_guards(self):
        old = (tool.SKY / "before/meadow_sky.gdshader").read_bytes()
        new = (tool.SKY / "entries" / tool.ENTRY).read_bytes()
        tool.verify_sky_delta(old, new)
        for wrong in (new.replace(b" = 48;", b" = 47;"), new.replace(b"3.71", b"3.72")):
            with self.assertRaises(ValueError): tool.verify_sky_delta(old, wrong)

    def test_variant_metadata_never_inherits_acceptance_or_old_sizes(self):
        old = {"coreSha256":"old", "coreBytes":100, "coreGzipBytes":80,
               "visualAcceptance":"passed", "tenSecondTarget":"passed", "nativeRuntimeValidation":"passed",
               "textureUpgrades":[{"sha256":"same"}], "chunks":12, "sourcePackSha256":"original"}
        snapshot = copy.deepcopy(old)
        new = tool.variant_proof(old, "new", 120, 99, [{"entry":tool.ENTRY}])
        self.assertEqual(old, snapshot)
        self.assertEqual((new["coreSha256"],new["coreBytes"],new["coreGzipBytes"]), ("new",120,99))
        self.assertEqual(new["visualAcceptance"], "pending")
        self.assertEqual(new["readinessValidation"], "pending")
        self.assertEqual(new["nativeRuntimeValidation"], "not-run")
        self.assertEqual(new["tenSecondTarget"], "unverified")
        self.assertEqual(new["textureUpgrades"], old["textureUpgrades"])

    def test_script_proof_reuses_every_original_pin(self):
        old = {"mainGdcSha256":"a", "controllerGdcSha256":"b", "mainSourceSha256":"c", "rootConformHook":True}
        new = tool.script_proof(old)
        for key,value in old.items(): self.assertEqual(new[key], value)
        self.assertFalse(new["recompiled"])
        self.assertEqual(new["readinessValidation"], "pending")

    def test_boot_updates_only_original_core_binding(self):
        old = json.loads((tool.BOOT_SOURCE / "bootstrap-manifest.json").read_bytes())
        new = tool.boot_manifest(old, "new-core")
        self.assertEqual(new["coreSha256"], "new-core")
        for key,value in old.items():
            if key != "coreSha256": self.assertEqual(new[key], value)
        self.assertTrue(new["bootstrapBytesExactToBoot10"])
        self.assertFalse(new["reportsSceneReady"])
        self.assertFalse(new["recompiled"])

    def test_existing_or_outside_outputs_refused(self):
        with self.assertRaises(ValueError): tool.ensure_fresh(tool.SOURCE, tool.BOOT_OUTPUT)
        with patch.object(Path, "exists", return_value=True):
            with self.assertRaisesRegex(ValueError, "existing output"): tool.ensure_fresh()
        with self.assertRaises(ValueError): tool.emit(tool.ROOT / "godot/shaders/never-write", b"no")

    def test_bad_input_never_reaches_writer_or_mkdir(self):
        with patch.object(tool, "ensure_fresh"), patch.object(tool, "preflight", side_effect=ValueError("bad pin")), \
                patch.object(tool, "write_pack") as writer, patch.object(Path, "mkdir") as mkdir:
            with self.assertRaisesRegex(ValueError, "bad pin"): tool.build()
            writer.assert_not_called(); mkdir.assert_not_called()

    def test_copy_verifies_source_before_writing(self):
        with patch.object(tool, "pinned", side_effect=ValueError("bad chunk")), patch.object(tool, "emit") as emit:
            with self.assertRaisesRegex(ValueError, "bad chunk"):
                tool.copy_exact(Path("source"), Path("target"), "digest")
            emit.assert_not_called()

    def test_cli_requires_explicit_action(self):
        with patch.object(tool, "build") as build, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): tool.main([])
            build.assert_not_called()

    def test_check_cannot_build(self):
        with patch.object(tool, "preflight", return_value={"entries":{"mode5":self.before}}), \
                patch.object(tool, "build") as build, patch.object(tool, "write_pack") as writer, contextlib.redirect_stdout(io.StringIO()):
            tool.main(["--check"])
            build.assert_not_called(); writer.assert_not_called()


class FrozenInputsTests(unittest.TestCase):
    def test_current_pins_and_all_chunks_read_only(self):
        prior = {p:p.exists() for p in (tool.OUTPUT,tool.BOOT_OUTPUT)}
        with patch.object(tool, "write_pack", side_effect=AssertionError("Tests must not repack")), \
                patch.object(tool, "emit", side_effect=AssertionError("Tests must not write")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("Tests must not create output")):
            inputs = tool.preflight()
        self.assertEqual(len(inputs["entries"]["mode5"]), 222)
        for kind in tool.CORE_PINS:
            self.assertEqual(len(inputs["chunks"][kind]), 12)
            self.assertEqual(tool.sha(inputs["entries"][kind][tool.ENTRY]), tool.BEFORE_SHA)
            self.assertEqual(tool.sha(inputs["entries"][kind]["progressive/manifest.json"]), tool.EMBEDDED_MANIFEST_PINS[kind])
        # The known encoding-specific manifests pass, but any changed byte fails.
        wrong = dict(inputs["entries"]["mode5"])
        wrong["progressive/manifest.json"] += b" "
        with self.assertRaisesRegex(ValueError, "Pinned twin transport manifest"):
            tool.verify_twins(inputs["entries"]["native"], wrong)
        self.assertEqual(tool.sha(inputs["replacement"]), tool.AFTER_SHA)
        self.assertEqual(prior, {p:p.exists() for p in prior})


if __name__ == "__main__":
    unittest.main()
