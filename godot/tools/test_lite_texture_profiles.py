"""Focused v126 tests: original-derived mips, exact alpha, frozen full-scene base."""
import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import build_lite_pack as lite
from build_web_quality import write_pack
from inspect_web_pack import read_pack


def texture_fixture(size=(64, 32), lossy_level=None, seed=126):
    blob = bytearray(52)
    struct.pack_into("<9I", blob, 0, 844387143, 1, *size, 226492416, 4294967295, 0, 0, 0)
    count = max(size).bit_length() - 1
    struct.pack_into("<IHHII", blob, 36, 2, *size, count, 5)
    rng = np.random.default_rng(seed)
    for level in range(count + 1):
        w, h = max(1, size[0] >> level), max(1, size[1] >> level)
        pixels = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)
        # Includes transparent edges, semitransparency, opaque pixels, and odd sizes.
        pixels[:, :, 3] = np.linspace(0, 255, w, dtype=np.uint8)
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, "WEBP", lossless=level != lossy_level,
                                     quality=76, exact=True, alpha_quality=100)
        data = stream.getvalue()
        blob += struct.pack("<I", len(data)) + data
    return bytes(blob)


def pack_fixture(root, name, resources):
    seed = root / (name + ".seed")
    header = bytearray(112)
    struct.pack_into("<6I", header, 0, 0x43504447, 4, 4, 7, 2, 0)
    entries, contents = [], bytearray(header)
    for path, data in resources.items():
        entries.append(dict(path=path, offset=len(contents), bytes=len(data)))
        contents.extend(data)
    seed.write_bytes(contents)
    result = root / (name + ".pck")
    write_pack(seed, dict(version=4, entries=entries), result, {})
    return result


def payloads(path):
    blob = path.read_bytes()
    return {row["path"]: blob[row["offset"]:row["offset"] + row["bytes"]]
            for row in read_pack(path)["entries"]}


class TextureProfileTests(unittest.TestCase):
    def test_two_bounded_profiles_and_unknown_texture_rejected(self):
        self.assertEqual(lite.TEXTURE_PROFILES, {"mip2-q60": 60, "mip2-q48": 48})
        for profile in lite.TEXTURE_PROFILES:
            with self.subTest(profile=profile):
                self.assertEqual(lite.texture_recipe("meadow-patches-v37", profile)["mip_drop"], 2)
                self.assertEqual(lite.texture_recipe("castle-dragon-turns-v57", profile)["mip_drop"], 0)
                for name in lite.KEEP_LITE_TEXTURES:
                    self.assertIsNone(lite.texture_recipe(name, profile))
                with self.assertRaisesRegex(ValueError, "Unreviewed"):
                    lite.texture_recipe("future-boss-atlas", profile)
        with self.assertRaises(ValueError):
            lite.texture_recipe("meadow-patches-v37", "future-profile")

    def test_odd_atlas_keeps_logical_size_original_mips_and_exact_alpha(self):
        original = texture_fixture((67, 35))
        for profile in lite.TEXTURE_PROFILES:
            result, _ = lite.compress_ctex(original, "meadow-patches-v37",
                                           **lite.texture_recipe("meadow-patches-v37", profile))
            proof = lite.verify_texture(original, result, "meadow-patches-v37")
            self.assertEqual(result[:36], original[:36])
            self.assertEqual(proof["logicalSize"], [67, 35])
            self.assertEqual(proof["physicalAfter"], [16, 8])
            self.assertEqual(proof["mipDrop"], 2)
            self.assertEqual([row["sourceLevel"] for row in proof["levels"]], list(range(2, 7)))
            self.assertEqual(proof["levels"][-1]["size"], [1, 1])
            self.assertTrue(all(row["alphaExact"] for row in proof["levels"]))

    def test_protected_atlas_cannot_drop_physical_mip(self):
        original = texture_fixture()
        for name in lite.PRESERVE_PHYSICAL:
            result, _ = lite.compress_ctex(original, name, **lite.texture_recipe(name, "mip2-q48"))
            self.assertEqual(lite.verify_texture(original, result, name)["physicalAfter"], [64, 32])
            with self.assertRaises(ValueError):
                lite.compress_ctex(original, name, mip_drop=1)

    def test_reject_lossy_original_even_in_later_mip_and_malformed_riff(self):
        for level in (0, 3, 6):
            original = texture_fixture(lossy_level=level)
            with self.assertRaisesRegex(ValueError, "lossy/re-encoded"):
                lite.verify_texture(original, original, "meadow-patches-v37")
        with self.assertRaises(ValueError):
            lite.is_lossless_webp(b"RIFFbroken")

    def test_reject_changed_alpha_header_missing_mip_and_water(self):
        original = texture_fixture()
        data = bytearray(original)
        data[8] ^= 1
        with self.assertRaisesRegex(ValueError, "logical/header"):
            lite.verify_texture(original, bytes(data), "meadow-patches-v37")
        data = bytearray(original)
        data[36 + 8] = 5  # Declare fewer mips and remove the last encoded level.
        last = lite.decode_ctex(original)[2][-1][0]
        del data[-len(last) - 4:]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            lite.verify_texture(bytes(data), bytes(data), "meadow-patches-v37")
        changed, _ = lite.compress_ctex(original, "meadow-patches-v37", mip_drop=0, quality=48)
        with self.assertRaisesRegex(ValueError, "water"):
            lite.verify_texture(original, changed, "river-ripples-v37")
        _, _, levels = lite.decode_ctex(original)
        pixels = np.asarray(levels[0][1]).copy()
        pixels[0, 0, 3] = 255
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, "WEBP", lossless=True, exact=True)
        encoded = stream.getvalue()
        changed = (original[:52] + struct.pack("<I", len(encoded)) + encoded
                   + original[56 + len(levels[0][0]):])
        with self.assertRaisesRegex(ValueError, "alpha/dimensions"):
            lite.verify_texture(original, changed, "meadow-patches-v37")

    def test_invalid_encoder_options_rejected(self):
        for options in ({"mip_drop": -1}, {"mip_drop": True}, {"quality": 0}, {"quality": 101}):
            with self.assertRaises(ValueError):
                lite.compress_ctex(texture_fixture(), "meadow-patches-v37", **options)


class TextureCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        names = lite.PRESERVE_PHYSICAL | lite.EXTRA_MIP_TEXTURES | lite.KEEP_LITE_TEXTURES
        original = {f".godot/imported/{name}.png-fixture.ctex": texture_fixture(seed=126 + index)
                    for index, name in enumerate(sorted(names))}
        original.update({"scenes/main.scn": b"all scene objects", "scripts/main.gdc": b"all scripts",
                         "shaders/cloud.gdshaderinc": b"original", "project.binary": b"ECFGfixture",
                         "shaders/water.gdshader": b"water exact"})
        base = dict(original)
        for path, data in original.items():
            name = Path(path).name.split(".png-")[0]
            if path.endswith(".ctex") and name not in lite.PRESERVE_BYTES:
                base[path] = lite.compress_ctex(data, name)[0]
        base["shaders/cloud.gdshaderinc"] = b"v125 combined shader changes retained"
        self.original = pack_fixture(self.root, "original", original)
        self.base = pack_fixture(self.root, "base", base)
        self.original_hash, self.base_hash = lite.sha(self.original.read_bytes()), lite.sha(self.base.read_bytes())

    def run_build(self, output, profile="mip2-q48"):
        with patch.object(lite, "TEXTURE_ORIGINAL_SHA256", self.original_hash), \
                patch.object(lite, "TEXTURE_BASE_SHA256", self.base_hash), contextlib.redirect_stdout(io.StringIO()):
            return lite.build_texture_candidate(self.base, output, self.original, profile)

    def test_actual_composition_only_uses_original_as_encoder_input(self):
        output = self.root / "candidate" / "index-lite.pck"
        original = payloads(self.original)
        with patch.object(lite, "compress_ctex", wraps=lite.compress_ctex) as encoder:
            report = self.run_build(output)
        self.assertEqual(encoder.call_count, 22)
        for call in encoder.call_args_list:
            data, name = call.args
            self.assertEqual(data, original[f".godot/imported/{name}.png-fixture.ctex"])
        before, after = payloads(self.base), payloads(output)
        self.assertEqual(before.keys(), after.keys())
        for path, data in before.items():
            name = Path(path).name.split(".png-")[0]
            if not path.endswith(".ctex") or name in lite.KEEP_LITE_TEXTURES:
                self.assertEqual(after[path], data)
        self.assertEqual(lite.sha(self.base.read_bytes()), self.base_hash)
        self.assertEqual(lite.sha(self.original.read_bytes()), self.original_hash)
        self.assertEqual(gzip.decompress(output.with_suffix(".pck.gz").read_bytes()), output.read_bytes())
        self.assertLess(report["liteBytes"], report["sourceBytes"])
        self.assertLess(report["liteGzipBytes"], report["sourceGzipBytes"])
        self.assertTrue(report["allNonTexturesByteExact"])
        self.assertEqual(report, json.loads(output.with_name("lite-build.json").read_text()))
        with self.assertRaisesRegex(ValueError, "fresh"):
            self.run_build(output)

    def test_wrong_frozen_inputs_rejected_before_creating_candidate(self):
        output = self.root / "rejected" / "index-lite.pck"
        with self.assertRaisesRegex(ValueError, "pinned"):
            lite.build_texture_candidate(self.base, output, self.original, "mip2-q60")
        self.assertFalse(output.exists())

    def test_no_win_keeps_base_entry_without_reencoding_it(self):
        def too_large(blob, name, **options):
            # A valid full-size original cannot beat these smaller fixture lite entries.
            return blob, {}
        with patch.object(lite, "compress_ctex", side_effect=too_large):
            with self.assertRaisesRegex(ValueError, "no smaller"):
                self.run_build(self.root / "no-win" / "index-lite.pck")
        self.assertEqual(lite.sha(self.base.read_bytes()), self.base_hash)


@unittest.skipUnless(os.environ.get("MEADOW_TEST_TEXTURE_ARTIFACTS") == "1",
                     "Opt-in read-only validation of the two real v126 candidates")
class ActualTextureArtifactTests(unittest.TestCase):
    def test_real_candidates_frozen_entries_headers_mips_and_alpha(self):
        root = Path(__file__).resolve().parents[2]
        original_path = root / "artifacts/v114/index.pck"
        base_path = root / "artifacts/v125/index-lite.pck"
        self.assertEqual(lite.sha(original_path.read_bytes()), lite.TEXTURE_ORIGINAL_SHA256)
        self.assertEqual(lite.sha(base_path.read_bytes()), lite.TEXTURE_BASE_SHA256)
        original, base = payloads(original_path), payloads(base_path)
        for profile in lite.TEXTURE_PROFILES:
            with self.subTest(profile=profile):
                path = root / "artifacts/startup-v126/textures" / profile / "index-lite.pck"
                report = json.loads(path.with_name("lite-build.json").read_text())
                candidate = payloads(path)
                self.assertEqual(lite.sha(path.read_bytes()), report["liteSha256"])
                self.assertEqual(gzip.decompress(path.with_suffix(".pck.gz").read_bytes()), path.read_bytes())
                self.assertEqual(base.keys(), candidate.keys())
                self.assertEqual(len(candidate), 184)
                changed, mips = 0, 0
                for resource, data in candidate.items():
                    name = Path(resource).name.split(".png-")[0]
                    if not resource.endswith(".ctex") or name in lite.KEEP_LITE_TEXTURES:
                        self.assertEqual(data, base[resource], resource)
                    if not resource.endswith(".ctex"):
                        continue
                    changed += data != base[resource]
                    self.assertEqual(data[:36], original[resource][:36], resource)
                    logical, fmt, levels = lite.decode_ctex(data)
                    original_logical, original_fmt, original_levels = lite.decode_ctex(original[resource])
                    self.assertEqual((logical, fmt), (original_logical, original_fmt))
                    drop = len(original_levels) - len(levels)
                    expected_drop = (0 if name in lite.PRESERVE_PHYSICAL | lite.PRESERVE_BYTES
                                     else 2 if name in lite.EXTRA_MIP_TEXTURES | lite.MATERIALS else 1)
                    self.assertEqual(drop, expected_drop, resource)
                    self.assertEqual(levels[-1][1].size, (1, 1))
                    for index, (_, decoded) in enumerate(levels):
                        selected = original_levels[drop + index][1]
                        self.assertEqual(decoded.size, selected.size)
                        np.testing.assert_array_equal(np.asarray(decoded)[:, :, 3], np.asarray(selected)[:, :, 3])
                        mips += 1
                self.assertEqual(changed, 22)
                self.assertEqual(mips, 319)
                self.assertEqual(report["exactEntryCount"], 162)


if __name__ == "__main__":
    unittest.main()
