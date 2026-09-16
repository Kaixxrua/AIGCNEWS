"""Candidate15: accept the exact reviewed engine-only bootstrap settings file.

load_resource_pack(..., false) intentionally leaves bootstrap project.binary in
the mounted filesystem. Effective main_scene is restored before real scene load.
The saved-world guard accepts ONLY its original bytes or this pinned bootstrap's
bytes after proving that the initial main-scene filename is the sole difference.
No context comparison, dependency, renderer, script or readiness is bypassed.
"""
import argparse
import copy
import gzip
import json
from pathlib import Path

import build_static_overlay_v135 as previous
import build_sky_overlay_v135 as frozen
import build_progressive_web_v135 as packer
from audit_lite_contract import project_records

SOURCE = frozen.BUILD / 'candidate-14'
BOOT_SOURCE = frozen.BUILD / 'boot-14'
OUT = frozen.BUILD / 'candidate-15'
BOOT = frozen.BUILD / 'boot-15'
PINS = {'native': '6f8b003b703a1a4edf2636ae8f80f75be85add4cd7144b92dede0df028f285d3',
        'mode5': 'e8ae823296bb2281fc0c6eee558b8ef20fd4a06cd52f58834d6a41ff9f4d36cd'}
BOOT_SHA = 'fd5727057ca877d5d4efb6635495df5a80926a85195d4766d090a4f08c162885'
require = frozen.require


def validated_boot_project(core, boot):
    original, selected = project_records(core), project_records(boot)
    require(set(original) == set(selected), 'Bootstrap/core setting inventory exact')
    require({n for n in original if original[n] != selected[n]} == {'application/run/main_scene'},
            'Only initial main-scene setting may differ')
    require(b'res://progressive/boot.tscn' in selected['application/run/main_scene'] and
            b'res://scenes/main.tscn' in original['application/run/main_scene'], 'Exact real scene and boot entry')
    return frozen.sha(boot)


def preflight():
    previous.preflight()
    values, blobs = {}, {}
    for kind, digest in PINS.items():
        path = SOURCE / kind / 'index-lite.pck'
        blobs[kind] = frozen.pinned(path, digest)
        _, values[kind] = frozen.pack_entries(path, blobs[kind])
    previous.verify_twins(values['native'], values['mode5'])
    boot_data = frozen.pinned(BOOT_SOURCE / 'bootstrap.pck', BOOT_SHA)
    _, boot_entries = frozen.pack_entries(BOOT_SOURCE / 'bootstrap.pck', boot_data)
    require(values['native']['project.binary'] == values['mode5']['project.binary'], 'Same project bytes in twins')
    allowed = validated_boot_project(values['native']['project.binary'], boot_entries['project.binary'])
    require(boot_entries['progressive/boot-main-scene.txt'] == b'res://scenes/main.tscn', 'Boot really re-enters original scene')
    boot = json.loads((BOOT_SOURCE / 'bootstrap-manifest.json').read_bytes())
    require(boot['coreSha256'] == PINS['mode5'] and boot['sha256'] == BOOT_SHA and boot['reportsSceneReady'] is False,
            'Original bootstrap binding and real ready boundary')
    for kind in PINS:
        spec = json.loads(values[kind][previous.RUNTIME])
        require(spec['dependencies']['res://project.binary'] == [frozen.sha(values[kind]['project.binary'])], 'Original one-element dependency pin')
        previous.validate_runtime(values[kind])
        manifest = json.loads((SOURCE / kind / 'progressive-manifest.json').read_bytes())
        require(manifest == json.loads(values[kind]['progressive/manifest.json']), 'Original full detail manifest')
        for row in frozen.validate_chunks(manifest):
            require(len(frozen.pinned(SOURCE / kind / row['file'], row['sha256'])) == row['bytes'], 'Frozen real detail chunk')
    return values, blobs, boot_data, boot, allowed


def write(path, data):
    require(any(path.resolve().is_relative_to(p.resolve()) for p in (OUT, BOOT)), 'Owned fresh output')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def record(path, data):
    write(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())


def build():
    require(not OUT.exists() and not BOOT.exists(), 'Fresh candidate15/boot15 only')
    originals, blobs, boot_bytes, boot, allowed = preflight()
    proofs, output_values = {}, {}
    for kind in PINS:
        values = dict(originals[kind])
        before = json.loads(values[previous.RUNTIME])
        revised = copy.deepcopy(before)
        revised['dependencies']['res://project.binary'].append(allowed)
        values[previous.RUNTIME] = (json.dumps(revised, ensure_ascii=False, indent=2) + '\n').encode()
        previous.validate_runtime(values)
        simulated_mount = dict(values)
        _, boot_values = frozen.pack_entries(BOOT_SOURCE / 'bootstrap.pck', boot_bytes)
        simulated_mount.update(boot_values)
        previous.validate_runtime(simulated_mount)
        blob = packer.pack(blobs[kind][:112], values)
        path = OUT / kind / 'index-lite.pck'
        write(path, blob)
        _, actual = frozen.pack_entries(path, blob)
        require(actual == values and {n for n in actual if actual[n] != originals[kind][n]} == {previous.RUNTIME},
                'Only exact runtime manifest may change')
        output_values[kind] = actual
        proof = json.loads((SOURCE / kind / 'proof.json').read_bytes())
        proof.update(sourceCoreSha256=PINS[kind], coreSha256=frozen.sha(blob), coreBytes=len(blob),
                     coreGzipBytes=len(gzip.compress(blob, compresslevel=6, mtime=0)),
                     bootstrapProjectSha256=allowed, onlyExactBootProjectHashAdded=True,
                     coreContextAndAllOtherDependenciesUnchanged=True, tenSecondTarget='unverified')
        proofs[kind] = proof
        manifest = json.loads(values['progressive/manifest.json'])
        for row in manifest['chunks']:
            write(OUT / kind / row['file'], frozen.pinned(SOURCE / kind / row['file'], row['sha256']))
        write(OUT / kind / 'progressive-manifest.json', (SOURCE / kind / 'progressive-manifest.json').read_bytes())
        changes = json.loads((SOURCE / (kind + '-allowed-changes.json')).read_bytes())
        changes['candidateSha256'] = proof['coreSha256']
        for row in changes['changes']:
            if row['path'] == previous.RUNTIME:
                row['afterSha256'] = frozen.sha(values[previous.RUNTIME])
        changes['exactBootstrapProjectHashAdded'] = allowed
        record(OUT / (kind + '-allowed-changes.json'), changes)
    previous.verify_twins(output_values['native'], output_values['mode5'])
    for name in ('script-proof.json', 'water-proof.json', 'meadow_scene.progressive.gd'):
        write(OUT / name, (SOURCE / name).read_bytes())
    write(BOOT / 'bootstrap.pck', boot_bytes)
    boot['coreSha256'] = proofs['mode5']['coreSha256']
    record(BOOT / 'bootstrap-manifest.json', boot)
    preflight()  # All frozen inputs still valid after writing new artifacts.
    for kind in PINS:
        record(OUT / kind / 'proof.json', proofs[kind])
    record(OUT / 'proof.json', proofs)
    print(json.dumps({k: {field: v[field] for field in ('coreSha256', 'coreBytes', 'coreGzipBytes', 'bootstrapProjectSha256')}
                      for k, v in proofs.items()}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        print(json.dumps({'bootstrapProjectSha256': preflight()[-1], 'status': 'READ_ONLY_PREFLIGHT_PASS'}))
    else:
        build()
