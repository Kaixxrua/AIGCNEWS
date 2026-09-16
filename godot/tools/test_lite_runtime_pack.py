"""Fail-closed scoping tests for the one authorized lite runtime replacement."""
import json
from pathlib import Path
import tempfile
import unittest

from build_lite_pack import runtime_replacements, sha


class RuntimePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before = b"GDSC\x64\x00\x00\x00original-token-fixture"
        self.after = b"GDSC\x64\x00\x00\x00candidate-token-fixture"
        self.source = self.root / "original.pck"
        self.source.write_bytes(b"prefix" + self.before)
        self.candidate = self.root / "main.gdc"
        self.candidate.write_bytes(self.after)
        (self.root / "proof.json").write_text('{"fixture":true}')
        self.manifest_path = self.root / "runtime.json"
        self.manifest = {"sourcePckSha256": sha(self.source.read_bytes()), "replacements": [{
            "path": "scripts/meadow_scene.gdc", "file": "main.gdc", "proof": "proof.json",
            "beforeSha256": sha(self.before), "afterSha256": sha(self.after)}]}
        self.entries = {"scripts/meadow_scene.gdc": {"offset": 6, "bytes": len(self.before)}}

    def run_candidate(self):
        self.manifest_path.write_text(json.dumps(self.manifest))
        return runtime_replacements(self.source, self.entries, self.manifest_path, sha(self.source.read_bytes()))

    def test_exact_scope_and_artifact_proof_are_recorded(self):
        original = self.source.read_bytes()
        replacements, changes = self.run_candidate()
        self.assertEqual(replacements, {"scripts/meadow_scene.gdc": self.after})
        self.assertEqual(changes[0]["kind"], "lite-runtime")
        self.assertEqual(changes[0]["proofSha256"], sha((self.root / "proof.json").read_bytes()))
        self.assertEqual(self.source.read_bytes(), original)

    def test_wrong_pack_and_wrong_before_hash_rejected(self):
        for key, target in (("sourcePckSha256", self.manifest),
                            ("beforeSha256", self.manifest["replacements"][0])):
            original = target[key]
            target[key] = "0" * 64
            with self.assertRaises(ValueError):
                self.run_candidate()
            target[key] = original

    def test_other_script_and_multiple_entries_rejected(self):
        row = self.manifest["replacements"][0]
        row["path"] = "scripts/meadow_weather.gdc"
        with self.assertRaises(ValueError):
            self.run_candidate()
        row["path"] = "scripts/meadow_scene.gdc"
        self.manifest["replacements"].append(dict(row))
        with self.assertRaises(ValueError):
            self.run_candidate()

    def test_tampered_candidate_and_different_bytecode_version_rejected(self):
        self.candidate.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.run_candidate()
        changed = b"GDSC\x65\x00\x00\x00new-version"
        self.candidate.write_bytes(changed)
        self.manifest["replacements"][0]["afterSha256"] = sha(changed)
        with self.assertRaises(ValueError):
            self.run_candidate()

    def test_missing_proof_rejected(self):
        self.manifest["replacements"][0]["proof"] = "missing.json"
        with self.assertRaises(FileNotFoundError):
            self.run_candidate()


if __name__ == "__main__":
    unittest.main()
