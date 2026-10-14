"""Focused, offline CTEX byte-copy and artifact-contract checks; no engine."""
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, patch

import build_progressive_textures_v135 as tool


# Existing encoded 9/4/2/1-pixel mips, copied from the frozen bridge CTEX.
# Tests never encode, resample or write artwork.
MIPS = [bytes.fromhex(value) for value in (
    "524946463600000057454250565038202a0000007001009d012a0900090002403a258c027401400000feee57c6ec78b2e9860c49e525d2e43609a6be8000",
    "524946462e0000005745425056503820220000007001009d012a0400040002403a258c027401400000feef512c613493a1b2813cd000",
    "524946462e0000005745425056503820220000007001009d012a0200020002403a258c027401400000feeeff9bdcb45228abd5e57000",
    "524946461e000000574542505650384c110000002f0000000007d0a99675a8ff8188e87f0000",
)]


def fixture(single=False):
    header = bytearray(52)
    header[:4] = b"GST2"
    struct.pack_into("<III", header, 4, 1, 1254, 1254)
    struct.pack_into("<I", header, 16, 0x800001)  # Preserved flags, not interpreted.
    struct.pack_into("<IHHII", header, 36, 2, 9, 9, 0 if single else 3, 4)
    for payload in (MIPS[:1] if single else MIPS):
        header.extend(struct.pack("<I", len(payload)) + payload)
    return bytes(header)


class ByteCopyTests(unittest.TestCase):
    def test_odd_dimensions_preserve_logical_header_and_all_remaining_records(self):
        original = fixture()
        candidate, drop, reason = tool.select_bootstrap(original, 4)
        self.assertEqual((drop, reason), (1, "selected-existing-mip"))
        parsed = tool.parse_ctex(candidate)
        self.assertEqual(parsed["logical"], (1254, 1254))
        self.assertEqual(parsed["physical"], (4, 4))
        self.assertEqual([r["payload"] for r in parsed["levels"]], MIPS[1:])
        proof = tool.verify_copy(original, candidate, drop)
        self.assertTrue(proof["logicalDimensionsAndHeaderExact"])
        self.assertEqual([r["sourceMip"] for r in proof["levels"]], [1, 2, 3])

    def test_already_small_is_identity(self):
        source = fixture()
        result, drop, reason = tool.select_bootstrap(source, 256)
        self.assertIs(result, source)
        self.assertEqual((drop, reason), (0, "already-small"))

    def test_single_mip_is_preserved_without_synthesizing_lower_pixels(self):
        source = fixture(single=True)
        result, drop, reason = tool.select_bootstrap(source, 4)
        self.assertIs(result, source)
        self.assertEqual((drop, reason), (0, "no-existing-small-mip"))
        self.assertEqual(len(tool.parse_ctex(result)["levels"]), 1)

    def test_invalid_limits_and_drop_rejected(self):
        for value in (0, -1, True, 4.5, None):
            with self.assertRaises(ValueError):
                tool.select_bootstrap(fixture(), value)
        for value in (-1, 4, True, 1.5):
            with self.assertRaises(ValueError):
                tool.copy_from_level(fixture(), value)

    def test_malformed_container_riff_dimensions_and_incomplete_chain_rejected(self):
        source = fixture()
        mutations = [b"bad", source[:-1], source + b"x"]
        for offset, value in ((4, 2), (36, 1), (40, 8), (44, 2), (48, 99), (52, 0), (60, 7)):
            blob = bytearray(source)
            struct.pack_into("<I", blob, offset, value)
            mutations.append(bytes(blob))
        for blob in mutations:
            with self.subTest(length=len(blob)), self.assertRaises(ValueError):
                tool.parse_ctex(blob)

    def test_changed_logical_dimension_or_flag_cannot_claim_exact(self):
        source = fixture()
        for offset in (8, 16, 24):
            result = bytearray(tool.copy_from_level(source, 1))
            result[offset] ^= 1
            with self.assertRaisesRegex(ValueError, "changed"):
                tool.verify_copy(source, bytes(result), 1)

    def test_wrong_source_pin_rejected_before_pack_reader(self):
        source = Mock()
        source.read_bytes.return_value = b"not the pinned pack"
        with patch.object(tool, "read_pack") as reader:
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                tool.pinned_entries(source, tool.SOURCE_SHA)
            reader.assert_not_called()

    def test_unmapped_or_duplicate_ctex_rejected(self):
        entry = ".godot/imported/example.ctex"
        remap = b'[remap]\npath="res://.godot/imported/example.ctex"\n'
        with self.assertRaises(ValueError):
            tool.import_map({entry: fixture()})
        with self.assertRaises(ValueError):
            tool.import_map({entry: fixture(), "one.png.import": remap, "two.png.import": remap})

    def test_scope_and_existing_output_rejected_before_inventory(self):
        with self.assertRaises(ValueError):
            tool.write_new(tool.ROOT / "outside-texture-scope.ctex", b"x")
        for destination in (tool.ROOT, tool.SCOPE):
            with patch.object(tool, "inventory") as inventory:
                with self.assertRaises(ValueError):
                    tool.generate(destination)
                inventory.assert_not_called()

    def test_only_two_profiles_and_explicit_initial_blockers(self):
        self.assertEqual(tool.PROFILES, {"bootstrap128": 128, "bootstrap256": 256})
        self.assertEqual(len(tool.INITIAL_CONTRACTS), 8)
        self.assertIn("dragon-physical-pixels", tool.INITIAL_CONTRACTS["castle-dragon-turns-v57"])
        self.assertIn("absolute-pixel-mesh-build", tool.INITIAL_CONTRACTS["windmill-village-v50"])
        self.assertIn("exact-alpha-derived-geometry", tool.INITIAL_CONTRACTS["castle-town-v62"])
        self.assertNotIn(tool.WATER_NAME, tool.INITIAL_CONTRACTS)


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tool.SCOPE / "candidate-01"
        if not (cls.directory / "proof.json").is_file():
            raise unittest.SkipTest("Offline candidate has not been generated")
        cls.proof = json.loads((cls.directory / "proof.json").read_text(encoding="utf-8"))
        cls.inventory = json.loads((cls.directory / "inventory.json").read_text(encoding="utf-8"))
        cls.source = tool.pinned_entries(tool.SOURCE, tool.SOURCE_SHA)
        cls.core = tool.pinned_entries(tool.OBSERVED_CORE, tool.CORE_SHA)
        cls.manifests = {key: json.loads(Path(value["path"]).read_text(encoding="utf-8"))
                         for key, value in cls.proof["manifests"].items()}

    def test_exact_inventory_and_untouched_sources(self):
        self.assertEqual(len(self.inventory["textures"]), 32)
        self.assertEqual(self.inventory["singleMipTextures"], [])
        self.assertEqual(self.proof["exactFullTextureCopies"], 31)
        self.assertEqual(self.proof["packWrites"], 0)
        self.assertFalse(list(self.directory.rglob("*.pck")))
        for profile, pin in self.proof["manifests"].items():
            self.assertEqual(tool.sha(Path(pin["path"]).read_bytes()), pin["sha256"])
            self.assertFalse(self.manifests[profile]["runtimeReady"])

    def test_every_generated_initial_mip_and_full_file_exact(self):
        mappings = tool.import_map(self.source)
        for profile, manifest in self.manifests.items():
            self.assertEqual(len(manifest["replacements"]), 31)
            for row in manifest["replacements"]:
                before = self.source[row["entry"]]
                after = Path(row["initialFile"]).read_bytes()
                expected, drop, _ = tool.select_bootstrap(before, manifest["maxPhysicalEdge"])
                self.assertEqual(after, expected)
                self.assertEqual(tool.sha(after), row["initial"]["sha256"])
                self.assertEqual(tool.verify_copy(before, after, drop), row["proof"])
                self.assertEqual(Path(row["full"]["path"]).read_bytes(), before)
                self.assertEqual(tool.sha(before), row["full"]["sha256"])
                self.assertEqual(row["source"], mappings[row["entry"]]["source"])
                self.assertIs(row["textureSpec"]["inPlace"], True)
                self.assertEqual(row["textureSpec"]["source"], row["source"])
                self.assertEqual(row["textureSpec"]["resource"], "res://" + row["full"]["entry"])
                self.assertEqual(tool.sha(self.source[row["importEntry"]]), row["importSha256"])

    def test_existing_water_is_not_output_or_dropped_again(self):
        self.assertEqual(self.proof["waterFilesEmitted"], 0)
        self.assertFalse(list(self.directory.rglob("*river-ripples*.ctex")))
        for manifest in self.manifests.values():
            water = manifest["water"]
            original, current = self.source[water["entry"]], self.core[water["entry"]]
            self.assertEqual(current, tool.copy_from_level(original, 2))
            self.assertEqual(tool.sha(current), water["expectedCoreSha256"])
            self.assertEqual(tool.sha(original), water["requiredFullSha256"])

    def test_budget_distinguishes_conditional_savings_from_unadapted_runtime(self):
        totals = self.inventory["totals"]
        self.assertEqual(totals["observedCoreTextureBytes"], 5295824)
        for profile, manifest in self.manifests.items():
            budget = manifest["budget"]
            self.assertGreater(budget["rawSavingsVsObservedCore"], 2_000_000)
            self.assertLess(budget["rawSavingsIfEightInitialContractTexturesStayOriginal"], 2_000_000)
            emitted = sum(len(Path(row["initialFile"]).read_bytes()) for row in manifest["replacements"])
            self.assertEqual(emitted + manifest["water"]["expectedCoreBytes"], budget["coreTextureBytesIncludingExistingWater"])
        self.assertLess(totals["profiles"]["bootstrap128"]["coreTextureBytesIncludingExistingWater"],
                        totals["profiles"]["bootstrap256"]["coreTextureBytesIncludingExistingWater"])

    def test_all_initial_risks_and_code_reference_holders_are_reported(self):
        for manifest in self.manifests.values():
            blocked = [row for row in manifest["replacements"] if row["keepOriginalUntilInitialConditionsHandled"]]
            self.assertEqual(len(blocked), 8)
            self.assertTrue(all(row["directCodeReferences"] for row in manifest["replacements"]))
        references = self.inventory["codeReferences"]
        self.assertTrue(any(row["packedEntry"] == "shaders/meadow_dragon.gdshader"
                            for row in references["packedShaderPhysicalPixelAccesses"]))
        self.assertTrue(any("animals[].texture" in row for row in references["runtimeHeldReferences"]))

    def test_sampler_policy_preserves_all_cpu_images_and_dragon(self):
        expected_savings = {"bootstrap128": 1476104, "bootstrap256": 1262564}
        for profile, manifest in self.manifests.items():
            policy = manifest["recommendedSamplerPolicy"]
            self.assertEqual(policy, tool.sampler_policy(self.inventory, profile))
            self.assertEqual(len(policy["keepOriginal"]), 9)
            self.assertEqual(policy["applyTextureCount"], 22)
            self.assertEqual(policy["rawSavingsVsObservedCore"], expected_savings[profile])
            self.assertFalse(set(policy["applyEntries"]) & {r["entry"] for r in policy["keepOriginal"]})
            applied = [r for r in manifest["replacements"] if r["entry"] in policy["applyEntries"]]
            self.assertEqual(sum("/creatures/" in r["source"] for r in applied), 4)
            self.assertTrue(all(r["textureSpec"]["inPlace"] for r in applied))


if __name__ == "__main__":
    unittest.main(verbosity=2)
