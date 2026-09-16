"""Apply existing rock AO offline to a scoped lite candidate; no source edits."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import gzip
from inspect_web_pack import read_pack
from build_web_quality import write_pack
from repack_web_cache import _pack, _unpack

ROOT=Path(__file__).resolve().parents[2]
SCOPE=ROOT/'artifacts/startup-v128/ready-ao'
GODOT=ROOT/'.tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe'
def sha(data): return hashlib.sha256(data).hexdigest()

def build(source, output):
    source=source.resolve(strict=True);output=output.resolve()
    if not source.is_relative_to(ROOT/'artifacts/startup-v128') or output.exists() or not output.is_relative_to(SCOPE) or SCOPE.resolve()!=SCOPE:
        raise ValueError('New scoped source/output required')
    output.mkdir(parents=True)
    blob=source.read_bytes();inventory=read_pack(source)
    project=output/'sandbox';project.mkdir()
    (project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="OfflineAO"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[shader_globals]\nmeadow_clock={"type":"float","value":0.0}\nmeadow_night={"type":"float","value":0.0}\n')
    req=output/'request.json';req.write_text(json.dumps({'pack':str(source),'sha256':sha(blob),'output':str(output)}))
    env=dict(os.environ)
    for name in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        directory=output/name.lower();directory.mkdir();env[name]=str(directory)
    p=subprocess.run([str(GODOT),'--headless','--path',str(project),'--script',str(Path(__file__).with_suffix('.gd')),'--',str(req)],
        capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    (output/'process.log').write_text(p.stdout+p.stderr,encoding='utf-8')
    if p.returncode or 'AO_PREAPPLY: PASS' not in p.stdout or 'ERROR:' in p.stdout+p.stderr:
        raise ValueError(p.stdout+p.stderr)
    native=json.loads((output/'native-proof.json').read_text());assert native['passed']
    raw=_unpack((output/'detail.scn').read_bytes());data=_pack(raw,1048576,19);assert _unpack(data)==raw
    candidate=output/'index-lite.pck';write_pack(source,inventory,candidate,{'assets/baked/v77/detail.scn':data})
    after=candidate.read_bytes();out=read_pack(candidate)
    old={e['path']:blob[e['offset']:e['offset']+e['bytes']] for e in inventory['entries']}
    for e in out['entries']:
        assert after[e['offset']:e['offset']+e['bytes']]==(data if e['path']=='assets/baked/v77/detail.scn' else old[e['path']])
    assert source.read_bytes()==blob
    proof={'schemaVersion':1,'profile':'existing-AO-preapplied-v128','source':str(source),'sourceSha256':sha(blob),
        'candidateSha256':sha(after),'afterBytes':len(after),'afterGzip6Bytes':len(gzip.compress(after,compresslevel=6,mtime=0)),
        'allOtherEntriesByteExact':True,'native':native,'visualAcceptance':'pending'}
    (output/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    print(json.dumps(proof,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build(args.source,args.output)
