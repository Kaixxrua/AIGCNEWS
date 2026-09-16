"""Finite source/manifest/evidence guards; no extra native process or build."""
from pathlib import Path
import json
import re
import unittest

import build_static_geometry_cache_v135 as builder


def functions(data):
    matches = list(re.finditer(rb"^(?:static )?func ([\w]+)\(", data, re.M))
    return {m[1].decode(): data[m.start():matches[i + 1].start() if i + 1 < len(matches) else len(data)]
            for i, m in enumerate(matches)}


class StaticCacheTests(unittest.TestCase):
    def test_only_three_intended_function_bodies_change(self):
        for name, changed in [("meadow_herb_modules", "_conform"), ("meadow_village_builder", "build"),
                              ("meadow_mountain_relief", "apply")]:
            source = (builder.OUT / "frozen/scripts" / (name + ".gd")).read_bytes()
            before = functions(source)
            after = functions(builder.transform(name, source))
            self.assertEqual(before.keys(), after.keys())
            self.assertEqual([key for key in before if before[key] != after[key]], [changed])
            self.assertNotIn(builder.CAPTURE.encode(), builder.transform(name, source))

    def test_precise_fallback_loops_and_support_queries_remain(self):
        for name in builder.NAMES:
            before = (builder.OUT / "frozen/scripts" / (name + ".gd")).read_bytes()
            after = builder.transform(name, before)
            for needle in [b".image(", b".surface(", b"generate_triangle_mesh("]:
                self.assertEqual(before.count(needle), after.count(needle))
        village = (builder.OUT / "frozen/scripts/meadow_village_builder.gd").read_text()
        patched = builder.transform("meadow_village_builder", village.encode()).decode()
        # The exact pixel predicate/radius arithmetic remains as the cache-miss body.
        radius = 'radius = maxf(radius, Vector2(x, y).distance_to(pivot))'
        self.assertEqual(village.count(radius), 1)
        self.assertEqual(patched.count(radius), 1)
        self.assertEqual(functions(village.encode())["_conform_foundation"], functions(patched.encode())["_conform_foundation"])

    def test_complete_superset_actual_hashes_and_original_before_pins(self):
        manifest = json.loads((builder.OUT / "manifest.json").read_bytes())
        old = json.loads((builder.OLD / "manifest.json").read_bytes())
        entries = {x["entry"]: x for x in manifest["entries"]}
        self.assertEqual(len(entries), 44)
        self.assertTrue(manifest["baselineCompilerAllExact"])
        self.assertEqual(manifest["sourcePackSha256"], old["sourcePackSha256"])
        for item in old["entries"]:
            self.assertIn(item["entry"], entries)
            self.assertEqual(entries[item["entry"]]["beforeSha256"], item.get("beforeSha256"))
        for path, item in entries.items():
            self.assertEqual(builder.sha(Path(item["path"]).read_bytes()), item["sha256"])
            self.assertNotIn("meadow_scene", path)
            self.assertNotIn("meadow_progressive.gd", path)
            self.assertNotIn(".capture", path)
            self.assertTrue(path.startswith(("scripts/", "progressive/static-cache/")))
        self.assertLess(manifest["size"]["incrementalGzipBytes"], 400_000)

    def test_actual_cache_and_full_progressive_native_pass(self):
        proof = json.loads((builder.OUT / "validation.json").read_bytes())
        self.assertEqual(proof["status"], "PASS_EXACT_STATIC_CACHE_NATIVE_FULL_PROGRESSIVE")
        self.assertEqual(proof["manifest"]["sha256"], builder.sha((builder.OUT / "manifest.json").read_bytes()))
        for pin in proof["reports"].values():
            data = Path(pin["file"]).read_bytes()
            self.assertEqual(builder.sha(data), pin["sha256"])
            self.assertFalse(json.loads(data)["errors"])
        capture = json.loads((builder.OUT / "capture-report.json").read_bytes())
        self.assertEqual(capture["counts"], {"herb": 14, "village": 1, "mountain": 2})
        self.assertTrue(all(item["rawReloadExact"] for item in capture["records"]))
        observations = json.loads((builder.AUDIT / "static-cache-observations.json").read_bytes())
        self.assertEqual(len(observations["snapshots"]), 16)
        self.assertTrue(all(len(row["hits"]) == 17 for row in observations["snapshots"]))


if __name__ == "__main__":
    unittest.main()
