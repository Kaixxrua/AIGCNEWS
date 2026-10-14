"""Focused proxy04 bounds and immutable-resource tests, no engine launches."""
from pathlib import Path
import json
import struct
import unittest
import numpy as np

import build_progressive_proxy_precision_v135 as tool


class PureTests(unittest.TestCase):
    def test_octahedral_axes_and_bounded_grid(self):
        words = np.array([[32768,32768],[65535,32768],[32768,65535],[0,0]],dtype="<u2")
        decoded = tool.oct_decode(words)
        self.assertTrue(np.allclose(np.linalg.norm(decoded,axis=1),1))
        self.assertGreater(decoded[0,2],.999)
        self.assertLess(decoded[-1,2],-.999)
        values = np.arange(0,65536,257,dtype="<u2")
        pairs = np.stack(np.meshgrid(values,values),axis=-1).reshape(-1,2)
        quantized = np.clip(np.rint(pairs.astype(float)/1024)*1024,0,65535).astype("<u2")
        self.assertLess(float(tool.normal_angles(pairs,quantized).max()),5)

    def test_positions_world_bound_and_contact_exact(self):
        xyz = np.array([[.011,.009,.004],[1.013,.001,.008],[.005,.004,1.01]],dtype="<f4")
        locked = np.array([True,False,False])
        q,proof = tool.quantize_positions(xyz,np.array([[0,1,2]]),locked)
        self.assertEqual(q[0].tobytes(),xyz[0].tobytes())
        self.assertLessEqual(proof["maxVectorError"],.02)
        self.assertLessEqual(proof["maxGeometricNormalDegrees"],5)

    def test_thin_triangle_and_shared_position_guards(self):
        xyz = np.array([[0,0,0],[1,0,0],[.4,.0001,.00001],[.4,.0001,.00001]],dtype="<f4")
        q,proof = tool.quantize_positions(xyz,np.array([[0,1,2]]),np.zeros(4,dtype=bool))
        self.assertEqual(q[2].tobytes(),q[3].tobytes())
        self.assertEqual(proof["newDegenerateOrFlippedTriangles"],0)
        self.assertLessEqual(proof["maxGeometricNormalDegrees"],5.000001)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            tool.quantize_positions(np.array([[0,0,0],[1,0,0],[0,np.nan,1]],dtype="<f4"),np.array([[0,1,2]]),np.zeros(3,dtype=bool))

    def test_patch_typed_span_only_and_fail_closed(self):
        before = bytes(range(80));after = bytes(reversed(range(80)))
        raw = b"header"+struct.pack("<II",31,len(before))+before+b"tail"
        changed,proof = tool.patch_resource(raw,[("buffer",before,after)])
        self.assertEqual(changed[:14],raw[:14]);self.assertEqual(changed[-4:],raw[-4:])
        self.assertEqual(changed[14:-4],after)
        self.assertEqual(proof[0]["offset"],14)
        for bad in (raw+raw,raw.replace(struct.pack("<II",31,80),struct.pack("<II",35,80))):
            with self.assertRaises(ValueError): tool.patch_resource(bad,[("buffer",before,after)])

    def test_cannot_write_old_proxy(self):
        with self.assertRaises(ValueError): tool.write(tool.OLD/"never-created.test",b"x")


@unittest.skipUnless((tool.OUT/"manifest.json").exists(),"Candidate not yet emitted")
class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((tool.OUT/"manifest.json").read_bytes())
        cls.native=json.loads(tool.base.pinned(Path(cls.manifest["nativeProof"]),cls.manifest["nativeProofSha256"]))

    def test_old_proxy_and_full_carrier_stay_pinned(self):
        old=json.loads(tool.base.pinned(tool.OLD/"manifest.json",tool.OLD_SHA))
        self.assertEqual(old["resources"]["world-visuals"],self.manifest["resources"]["world-visuals"])
        self.assertEqual(old["sceneSpec"],self.manifest["sceneSpec"])
        for row in old["resources"].values():
            for item in row["encodings"].values(): tool.base.pinned(Path(item["path"]),item["sha256"])

    def test_native_bounds_contacts_and_final_restoration(self):
        self.assertEqual(self.native["status"],"PASS")
        for row in self.native["groups"]:
            self.assertLessEqual(row["maxWorldPositionError"],.02)
            self.assertLessEqual(row["maxNormalDegrees"],5)
            self.assertLessEqual(row["maxUvVectorError"],.002)
            self.assertLessEqual(row["maxUv2VectorError"],.002)
            self.assertTrue(row["allNonMeshPropertiesExact"])
            self.assertTrue(row["finalRestoredExact"])
            self.assertTrue(row["nativeTypedRestorationExact"])
            self.assertTrue(row["colliderInstancesPreserved"])

    def test_candidate_codecs_and_span_proof(self):
        old=json.loads(tool.base.pinned(tool.OLD/"manifest.json",tool.OLD_SHA))
        patches=json.loads((tool.OUT/"raw-span-proof.json").read_bytes())["resources"]
        for label,spans in patches.items():
            before_info=old["resources"][label]["encodings"]["native"]
            before=tool.base.logical(tool.base.pinned(Path(before_info["path"]),before_info["sha256"]))
            resource=self.manifest["resources"][label]
            decoded=[tool.base.logical(tool.base.pinned(Path(i["path"]),i["sha256"])) for i in resource["encodings"].values()]
            self.assertEqual(decoded[0],decoded[1]);self.assertEqual(len(decoded[0]),len(before))
            cursor=0
            for span in spans:
                offset,end=span["offset"],span["offset"]+span["bytes"]
                self.assertEqual(before[cursor:offset],decoded[0][cursor:offset])
                self.assertEqual(tool.base.sha(before[offset:end]),span["beforeSha256"])
                self.assertEqual(tool.base.sha(decoded[0][offset:end]),span["afterSha256"])
                cursor=end
            self.assertEqual(before[cursor:],decoded[0][cursor:])

    def test_no_topology_ao_tangent_changes_and_measured_gate(self):
        for row in self.manifest["parameters"]:
            for field in ("indicesExact","tangentsExact","RGBAExact","protectedWholeRecordsExact","noVertexOrTriangleReordering"):
                self.assertTrue(row[field])
            self.assertEqual(row["positions"]["newDegenerateOrFlippedTriangles"],0)
        m=self.manifest["measurements"]
        self.assertEqual(m["visualSavedGzip6Bytes"],1264877-m["visualOnlyGzip6Bytes"])
        self.assertEqual(self.manifest["integrationEligible"],min(m["visualSavedGzip6Bytes"],m["coreSavedGzip6Bytes"])>=200000)


if __name__=="__main__": unittest.main()
