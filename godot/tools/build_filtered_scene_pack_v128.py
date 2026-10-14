"""Lossless project-specific RSCC mode 5, requiring the matching custom engine.

All decoded resource bytes are exact. Standard original/balanced packs continue
using stock codecs. Writes a NEW artifact candidate and a stock-codec audit twin;
the twin is only for stock-native probes, never used as Web timing evidence.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import struct
import time
import zstandard as zstd
from inspect_web_pack import read_pack
from build_web_quality import write_pack
from repack_web_cache import _pack, _unpack
from probe_lossless_filter_v128 import transform, inverse, MODES

ROOT=Path(__file__).resolve().parents[2]
SCOPE=ROOT/'artifacts/startup-v128/filtered-scenes'
BLOCK=1048576

def decode(blob):
    if len(blob)<24 or blob[:4]!=b'RSCC' or blob[-4:]!=b'RSCC': raise ValueError('Invalid resource')
    mode,block,size=struct.unpack_from('<III',blob,4)
    if mode!=5 or block!=BLOCK or size>512*1024*1024: raise ValueError('Unsupported filtered format')
    count=size//block+1;cursor=16+count*4
    if cursor>len(blob)-4: raise ValueError('Missing table')
    result=[];decoder=zstd.ZstdDecompressor()
    for n,length in enumerate(struct.unpack_from(f'<{count}I',blob,16)):
        if length<2 or cursor+length>len(blob)-4: raise ValueError('Invalid frame span')
        filter_id=blob[cursor]
        if filter_id>=len(MODES): raise ValueError('Invalid filter')
        frame=blob[cursor+1:cursor+length];cursor+=length
        expected=min(block,size-n*block)
        data=decoder.decompress(frame,max_output_size=max(1,expected),allow_extra_data=False)
        if len(data)!=expected: raise ValueError('Wrong decoded size')
        result.append(inverse(data,*MODES[filter_id]))
    if cursor!=len(blob)-4: raise ValueError('Unexpected trailing frame')
    return b''.join(result)


def encode(raw,level=19):
    compressor=zstd.ZstdCompressor(level=level)
    frames=[];chosen=[]
    for offset in range(0,len(raw)+1,BLOCK):
        block=raw[offset:offset+BLOCK]
        alternatives=[]
        for mode,(width,stride) in enumerate(MODES):
            transformed=transform(block,width,stride)
            assert inverse(transformed,width,stride)==block
            alternatives.append(bytes([mode])+compressor.compress(transformed))
        mode=min(range(len(alternatives)),key=lambda k:len(alternatives[k]))
        frames.append(alternatives[mode]);chosen.append(mode)
    blob=struct.pack('<4sIII',b'RSCC',5,BLOCK,len(raw))+struct.pack(f'<{len(frames)}I',*map(len,frames))+b''.join(frames)+b'RSCC'
    if decode(blob)!=raw: raise ValueError('Lossless roundtrip mismatch')
    return blob,chosen


def build(source,output):
    source=source.resolve(strict=True);output=output.resolve()
    if output.exists() or not output.is_relative_to(SCOPE) or SCOPE.resolve()!=SCOPE or not source.is_relative_to(ROOT/'artifacts'):
        raise ValueError('New scoped artifact required')
    output.mkdir(parents=True);blob=source.read_bytes();inventory=read_pack(source)
    replacements={};twin_changes={};reports=[]
    for entry in inventory['entries']:
        name=entry['path']
        if not name.startswith('assets/baked/') or not name.endswith('.scn'):continue
        before=blob[entry['offset']:entry['offset']+entry['bytes']]
        if before[:4]!=b'RSCC': continue
        raw=_unpack(before);started=time.monotonic();candidate,modes=encode(raw)
        before_gz=len(gzip.compress(before,compresslevel=6,mtime=0))
        after_gz=len(gzip.compress(candidate,compresslevel=6,mtime=0))
        use=after_gz<before_gz
        if use:
            replacements[name]=candidate
            (output/Path(name).name).write_bytes(candidate)
            twin_changes[name]=_pack(raw,BLOCK,19)
        row={'path':name,'decodedBytes':len(raw),'decodedSha256':hashlib.sha256(raw).hexdigest(),
             'beforeBytes':len(before),'afterBytes':len(candidate),'beforeGzip6Bytes':before_gz,'afterGzip6Bytes':after_gz,
             'selected':use,'filters':modes,'encodeSeconds':round(time.monotonic()-started,2),'allDecodedBytesExact':True}
        reports.append(row);print(json.dumps(row),flush=True)
    destination=output/'index-lite.pck';write_pack(source,inventory,destination,replacements)
    twin=output/'native-audit-twin.pck';write_pack(source,inventory,twin,twin_changes)
    after=destination.read_bytes();rows=read_pack(destination)['entries']
    original={e['path']:blob[e['offset']:e['offset']+e['bytes']] for e in inventory['entries']}
    assert len(rows)==len(inventory['entries'])
    for e in rows:
        value=after[e['offset']:e['offset']+e['bytes']]
        assert value==replacements.get(e['path'],original[e['path']])
        if e['path'] in replacements: assert decode(value)==_unpack(original[e['path']])
    assert source.read_bytes()==blob
    proof={'schemaVersion':1,'profile':'lossless-filtered-RSCC-v128','source':str(source),'sourceSha256':hashlib.sha256(blob).hexdigest(),
           'candidateSha256':hashlib.sha256(after).hexdigest(),'afterBytes':len(after),'afterGzip6Bytes':len(gzip.compress(after,compresslevel=6,mtime=0)),
           'requiresEngineCodec':5,'allDecodedResourcesExact':True,'changes':reports,'nativeAuditTwin':str(twin),
           'visualAcceptance':'pending','readyGateUnchanged':True}
    (output/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k!='changes'},indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build(args.source,args.output)
