"""Separate complete-scene lite candidate: fewer subdivisions, never fewer plants.

Only verified five-triangle grass strips and six-triangle oval fans change.
Every root/leaf remains; unmatched topology stays exact. Keep raw selected
vertex attributes, wind alpha, materials, root metadata, collisions and all
other resources. This is bounded lossy GEOMETRY and requires visual review.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
import compact_lite_meshes as native
from inspect_web_pack import read_pack
from build_web_quality import write_pack
from repack_web_cache import _pack, _unpack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / 'artifacts/startup-v128/leaf-lod'
BASE = ROOT / 'artifacts/v127/index-lite.pck'
PIN = '771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf'
TARGETS = {
 'assets/baked/v77/detail.scn':['PropGroundStitches','CreepingMeadowAndLedgeGrowth','LivingMeadowUnderstory'],
 'assets/baked/v77/foothill.scn':['CastleFoothillWoodland'],
 'assets/baked/v77/riverbank.scn':['RootedRiparianCover'],
}
sha = native.sha
require = native.require


def reduce_leaf_indices(positions, color, triangles, aggressive):
    """Recognize authored primitive order, including seam-duplicated vertices."""
    alpha = np.rint(color[:,3]*255).astype(np.int32)
    strips = np.array([0,85,0,0,85,85,85,170,85,85,170,170,170,255,170])
    fans = np.array([0,255,166,166,255,166,166,255,166,166,255,166,166,255,166,166,255,0])
    result=[]; i=0; counts={'blades':0,'ovals':0,'unmatchedTriangles':0}
    root_rows=[]
    def coincident(a,b):
        return np.array_equal(positions[a],positions[b])
    while i < len(triangles):
        five = triangles[i:i+5].ravel()
        if len(five)==15 and np.all(np.abs(alpha[five]-strips)<=1):
            # Authored wa=(1-.88*t), wb=(1-t): adjoining strip sections
            # deliberately overlap laterally, so only their CENTRES coincide.
            links=((2,3),(1,4),(7,10),(8,9))
            centres=[(positions[five[a]]+positions[five[b]])*.5 for a,b in ((1,5),(6,8),(7,11),(12,14))]
            joins=max(np.linalg.norm(centres[0]-centres[1]),np.linalg.norm(centres[2]-centres[3]))
            if all(coincident(five[a],five[b]) for a,b in links) and joins < .008:
                if aggressive:
                    result.append([int(five[0]),int(five[13]),int(five[2])])
                else:
                    # Retain the lower curve, then bridge the final two sections.
                    result.extend(triangles[i:i+2].tolist())
                    result.append([int(five[6]),int(five[13]),int(five[8])])
                root_rows.append((int(five[0]),int(five[2])))
                counts['blades']+=1; i+=5; continue
        six = triangles[i:i+6].ravel()
        if len(six)==18 and np.all(np.abs(alpha[six]-fans)<=1):
            ring_ok=all(coincident(six[j*3+2],six[((j+1)%6)*3]) for j in range(6))
            ridge_ok=all(coincident(six[1],six[j*3+1]) for j in range(1,6))
            if ring_ok and ridge_ok:
                # Keep root, both widest shoulders, tip and central ridge. One
                # subdivision along each outer side goes; no plant is deleted.
                ring=[int(six[j*3]) for j in (0,1,3,5)]
                result.extend([[ring[j],int(six[1]),ring[(j+1)%4]] for j in range(4)])
                root_rows.append((int(six[0]),))
                counts['ovals']+=1; i+=6; continue
        result.append(triangles[i].tolist());counts['unmatchedTriangles']+=1;i+=1
    result=np.asarray(result,dtype=np.uint32)
    used=set(np.unique(result).tolist())
    require(all(all(root in used for root in roots) for roots in root_rows),'Every recognized plant root retained')
    counts.update(beforeTriangles=len(triangles),afterTriangles=len(result),recognizedPlants=len(root_rows),
                  allRecognizedRootsRetained=True,unrecognizedTopologyRetained=True)
    return result, counts


def buffers_for(surface, indices):
    count=surface['vertex_count'];vs=surface['vertex_stride'];ns=surface['normal_tangent_stride'];ats=surface['attribute_stride']
    raw={k:native.read_record(v) for k,v in surface['raw_buffers'].items()}
    ids=np.unique(indices)
    mapping=np.zeros(count,dtype=np.uint32);mapping[ids]=np.arange(len(ids),dtype=np.uint32)
    # The raw ArrayMesh surface parser infers index width from vertex count.
    width=2 if len(ids)<=65536 else 4
    vertex=raw['vertex_data']; split=count*vs
    result={
      'vertex_data':np.frombuffer(vertex[:split],dtype=np.uint8).reshape(count,vs)[ids].tobytes()
        + np.frombuffer(vertex[split:],dtype=np.uint8).reshape(count,ns)[ids].tobytes(),
      'attribute_data':np.frombuffer(raw['attribute_data'],dtype=np.uint8).reshape(count,ats)[ids].tobytes(),
      'index_data':mapping[indices].astype(f'<u{width}').tobytes(),
    }
    return result,ids,mapping


def build(output, aggressive):
    require(not output.exists(),'New output required')
    native.SCOPE=SCOPE;native.BASE=BASE;native.BASE_SHA=PIN;native.TARGETS=TARGETS
    output=native.scoped(output);output.mkdir(parents=True)
    blob=BASE.read_bytes();require(sha(blob)==PIN,'Frozen v127 source')
    inventory=read_pack(BASE)
    entries={r['path']:blob[r['offset']:r['offset']+r['bytes']] for r in inventory['entries']}
    files=[]
    for resource,targets in TARGETS.items():
        path=output/'source'/Path(resource).name
        native.write_new(path,entries[resource])
        files.append(dict(resource=resource,path=str(path),sha256=sha(entries[resource]),targets=targets))
    before=native.run_engine(output,files)
    native.write_json(output/'before.json',before)
    replacements=copy.deepcopy(files);reports={}
    for item in replacements:
        mesh_set=before['files'][item['resource']]['snapshot']['meshes'];item['replacements']={}
        for label in item['targets']:
            s=mesh_set[label]['surfaces'][0]
            positions=np.frombuffer(native.read_record(s['decoded']['0']),dtype='<f4').reshape(-1,3)
            colors=np.frombuffer(native.read_record(s['decoded']['3']),dtype='<f4').reshape(-1,4)
            old_indices=np.frombuffer(native.read_record(s['raw_buffers']['index_data']),dtype=f"<u{s['index_stride']}").astype(np.uint32).reshape(-1,3)
            indices,stats=reduce_leaf_indices(positions,colors,old_indices,aggressive)
            new,ids,mapping=buffers_for(s,indices)
            stats.update(beforeVertices=s['vertex_count'],afterVertices=len(ids),selectedVertexAttributesByteExact=True)
            target={'vertex_count':len(ids),'index_count':indices.size,'buffers':{}}
            for key,value in new.items():
                path=output/'buffers'/f'{label}-{key}.bin';native.write_new(path,value)
                target['buffers'][key]={'path':str(path),'bytes':len(value),'sha256':sha(value)}
            item['replacements'][label]=target;reports[label]=stats
            print(json.dumps({'mesh':label,**stats}),flush=True)
    after=native.run_engine(output,replacements,assemble=True)
    changes={}
    for resource in TARGETS:
        a=before['files'][resource]['snapshot'];b=after['files'][resource]['snapshot']
        for key in ('tree','bundle','packed_properties'):
            require(a[key]==b[key],f'Node/material/collision/metadata exact: {resource}:{key}')
        for label in a['meshes']:
            if label not in TARGETS[resource]:
                require(a['meshes'][label]==b['meshes'][label],'Untargeted mesh exact')
            else:
                s=b['meshes'][label]['surfaces'][0]
                item=next(f for f in replacements if f['resource']==resource)['replacements'][label]
                require(s['vertex_count']==item['vertex_count'] and s['index_count']==item['index_count'],'Native LOD counts')
                for key,record in item['buffers'].items():
                    require(s['raw_buffers'][key]['sha256']==record['sha256'],'Native raw vertex/index reload exact')
        data=Path(after['files'][resource]['path']).read_bytes();raw=_unpack(data)
        packed=_pack(raw,1048576,19);require(_unpack(packed)==raw,'RSCC roundtrip')
        changes[resource]=packed
        native.write_new(output/'caches'/Path(resource).name,packed)
    candidate=output/'index-lite.pck';write_pack(BASE,inventory,candidate,changes)
    proof={'schemaVersion':1,'sourceSha256':PIN,'profile':'complete-scene-leaf-lod-v128',
           'aggressiveBlades':aggressive,'meshes':reports,'candidateSha256':sha(candidate.read_bytes()),
           'beforeBytes':len(blob),'afterBytes':candidate.stat().st_size,
           'afterGzip6Bytes':len(gzip.compress(candidate.read_bytes(),compresslevel=6,mtime=0)),
           'allOtherEntriesByteExact':True,'visualAcceptance':'pending'}
    ci=read_pack(candidate);cb=candidate.read_bytes()
    require(len(ci['entries'])==len(inventory['entries']),'Inventory exact')
    for r in ci['entries']:
        require(cb[r['offset']:r['offset']+r['bytes']]==changes.get(r['path'],entries[r['path']]),'PCK resource exact')
    require(BASE.read_bytes()==blob,'Frozen input unchanged')
    native.write_json(output/'proof.json',proof)
    native.write_json(output/'after.json',after)
    print(json.dumps(proof,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--aggressive',action='store_true')
    args=parser.parse_args();build(args.output,args.aggressive)
