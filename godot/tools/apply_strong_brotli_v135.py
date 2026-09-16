"""Finalize a NEW, not-yet-previewed v152 with the exact verified Brotli11 WASM.

Only compressed transport and its size/hash metadata change. Raw engine, packs,
JS, controls and gzip fallback remain frozen. No recompression is performed.
"""
from pathlib import Path
import copy
import json
import brotli

from prepare_web_build import sha256, atomic_output, quality_html

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'artifacts/v152'
TRANSFER = ROOT / 'artifacts/startup-v135/transfer-br/candidate-01'
PROOF_SHA = 'd081a04af27ea401a906f3f13854ee75ca4b89a1ffd3eaaf5d5e2d33bf0158c8'
RAW_SHA = '1bf0d192b97645d76e31fbb7582e3c112981a1e420d5d976ae71757866ee92e1'
BEFORE_BR = '772dfb415d75c2516c849b3eb14e2a9aad9dc48a8eb5ec584363404aca91963b'
AFTER_BR = 'd04c9aede11842cce88dca647a15812d2514037858e8a02727fc0d068e0d089e'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def finalize():
    require(DEST.resolve() == DEST and not (DEST / 'strong-brotli-proof.json').exists(), 'Exact fresh not-yet-previewed v152 only')
    require(sha256(TRANSFER / 'proof.json') == PROOF_SHA, 'Frozen independent compression proof')
    proof = json.loads((TRANSFER / 'proof.json').read_bytes())
    require(proof['status'] == 'PASS' and proof['candidate']['sha256'] == AFTER_BR and proof['source']['sha256'] == RAW_SHA,
            'Reviewed compression candidate only')
    raw = (DEST / 'index.wasm').read_bytes()
    br = (TRANSFER / 'wasm.br').read_bytes()
    require(sha256(DEST / 'index.wasm') == RAW_SHA and sha256(DEST / 'index.wasm.br') == BEFORE_BR and
            sha256(TRANSFER / 'wasm.br') == AFTER_BR, 'Original staging and replacement exact')
    require(brotli.decompress(br) == raw and len(br) == 4448037, 'Actual compressed transport decodes byte-for-byte')
    changed_names = {'index.wasm.br', 'web-payload.json', 'index.html'}
    retained = {p.name: sha256(p) for p in DEST.iterdir() if p.is_file() and p.name not in changed_names}
    before_sizes = json.loads((DEST / 'web-payload.json').read_bytes())
    require(before_sizes['index.wasm']['sha256'] == RAW_SHA and
            before_sizes['index.wasm']['encodings']['br']['sha256'] == BEFORE_BR, 'Metadata matches actual staging')
    sizes = copy.deepcopy(before_sizes)
    sizes['index.wasm']['brotliBytes'] = len(br)
    sizes['index.wasm']['encodings']['br'] = {'bytes': len(br), 'sha256': AFTER_BR}
    html = (DEST / 'index.html').read_text(encoding='utf-8')
    revised_html = quality_html(html, sizes)
    require(revised_html != html, 'Actual HTML transfer metadata must update')
    for path, data in [(DEST / 'index.wasm.br', br),
                       (DEST / 'web-payload.json', json.dumps(sizes, indent=2).encode()),
                       (DEST / 'index.html', revised_html.encode())]:
        with atomic_output(path) as temporary:
            temporary.write_bytes(data)
    require(all(sha256(DEST / name) == digest for name, digest in retained.items()), 'Raw engine, game and fallback bytes must remain unchanged')
    require(brotli.decompress((DEST / 'index.wasm.br').read_bytes()) == (DEST / 'index.wasm').read_bytes(), 'Published sidecar re-read exact')
    result = {'status': 'EXACT_TRANSPORT_ONLY', 'transferProofSha256': PROOF_SHA,
              'sourceWasmSha256': RAW_SHA, 'brotliSha256': AFTER_BR, 'brotliBytes': len(br),
              'savedBrotliBytes': 801162, 'changedFiles': sorted(changed_names),
              'unchangedFiles': retained, 'nativeRuntimeAndVisualBytesChanged': False,
              'networkReadyTarget': 'NOT_YET_MEASURED',
              'reprepareWarning': 'Do not run default Brotli6 preparation over this sealed selected sidecar.'}
    with (DEST / 'strong-brotli-proof.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'unchangedFiles'}, indent=2))


if __name__ == '__main__':
    finalize()
