"""Bounded standard-Zstd long-window experiment, preserving all resource bytes."""
from pathlib import Path
import json
import struct
import time
import zstandard as zstd
from inspect_web_pack import read_pack
from repack_web_cache import _unpack
from probe_lossless_filter_v128 import transform, inverse

ROOT=Path(__file__).resolve().parents[2]
def run(source,output):
    data=source.read_bytes();records=[]
    for e in read_pack(source)['entries']:
        if e['path'] not in ('assets/baked/v77/detail.scn','assets/baked/v77/terrain.scn','assets/baked/v77/brush.scn'):continue
        blob=data[e['offset']:e['offset']+e['bytes']];raw=_unpack(blob);trials=[]
        for window in (23,26):
            params=zstd.ZstdCompressionParameters.from_level(19,window_log=window)
            encoder=zstd.ZstdCompressor(compression_params=params)
            for width in (0,2):
                start=time.monotonic();encoded=encoder.compress(transform(raw,width,0))
                decoded=zstd.ZstdDecompressor().decompress(encoded,max_output_size=len(raw))
                assert inverse(decoded,width,0)==raw
                trials.append({'windowLog':window,'bytePlaneWidth':width,'bytes':len(encoded),'seconds':round(time.monotonic()-start,2)})
        row={'path':e['path'],'beforeBytes':len(blob),'decodedBytes':len(raw),'trials':trials}
        records.append(row);print(json.dumps(row),flush=True)
    assert not output.exists() and output.resolve().is_relative_to(ROOT/'artifacts/startup-v128')
    output.write_text(json.dumps(records,indent=2))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.source,a.output)
