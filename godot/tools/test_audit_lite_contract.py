"""In-memory contract/negative fixtures. No engine, files, services or exports.

E:/Anaconda3/python.exe -B -m unittest discover -s godot/tools -p test_audit_lite_contract.py
"""

import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import audit_lite_contract as audit


def pck(entries, header_marker=0):
    blob = bytearray(112)
    struct.pack_into("<4s5IQQ", blob, 0, b"GDPC", 4, 4, 7, 2, 2, 112, 0)
    blob[50] = header_marker
    records = []
    for name, data in entries.items():
        blob.extend(b"\0" * (-len(blob) % 16))
        records.append((name, len(blob) - 112, data))
        blob.extend(data)
    blob.extend(b"\0" * (-len(blob) % 16))
    struct.pack_into("<Q", blob, 32, len(blob))
    blob.extend(struct.pack("<I", len(records)))
    for name, offset, data in records:
        encoded = name.encode()
        encoded += b"\0" * (-len(encoded) % 4)
        blob.extend(struct.pack("<I", len(encoded)) + encoded)
        blob.extend(struct.pack("<QQ", offset, len(data)) + hashlib.md5(data).digest() + struct.pack("<I", 0))
    return bytes(blob)


def atlas(size=(72, 36)):
    image = Image.new("RGBA", size, (40, 100, 30, 0))
    draw = ImageDraw.Draw(image)
    for row in range(2):
        for col in range(4):
            x, y = col * size[0] / 4, row * size[1] / 2
            draw.rectangle((x + 3, y + 3, x + size[0] / 4 - 4, y + size[1] / 2 - 3),
                           fill=(40 + col * 20, 100, 30, 100 + row * 120))
    return image


def levels(image):
    return [image if i == 0 else image.convert("RGBa").resize(
        (max(1, image.width >> i), max(1, image.height >> i)), Image.Resampling.BOX).convert("RGBA")
        for i in range(max(image.size).bit_length())]


def ctex(images, logical=None, fmt=5):
    logical = logical or images[0].size
    result = bytearray(52)
    struct.pack_into("<4s4I", result, 0, b"GST2", 1, *logical, 226492416)
    struct.pack_into("<IHHII", result, 36, 2, *images[0].size, len(images) - 1, fmt)
    for image in images:
        output = io.BytesIO()
        image.save(output, "WEBP", lossless=True, exact=True)
        encoded = output.getvalue()
        result.extend(struct.pack("<I", len(encoded)) + encoded)
    return bytes(result)


def texture_rule(before, after, images, mip=1, resource="assets/creatures/leaf-hare-v54.png"):
    return {"path": ".godot/imported/atlas.ctex", "kind": "texture",
            "before_sha256": audit.sha(before), "after_sha256": audit.sha(after),
            "resource": resource, "reason": "Approved selected mip", "source_mip": mip,
            "logical_size": list(images[0].size), "stored_size": list(images[mip].size),
            "atlas": {"layout": "grid", "grid": [4, 2]},
            "runtime": {"coordinates": "logical-preserved", "adapted_scripts": []}}


def change(name, kind, before, after):
    return {"path": name, "kind": kind, "reason": "Scoped candidate for independent review",
            "before_sha256": audit.sha(before) if before is not None else None,
            "after_sha256": audit.sha(after)}


def manifest(a, b, changes=()):
    return {"schema_version": 1, "original_sha256": a.header["sha256"],
            "lite_sha256": b.header["sha256"], "changes": list(changes)}


def native_manifest(a, b, rows=()):
    return {"schemaVersion": 1, "source": "original.pck", "sourceSha256": a.header["sha256"],
            "sourceBytes": a.header["bytes"], "liteBytes": b.header["bytes"], "liteSha256": b.header["sha256"],
            "fullScene": True, "waterTextureUnchanged": True, "changes": list(rows)}


def ecfg(records):
    output = bytearray(b"ECFG" + struct.pack("<I", len(records)))
    for name, data in records.items():
        encoded = name.encode()
        output.extend(struct.pack("<I", len(encoded)) + encoded + struct.pack("<I", len(data)) + data)
    return bytes(output)


class NativeSchemaTests(unittest.TestCase):
    def setUp(self):
        images = levels(atlas((71, 35)))
        old, new = ctex(images), ctex(images[1:], images[0].size)
        path = ".godot/imported/leaf-hare-v54.png-hash.ctex"
        imported = {"assets/creatures/leaf-hare-v54.png.import": f'path="res://{path}"\n'.encode()}
        self.a = audit.Snapshot(pck({**imported, path: old}))
        self.b = audit.Snapshot(pck({**imported, path: new}))
        decoded = audit.decode_texture(new)
        evidence = [{"sourceLevel": i + 1, "size": list(im.size), "bytes": decoded["encoded_sizes"][i],
                     "alphaExact": True, "alphaSha256": audit.sha(im.getchannel("A").tobytes()),
                     "visibleRgbRmse": 0.0} for i, im in enumerate(decoded["levels"])]
        self.record = {"path": path, "kind": "lite-ctex", "before": len(old), "after": len(new),
                       "beforeSha256": audit.sha(old), "afterSha256": audit.sha(new),
                       "logicalSize": [71, 35], "physicalBefore": [71, 35], "physicalAfter": [35, 17],
                       "mipDrop": 1, "quality": 76, "levels": evidence, "reason": "screen-detail-budget"}

    def test_actual_builder_schema_needs_no_manual_conversion(self):
        result = audit.audit(self.a, self.b, native_manifest(self.a, self.b, [self.record]), required_resources=())
        self.assertEqual(result["status"], "STRUCTURAL_PASS", result["errors"])
        self.assertEqual(result["manifest_format"], "build_lite_pack.schemaVersion1")
        self.assertEqual(result["checks"][0]["frame_count"], 8)

    def test_native_evidence_is_verified_not_trusted(self):
        for key, bad in (("sourceLevel", 7), ("size", [1, 1]), ("bytes", 1), ("alphaExact", False),
                         ("alphaSha256", "0" * 64), ("visibleRgbRmse", 99)):
            row = copy.deepcopy(self.record)
            row["levels"][0][key] = bad
            result = audit.audit(self.a, self.b, native_manifest(self.a, self.b, [row]), required_resources=())
            with self.subTest(key=key):
                self.assertEqual(result["status"], "FAIL")

    def test_native_sizes_and_fullscene_claims_checked(self):
        for key, bad in (("sourceBytes", 1), ("liteBytes", 1), ("fullScene", False), ("waterTextureUnchanged", False)):
            contract = native_manifest(self.a, self.b, [self.record])
            contract[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit.audit(self.a, self.b, contract, required_resources=())

    def test_native_noop_geometry_replacement_has_no_false_regression(self):
        name, data = "assets/baked/v110/rock-occlusion.bin", b"unchanged atomic replacement"
        a = audit.Snapshot(pck({name: data}))
        row = {"path": name, "kind": "lite-geometry", "before": len(data), "after": len(data),
               "beforeSha256": audit.sha(data), "afterSha256": audit.sha(data)}
        result = audit.audit(a, a, native_manifest(a, a, [row]), required_resources=())
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertEqual(result["pending"], [])
        self.assertTrue(result["checks"][0]["unchanged_replacement"])


class AORebindTests(unittest.TestCase):
    def setUp(self):
        old = bytearray(240)
        struct.pack_into("<I", old, 0, len(old) - 4)
        old[36:68] = struct.pack("<II", 4, 14) + b"mesh_signature\0\0" + struct.pack("<II", 4, 64)
        old[68:132], old[168:232] = b"1" * 64, b"3" * 64
        new = bytearray(old)
        new[68:132] = b"2" * 64
        self.original = {name: (bytes(old) if name == audit.AO_PATH else b"old " + name.encode())
                         for name in audit.GEOMETRY_SET}
        self.candidate = {name: (bytes(new) if name == audit.AO_PATH else b"new " + name.encode())
                          for name in audit.GEOMETRY_SET}
        self.original["scripts/meadow_rock_occlusion.gdc"] = b"original validation"
        self.candidate["scripts/meadow_rock_occlusion.gdc"] = b"original validation"
        self.records = {}
        for name in audit.GEOMETRY_SET:
            self.records[name] = {"path": name, "kind": "lite-geometry",
                                  "before": len(self.original[name]), "after": len(self.candidate[name]),
                                  "beforeSha256": audit.sha(self.original[name]),
                                  "afterSha256": audit.sha(self.candidate[name])}
        self.records[audit.AO_PATH]["checks"] = {
            "kind": audit.AO_REBIND_KIND,
            "patches": [{"field": "mesh_signature", "offset": 68, "length": 64,
                         "before": "1" * 64, "after": "2" * 64}],
            "signature_bypass": False, "visibility_and_sampling_geometry_exact": True,
            "original_rock_POSITION_NORMAL_TANGENT_COLOR_INDEX_exact": True,
            "all_original_terrain_arrays_exact": True, "visibility_prefix_bytes_and_mapping_exact": True,
            "runtime_probe": {"applied": True, "original_runtime_helper": True, "off_tree": True,
                              "all_sample_indices_and_nonblue_attributes_exact": True,
                              "mesh_signature": "2" * 64, "terrain_signature": "3" * 64,
                              "visibility_samples_checked": 317556, "collision_shapes_checked": 1}}
        for name, label, channels in (("assets/baked/v77/detail.scn", "SolidLimestoneGeology", range(6)),
                                      ("assets/baked/v77/terrain.scn", "ContinuousMeadow", (0, 1, 2, 4, 5))):
            hashes = {str(i): str(i) * 64 for i in channels}
            self.records[name]["checks"] = {
                "topology_vertex_index_triangle_order_exact": True,
                "collision_arrays_and_node_material_mesh_metadata_exact": True, "signature_bypass": False,
                "surfaces": [{"label": label, "decoded_channel_sha256_before": dict(hashes),
                              "decoded_channel_sha256_after": dict(hashes), "position_max_vector_error": 0,
                              "normal_max_angle_degrees": 0,
                              "topology": {"new_degenerate_triangles": 0, "winding_reversals": 0}}]}

    def compare(self, candidate=None, records=None):
        a = audit.Snapshot(pck(self.original))
        b = audit.Snapshot(pck(self.candidate if candidate is None else candidate))
        rows = (self.records if records is None else records).values()
        with mock.patch.object(audit, "AO_ORIGINAL_SHA256", audit.sha(self.original[audit.AO_PATH])):
            return audit.audit(a, b, native_manifest(a, b, rows), required_resources=())

    def test_native_signature_only_rebind_not_blanket_unchanged(self):
        result = self.compare()
        self.assertEqual(result["status"], "STRUCTURAL_PASS", result["errors"])
        row = next(r for r in result["checks"] if r["path"] == audit.AO_PATH)
        self.assertTrue(row["all_other_ao_bytes_exact"])
        self.assertEqual(len(row["bound_geometry_sha256"]), 7)
        self.assertEqual(row["semantic_status"], "REVIEW_REQUIRED")

    def test_visibility_or_metadata_byte_change_rejected_even_with_updated_pin(self):
        for offset in (5, 33, 140, 239):
            candidate, records = copy.deepcopy(self.candidate), copy.deepcopy(self.records)
            bad = bytearray(candidate[audit.AO_PATH])
            bad[offset] ^= 1
            candidate[audit.AO_PATH] = bytes(bad)
            records[audit.AO_PATH]["afterSha256"] = audit.sha(bad)
            with self.subTest(offset=offset):
                self.assertIn("non-signature bytes changed", " ".join(self.compare(candidate, records)["errors"]))

    def test_signature_proof_cannot_patch_another_field_or_span(self):
        for key, value in (("offset", 168), ("length", 63), ("field", "terrain_signature"),
                           ("before", "0" * 64), ("after", "4" * 64)):
            records = copy.deepcopy(self.records)
            records[audit.AO_PATH]["checks"]["patches"][0][key] = value
            with self.subTest(key=key):
                self.assertEqual(self.compare(records=records)["status"], "FAIL")

    def test_no_proof_bypass_or_partial_seven_resource_set(self):
        for mutation in ("missing_proof", "signature_bypass", "missing_detail"):
            records = copy.deepcopy(self.records)
            if mutation == "missing_proof":
                records[audit.AO_PATH].pop("checks")
            elif mutation == "signature_bypass":
                records[audit.AO_PATH]["checks"]["signature_bypass"] = True
            else:
                records.pop("assets/baked/v77/detail.scn")
            with self.subTest(mutation=mutation):
                self.assertEqual(self.compare(records=records)["status"], "FAIL")

    def test_sample_geometry_must_be_exact_not_approximately_equal(self):
        for key in ("position_max_vector_error", "normal_max_angle_degrees", "decoded_channel_sha256_after"):
            records = copy.deepcopy(self.records)
            surface = records["assets/baked/v77/detail.scn"]["checks"]["surfaces"][0]
            if key == "decoded_channel_sha256_after":
                surface[key]["1"] = "9" * 64
            else:
                surface[key] = .000001
            with self.subTest(field=key):
                self.assertEqual(self.compare(records=records)["status"], "FAIL")

    def test_runtime_probe_and_companion_pins_are_bound(self):
        for key, value in (("applied", False), ("mesh_signature", "0" * 64),
                           ("terrain_signature", "0" * 64), ("visibility_samples_checked", 317555)):
            records = copy.deepcopy(self.records)
            records[audit.AO_PATH]["checks"]["runtime_probe"][key] = value
            with self.subTest(field=key):
                self.assertEqual(self.compare(records=records)["status"], "FAIL")
        records = copy.deepcopy(self.records)
        records["assets/baked/v77/detail.scn"]["afterSha256"] = "0" * 64
        self.assertIn("companion geometry hash mismatch", " ".join(self.compare(records=records)["errors"]))

    def test_runtime_validation_code_cannot_be_replaced(self):
        name = "scripts/meadow_rock_occlusion.gdc"
        result = self.compare(candidate={**self.candidate, name: b"bypass runtime gate"})
        self.assertIn("unchanged original runtime scripts", " ".join(result["errors"]))


    def startup_row(self):
        name = audit.STARTUP_PATH
        self.original[name], self.candidate[name] = b"original startup", b"attested startup"
        self.records[name] = {"path": name, "kind": "lite-runtime", "before": len(self.original[name]),
                              "after": len(self.candidate[name]), "beforeSha256": audit.sha(self.original[name]),
                              "afterSha256": audit.sha(self.candidate[name]), "reason": "startup audit only"}
        return {"runtime_proof_status": "PINNED_SOURCE_COMPILER_ATTESTATION_VERIFIED",
                "exact_runtime_exception": name, "after_sha256": audit.sha(self.candidate[name]),
                "semantic_status": "REVIEW_REQUIRED"}

    def test_verified_startup_proof_is_checked_before_ao_and_stays_pending(self):
        with mock.patch.object(audit, "verify_runtime_proof", return_value=self.startup_row()) as verify:
            result = self.compare()
        self.assertEqual(result["status"], "STRUCTURAL_PASS", result["errors"])
        verify.assert_called_once()
        row = next(r for r in result["checks"] if r["path"] == audit.AO_PATH)
        self.assertEqual(row["attested_runtime_exceptions"], [audit.STARTUP_PATH])
        self.assertTrue(any("final-pack native/release-Web" in s for s in result["pending"]))

    def test_runtime_kind_alone_never_unlocks_ao(self):
        self.startup_row()
        with mock.patch.object(audit, "verify_runtime_proof", side_effect=ValueError("missing proof")):
            result = self.compare()
        self.assertIn("missing proof", " ".join(result["errors"]))
        self.assertIn("unchanged original runtime scripts", " ".join(result["errors"]))

    def test_verified_exception_cannot_target_another_script_or_other_bytes(self):
        for field, value in (("exact_runtime_exception", "scripts/meadow_rock_occlusion.gdc"),
                             ("after_sha256", "0" * 64)):
            proof = self.startup_row()
            proof[field] = value
            with self.subTest(field=field), mock.patch.object(audit, "verify_runtime_proof", return_value=proof):
                self.assertIn("unchanged original runtime scripts", " ".join(self.compare()["errors"]))


class StartupProofTests(unittest.TestCase):
    """All compiler files/proofs are mocked bytes; no fixture disk writes."""

    def setUp(self):
        self.base = audit.STARTUP_ROOT / "in-memory-test"
        self.files = {}
        self.old_gdc = b"GDSC" + struct.pack("<I", 101) + b"original compiled fixture"
        self.new_gdc = b"GDSC" + struct.pack("<I", 101) + b"candidate compiled fixture"
        physics = (b"func _physics_process(delta: float) -> void:\n\tif not audit_complete:\n"
                   b"\t\t_audit_walk_surface()\n\t\taudit_complete = true\n"
                   b"\tif not scale_guide.visible:\n\t\treturn\n\ttravel += delta\n\n")
        helpers = (b"func _startup_audit_enabled() -> bool:\n\treturn OS.is_debug_build()\n\n"
                   b"func _report_startup_audit(status: String) -> void:\n\tprint(status)\n\n")
        self.old_source = b"extends Node3D\n" + physics + b"func _other() -> void:\n\tpass\n"
        self.new_source = self.old_source.replace(physics, physics.replace(
            b"\t\t_audit_walk_surface()", b"\t\tif _startup_audit_enabled():\n\t\t\t_audit_walk_surface()") + helpers)
        self.a = audit.Snapshot(pck({audit.STARTUP_PATH: self.old_gdc, "scripts/ao.gdc": b"original AO"}))
        self.b = audit.Snapshot(pck({audit.STARTUP_PATH: self.new_gdc, "scripts/ao.gdc": b"original AO"}))
        for key, value in (("STARTUP_PACK_SHA256", self.a.header["sha256"]),
                           ("STARTUP_GDC_SHA256", audit.sha(self.old_gdc)),
                           ("STARTUP_SOURCE_SHA256", audit.sha(self.old_source)),
                           ("STARTUP_PATCHED_SHA256", audit.sha(self.new_source))):
            patch = mock.patch.object(audit, key, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.rule = change(audit.STARTUP_PATH, "runtime", self.old_gdc, self.new_gdc)
        self.row = {"path": audit.STARTUP_PATH, "kind": "lite-runtime", "before": len(self.old_gdc),
                    "after": len(self.new_gdc), "beforeSha256": audit.sha(self.old_gdc),
                    "afterSha256": audit.sha(self.new_gdc), "reason": "reviewed startup only",
                    "proof": str(self.base / "startup-proof.json")}
        self.rule["builder_record"] = self.row
        contracts = {"base": "Node3D", "methods": [{"name": "_physics_process"}], "properties": [], "signals": []}
        self.validation = {"engine": "4.7.2-stable (official)", "mode": "validate", "failures": 0,
                           "original_and_patched_compiled_scripts_valid": True,
                           "existing_script_contracts_equal": True, "no_main_scene_instantiation": True,
                           "test_build_flag_injected_only_in_function_harness": True,
                           "added_methods": audit.STARTUP_HELPERS, "original_contract": contracts,
                           "patched_contract": {**contracts, "methods": contracts["methods"] +
                                                [{"name": n} for n in audit.STARTUP_HELPERS]}, "branch_cases": {}}
        for name, count in (("original_release_function", 1), ("patched_release_function", 0),
                             ("patched_debug_function", 1), ("release_web_default", 0), ("exact_cli_opt_in", 1),
                             ("cli_lookalike", 0), ("web_query_opt_in", 1), ("native_ignores_web_query", 0),
                             ("architecture_independent", 0), ("debug_reentry_guard", 1)):
            row = {"audit_calls": count, "audit_complete": True, "off_tree": True,
                   "travel": .75, "walker_position": [.75, 1.01999998092651, -12.0], "guard_set_during_audit": True}
            (self.validation if name.endswith("_function") else self.validation["branch_cases"])[name] = row
        self.proof = {"schema": "lite-startup-compiler-proof-v115-1", "status": "passed",
                      "originalPck": {"sha256": audit.STARTUP_PACK_SHA256, "entry": audit.STARTUP_PATH,
                                      "entrySha256": audit.STARTUP_GDC_SHA256},
                      "originalSource": {"path": str(self.base / "original.gd"), "sha256": audit.STARTUP_SOURCE_SHA256},
                      "patchedSource": {"path": str(self.base / "patched.gd"), "sha256": audit.STARTUP_PATCHED_SHA256},
                      "candidateGdc": {"path": str(self.base / "meadow_scene.gdc"),
                                       "sha256": audit.sha(self.new_gdc), "bytes": len(self.new_gdc)},
                      "compiledContractEvidence": str(self.base / "validate-final/result.json"),
                      "validation": self.validation, "compilerReports": []}
        self.put("original.gd", self.old_source)
        self.put("patched.gd", self.new_source)
        self.put("original.gdc", self.old_gdc)
        self.put("meadow_scene.gdc", self.new_gdc)
        for folder, source, compiled in (("original-compile", self.old_source, self.old_gdc),
                                         ("patched-compile", self.new_source, self.new_gdc),
                                         ("patched-repeat", self.new_source, self.new_gdc)):
            self.put(folder + "/project/scripts/meadow_scene.gd", source)
            self.put(folder + "/meadow_scene.gdc", compiled)
            self.put(folder + "/script-only.pck", pck({audit.STARTUP_PATH: compiled}))
            report = {"sourceSha256": audit.sha(source), "outputSha256": audit.sha(compiled),
                      "outputBytes": len(compiled), "stockGodotTokenizer": True,
                      "privateExportEntries": {audit.STARTUP_PATH: {"bytes": len(compiled), "sha256": audit.sha(compiled)}}}
            self.proof["compilerReports"].append(self.put(folder + "/compilation.json", report))
        fa, fb = audit.startup_functions(self.old_source), audit.startup_functions(self.new_source)
        self.request = {"original_sha256": audit.sha(self.old_gdc), "patched_sha256": audit.sha(self.new_gdc),
                        "original": str(self.base / "original.gdc"), "patched": str(self.base / "meadow_scene.gdc"),
                        "original_physics": fa["_physics_process"].decode().rstrip("\n") + "\n",
                        "patched_physics": fb["_physics_process"].decode().rstrip("\n") + "\n",
                        "patched_helpers": "\n".join(fb[n].decode() for n in audit.STARTUP_HELPERS),
                        "added_methods": audit.STARTUP_HELPERS}
        self.put("validate-final/request.json", self.request)
        self.repin()
        patch = mock.patch.object(audit, "read_startup_file", side_effect=lambda p: self.files[str(Path(p))])
        patch.start()
        self.addCleanup(patch.stop)

    def put(self, path, data):
        path = str(self.base / path)
        self.files[path] = json.dumps(data).encode() if isinstance(data, dict) else data
        return path

    def repin(self):
        self.put("validate-final/result.json", self.validation)
        self.put("startup-proof.json", self.proof)
        self.row["proofSha256"] = audit.sha(self.files[str(self.base / "startup-proof.json")])

    def verify(self):
        return audit.verify_runtime_proof(self.a, self.b, self.rule)

    def test_native_runtime_kind_normalizes_and_verified_proof_stays_pending(self):
        result = audit.audit(self.a, self.b, native_manifest(self.a, self.b, [self.row]), required_resources=())
        self.assertEqual(result["status"], "STRUCTURAL_PASS", result["errors"])
        self.assertEqual(result["checks"][0]["kind"], "runtime")
        self.assertEqual(result["checks"][0]["gdsc_version"], 101)
        self.assertEqual(result["checks"][0]["semantic_status"], "REVIEW_REQUIRED")
        self.assertTrue(result["pending"])

    def test_missing_or_unpinned_proof_fails_closed(self):
        for key, value in (("proof", None), ("proof", "relative.json"), ("proofSha256", "0" * 64)):
            row = {**self.row, key: value}
            with self.subTest(key=key):
                result = audit.audit(self.a, self.b, native_manifest(self.a, self.b, [row]), required_resources=())
                self.assertEqual(result["status"], "FAIL")

    def test_native_runtime_scope_is_one_exact_existing_path(self):
        for rows in ([self.row, self.row], [{**self.row, "path": "scripts/ao.gdc"}]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                audit.normalize_manifest(native_manifest(self.a, self.b, rows), self.a, self.b)

    def test_frozen_original_pck_and_entry_cannot_be_substituted(self):
        for constant in ("STARTUP_PACK_SHA256", "STARTUP_GDC_SHA256"):
            with self.subTest(constant=constant), mock.patch.object(audit, constant, "0" * 64), self.assertRaises(ValueError):
                self.verify()

    def test_other_scripts_cannot_change_under_startup_attestation(self):
        self.b.entries["scripts/ao.gdc"] = b"disabled AO"
        with self.assertRaisesRegex(ValueError, "exactly one changed runtime"):
            self.verify()

    def test_gdsc_format_version_is_not_waived_by_hash_update(self):
        for offset in (0, 4):
            bad = bytearray(self.new_gdc)
            bad[offset] ^= 1
            self.b.entries[audit.STARTUP_PATH] = bytes(bad)
            self.rule["after_sha256"] = audit.sha(bad)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "GDSC format/version"):
                self.verify()

    def test_source_change_is_rejected_even_when_attestation_hash_is_updated(self):
        source = self.new_source + b"# unreviewed source revision\n"
        self.put("patched.gd", source)
        self.proof["patchedSource"]["sha256"] = audit.sha(source)
        self.repin()
        with self.assertRaisesRegex(ValueError, "patchedSource hash mismatch"):
            self.verify()

    def test_original_movement_tail_is_independently_checked(self):
        source = self.new_source.replace(b"travel += delta", b"travel += delta * 2")
        with mock.patch.object(audit, "STARTUP_PATCHED_SHA256", audit.sha(source)), self.assertRaisesRegex(ValueError, "movement tail"):
            audit.verify_startup_source(self.old_source, source)

    def test_original_reproduction_repeat_and_private_pack_bytes_are_verified(self):
        for name in ("original-compile/meadow_scene.gdc", "patched-repeat/meadow_scene.gdc",
                     "patched-compile/project/scripts/meadow_scene.gd", "patched-repeat/script-only.pck"):
            path = str(self.base / name)
            old = self.files[path]
            self.files[path] = pck({audit.STARTUP_PATH: b"wrong"}) if name.endswith(".pck") else b"wrong"
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify()
            self.files[path] = old

    def test_success_flags_do_not_waive_compiled_contract_changes(self):
        self.validation["patched_contract"]["properties"] = [{"name": "disable_ao"}]
        self.repin()
        with self.assertRaisesRegex(ValueError, "methods/properties/signals changed"):
            self.verify()

    def test_failed_or_unbound_validation_cannot_be_attested(self):
        self.validation["failures"] = 1
        self.repin()
        with self.assertRaisesRegex(ValueError, "did not pass"):
            self.verify()
        self.validation["failures"] = 0
        self.repin()
        self.request["patched_helpers"] += "# different harness"
        self.put("validate-final/request.json", self.request)
        with self.assertRaisesRegex(ValueError, "harness differs"):
            self.verify()

    def test_release_debug_optin_reentry_and_walking_results_are_checked(self):
        for name, field, bad in (("release_web_default", "audit_calls", 1),
                                 ("exact_cli_opt_in", "audit_calls", 0),
                                 ("debug_reentry_guard", "guard_set_during_audit", False),
                                 ("web_query_opt_in", "walker_position", [.75, 99, -12])):
            row = self.validation["branch_cases"][name]
            before = row[field]
            row[field] = bad
            self.repin()
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify()
            row[field] = before


class ProofFileBoundaryTests(unittest.TestCase):
    def test_foreign_and_relative_proof_paths_are_rejected_before_filesystem_lookup(self):
        with mock.patch.object(Path, "resolve", side_effect=AssertionError("Unexpected filesystem lookup")):
            for path in ("relative.json", "Z:/unrelated/proof.json", "//server/share/proof.json"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    audit.read_startup_file(path)


class ProjectSettingsTests(unittest.TestCase):
    def setUp(self):
        self.base = {"application/name": b"arbitrary unchanged Variant",
                     "rendering/lights_and_shadows/directional_shadow/size": struct.pack("<Ii", 2, 4096)}
        self.candidate = {**self.base}
        for name, value in audit.LITE_SETTINGS.items():
            if name == "rendering/scaling_3d/mode":
                continue
            self.candidate[name] = struct.pack("<If", 3, value) if type(value) is float else struct.pack("<Ii", 2, value)

    def test_only_approved_render_keys_change(self):
        result = audit.verify_project(ecfg(self.base), ecfg(self.candidate))
        self.assertEqual(len(result["changed_keys"]), 3)
        self.assertTrue(result["all_other_variant_bytes_exact"])
        self.assertEqual(result["runtime_render_resolution"], "NOT_RUN")

    def test_unrelated_setting_or_value_change_rejected(self):
        for change in ({"application/name": b"different"},
                       {"rendering/scaling_3d/scale": struct.pack("<If", 3, 0.25)},
                       {"rendering/scaling_3d/mode": struct.pack("<Ii", 2, 1)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit.verify_project(ecfg(self.base), ecfg({**self.candidate, **change}))

    def test_missing_settings_or_malformed_ecfg_rejected(self):
        missing = dict(self.candidate)
        missing.pop("application/name")
        for blob in (ecfg(missing), ecfg(self.candidate)[:-1], ecfg(self.candidate) + b"extra"):
            with self.subTest(length=len(blob)), self.assertRaises(ValueError):
                audit.verify_project(ecfg(self.base), blob)


class PackTests(unittest.TestCase):
    def setUp(self):
        self.base = {"scenes/main.tscn": b"main", "scripts/game.gdc": b"code",
                     "shaders/meadow_water.gdshader": b"shader"}

    def compare(self, candidate=None, changes=(), mutate=None):
        a = audit.Snapshot(pck(self.base))
        b = audit.Snapshot(pck(self.base if candidate is None else candidate))
        contract = manifest(a, b, changes)
        if mutate:
            mutate(contract)
        return audit.audit(a, b, contract, required_resources=("scenes/main.tscn",))

    def test_unchanged_resource_closure(self):
        # Disable unrelated full-scene critical fixture requirements only here.
        a = audit.Snapshot(pck(self.base))
        result = audit.audit(a, a, manifest(a, a), required_resources=())
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertTrue(result["original_frozen"])

    def test_original_entire_container_hash_not_just_entry_hashes(self):
        a = audit.Snapshot(pck(self.base))
        mutated = audit.Snapshot(pck(self.base, header_marker=7))
        result = audit.audit(mutated, a, manifest(a, a), required_resources=())
        self.assertFalse(result["original_frozen"])
        self.assertIn("Whole-pack original_sha256", " ".join(result["errors"]))

    def test_corrupt_md5_and_truncation(self):
        blob = pck(self.base)
        broken = bytearray(blob)
        broken[112] ^= 1
        for data in (blob[:-1], bytes(broken), blob + b"trailing"):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                audit.Snapshot(data)

    def test_unsafe_resource_path(self):
        for name in ("../scripts/game.gdc", "/absolute", "scripts\\game.gdc"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.Snapshot(pck({name: b"data"}))

    def test_runtime_deletion_and_unmanifested_mutation(self):
        for candidate in ({}, {**self.base, "scripts/game.gdc": b"lost animation"},
                          {**self.base, "scripts/new.gdc": b"unlisted"}):
            result = self.compare(candidate)
            self.assertEqual(result["status"], "FAIL")

    def test_shader_cannot_be_waived(self):
        name = "shaders/meadow_water.gdshader"
        result = self.compare({**self.base, name: b"new"}, [change(name, "runtime", b"shader", b"new")])
        self.assertIn("Protected water/shader", " ".join(result["errors"]))

    def test_water_texture_protected_after_logical_resolution(self):
        target = ".godot/imported/opaque-name.ctex"
        self.base.update({target: b"original water", audit.WATER + ".import":
                          f'[remap]\npath="res://{target}"\n'.encode()})
        result = self.compare({**self.base, target: b"different water"},
                              [change(target, "texture", b"original water", b"different water")])
        self.assertIn("Protected water/shader", " ".join(result["errors"]))

    def test_changed_import_not_waived(self):
        name = "art.png.import"
        self.base.update({name: b'path="res://old.ctex"\n', "old.ctex": b"x", "new.ctex": b"x"})
        replacement = b'path="res://new.ctex"\n'
        result = self.compare({**self.base, name: replacement}, [change(name, "runtime", self.base[name], replacement)])
        self.assertIn("Protected water/shader", " ".join(result["errors"]))

    def test_dangling_remap(self):
        self.base["art.png.import"] = b'path="res://missing.ctex"\n'
        self.assertIn("dangling import/remap", " ".join(self.compare()["errors"]))

    def test_new_runtime_helpers_are_explicit_and_pending(self):
        a = audit.Snapshot(pck(self.base))
        extras = {"scripts/lite.gdc": b"helper", "scripts/lite.gd.remap": b'path="res://scripts/lite.gdc"\n'}
        b = audit.Snapshot(pck({**self.base, **extras}))
        result = audit.audit(a, b, manifest(a, b, [change(n, "runtime", None, d) for n, d in extras.items()]),
                             required_resources=())
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertEqual(len(result["pending"]), 2)
        self.assertEqual(result["runtime_status"], "NOT_RUN")

    def test_hash_pins_required(self):
        name = "scripts/game.gdc"
        record = change(name, "runtime", b"code", b"new")
        record["after_sha256"] = "0" * 64
        self.assertIn("entry SHA256 mismatch", " ".join(self.compare({**self.base, name: b"new"}, [record])["errors"]))

    def test_duplicate_or_noncanonical_manifest(self):
        a = audit.Snapshot(pck(self.base))
        record = change("scripts/game.gdc", "runtime", b"code", b"new")
        for rows in ([record, record], [{**record, "path": "res://scripts/game.gdc"}]):
            with self.assertRaises(ValueError):
                audit.audit(a, a, manifest(a, a, rows), required_resources=())

    def test_misclassified_payload_not_allowed(self):
        record = change("scripts/game.gdc", "geometry", b"code", b"new")
        self.assertIn("Kind does not match", " ".join(self.compare({**self.base, "scripts/game.gdc": b"new"}, [record])["errors"]))

    def test_lossless_rscc_decoded_content_and_metadata(self):
        from repack_web_cache import _pack
        name = "assets/baked/v77/detail.scn"
        raw = b"geometry and material metadata" * 1000
        old, new = _pack(raw, 4096, 3), _pack(raw, 262144, 9)
        a, b = audit.Snapshot(pck({name: old})), audit.Snapshot(pck({name: new}))
        result = audit.audit(a, b, manifest(a, b, [change(name, "lossless-rscc", old, new)]), required_resources=())
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        modified = _pack(raw + b"changed metadata")
        b = audit.Snapshot(pck({name: modified}))
        result = audit.audit(a, b, manifest(a, b, [change(name, "lossless-rscc", old, modified)]), required_resources=())
        self.assertIn("decoded geometry/metadata changed", " ".join(result["errors"]))

    def test_no_output_files_in_cli_example(self):
        with mock.patch("builtins.open", side_effect=AssertionError("Unexpected file access")), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(audit.main(["--manifest-example"]), 0)
            self.assertEqual(json.loads(out.getvalue())["schema_version"], 1)


class TextureTests(unittest.TestCase):
    def setUp(self):
        self.images = levels(atlas())
        self.original = ctex(self.images)
        self.candidate = ctex(self.images[1:], self.images[0].size)
        self.rule = texture_rule(self.original, self.candidate, self.images)

    def verify(self, blob=None, rule=None):
        return audit.verify_texture(self.original, blob or self.candidate, rule or self.rule)[0]

    def test_selected_mip_alpha_is_exact_not_fullsize_alpha(self):
        result = self.verify()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["frame_count"], 8)
        self.assertTrue(all(row["alpha_exact_to_selected_mip"] for row in result["levels"]))
        self.assertEqual(len(result["levels"]), len(self.images) - 1)

    def test_fractional_odd_grid_cells_allowed(self):
        images = levels(atlas((71, 35)))
        old, new = ctex(images), ctex(images[1:], images[0].size)
        result = audit.verify_texture(old, new, texture_rule(old, new, images))[0]
        self.assertEqual(result["errors"], [])

    def test_alpha_byte_change_in_any_selected_level_rejected(self):
        for level in (0, len(self.images) - 2):
            changed = [im.copy() for im in self.images[1:]]
            pixel = list(changed[level].getpixel((0, 0)))
            pixel[3] = (pixel[3] + 1) % 256
            changed[level].putpixel((0, 0), tuple(pixel))
            with self.subTest(level=level), self.assertRaisesRegex(ValueError, "alpha differs"):
                self.verify(ctex(changed, self.images[0].size))

    def test_lost_animal_frame_rejected(self):
        changed = [im.copy() for im in self.images[1:]]
        ImageDraw.Draw(changed[0]).rectangle((0, 0, 8, 8), fill=(0, 0, 0, 0))
        with self.assertRaisesRegex(ValueError, "alpha differs"):
            self.verify(ctex(changed, self.images[0].size))

    def test_selected_mip_cannot_erase_formerly_visible_design(self):
        images = [self.images[0]] + [Image.new("RGBA", im.size, (0, 0, 0, 0)) for im in self.images[1:]]
        original, candidate = ctex(images), ctex(images[1:], images[0].size)
        result = audit.verify_texture(original, candidate, texture_rule(original, candidate, images))[0]
        self.assertTrue(any("selected mip loses" in error for error in result["errors"]))

    def test_logical_runtime_size_must_match(self):
        bad = {**self.rule, "logical_size": [36, 18]}
        with self.assertRaisesRegex(ValueError, "logical texture size"):
            self.verify(rule=bad)
        changed = ctex(self.images[1:])
        bad["logical_size"] = list(self.images[1].size)
        with self.assertRaisesRegex(ValueError, "original outer logical"):
            self.verify(changed, bad)

    def test_wrong_stored_dimension_declared(self):
        with self.assertRaisesRegex(ValueError, "Stored size"):
            self.verify(rule={**self.rule, "stored_size": [35, 18]})

    def test_incomplete_or_truncated_chain(self):
        for blob in (self.candidate[:-1], self.candidate + b"extra", ctex(self.images[1:3], self.images[0].size)):
            with self.subTest(length=len(blob)), self.assertRaises(ValueError):
                self.verify(blob)

    def test_invalid_selected_mip(self):
        for value in (None, True, -1, 2, 100):
            with self.subTest(mip=value), self.assertRaises(ValueError):
                self.verify(rule={**self.rule, "source_mip": value})

    def test_ctex_flags_and_format_not_waived(self):
        blob = bytearray(self.candidate)
        blob[16] ^= 1
        with self.assertRaisesRegex(ValueError, "flags/codec/format"):
            self.verify(bytes(blob))

    def test_animal_grid_not_reduced_or_reordered(self):
        for grid in ([8, 1], [2, 2], [2, 4]):
            with self.subTest(grid=grid), self.assertRaisesRegex(ValueError, "eight frames"):
                self.verify(rule={**self.rule, "atlas": {"layout": "grid", "grid": grid}})

    def test_keep_physical_for_cpu_and_dragon(self):
        for name in audit.KEEP_PHYSICAL:
            rule = {**self.rule, "resource": "assets/" + name}
            with self.subTest(texture=name), self.assertRaisesRegex(ValueError, "physical resolution"):
                self.verify(rule=rule)

    def test_dragon_rejects_equal_grid_and_pose_order_change(self):
        dimensions = {"logical": (1774, 887), "stored": (1774, 887)}
        with self.assertRaisesRegex(ValueError, "32 measured irregular"):
            audit.atlas_regions({"resource": audit.DRAGON, "atlas": {"layout": "grid", "grid": [8, 4]}}, dimensions, dimensions)
        rects = copy.deepcopy(audit.DRAGON_RECTS)
        rects[0], rects[1] = rects[1], rects[0]
        rule = {"resource": audit.DRAGON, "atlas": {"layout": "rects", "rects": rects}}
        with self.assertRaisesRegex(ValueError, "32 measured irregular"):
            audit.atlas_regions(rule, dimensions, dimensions)

    def test_rectangles_preserve_uvs_order_and_no_overlap(self):
        a = {"logical": (100, 100), "stored": (100, 100)}
        b = {"logical": (100, 100), "stored": (50, 50)}
        layout = {"layout": "rects", "rects": [[0, 0, 40, 90], [60, 0, 40, 90]],
                  "lite_rects": [[0, 0, 20, 45], [30, 0, 20, 45]], "coordinate_size": [50, 50]}
        self.assertEqual(len(audit.atlas_regions({"resource": "cards.png", "atlas": layout}, a, b)), 2)
        for rects in (list(reversed(layout["lite_rects"])), [[0, 0, 30, 45], [20, 0, 30, 45]], [[0, 0, 51, 45]]):
            with self.subTest(rects=rects), self.assertRaises(ValueError):
                audit.atlas_regions({"resource": "cards.png", "atlas": {**layout, "lite_rects": rects}}, a, b)

    def test_white_edge_contamination_detected(self):
        base = Image.new("RGBA", (64, 64), (30, 50, 20, 0))
        ImageDraw.Draw(base).rectangle((8, 8, 55, 55), fill=(30, 50, 20, 128))
        white = base.copy()
        white.paste((255, 255, 255), (0, 0, 64, 64))
        white.putalpha(base.getchannel("A"))
        result = audit.alpha_metrics(base, white)
        errors = []
        audit.check_metrics(result, "edge", errors)
        self.assertTrue(any("bright fringe" in row for row in errors))

    def test_opaque_texture_remains_opaque(self):
        images = levels(Image.new("RGB", (32, 32), (40, 80, 20)))
        old, new = ctex(images, fmt=4), ctex(images[1:], (32, 32), fmt=4)
        rule = texture_rule(old, new, images, resource="assets/materials/ground.png")
        rule["atlas"] = {"layout": "whole"}
        self.assertEqual(audit.verify_texture(old, new, rule)[0]["errors"], [])


if __name__ == "__main__":
    unittest.main()
