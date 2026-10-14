"""Offline, read-only payload experiment; outputs new JSON, never source assets.

Compare reversible byte-plane/delta filters before RSCC Zstd. This is NOT an
engine-supported delivery format yet and cannot be staged without a decoder.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import time
import numpy as np
import zstandard as zstd
from inspect_web_pack import read_pack
from repack_web_cache import _unpack

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'artifacts/v127/index-lite.pck'
PIN = '771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf'
MODES = ((0, 0), (2, 0), (4, 0), (8, 0), (4, 1), (4, 3), (4, 5), (2, 4))


def transform(blob, width, stride):
    if not width:
        return blob
    size = len(blob) // width * width
    words = np.frombuffer(blob[:size], dtype=f'<u{width}').copy()
    if stride and len(words) > stride:
        words[stride:] = words[stride:] - words[:-stride]
    return words.view(np.uint8).reshape(-1, width).T.copy().tobytes() + blob[size:]


def inverse(blob, width, stride):
    if not width:
        return blob
    size = len(blob) // width * width
    words = np.frombuffer(blob[:size], dtype=np.uint8).reshape(width, -1).T.copy().ravel().view(f'<u{width}')
    if stride:
        for offset in range(stride):
            words[offset::stride] = np.cumsum(words[offset::stride], dtype=f'<u{width}')
    return words.tobytes() + blob[size:]


def run(output, full=False):
    output = output.resolve()
    scope = ROOT / 'artifacts/startup-v128'
    if output.exists() or scope.resolve() != scope or not output.is_relative_to(scope):
        raise ValueError('NEW scoped report required')
    pack = BASE.read_bytes()
    assert hashlib.sha256(pack).hexdigest() == PIN
    rows = []
    compressor = zstd.ZstdCompressor(level=16 if full else 9)
    for entry in read_pack(BASE)['entries']:
        name = entry['path']
        if not name.endswith('.scn') or '/baked/' not in name:
            continue
        before = pack[entry['offset']:entry['offset']+entry['bytes']]
        raw = _unpack(before)
        blocks = [raw[i:i+1048576] for i in range(0, len(raw), 1048576)]
        if not full:
            blocks = [blocks[i] for i in sorted(set([0, len(blocks)//3, len(blocks)//2, len(blocks)-1]))]
        trials = []
        best = []
        for i, block in enumerate(blocks):
            scores = []
            for mode, (width, stride) in enumerate(MODES):
                data = transform(block, width, stride)
                assert inverse(data, width, stride) == block
                scores.append(len(compressor.compress(data))+1)
            best.append(min(scores))
            trials.append(scores)
        row = {'path':name, 'sourceBytes':len(before), 'decodedBytes':len(raw), 'sampledBytes':sum(map(len,blocks)),
               'filterTotals':np.array(trials).sum(axis=0).tolist(), 'adaptiveBytes':sum(best),
               'blocks':trials, 'roundTripExact':True}
        rows.append(row)
        print(json.dumps({k:v for k,v in row.items() if k!='blocks'}), flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump({'sourceSha256':PIN,'full':full,'modes':MODES,'rows':rows},stream,indent=2)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    run(args.output,args.full)
