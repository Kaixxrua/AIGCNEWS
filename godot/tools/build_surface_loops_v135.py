"""Isolated two-include equivalent-loop candidate; no source art/compiler edits.

Build once into candidate-13/boot-13. Only bound the two existing count-guarded
32-element loops by their existing count uniforms. Keep every loop body, break,
uniform, material, source GDC and detail chunk byte exact.
"""
from pathlib import Path
import copy
import gzip
import json
import sys

sys.dont_write_bytecode = True
import build_sky_overlay_v135 as frozen
import build_progressive_web_v135 as packer

OUT = frozen.BUILD/'candidate-13'
BOOT = frozen.BUILD/'boot-13'
TARGETS = {
    'shaders/meadow_cutout_surface.gdshaderinc': ('window_count',
        'e3631dedde7d8d7909e520cbff9277369fdbb6bdad6f86edcc3b48f098a3b0f0'),
    'shaders/meadow_architecture.gdshaderinc': ('architecture_count',
        '4d6de71b7efe62475f7cfb11835b0dfe97c2400fb3d3db73958124f0da4ef70b'),
}


def revise(data, count, expected):
    frozen.require(frozen.sha(data) == expected, 'Exact original include required')
    old = b'for (int i = 0; i < 32; i++) {'
    new = f'for (int i = 0; i < min({count}, 32); i++) {{'.encode()
    guard = f'if (i >= {count}) {{ break; }}'.encode()
    frozen.require(data.count(old) == 1 and data.count(guard) == 1, 'One count-guarded loop')
    result = data.replace(old, new, 1)
    frozen.require(result.replace(new, old, 1) == data, 'All non-bound bytes exact')
    # The count is an existing signed uniform. Negative/large counts, zero and
    # every array-valid count retain the same iteration indices and ordering.
    for n in [-2147483648, *range(-2, 36), 2147483647]:
        original = []
        for i in range(32):
            if i >= n:
                break
            original.append(i)
        frozen.require(original == list(range(max(0, min(n, 32)))), 'Index-sequence equality')
    return result


def write(path, data):
    frozen.require(any(path.resolve().is_relative_to(root) for root in (OUT, BOOT)), 'Owned fresh output')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def record(path, data):
    write(path, (json.dumps(data, indent=2, ensure_ascii=False)+'\n').encode())


def build():
    frozen.require(not OUT.exists() and not BOOT.exists(), 'New candidate13 and boot13 only')
    inputs = frozen.preflight()
    replacements = {name: revise(inputs['entries']['mode5'][name], count, pin)
                    for name, (count, pin) in TARGETS.items()}
    proofs = {}
    for kind in ('mode5', 'native'):
        source = frozen.SOURCE/kind/'index-lite.pck'
        values = dict(inputs['entries'][kind])
        for name, (count, pin) in TARGETS.items():
            frozen.require(revise(values[name], count, pin) == replacements[name], 'Same twin include')
        values.update(replacements)
        blob = packer.pack(source.read_bytes()[:112], values)
        destination = OUT/kind/'index-lite.pck'
        write(destination, blob)
        _, after = frozen.pack_entries(destination, blob)
        frozen.require(list(after) == list(inputs['entries'][kind]), 'Same ordered entries')
        changed = {name for name in after if after[name] != inputs['entries'][kind][name]}
        frozen.require(changed == set(TARGETS), 'Only the two loop bounds may change')
        for row in inputs['chunks'][kind]:
            write(OUT/kind/row['file'], frozen.pinned(frozen.SOURCE/kind/row['file'], row['sha256']))
        write(OUT/kind/'progressive-manifest.json', (frozen.SOURCE/kind/'progressive-manifest.json').read_bytes())
        proof = copy.deepcopy(inputs['sourceProofs'][kind])
        proof.update(coreSha256=frozen.sha(blob), coreBytes=len(blob),
                     coreGzipBytes=len(gzip.compress(blob, compresslevel=6, mtime=0)),
                     sourceCoreSha256=frozen.CORE_PINS[kind], visualAcceptance='pending',
                     tenSecondTarget='unverified', loopOverlay={
                         name: {'beforeSha256': TARGETS[name][1], 'sha256': frozen.sha(value)}
                         for name, value in replacements.items()},
                     allOtherEntriesAndChunksExact=True, noNewUniforms=True,
                     originalBodiesAndBreaksExact=True)
        proofs[kind] = proof
    for name in ('script-proof.json', 'water-proof.json', 'meadow_scene.progressive.gd'):
        write(OUT/name, frozen.pinned(frozen.SOURCE/name, frozen.PINS[frozen.SOURCE/name]))
    boot_bytes = frozen.pinned(frozen.BOOT_SOURCE/'bootstrap.pck', frozen.PINS[frozen.BOOT_SOURCE/'bootstrap.pck'])
    write(BOOT/'bootstrap.pck', boot_bytes)
    boot = copy.deepcopy(inputs['bootManifest'])
    boot.update(coreSha256=proofs['mode5']['coreSha256'], inheritedFrom=str(frozen.BOOT_SOURCE),
                bootstrapBytesExact=True, reportsSceneReady=False)
    record(BOOT/'bootstrap-manifest.json', boot)
    for path, pin in inputs['inputPins'].items():
        frozen.pinned(path, pin)
    for kind, proof in proofs.items():
        record(OUT/kind/'proof.json', proof)
    record(OUT/'proof.json', proofs)
    print(json.dumps({kind: {key: value[key] for key in ('coreSha256','coreBytes','coreGzipBytes')}
                      for kind,value in proofs.items()}, indent=2))


if __name__ == '__main__':
    build()
