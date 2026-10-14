"""One bounded proxy-04 attribute-only candidate; no topology/physics changes.

Patches only exact typed raw-buffer spans in pinned proxy-03 SCNs. No scene
resaving, extra LOD generation, full export, main-scene run or runtime decoder.
"""
from pathlib import Path
import argparse
import copy
import gzip
import json
import struct
import numpy as np

import build_progressive_scenes_v135 as base

OUT = base.SCOPE / "proxy-04"
OLD = base.SCOPE / "proxy-03"
OLD_SHA = "dc01a9e7b19b2f4a1e3a16770cd4364dc76a7ff134825edf801cd8be4752c040"
POSITION_STEP = 1 / 64
UV_STEP = 1 / 512
NORMAL_WORD_STEP = 1024


def write(path, data):
    base.require(path.resolve().is_relative_to(OUT.resolve()), "Only new proxy-04 output")
    base.write(path, data)


def json_write(path, data):
    write(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())


def record(path, data):
    payload = data.tobytes() if isinstance(data, np.ndarray) else data
    write(path, payload)
    return {"path": path.as_posix(), "bytes": len(payload), "sha256": base.sha(payload)}


def vector_error(before, after):
    delta = after.astype(np.float64) - before.astype(np.float64)
    return {"maxComponentError": float(np.abs(delta).max(initial=0)),
            "maxVectorError": float(np.linalg.norm(delta, axis=1).max(initial=0)),
            "changedVertices": int(np.count_nonzero(np.any(delta != 0, axis=1)))}


def oct_decode(words):
    """Pinned Vector3::octahedron_decode in float64 for conservative measurement.

    Native proof independently checks actual float32 Godot decoded normals.
    """
    f = words.astype(np.float64) / 65535 * 2 - 1
    z = 1 - np.abs(f).sum(axis=1)
    t = np.clip(-z, 0, 1)
    xy = f + np.where(f >= 0, -t[:, None], t[:, None])
    n = np.column_stack((xy, z))
    return n / np.linalg.norm(n, axis=1)[:, None]


def normal_angles(before, after):
    a, b = oct_decode(before), oct_decode(after)
    return np.degrees(np.arctan2(np.linalg.norm(np.cross(a,b),axis=1), np.einsum("ij,ij->i",a,b)))


def face_state(positions, triangles):
    v = positions.astype(np.float64)[triangles]
    n = np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0])
    return n, np.linalg.norm(n,axis=1)


def quantize_positions(positions, triangles, protected):
    base.require(np.isfinite(positions).all(), "Finite original positions")
    result = (np.rint(positions.astype(np.float64)/POSITION_STEP)*POSITION_STEP).astype("<f4")
    result = np.clip(result,positions.min(0),positions.max(0))
    _, groups = np.unique(positions.view("<u4"),axis=0,return_inverse=True)
    locked = np.zeros(groups.max()+1,dtype=bool)
    locked[groups[protected]] = True
    old_n, old_area = face_state(positions,triangles)
    valid = old_area > 1e-12
    # Keep proxy03's existing zero-area boundary triangles exactly as they were.
    locked[groups[triangles[~valid].ravel()]] = True
    fallback = False
    for guard_pass in range(17):
        result[locked[groups]] = positions[locked[groups]]
        new_n, new_area = face_state(result,triangles)
        dot = np.einsum("ij,ij->i",old_n,new_n)
        angles = np.degrees(np.arctan2(np.linalg.norm(np.cross(old_n,new_n),axis=1),dot))
        ratio = np.divide(new_area,old_area,out=np.ones_like(old_area),where=valid)
        bad = valid & ((new_area <= 1e-12) | (dot <= 0) | (angles > 5.0) | (ratio < .90) | (ratio > 1.10))
        if not np.any(bad):
            break
        if guard_pass == 16:
            result = positions.copy()
            fallback = True
            break
        # Whole exact-XYZ groups revert together: no splits at shading seams.
        locked[groups[triangles[bad].ravel()]] = True
    new_n,new_area = face_state(result,triangles)
    dot = np.einsum("ij,ij->i",old_n,new_n)
    angles = np.degrees(np.arctan2(np.linalg.norm(np.cross(old_n,new_n),axis=1),dot))[valid]
    ratios = new_area[valid]/old_area[valid]
    base.require(not np.any(valid & ((new_area <= 1e-12)|(dot <= 0))), "No new zero-area or reversed triangles")
    error = vector_error(positions,result)
    base.require(error["maxVectorError"] <= .02 and float(angles.max(initial=0)) <= 5.000001, "World position and geometric-normal limits")
    base.require(result[protected].tobytes() == positions[protected].tobytes(), "Protected contact positions exact")
    return result,{**error,"step":POSITION_STEP,"guardPasses":guard_pass+1,"allPositionFallback":fallback,
                   "originalZeroAreaTriangles":int((~valid).sum()),"newDegenerateOrFlippedTriangles":0,
                   "maxGeometricNormalDegrees":float(angles.max(initial=0)),
                   "areaRatioMin":float(ratios.min()),"areaRatioMax":float(ratios.max()),
                   "lockedXYZGroups":int(locked.sum()),"exactXYZGroupsRevertedTogether":True}


def transform_buffers(spec, attribute_stride, protected):
    count = int(spec["vertex_count"])
    original = {k:base.read_buffer(v) for k,v in spec["buffers"].items()}
    base.require(len(original["vertex_data"]) == count*20 and len(original["attribute_data"]) == count*attribute_stride,
                 "Pinned position12 + normal4 + tangent4 / RGBA0-or4 + UV16 layout")
    index_stride = 2 if count <= 65536 else 4
    triangles = np.frombuffer(original["index_data"],dtype=f"<u{index_stride}").reshape(-1,3)
    base.require(triangles.size == spec["index_count"] and triangles.max() < count,"Original index bounds")
    positions = np.frombuffer(original["vertex_data"][:count*12],dtype="<f4").reshape(-1,3)
    new_positions,pos_proof = quantize_positions(positions,triangles,protected)
    nt = np.frombuffer(original["vertex_data"][count*12:],dtype="<u2").reshape(count,4)
    new_nt = nt.copy()
    qn = np.clip(np.rint(nt[:,:2].astype(np.float64)/NORMAL_WORD_STEP)*NORMAL_WORD_STEP,0,65535).astype("<u2")
    normal_error = normal_angles(nt[:,:2],qn)
    # Small safety margin leaves actual float32 decode strictly inside 5 degrees.
    qn[normal_error > 4.9] = nt[normal_error > 4.9,:2]
    qn[protected] = nt[protected,:2]
    new_nt[:,:2] = qn
    normal_error = normal_angles(nt[:,:2],new_nt[:,:2])
    base.require(float(normal_error.max(initial=0)) < 5, "Packed-normal angle limit")
    attrs = np.frombuffer(original["attribute_data"],dtype=np.uint8).reshape(count,attribute_stride)
    new_attrs = attrs.copy()
    colour_width = attribute_stride-16
    base.require(colour_width in (0,4), "Only expected exact RGBA prefix")
    uv = attrs[:,colour_width:].copy().view("<f4").reshape(count,4)
    base.require(np.isfinite(uv).all(),"Finite UV/UV2")
    new_uv = (np.rint(uv.astype(np.float64)/UV_STEP)*UV_STEP).astype("<f4")
    # Preserve the observed mapped-face / sentinel and other existing boundaries.
    for threshold in (-1800.,-900.,0.,1.):
        crossed = (uv[:,0] < threshold) != (new_uv[:,0] < threshold)
        new_uv[crossed,0] = uv[crossed,0]
    new_uv[protected] = uv[protected]
    uv_proof = {name:vector_error(uv[:,start:start+2],new_uv[:,start:start+2]) for name,start in (("UV",0),("UV2",2))}
    base.require(all(row["maxVectorError"] <= .002 for row in uv_proof.values()),"UV vector limit")
    new_attrs[:,colour_width:] = new_uv.view(np.uint8).reshape(count,16)
    result = {"vertex_data":new_positions.tobytes()+new_nt.tobytes(),"attribute_data":new_attrs.tobytes(),"index_data":original["index_data"]}
    base.require(new_nt[:,2:].tobytes() == nt[:,2:].tobytes(),"Tangents exact")
    base.require(new_attrs[:,:colour_width].tobytes() == attrs[:,:colour_width].tobytes(),"RGBA/AO exact")
    proof = {"positions":pos_proof,"normals":{"wordStep":NORMAL_WORD_STEP,"maxDegrees":float(normal_error.max(initial=0)),
              "changedVertices":int(np.any(nt[:,:2] != new_nt[:,:2],axis=1).sum())},"uv":uv_proof,"uvStep":UV_STEP,
              "vertices":count,"triangles":len(triangles),"indicesExact":True,"tangentsExact":True,"RGBAExact":True,
              "protectedVertices":int(protected.sum()),"protectedWholeRecordsExact":True,"noVertexOrTriangleReordering":True}
    return original,result,proof


def patch_resource(raw, changes):
    result = bytearray(raw)
    spans = []
    for label,before,after in changes:
        base.require(len(before) == len(after) and len(before) > 64,"Only same-size complete raw buffers")
        offset = raw.find(before)
        base.require(offset >= 8 and raw.find(before,offset+1) < 0,"Unique observed complete source buffer")
        base.require(struct.unpack_from("<II",raw,offset-8) == (31,len(before)),"Exact typed PackedByteArray span")
        spans.append({"buffer":label,"offset":offset,"bytes":len(before),"beforeSha256":base.sha(before),"afterSha256":base.sha(after)})
        result[offset:offset+len(before)] = after
    spans.sort(key=lambda r:r["offset"])
    cursor = 0
    for row in spans:
        base.require(row["offset"] >= cursor,"Disjoint target spans")
        base.require(raw[cursor:row["offset"]] == result[cursor:row["offset"]],"Untargeted serialized bytes exact")
        cursor = row["offset"]+row["bytes"]
    base.require(raw[cursor:] == result[cursor:],"Trailing serialized bytes exact")
    return bytes(result),spans


def build():
    base.require(not OUT.exists(),"One fresh proxy-04 only")
    manifest = json.loads(base.pinned(OLD / "manifest.json",OLD_SHA))
    old_proof = json.loads(base.pinned(Path(manifest["nativeProof"]),manifest["nativeProofSha256"]))
    old_request = json.loads((Path(manifest["nativeProof"]).parent / "request.json").read_bytes())
    metadata = {r["group"]:r for r in manifest["parameters"]}
    existing = {r["group"]:r for r in old_proof["groups"]}
    changes,parameters,specs = {},[],{}
    for row in old_request["groups"]:
        group = row["group"]
        protected = np.zeros(row["vertex_count"],dtype=bool)
        if group == "terrain":
            corners = np.fromfile(OLD / "final/buffers/terrain-source-indices.bin",dtype="<i4")
            n = int(metadata[group]["protectedTriangles"])*3
            base.require(base.sha(corners[:n].tobytes()) == metadata[group]["protectedTriangleIndexSha256"],"Exact original protected triangle pin")
            protected[np.searchsorted(np.unique(corners),corners[:n])] = True
        before,after,proof = transform_buffers(row,16 if group == "terrain" else 20,protected)
        changes[group] = [(group+"/"+k,before[k],after[k]) for k in ("vertex_data","attribute_data")]
        buffer_refs = {k:record(OUT / "buffers" / (group+"-"+k+".bin"),v) for k,v in after.items()}
        protected_ref = record(OUT / "buffers" / (group+"-protected.bin"),np.flatnonzero(protected).astype("<i4"))
        parameters.append({"group":group,"mesh":row["mesh"],"proxyAoPrefix":metadata[group]["proxyAoPrefix"],
                           "originalAoPrefix":metadata[group]["originalAoPrefix"],**proof})
        old_resource = manifest["resources"][group+"-core"]["encodings"]["native"]
        specs[group] = {"entry":row["entry"],"mesh":row["mesh"],"before":old_resource,
                        "buffers":buffer_refs,"protected":protected_ref,"expected_full":existing[group]["expectedCoreSnapshot"],
                        "collider_paths":existing[group]["colliderPaths"],"full_ao_prefix":metadata[group]["originalAoPrefix"]}
        print("PROXY04_QUANTIZED",json.dumps(parameters[-1]),flush=True)
    json_write(OUT / "quantization-proof.json",{"profile":{"positionStep":POSITION_STEP,"uvStep":UV_STEP,"normalWordStep":NORMAL_WORD_STEP},"groups":parameters})
    resources = {"world-visuals":copy.deepcopy(manifest["resources"]["world-visuals"])}
    patches = {}
    for label in ("terrain-core","detail-core","bootstrap-visuals-measurement-only"):
        previous = manifest["resources"][label]
        original = previous["encodings"]["native"]
        raw = base.logical(base.pinned(Path(original["path"]),original["sha256"]))
        chosen = changes["terrain"]+changes["detail"] if label.startswith("bootstrap") else changes[label.split("-")[0]]
        modified,patches[label] = patch_resource(raw,chosen)
        print("PROXY04_ENCODE",label,len(modified),flush=True)
        native = base._pack(modified,1048576,19)
        mode5,filters = base.encode(modified)
        base.require(base.logical(native) == base.logical(mode5) == modified,"Both candidate codecs exact")
        encodings = {}
        for kind,payload in (("native",native),("mode5",mode5)):
            info = record(OUT / kind / (label+".scn"),payload)
            info["gzip6Bytes"] = len(gzip.compress(payload,6,mtime=0))
            encodings[kind] = info
        resources[label] = {"entry":previous["entry"],"encodings":encodings,"decodedBytes":len(modified),
                            "decodedSha256":base.sha(modified),"filters":filters}
        if not label.startswith("bootstrap"):
            specs[label.split("-")[0]]["after"] = encodings["native"]
    json_write(OUT / "raw-span-proof.json",{"allOtherSerializedBytesExact":True,"resources":patches})
    finish(manifest,resources,parameters,specs,OUT / "native-verify")


def finish(manifest,resources,parameters,specs,verify_dir):
    # Existing engine reads only the two completed static scenes, no resaving.
    base.pinned(base.NATIVE,base.NATIVE_SHA)
    native_entries = base.entries(base.NATIVE,base.NATIVE_SHA)
    for spec in specs.values():
        spec["full_carrier"] = resources["world-visuals"]["encodings"]["native"]
    base.GD = Path(__file__).with_suffix(".gd")
    native_proof = base.native_run("precision_verify",native_entries,verify_dir,specs)
    base.require(all(r["finalRestoredExact"] and r["colliderInstancesPreserved"] for r in native_proof["groups"]),"Exact final geometry and collision lifecycle")
    measures = {"previousVisualOnlyGzip6Bytes":1264877,
                "visualOnlyGzip6Bytes":resources["bootstrap-visuals-measurement-only"]["encodings"]["mode5"]["gzip6Bytes"],
                "previousCorePairGzip6Bytes":4004576,
                "corePairGzip6Bytes":sum(resources[k]["encodings"]["mode5"]["gzip6Bytes"] for k in ("terrain-core","detail-core")),
                "notWholePackOrWebTiming":True}
    measures["visualSavedGzip6Bytes"] = measures["previousVisualOnlyGzip6Bytes"]-measures["visualOnlyGzip6Bytes"]
    measures["coreSavedGzip6Bytes"] = measures["previousCorePairGzip6Bytes"]-measures["corePairGzip6Bytes"]
    eligible = min(measures["visualSavedGzip6Bytes"],measures["coreSavedGzip6Bytes"]) >= 200000
    result = {k:copy.deepcopy(manifest[k]) for k in ("schema","sourceShippingPackSha256","sourceNativePackSha256",
              "basePartitionManifest","basePartitionManifestSha256","sceneSpec","coreMarker","candidate07CoreSha256")}
    result.update(status="BOUNDED_CORE_PRECISION_VISUAL_QA_PENDING" if eligible else "REJECTED_SAVINGS_UNDER_200000_BYTES_DO_NOT_INTEGRATE",
                  integrationEligible=eligible,previousProxyManifestSha256=OLD_SHA,resources=resources,parameters=parameters,
                  measurements=measures,allOriginalColliderBytesExact=True,meshOnlyRestoredExact=True,
                  preserveLiveMaterialsAndWeather=True,sourceGdcEdits=False,fullCarrierReusedByteExact=True,
                  finalCandidate07RootGeometryExact=True,allIndicesAndTriangleOrderExact=True,allRGBAAndTangentsExact=True,
                  nativeProof=(verify_dir / "native-proof.json").as_posix(),
                  nativeProofSha256=base.sha((verify_dir / "native-proof.json").read_bytes()),
                  limits=["Only optional progressive core attributes are lossy; full carrier and full colliders remain frozen.",
                          "Position, UV vector and decoded-normal bounds are measured; rendered appearance and Web loading time still require main QA.",
                          "No triangle simplification/reordering, new root, material layer, shadow policy or runtime decoder."])
    base.pinned(OLD / "manifest.json",OLD_SHA)
    for info in resources["world-visuals"]["encodings"].values():
        base.pinned(Path(info["path"]),info["sha256"])
    json_write(OUT / "manifest.json",result)
    print("PROXY04_DONE",json.dumps({"status":result["status"],"manifest":str(OUT / "manifest.json"),**measures}),flush=True)


def verify_existing():
    """Finish the same bytes after a verifier-only correction; no quantization."""
    base.require(not (OUT / "manifest.json").exists(),"Never change an emitted candidate")
    manifest = json.loads(base.pinned(OLD / "manifest.json",OLD_SHA))
    staged = json.loads((OUT / "native-verify/request.json").read_bytes())
    parameters = json.loads((OUT / "quantization-proof.json").read_bytes())["groups"]
    specs = {r["group"]:r for r in staged["groups"]}
    resources = {"world-visuals":copy.deepcopy(manifest["resources"]["world-visuals"])}
    spans = json.loads((OUT / "raw-span-proof.json").read_bytes())["resources"]
    for label in spans:
        encodings,decoded = {},[]
        for kind in ("native","mode5"):
            path = OUT / kind / (label+".scn")
            data = path.read_bytes()
            if kind == "native" and not label.startswith("bootstrap"):
                base.require(base.sha(data) == specs[label.split("-")[0]]["after"]["sha256"],"Same completed candidate bytes")
            decoded.append(base.logical(data))
            encodings[kind] = {"path":path.as_posix(),"bytes":len(data),"sha256":base.sha(data),
                               "gzip6Bytes":len(gzip.compress(data,6,mtime=0))}
            if kind == "mode5":
                count = len(decoded[-1])//1048576+1
                cursor,filters = 16+count*4,[]
                for length in struct.unpack_from(f"<{count}I",data,16):
                    filters.append(data[cursor]);cursor += length
        base.require(decoded[0] == decoded[1],"Same exact codec twins")
        old_info = manifest["resources"][label]["encodings"]["native"]
        old_raw = base.logical(base.pinned(Path(old_info["path"]),old_info["sha256"]))
        cursor = 0
        for row in spans[label]:
            end = row["offset"]+row["bytes"]
            base.require(old_raw[cursor:row["offset"]] == decoded[0][cursor:row["offset"]],"Same untouched resource spans")
            base.require(base.sha(decoded[0][row["offset"]:end]) == row["afterSha256"],"Same already measured quantized bytes")
            cursor=end
        base.require(old_raw[cursor:] == decoded[0][cursor:],"Same resource tail")
        resources[label] = {"entry":manifest["resources"][label]["entry"],"encodings":encodings,
                            "decodedBytes":len(decoded[0]),"decodedSha256":base.sha(decoded[0]),"filters":filters}
    finish(manifest,resources,parameters,specs,OUT / "native-verify-03")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--build",action="store_true")
    modes.add_argument("--verify-existing",action="store_true")
    args = parser.parse_args()
    verify_existing() if args.verify_existing else build()
