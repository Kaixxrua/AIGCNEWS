"""Focused proxy-03 tests; no engine launch, imports, or artifact generation."""
from pathlib import Path
import json
import unittest
import numpy as np

import build_progressive_proxy_v135 as tool


class PureTests(unittest.TestCase):
    def test_disconnected_same_material_pieces_never_merge(self):
        xyz = np.array([[0,0,0],[1,0,0],[0,1,0],[4,0,0],[5,0,0],[4,1,0]], dtype="<f4")
        triangles = np.array([[0,1,2],[3,4,5]], dtype=np.int32)
        pieces, _ = tool.component_partition(xyz, triangles)
        self.assertEqual([p.tolist() for p in pieces], [[0],[1]])

    def test_exact_positions_join_but_semantic_seam_does_not(self):
        xyz = np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,0],[0,1,0],[-1,0,0]], dtype="<f4")
        triangles = np.array([[0,1,2],[3,4,5]], dtype=np.int32)
        self.assertEqual(len(tool.component_partition(xyz, triangles)[0]), 1)
        self.assertEqual(len(tool.component_partition(xyz, triangles, np.array([0,0,0,1,1,1]))[0]), 2)
        with self.assertRaises(ValueError):
            tool.component_partition(xyz, triangles, np.array([0,1,0,1,1,1]))

    def test_paths_boss_and_bridge_protected_far_region_not(self):
        centres = np.array([[5,-12],[13,-38],[-20,-6],[-200,-260]], dtype=float)
        xyz = np.array([[x+dx,0,z+dz] for x,z in centres for dx,dz in ((-.05,0),(.05,0),(0,.05))], dtype="<f4")
        result = tool.protect_terrain(xyz, np.arange(12).reshape(-1,3))
        self.assertEqual(result.tolist(), [True,True,True,False])

    def test_missing_boundary_edge_rejects_simplified_hole(self):
        xyz = np.array([[0,0,0],[1,0,0],[1,0,1],[0,0,1]], dtype="<f4")
        triangles = np.array([[0,1,2],[0,2,3]], dtype=np.int32)
        candidate = triangles[:1]
        chosen, report = tool.select_piece(xyz, xyz[:,[0,2]], np.arange(4), triangles,
                                            [({"level": 0},candidate)])
        self.assertTrue(np.array_equal(chosen, triangles))
        self.assertEqual(report["selectedLevel"], -1)

    def test_protected_patch_does_not_simplify(self):
        xyz = np.array([[0,0,0],[1,0,0],[1,0,1],[0,0,1]], dtype="<f4")
        triangles = np.array([[0,1,2],[0,2,3]], dtype=np.int32)
        chosen, report = tool.select_piece(xyz, xyz[:,[0,2]], np.arange(4), triangles, [], protected=True)
        self.assertTrue(report["protected"])
        self.assertEqual(chosen.tobytes(), triangles.tobytes())

    def test_writer_rejects_previous_candidate(self):
        with self.assertRaises(ValueError):
            tool.write(tool.PREVIOUS / "never-created.test", b"x")


@unittest.skipUnless((tool.OUT / "manifest.json").exists(), "Candidate not yet emitted")
class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((tool.OUT / "manifest.json").read_bytes())
        cls.proof = json.loads(tool.base.pinned(Path(cls.manifest["nativeProof"]), cls.manifest["nativeProofSha256"]))

    def test_candidate07_original_and_partition_pins_stay_exact(self):
        for path,pin in ((tool.CORE07,tool.CORE07_SHA),(tool.base.SHIP,tool.base.SHIP_SHA),
                         (tool.base.NATIVE,tool.base.NATIVE_SHA),(tool.PREVIOUS / "manifest.json",tool.PREVIOUS_SHA)):
            tool.base.pinned(path,pin)
        self.assertTrue(self.manifest["finalCandidate07RootGeometryExact"])
        self.assertFalse(self.manifest["sourceGdcEdits"])

    def test_codec_pairs_are_logically_exact_and_original_full_carrier_reused(self):
        previous = json.loads(tool.base.pinned(tool.PREVIOUS / "manifest.json", tool.PREVIOUS_SHA))
        self.assertEqual(self.manifest["resources"]["world-visuals"], previous["resources"]["world-visuals"])
        for resource in self.manifest["resources"].values():
            decoded = [tool.base.logical(tool.base.pinned(Path(info["path"]),info["sha256"])) for info in resource["encodings"].values()]
            self.assertEqual(decoded[0],decoded[1])
            self.assertEqual(tool.base.sha(decoded[0]),resource["decodedSha256"])

    def test_all_core_properties_and_colliders_survive_exact_final_restore(self):
        self.assertEqual(self.proof["status"],"PASS")
        for row in self.proof["groups"]:
            self.assertTrue(row["allSelectedDecodedChannelsExact"])
            self.assertTrue(row["meshOnlyRestoredExact"])
            self.assertTrue(row["collisionInstancesUnchangedDuringUpgrade"])
            self.assertEqual(row["expectedCoreSnapshot"],row["restoredSnapshot"])
            for path in row["colliderPaths"]:
                self.assertEqual(row["expectedCoreSnapshot"][path],row["proxyCoreSnapshot"][path])
            for path,fields in row["expectedCoreSnapshot"].items():
                if path != row["mesh"]:
                    self.assertEqual(fields,row["proxyCoreSnapshot"][path])
                else:
                    proxy = row["proxyCoreSnapshot"][path]
                    for field in ("class","index","groups","owner"):
                        self.assertEqual(fields[field],proxy[field])
                    for name,value in fields["properties"].items():
                        if name not in ("mesh","material_override"):
                            self.assertEqual(value,proxy["properties"][name])
                    old_material = fields["properties"]["material_override"]
                    new_material = proxy["properties"]["material_override"]
                    self.assertEqual(old_material[0],new_material[0])
                    for name,value in old_material[1].items():
                        if name != "shader_parameter/rock_ao_vertex_count":
                            self.assertEqual(value,new_material[1][name])

    def test_raw_selected_channels_reproduce_and_protected_terrain_is_exact(self):
        dump = json.loads(tool.base.pinned(tool.PREVIOUS / "dump/native-proof.json",tool.DUMP_SHA))
        request = json.loads((Path(self.manifest["nativeProof"]).parent / "request.json").read_bytes())
        selected_root = Path(self.manifest["nativeProof"]).parent.parent
        for row in dump["groups"]:
            group = row["group"]
            path = selected_root / "buffers" / (group + "-source-indices.bin")
            data = path.read_bytes()
            row["lodIndices"] = {"path": str(path),"bytes": len(data),"sha256": tool.base.sha(data)}
            actual, _, corners, channels, prefix = tool.base.selected_proxy_buffers(row)
            spec = next(s for s in request["groups"] if s["group"] == group)
            self.assertEqual(channels,spec["expected_channels"])
            self.assertEqual(prefix,spec["proxy_ao_prefix"])
            for key,value in actual.items():
                self.assertEqual(value,tool.base.read_buffer(spec["buffers"][key]))
            if group == "terrain":
                positions = np.frombuffer(tool.base.read_buffer(row["channels"]["0"]),dtype="<f4").reshape(-1,3)
                original = np.frombuffer(tool.base.read_buffer(row["buffers"]["index_data"]),dtype="<u4").reshape(-1,3)
                protected = original[tool.protect_terrain(positions,original)]
                rows = set(map(tuple,corners.reshape(-1,3)))
                self.assertTrue(all(tuple(t) in rows for t in protected))

    def test_piece_fidelity_and_no_disappeared_piece(self):
        for params in self.manifest["parameters"]:
            pieces = json.loads(Path(params["pieceProof"]).read_bytes())["pieces"]
            self.assertEqual(len(pieces),params["pieceCount"])
            for piece in pieces:
                self.assertGreater(piece["afterTriangles"],0)
                self.assertTrue(piece["boundaryEdgesExact"])
                self.assertLessEqual(piece["lostFraction"],.08)
                self.assertLessEqual(piece["addedFraction"],.08)
                if piece["protected"]:
                    self.assertEqual(piece["beforeTriangles"],piece["afterTriangles"])


if __name__ == "__main__":
    unittest.main()
