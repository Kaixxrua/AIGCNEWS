"""Structural regression tests for the isolated sunbreak hoist, never run a scene."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_fast_shader_pack as builder


class SunbreakHoistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory, cls.original = builder.entry_blobs(builder.SOURCE)
        cls.after = builder.hoist(cls.original)

    def test_pinned_measured_source(self):
        self.assertEqual(builder.sha(builder.SOURCE.read_bytes()), builder.SOURCE_SHA)
        self.assertEqual(self.inventory["engine"], [4, 7, 2])

    def test_exact_five_resource_allowlist(self):
        self.assertEqual(set(self.after), builder.ALLOWED)
        self.assertEqual(len(self.after), 5)

    def test_all_four_cloud_functions_are_byte_identical(self):
        for name in ("sunbreak_hash", "sunbreak_noise", "sunbreak_scope", "sunbreak_transmission"):
            self.assertEqual(builder.function_body(self.original[builder.INCLUDE], name),
                             builder.function_body(self.after[builder.INCLUDE], name))

    def test_light_body_only_uses_new_read(self):
        before = builder.function_body(self.original[builder.INCLUDE], "light")
        after = builder.function_body(self.after[builder.INCLUDE], "light")
        self.assertEqual(after.replace(b"sunbreak_fragment_transmission", builder.EXPRESSION), before)
        self.assertNotIn(builder.EXPRESSION, after)

    def test_direct_fragment_assignment_not_vertex_approximation(self):
        for path in builder.CONSUMERS:
            self.assertIn(builder.ASSIGNMENT, builder.function_body(self.after[path], "fragment"))
            self.assertNotIn(b"sunbreak_fragment_transmission", builder.function_body(self.after[path], "vertex"))

    def test_cutout_assignment_keeps_existing_conditional_gate(self):
        after = self.after["shaders/meadow_cutout_surface.gdshaderinc"].replace(b"\r\n", b"\n")
        self.assertIn(b"#ifdef MEADOW_SUNBREAK\n    sunbreak_specular = SPECULAR;\n" +
                      builder.ASSIGNMENT + b"\n#endif", after)

    def test_all_original_vertex_functions_exact(self):
        for path in builder.CONSUMERS:
            self.assertEqual(builder.function_body(self.original[path], "vertex"),
                             builder.function_body(self.after[path], "vertex"))

    def test_adding_uniform_is_rejected(self):
        bad = dict(self.after)
        bad[builder.INCLUDE] += b"\nuniform float surprise = 1.0;\n"
        with self.assertRaises(ValueError):
            builder.verify_hoist(self.original, bad)

    def test_changing_cloud_strength_is_rejected(self):
        bad = dict(self.after)
        bad[builder.INCLUDE] = bad[builder.INCLUDE].replace(b"= 0.72;", b"= 0.71;")
        with self.assertRaises(ValueError):
            builder.verify_hoist(self.original, bad)

    def test_changing_light_response_is_rejected(self):
        bad = dict(self.after)
        bad[builder.INCLUDE] = bad[builder.INCLUDE].replace(b"> 0.999", b"> 0.998")
        with self.assertRaises(ValueError):
            builder.verify_hoist(self.original, bad)

    def test_water_or_settings_replacement_is_rejected(self):
        for path in ("project.binary", "shaders/meadow_water.gdshader", "scripts/meadow_scene.gdc"):
            bad = dict(self.after)
            bad[path] = self.original[path]
            with self.assertRaises(ValueError):
                builder.verify_hoist(self.original, bad)

    def test_missing_or_duplicate_anchor_rejected(self):
        for source in (b"no marker", b"anchor anchor"):
            with self.assertRaises(ValueError):
                builder.once(source, b"anchor", b"replacement")

    def test_reapplying_is_rejected(self):
        with self.assertRaises(ValueError):
            builder.hoist(self.after)

    def test_reject_non_owned_destination_without_writes(self):
        with self.assertRaises(ValueError):
            builder.build(builder.ROOT / "godot/shaders/must-not-exist")

    def test_reject_existing_destination_without_writes(self):
        with self.assertRaises(ValueError):
            builder.build(builder.SCOPE)

    def test_existing_source_shader_bytes_match_pinned_pack(self):
        for path in builder.ALLOWED:
            self.assertEqual((builder.ROOT / "godot" / path).read_bytes(), self.original[path])


class BuiltCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = builder.SCOPE / "sunbreak-hoist-01"
        manifest = cls.directory / "shader-replacements.v1.json"
        if not manifest.exists():
            raise unittest.SkipTest("Candidate not built yet; run builder then re-run tests")
        cls.manifest = json.loads(manifest.read_text())
        cls.proof = json.loads((cls.directory / "proof.json").read_text())
        _, cls.original = builder.entry_blobs(builder.SOURCE)
        _, cls.after = builder.entry_blobs(cls.directory / "index-lite.pck")

    def test_exact_changed_set_and_all_other_bytes(self):
        self.assertEqual(set(self.original), set(self.after))
        changed = {path for path in self.original if self.original[path] != self.after[path]}
        self.assertEqual(changed, builder.ALLOWED)

    def test_manifest_pins_and_payloads(self):
        self.assertEqual(self.manifest["sourcePckSha256"], builder.SOURCE_SHA)
        self.assertEqual(self.manifest["candidatePckSha256"], builder.sha((self.directory / "index-lite.pck").read_bytes()))
        for row in self.manifest["replacements"]:
            self.assertEqual(row["beforeSha256"], builder.sha(self.original[row["path"]]))
            self.assertEqual(row["afterSha256"], builder.sha(self.after[row["path"]]))
            self.assertEqual(Path(row["file"]).read_bytes(), self.after[row["path"]])

    def test_offline_language_compilation_and_uniform_interfaces(self):
        check = self.proof["shaderLanguageValidation"]
        self.assertEqual(check["shaderLanguageCompile"], "passed")
        self.assertTrue(check["uniformInterfacesExactlyEqual"])
        self.assertEqual(check["baseline"]["shaderCount"], 20)
        self.assertEqual(check["candidate"]["shaderCount"], 20)

    def test_protected_snapshot_unchanged(self):
        before = json.loads((self.directory / "protected-before.json").read_text())
        self.assertEqual(builder.protected_snapshot(), before)


class BoundedLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.original = builder.entry_blobs(builder.SOURCE)
        cls.after = builder.bounded_loops(cls.original)

    def test_four_entry_allowlist(self):
        self.assertEqual(set(self.after), set(builder.LOOP_RULES))
        self.assertEqual(len(self.after), 4)

    def test_default_iterations_72_48_not_reduced(self):
        for count in (72, 48):
            self.assertEqual(list(range(count)), list(range(min(count, count))))
        self.assertIn(b"uniform int v118_contact_shadow_loop_count = 72;", self.after["shaders/meadow_ground_surface.gdshaderinc"])
        self.assertIn(b"uniform int v118_cloud_loop_count = 48;", self.after["shaders/meadow_sky.gdshader"])

    def test_existing_count_loops_equivalent_below_within_and_above_bounds(self):
        for count in (-2147483648, *range(-2, 70), 2147483647):
            original_iterations = []
            for index in range(32):
                if index >= count:
                    break
                original_iterations.append(index)
            self.assertEqual(original_iterations, list(range(max(0, min(count, 32)))))

    def test_array_bounds_and_existing_guards_unchanged(self):
        for path, (count, name, anchor, new_uniform) in builder.LOOP_RULES.items():
            self.assertIn(f"min({name}, {count})".encode(), self.after[path])
            if not new_uniform:
                self.assertIn(f"if (i >= {name}) {{ break; }}".encode(), self.after[path])
            else:
                self.assertIn(anchor.encode(), self.after[path])

    def test_uniform_default_change_rejected(self):
        bad = dict(self.after)
        path = "shaders/meadow_sky.gdshader"
        bad[path] = bad[path].replace(b"v118_cloud_loop_count = 48", b"v118_cloud_loop_count = 47")
        with self.assertRaises(ValueError):
            builder.verify_bounded_loops(self.original, bad)

    def test_body_arithmetic_change_rejected(self):
        bad = dict(self.after)
        path = "shaders/meadow_ground_surface.gdshaderinc"
        bad[path] = bad[path].replace(b"shadow *= mix(0.72", b"shadow *= mix(0.73")
        with self.assertRaises(ValueError):
            builder.verify_bounded_loops(self.original, bad)

    def test_not_combined_with_hoist(self):
        self.assertNotIn(builder.INCLUDE, self.after)
        for blob in self.after.values():
            self.assertNotIn(b"sunbreak_fragment_transmission", blob)

    def test_existing_reserved_name_rejected(self):
        bad = dict(self.original)
        bad["a-stale-uniform.tres"] = b"v118_cloud_loop_count"
        with self.assertRaises(ValueError):
            builder.bounded_loops(bad)


class BuiltLoopCandidateTests(unittest.TestCase):
    def test_candidate_entry_byte_contract_and_language_compile(self):
        directory = builder.SCOPE / "bounded-loops-01"
        manifest_path = directory / "shader-replacements.v1.json"
        if not manifest_path.exists():
            self.skipTest("Bounded-loop candidate not built yet")
        manifest = json.loads(manifest_path.read_text())
        _, before = builder.entry_blobs(builder.SOURCE)
        _, after = builder.entry_blobs(directory / "index-lite.pck")
        self.assertEqual(set(before), set(after))
        self.assertEqual({path for path in before if before[path] != after[path]}, set(builder.LOOP_RULES))
        self.assertEqual(manifest["candidatePckSha256"], builder.sha((directory / "index-lite.pck").read_bytes()))
        proof = json.loads((directory / "proof.json").read_text())
        compile_check = proof["shaderLanguageValidation"]
        self.assertEqual(compile_check["shaderLanguageCompile"], "passed")
        self.assertTrue(compile_check["existingUniformInterfacesExactlyEqual"])
        self.assertFalse(compile_check["uniformInterfacesExactlyEqual"])
        self.assertEqual(set(compile_check["addedUniforms"]), set(builder.ADDED_UNIFORMS))


class MaterialLoopProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.original = builder.entry_blobs(builder.SOURCE)
        cls.after = builder.bounded_material_loops(cls.original)

    def test_three_includes_only_no_sky_hoist_or_water(self):
        self.assertEqual(set(self.after), builder.MATERIAL_ALLOWED)
        self.assertEqual(len(self.after), 3)
        for path in (builder.INCLUDE, "shaders/meadow_sky.gdshader", "shaders/meadow_water.gdshader"):
            self.assertNotIn(path, self.after)

    def test_two_redundant_breaks_removed_exactly(self):
        for path, (name, _) in builder.MATERIAL_LOOP_RULES.items():
            self.assertIn(f"i < min(32, {name})".encode(), self.after[path])
            self.assertNotIn(f"if (i >= {name}) {{ break; }}".encode(), self.after[path])

    def test_iteration_sequences_match_for_all_boundary_classes(self):
        for count in (-2147483648, *range(-2, 100), 2147483647):
            before = []
            for index in range(32):
                if index >= count:
                    break
                before.append(index)
            self.assertEqual(before, list(range(max(0, min(32, count)))))

    def test_default72_and_both_sided_clamp(self):
        ground = self.after[builder.MATERIAL_GROUND]
        self.assertEqual(ground.count(b"uniform int contact_shadow_iterations = 72;"), 1)
        self.assertIn(b"i < clamp(contact_shadow_iterations, 0, 72)", ground)
        self.assertEqual(list(range(72)), list(range(max(0, min(72, 72)))))

    def test_changed_original_default_or_iteration_count_rejected(self):
        for old, new in ((b"iterations = 72;", b"iterations = 71;"),
                         (b"shadow *= mix(0.72", b"shadow *= mix(0.70")):
            bad = dict(self.after)
            bad[builder.MATERIAL_GROUND] = bad[builder.MATERIAL_GROUND].replace(old, new)
            with self.assertRaises(ValueError):
                builder.verify_material_loops(self.original, bad)

    def test_shader_code_reverse_proof(self):
        builder.verify_material_loops(self.original, self.after)
        bad = dict(self.after)
        bad[builder.MATERIAL_GROUND] += b"\nuniform int different = 1;\n"
        with self.assertRaises(ValueError):
            builder.verify_material_loops(self.original, bad)

    def test_no_material_override_even_in_decoded_rscc(self):
        evidence = builder.verify_no_material_override(self.original)
        self.assertEqual(evidence["default"], 72)
        self.assertEqual(evidence["bounds"], [0, 72])
        self.assertGreaterEqual(len(evidence["decodedRsccEntries"]), 5)
        bad = dict(self.original)
        bad["fake-material.tres"] = b"shader_parameter/contact_shadow_iterations = 1"
        with self.assertRaises(ValueError):
            builder.verify_no_material_override(bad)


class BuiltMaterialLoopProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = builder.SCOPE / "bounded-material-loops-01"
        manifest_path = cls.directory / "shader-replacements.v1.json"
        if not manifest_path.exists():
            raise unittest.SkipTest("Material-loop candidate not built yet")
        cls.manifest = json.loads(manifest_path.read_text())
        cls.proof = json.loads((cls.directory / "proof.json").read_text())
        _, cls.before = builder.entry_blobs(builder.SOURCE)
        _, cls.after = builder.entry_blobs(cls.directory / "index-lite.pck")

    def test_entire_pack_exact_except_three_entries(self):
        self.assertEqual(set(self.before), set(self.after))
        self.assertEqual({path for path in self.before if self.before[path] != self.after[path]}, builder.MATERIAL_ALLOWED)
        self.assertEqual(self.manifest["candidatePckSha256"], builder.sha((self.directory / "index-lite.pck").read_bytes()))
        for row in self.manifest["replacements"]:
            self.assertEqual(row["beforeSha256"], builder.sha(self.before[row["path"]]))
            self.assertEqual(row["afterSha256"], builder.sha(self.after[row["path"]]))

    def test_compiler_only_new_int_on_two_ground_wrappers(self):
        result = self.proof["shaderLanguageValidation"]
        self.assertEqual(result["shaderLanguageCompile"], "passed")
        self.assertTrue(result["existingUniformInterfacesExactlyEqual"])
        self.assertEqual(set(result["addedUniforms"]), set(builder.MATERIAL_ADDED_UNIFORMS))
        for rows in result["addedUniforms"].values():
            self.assertEqual([row["name"] for row in rows], ["contact_shadow_iterations"])
            self.assertEqual([row["type"] for row in rows], [2])

    def test_defaults_sky_water_and_frozen_source_proof(self):
        self.assertEqual(self.proof["newUniformDefaultAndNoOverrideProof"]["default"], 72)
        self.assertTrue(self.proof["skyEntryByteExact"])
        self.assertTrue(self.proof["waterShaderAndMaterialsExact"])
        self.assertTrue(self.proof["sunbreakIncludeByteExact"])
        self.assertEqual(builder.protected_snapshot(), json.loads((self.directory / "protected-before.json").read_text()))


class CombinedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.original = builder.entry_blobs(builder.SOURCE)
        cls.hoisted = builder.hoist(cls.original)
        cls.intermediate = dict(cls.original)
        cls.intermediate.update(cls.hoisted)
        cls.after = builder.combined(cls.original)

    def test_exact_six_unique_entries(self):
        self.assertEqual(set(self.after), builder.COMBINED_ALLOWED)
        self.assertEqual(len(self.after), 6)
        self.assertEqual(builder.ALLOWED & builder.MATERIAL_ALLOWED, {
            "shaders/meadow_ground_surface.gdshaderinc", "shaders/meadow_cutout_surface.gdshaderinc"})

    def test_explicit_hoist_then_material_transform(self):
        stage_two = builder.bounded_material_loops(self.intermediate)
        for path in builder.MATERIAL_ALLOWED:
            self.assertEqual(self.after[path], stage_two[path])
        for path in builder.ALLOWED - builder.MATERIAL_ALLOWED:
            self.assertEqual(self.after[path], self.hoisted[path])
        builder.verify_combined(self.original, self.after)

    def test_overlap_retains_both_changes(self):
        for path in builder.ALLOWED & builder.MATERIAL_ALLOWED:
            self.assertEqual(self.after[path].count(builder.ASSIGNMENT), 1)
        self.assertIn(b"clamp(contact_shadow_iterations, 0, 72)", self.after[builder.MATERIAL_GROUND])
        cutout = self.after["shaders/meadow_cutout_surface.gdshaderinc"]
        self.assertIn(b"min(32, window_count)", cutout)
        self.assertNotIn(b"if (i >= window_count) { break; }", cutout)

    def test_naive_merge_that_loses_hoist_rejected(self):
        bad = dict(self.hoisted)
        bad.update(builder.bounded_material_loops(self.original))
        with self.assertRaises(ValueError):
            builder.verify_combined(self.original, bad)

    def test_reverse_overwrite_that_loses_loop_changes_rejected(self):
        bad = builder.bounded_material_loops(self.original)
        bad.update(self.hoisted)
        with self.assertRaises(ValueError):
            builder.verify_combined(self.original, bad)

    def test_no_sky_water_or_changed_source_mutation(self):
        for path in ("shaders/meadow_sky.gdshader", "shaders/meadow_water.gdshader", "project.binary", "scripts/meadow_scene.gdc"):
            self.assertNotIn(path, self.after)
        _, reloaded = builder.entry_blobs(builder.SOURCE)
        self.assertEqual(reloaded, self.original)

    def test_stage_one_still_matches_frozen_hoist_candidate(self):
        manifest = json.loads((builder.SCOPE / "sunbreak-hoist-01/shader-replacements.v1.json").read_text())
        for row in manifest["replacements"]:
            self.assertEqual(self.hoisted[row["path"]], Path(row["file"]).read_bytes())


class BuiltCombinedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = builder.SCOPE / "combined-01"
        if not (cls.directory / "shader-replacements.v1.json").exists():
            raise unittest.SkipTest("Combined candidate not built yet")
        cls.manifest = json.loads((cls.directory / "shader-replacements.v1.json").read_text())
        cls.proof = json.loads((cls.directory / "proof.json").read_text())
        _, cls.original = builder.entry_blobs(builder.SOURCE)
        _, cls.after = builder.entry_blobs(cls.directory / "index-lite.pck")

    def test_six_changed_178_byte_exact_and_pack_hash(self):
        self.assertEqual(set(self.original), set(self.after))
        changed = {path for path in self.original if self.original[path] != self.after[path]}
        self.assertEqual(changed, builder.COMBINED_ALLOWED)
        self.assertEqual(len(self.original) - len(changed), 178)
        self.assertEqual(builder.sha((self.directory / "index-lite.pck").read_bytes()), self.manifest["candidatePckSha256"])
        builder.verify_combined(self.original, {path: self.after[path] for path in changed})

    def test_composition_hash_chain_and_exact_intermediate(self):
        composition = json.loads((self.directory / "composition.json").read_text())
        self.assertEqual(composition["orderedTransforms"], ["original-v117", "sunbreak-hoist", "bounded-material-loops"])
        self.assertTrue(composition["noIntermediatePckBuilt"])
        hoisted = dict(self.original)
        hoisted.update(builder.hoist(self.original))
        for row in composition["entries"]:
            path = row["path"]
            self.assertEqual(row["originalSha256"], builder.sha(self.original[path]))
            self.assertEqual(row["afterHoistSha256"], builder.sha(hoisted[path]))
            self.assertEqual(Path(row["hoistedSourceFile"]).read_bytes(), hoisted[path])
            self.assertEqual(row["afterMaterialLoopsSha256"], builder.sha(self.after[path]))

    def test_compiler_defaults_sky_water_and_protected_tree(self):
        check = self.proof["shaderLanguageValidation"]
        self.assertEqual(check["shaderLanguageCompile"], "passed")
        self.assertEqual(check["candidate"]["shaderCount"], 20)
        self.assertTrue(check["existingUniformInterfacesExactlyEqual"])
        self.assertEqual(set(check["addedUniforms"]), set(builder.MATERIAL_ADDED_UNIFORMS))
        self.assertEqual(self.proof["newUniformDefaultAndNoOverrideProof"]["default"], 72)
        self.assertTrue(self.proof["skyEntryByteExact"])
        self.assertTrue(self.proof["waterShaderAndMaterialsExact"])
        self.assertEqual(builder.protected_snapshot(), json.loads((self.directory / "protected-before.json").read_text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
