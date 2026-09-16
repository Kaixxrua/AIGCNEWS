"""Bounded numeric precision, not polygon simplification or object removal.

Only the four uncompressed solid/brush surfaces in an isolated lite artifact.
Vertex positions snap by at most 0.000489m/axis, UV/UV2 by 0.000489; all
normals/tangents/RGBA/indices/collision shapes/materials remain storage-exact.
Native Godot reloads requested storage bytes. Original/balanced are untouched.
"""
from pathlib import Path
import argparse
import gzip
import json
import numpy as np
import compact_lite_meshes as native
from inspect_web_pack import read_pack
from build_web_quality import write_pack

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / 'artifacts/startup-v128/precision'
TARGETS = {
    'assets/baked/v77/terrain.scn': ['ContinuousMeadow'],
    'assets/baked/v77/detail.scn': ['SolidLimestoneGeology'],
    'assets/baked/v77/brush.scn': ['MiddleMeadowBrush'],
    'assets/baked/v77/riverbank.scn': ['EmbeddedRiverbankStrata'],
}


def quantize(data, step=1/1024, clamp_bounds=False):
    values = np.frombuffer(data, dtype='<f4').reshape(-1, 3 if clamp_bounds else 4)
    if not np.isfinite(values).all(): raise ValueError('Nonfinite input')
    result = (np.rint(values.astype(np.float64) / step) * step).astype('<f4')
    if clamp_bounds:
        result = np.clip(result, values.min(axis=0), values.max(axis=0))
    error = np.abs(result.astype(np.float64) - values)
    if error.max(initial=0) > step/2 + 0.000001: raise ValueError('Precision bound exceeded')
    return result.tobytes(), {'maxComponentError': float(error.max(initial=0)),
                             'meanComponentError': float(error.mean()),
                             'maxVectorError': float(np.linalg.norm(error, axis=1).max(initial=0)),
                             'step': step, 'count': len(values)}


def build(source, output, resume=False):
    source = source.resolve(strict=True); output = output.resolve()
    if not output.is_relative_to(SCOPE) or (output.exists() and not resume): raise ValueError('New scoped output required')
    if (output / 'index-lite.pck').exists(): raise ValueError('Never overwrite candidate')
    output.mkdir(parents=True, exist_ok=resume)
    native.SCOPE = SCOPE; native.BASE = source; native.TARGETS = TARGETS
    original = source.read_bytes(); inventory = read_pack(source)
    entries = {e['path']: original[e['offset']:e['offset']+e['bytes']] for e in inventory['entries']}
    sources=[]
    for path, targets in TARGETS.items():
        file = output / 'source' / Path(path).name
        if not file.exists(): native.write_new(file, entries[path])
        if file.read_bytes() != entries[path]: raise ValueError('Input fingerprint changed')
        sources.append(dict(resource=path, targets=targets, path=str(file), sha256=native.sha(entries[path])))
    cache=output/'before.json'
    before=json.loads(cache.read_text()) if cache.exists() else native.run_engine(output,sources)
    if not cache.exists(): native.write_json(cache,before)
    replacements={}; statistics={}; raw_expected={}
    for path, targets in TARGETS.items():
        replacements[path]={}
        for label in targets:
            mesh=before['files'][path]['snapshot']['meshes'][label]
            if len(mesh['surfaces']) != 1: raise ValueError('Only one surface expected')
            surface=mesh['surfaces'][0]; count=surface['vertex_count']
            stride=surface['attribute_stride']; color_width=stride-16
            if surface['vertex_stride'] != 12 or surface['normal_tangent_stride'] not in (4,8) or stride not in (16,20):
                raise ValueError(f'Unexpected solid format: {label}')
            buffers={k:native.read_record(surface['raw_buffers'][k]) for k in ('vertex_data','attribute_data','index_data')}
            position_bytes,pos_proof=quantize(buffers['vertex_data'][:count*12],clamp_bounds=True)
            result=dict(buffers); result['vertex_data']=position_bytes+buffers['vertex_data'][count*12:]
            attrs=np.frombuffer(buffers['attribute_data'],dtype=np.uint8).reshape(count,stride).copy()
            uv_bytes,uv_proof=quantize(attrs[:,color_width:].copy().tobytes())
            attrs[:,color_width:]=np.frombuffer(uv_bytes,dtype=np.uint8).reshape(count,16)
            result['attribute_data']=attrs.tobytes()
            # No new degenerate face or flipped face from numeric snapping.
            indices=np.frombuffer(buffers['index_data'],dtype=f"<u{surface['index_stride']}").reshape(-1,3)
            a=np.frombuffer(buffers['vertex_data'][:count*12],dtype='<f4').reshape(-1,3).astype(np.float64)[indices]
            b=np.frombuffer(position_bytes,dtype='<f4').reshape(-1,3).astype(np.float64)[indices]
            na=np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]); nb=np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0])
            valid=np.linalg.norm(na,axis=1)>1e-12
            bad=valid & ((np.linalg.norm(nb,axis=1)<=1e-12) | (np.einsum('ij,ij->i',na,nb)<=0))
            # Preserve all corners of affected triangles verbatim; never drop them.
            restored=np.unique(indices[bad].ravel())
            if len(restored):
                p=np.frombuffer(position_bytes,dtype='<f4').reshape(-1,3).copy()
                p[restored]=np.frombuffer(buffers['vertex_data'][:count*12],dtype='<f4').reshape(-1,3)[restored]
                result['vertex_data']=p.tobytes()+buffers['vertex_data'][count*12:]
                b=p.astype(np.float64)[indices]; nb=np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0])
                if np.any(valid & ((np.linalg.norm(nb,axis=1)<=1e-12)|(np.einsum('ij,ij->i',na,nb)<=0))):
                    raise ValueError('Restored local corners still changed another face')
            records={}
            for key,value in result.items():
                file=output/'buffers'/f'{label}-{key}.bin'
                if not file.exists(): native.write_new(file,value)
                if file.read_bytes()!=value: raise ValueError('Stale buffer')
                records[key]={'path':str(file),'bytes':len(value),'sha256':native.sha(value)}
            replacements[path][label]={'vertex_count':count,'buffers':records}
            raw_expected[label]=result
            statistics[label]={'positions':pos_proof,'UV_UV2':uv_proof,'preservedDegenerateCorners':len(restored),
                               'indicesExact':result['index_data']==buffers['index_data'],
                               'normalTangentExact':result['vertex_data'][count*12:]==buffers['vertex_data'][count*12:],
                               'RGBAExact':bool(np.array_equal(attrs[:,:color_width],np.frombuffer(buffers['attribute_data'],dtype=np.uint8).reshape(count,stride)[:,:color_width]))}
            print(json.dumps({label:statistics[label]}),flush=True)
    after=native.run_engine(output,[{**s,'replacements':replacements[s['resource']]} for s in sources],assemble=True)
    native.write_json(output/'after.json',after)
    changed={}
    for path,targets in TARGETS.items():
        a=before['files'][path]['snapshot']; b=after['files'][path]['snapshot']
        for key in ('tree','bundle','packed_properties'):
            if a[key] != b[key]: raise ValueError(f'Node/material/collider/metadata changed {path}:{key}')
        for label,mesh in a['meshes'].items():
            candidate=b['meshes'][label]
            if label not in targets:
                if mesh!=candidate: raise ValueError('Untargeted mesh changed')
                continue
            sa=mesh['surfaces'][0]; sb=candidate['surfaces'][0]
            for key in ('fixed','format','vertex_count','index_count','vertex_stride','normal_tangent_stride','attribute_stride','index_stride'):
                if sa[key]!=sb[key]: raise ValueError('Surface properties changed')
            for key,value in raw_expected[label].items():
                if native.read_record(sb['raw_buffers'][key])!=value: raise ValueError('Native storage not exact')
            for channel in ('1','2','3'):
                if sa['channel_hashes'][channel]!=sb['channel_hashes'][channel]: raise ValueError('Normals/tangents/colors changed')
        changed[path]=Path(after['files'][path]['path']).read_bytes()
    destination=output/'index-lite.pck'; write_pack(source,inventory,destination,changed)
    blob=destination.read_bytes()
    for e in read_pack(destination)['entries']:
        if blob[e['offset']:e['offset']+e['bytes']]!=changed.get(e['path'],entries[e['path']]): raise ValueError('Unscoped resource change')
    if source.read_bytes()!=original: raise ValueError('Source changed')
    proof={'source':str(source),'sourceSha256':native.sha(original),'candidateSha256':native.sha(blob),
           'candidateBytes':len(blob),'candidateGzip6Bytes':len(gzip.compress(blob,compresslevel=6,mtime=0)),
           'boundedLossyGeometry':True,'trianglesObjectsCollidersMaterialsRGBAExact':True,'details':statistics,
           'visualAcceptance':'pending; not equivalent to an image review'}
    native.write_json(output/'proof.json',proof);print(json.dumps(proof,indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true')
    args=p.parse_args();build(args.source,args.output,args.resume)
