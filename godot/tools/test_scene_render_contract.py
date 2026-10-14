"""Pure contract-publication regressions: no preparation, files, network or engine.

These tests use synthetic payload records, not native light-count proof. The
integration owner must independently accept that proof for the selected PCK.
Run: python -B godot/tools/test_scene_render_contract.py
"""
from copy import deepcopy
import json
import re
import unittest
from unittest.mock import patch

import prepare_web_build as build


COMBINED_SHA = "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"
V117_LITE_SHA = "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79"
DENSE_Q60_SHA = "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"
READY_AO_SHA = "1182ea711300b62fc4cd097acb1321840e75b53d02e884fbcdf02a2e15796460"
FILTERED_SHA = "dfae7b33bbf28a12a456610abb7dd80da36bd5158b5b5cfc8f1527c5150cadfc"
STARTUP_SHA = "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3"
PROGRESSIVE_SHA = "699c08aac4201b9c507d964b6a857247af6f718ebab203da085e5937de0052db"
TEXTURE_STREAM_SHA = "2850c2eebd3382b57866b77aba6dbfe5e4209190c478c502c637bce660fefff4"
PREDICATE_STREAM_SHA = "78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5"
ROOT_CACHE_SHA = "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b"
ORIGINAL_SHA = "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d"
BALANCED_SHA = "68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33"
CONTRACT = {"packSha256": COMBINED_SHA, "spotLights": 0, "areaLights": 0}
SHELL = ('<script src="meadow-quality.js"></script>'
         '<script src="meadow-loader.js"></script>'
         '<script>window.meadowQuality.mount({executable:"index",args:["--seed=3"]});</script>')


def record(digest):
    return {"sha256": digest, "bytes": 1234, "gzipBytes": 567,
            "immutableUrl": "irrelevant." + COMBINED_SHA + ".pck"}


def records():
    return {"index.pck": record(ORIGINAL_SHA),
            "index-balanced.pck": record(BALANCED_SHA),
            "index-lite.pck": record(COMBINED_SHA),
            "index.wasm": record("a" * 64), "index.js": record("b" * 64)}


def manifest(html, name="MEADOW_RENDER_CONTRACTS"):
    matches = re.findall(r"window\." + name + r" = (.*?);\n", html)
    if len(matches) != 1:
        raise AssertionError(f"Expected one {name} assignment, got {len(matches)}")
    return json.loads(matches[0])


class SceneRenderContractTests(unittest.TestCase):
    def setUp(self):
        # The test is allowed to exercise only the real pure manifest function.
        guard = patch.object(build, "prepare", side_effect=AssertionError("No artifact preparation allowed"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_allowlist_is_exact_hashes_with_integer_zero_counts(self):
        self.assertEqual(set(build.SCENE_RENDER_CONTRACTS), {COMBINED_SHA, V117_LITE_SHA, DENSE_Q60_SHA, READY_AO_SHA, FILTERED_SHA, STARTUP_SHA, PROGRESSIVE_SHA, TEXTURE_STREAM_SHA, PREDICATE_STREAM_SHA, ROOT_CACHE_SHA})
        for digest in (COMBINED_SHA, V117_LITE_SHA, DENSE_Q60_SHA, READY_AO_SHA, FILTERED_SHA, STARTUP_SHA, PROGRESSIVE_SHA, TEXTURE_STREAM_SHA, PREDICATE_STREAM_SHA, ROOT_CACHE_SHA):
            value = build.SCENE_RENDER_CONTRACTS[digest]
            self.assertEqual(value, {"spotLights": 0, "areaLights": 0})
            for count in value.values():
                self.assertIs(type(count), int)  # False == 0 must not satisfy the proof schema.

    def test_v117_lite_contract_retains_actual_prepared_hash_not_combined_hash(self):
        sizes = records()
        sizes["index-lite.pck"]["sha256"] = V117_LITE_SHA
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)),
                         {"index-lite.pck": {**CONTRACT, "packSha256": V117_LITE_SHA}})

    def test_composed_lite_retains_new_independently_audited_hash(self):
        sizes = records()
        sizes["index-lite.pck"]["sha256"] = DENSE_Q60_SHA
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)),
                         {"index-lite.pck": {**CONTRACT, "packSha256": DENSE_Q60_SHA}})

    def test_real_manifest_function_only_maps_the_known_combined_pack(self):
        sizes = records()
        before = deepcopy(sizes)
        html = build.quality_html(SHELL, sizes)
        self.assertEqual(manifest(html), {"index-lite.pck": CONTRACT})
        self.assertEqual(set(manifest(html, "MEADOW_QUALITY")), {"original", "balanced", "lite"})
        self.assertEqual(sizes, before)
        self.assertLess(html.index("window.MEADOW_RENDER_CONTRACTS"), html.index("window.meadowQuality.mount("))
        self.assertEqual(build.quality_html(html, sizes), html)
        self.assertNotIn("preload", html)
        self.assertNotIn("fast_compile", html, "publishing metadata does not enable the experiment")
        self.assertIn('mount({executable:"index",args:["--seed=3"]})', html)

    def test_original_balanced_unknown_and_absent_lite_never_borrow_a_contract(self):
        sizes = records()
        sizes.pop("index-lite.pck")
        sizes["future-boss.pck"] = record("f" * 64)
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)), {})
        self.assertEqual(manifest(build.quality_html(SHELL, {})), {})

    def test_future_hash_under_same_lite_filename_does_not_reuse_the_old_contract(self):
        sizes = records()
        sizes["index-lite.pck"]["sha256"] = "f" * 64
        # A filename, immutable URL or caller-supplied zero count is not proof.
        sizes["index-lite.pck"].update(CONTRACT)
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)), {})

    def test_hash_is_content_based_not_an_inferred_quality_or_immutable_alias(self):
        sizes = records()
        sizes["combined-copy.pck"] = sizes.pop("index-lite.pck")
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)), {"combined-copy.pck": CONTRACT})
        sizes["index.js"]["sha256"] = COMBINED_SHA
        sizes["index.wasm"]["sha256"] = COMBINED_SHA
        sizes["index-lite.pck.gz"] = record(COMBINED_SHA)
        sizes["index-lite.PCK"] = record(COMBINED_SHA)
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)), {"combined-copy.pck": CONTRACT})

    def test_missing_or_invalid_hash_values_emit_no_contract(self):
        for digest in (None, False, 0, 1, "", "0", "f" * 64, COMBINED_SHA.upper(), COMBINED_SHA + " "):
            with self.subTest(digest=digest):
                sizes = {"index-lite.pck": record(digest)}
                self.assertEqual(manifest(build.quality_html(SHELL, sizes)), {})
        sizes = {"index-lite.pck": record(COMBINED_SHA)}
        sizes["index-lite.pck"].pop("sha256")
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)), {})

    def test_malformed_payload_records_fail_closed_without_publishing_or_mutating(self):
        for invalid in (None, [], {}, record([]), record({})):
            with self.subTest(record=invalid):
                sizes = {"index-lite.pck": invalid}
                before = deepcopy(sizes)
                try:
                    html = build.quality_html(SHELL, sizes)
                except (TypeError, ValueError, KeyError, AttributeError):
                    pass  # Rejection is safe; no HTML was returned/published.
                else:
                    self.assertEqual(manifest(html), {})
                self.assertEqual(sizes, before)

    def test_contract_counts_come_from_pinned_allowlist_not_arbitrary_record_fields(self):
        sizes = records()
        sizes["index-lite.pck"].update({"spotLights": 10, "areaLights": "0", "packSha256": "f" * 64})
        self.assertEqual(manifest(build.quality_html(SHELL, sizes)), {"index-lite.pck": CONTRACT})

    def test_reinjection_removes_stale_contract_for_missing_or_changed_pack(self):
        original = build.quality_html(SHELL, records())
        for keep_lite in (False, True):
            with self.subTest(keep_lite=keep_lite):
                sizes = records()
                if keep_lite:
                    sizes["index-lite.pck"]["sha256"] = "f" * 64
                else:
                    sizes.pop("index-lite.pck")
                revised = build.quality_html(original, sizes)
                self.assertEqual(manifest(revised), {})
                self.assertEqual(revised.count(build.QUALITY_BEGIN), 1)
                self.assertEqual(revised.count(build.QUALITY_END), 1)
                self.assertNotIn(COMBINED_SHA, revised)
                self.assertEqual(build.quality_html(revised, sizes), revised)

    def test_legacy_shell_does_not_acquire_contracts_or_loader_gates(self):
        legacy = '<script>window.meadowTimeUI.start({executable:"index"});</script>'
        self.assertEqual(build.quality_html(legacy, records()), legacy)


if __name__ == "__main__":
    unittest.main()
