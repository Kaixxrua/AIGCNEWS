"""Fail closed when a private mode-5 PCK is paired with an unreviewed engine."""
import hashlib
import struct
from inspect_web_pack import read_pack

ENGINE_NAMES = ('index.js', 'index.wasm', 'index.audio.worklet.js', 'index.audio.position.worklet.js')
WORKLETS = ('5b476a9c9ce642c0ee4256436d1bc31d9c38f868aca0f9a8e2a57c18d2dec2a3',
            'be33985bc7160d6bf9646f259cd86b259cd67b02ccb297ee5c44f8ac84327bc8')
# Actual paired release hashes, not a filename/variant-label or user assertion.
MODE5_ENGINES = {
    '2cf070d8255851b908812a9cc7c6299b62b29ed7ebb6d10f8df0b45d8c93d7cc':
        ('f916b72c5d274dfbd51b92461a8cb42f3fd01b840045211ee07e23966ec0bc5d', *WORKLETS),
    '01e849967a05d6d008b9e2527b047e95f36a3e069d48edab67d497ea14c83945':
        ('aa5b17fbdc5f5e72ca7f5bf05c186623d6a86b1ab0aaf87e7dc15ade1d3e1a52', *WORKLETS),
    '52d3ad52fd004291970d1ef02b0f818500f4f57500e20aadcb911373e4a78716':
        ('aa5b17fbdc5f5e72ca7f5bf05c186623d6a86b1ab0aaf87e7dc15ade1d3e1a52', *WORKLETS),
    # Reviewed deferred Web stage diagnostics; actual paired instantiation and
    # unchanged mode-5 source/module/memory proofs live in startup-v135/engine.
    '1bf0d192b97645d76e31fbb7582e3c112981a1e420d5d976ae71757866ee92e1':
        ('96a4fbc94381a8e0c12362f7379f2febc775cf016175e2632820c5f6311195be', *WORKLETS),
}


def require_pair(required, hashes):
    if not required:
        return
    expected = MODE5_ENGINES.get(hashes.get('index.wasm'))
    actual = tuple(hashes.get(name) for name in ('index.js', *ENGINE_NAMES[2:]))
    if expected is None or actual != expected:
        raise ValueError('Private mode-5 scene requires an exact reviewed matching JS/WASM/worklet release; stock or mixed engines cannot be staged')


def validate_pack_engine(pack, members):
    inventory = read_pack(pack, verify=True)
    required = False
    with pack.open('rb') as stream:
        for entry in inventory['entries']:
            if entry['bytes'] < 16:
                continue
            stream.seek(entry['offset'])
            header = stream.read(8)
            required |= header[:4] == b'RSCC' and struct.unpack_from('<I', header, 4)[0] == 5
    hashes = {name: hashlib.sha256(blob).hexdigest() for name, blob in members.items()}
    require_pair(required, hashes)
    return required
