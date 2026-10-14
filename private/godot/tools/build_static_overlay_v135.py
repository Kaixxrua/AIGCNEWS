"""Main-owned candidate14: saved fixed world, original live tail and 12 chunks.

Only creates NEW candidate-14/boot-14. No native, compiler, browser or engine
invocation. --check is read-only; --build encodes the reviewed saved world with
the existing lossless mode5 codec. Retained original artifacts are never edited.
"""
from pathlib import Path
import argparse
import copy
import gzip
import json
import sys

sys.dont_write_bytecode = True
import build_sky_overlay_v135 as frozen
import build_progressive_web_v135 as packer
from build_filtered_scene_pack_v128 import encode, decode

OUT = frozen.BUILD / 'candidate-14'
BOOT = frozen.BUILD / 'boot-14'
SIDE = frozen.ROOT / 'artifacts/startup-v135/static-core/candidate-01'
MANIFEST_SHA = '64431a48225cdf625bc8a8a346fb83f284246523f20912679e9868b1d5222afb'
WORLD = 'progressive/static-core/world.scn'
RUNTIME = 'progressive/static-core/manifest.json'
PRIVATE_MAIN = 'scripts/meadow_scene.gdc'
REMAPPING = 'scenes/main.tscn.remap'
EXPECTED_NEW = {WORLD, RUNTIME, 'progressive/static-core/entry.tscn',
                'progressive/static-core/restore.gdc', 'progressive/static-core/restore.gd.remap'}


def require(value, message):
    frozen.require(value, message)


def preflight():
    # Reuse the pinned core10/chunk/bootstrap inventory; the independently
    # checked sky overlay is NOT applied. Every actual shader stays core10.
    inputs = frozen.preflight()
    manifest_bytes = frozen.pinned(SIDE / 'manifest.json', MANIFEST_SHA)
    spec = json.loads(manifest_bytes)
    require(spec['schema'] == 'static-core-overlay-v1' and spec['status'] == 'PASS_STATIC_RESTORE',
            'Actual final static restore proof required')
    require(spec['sourcePacks'] == frozen.CORE_PINS, 'Pinned twin source packs')
    require(spec['unchangedDynamicTail'] and spec['thinEntry']['initialMeshAndShapeCount'] == 0,
            'Original live tail and thin initial entry')
    input_pins = dict(inputs['inputPins'])
    input_pins[SIDE / 'manifest.json'] = MANIFEST_SHA
    for row in [spec['runtimeValidation'], *spec['proof'].values()]:
        if isinstance(row, dict) and 'path' in row:
            path = Path(row['path'])
            require(path.resolve().is_relative_to(SIDE.resolve()), 'Static proof within owned sidecar')
            data = frozen.pinned(path, row['sha256'])
            require(len(data) == row['bytes'], 'Static proof byte count')
            input_pins[path] = row['sha256']
    overlays = {}
    require(len(spec['entries']) == 8 and len(spec['removeEntries']) == 26, 'Reviewed bounded overlay inventory')
    for row in spec['entries']:
        name, path = row['entry'], Path(row['path'])
        require(name not in overlays and path.resolve().is_relative_to((SIDE / 'release-04/entries').resolve()), 'Exact final release04 entries')
        data = frozen.pinned(path, row['sha256'])
        require(len(data) == row['bytes'], 'Overlay byte length')
        for kind in frozen.CORE_PINS:
            previous = inputs['entries'][kind].get(name)
            require((frozen.sha(previous) if previous is not None else None) == row['beforeSha256'], 'Overlay before pin: ' + name)
        overlays[name] = data
        input_pins[path] = row['sha256']
    new = set(overlays) - set(inputs['entries']['native'])
    changed = {n for n, b in overlays.items() if n in inputs['entries']['native'] and b != inputs['entries']['native'][n]}
    require(new == EXPECTED_NEW and changed == {PRIVATE_MAIN, REMAPPING}, 'Only reviewed private main, entry and world')
    removals = {r['entry']: r for r in spec['removeEntries']}
    require(len(removals) == 26 and not set(removals) & set(overlays), 'Unique disjoint pinned removals')
    for name, row in removals.items():
        for kind, key in [('native', 'beforeSha256'), ('mode5', 'mode5BeforeSha256')]:
            require(name in inputs['entries'][kind] and frozen.sha(inputs['entries'][kind][name]) == row[key], 'Exact obsolete entry: ' + name)
    runtime = json.loads(overlays[RUNTIME])
    require(runtime['scene'] == 'res://' + WORLD and runtime['sceneSha256'] == frozen.sha(overlays[WORLD]), 'Native world hash binding')
    require(runtime['nodes'] == 121 and len(runtime['typedArrays']) == 21, 'Reviewed saved node/typed-array counts')
    require(not any(('res://' + n) in runtime['dependencies'] for n in removals), 'Removed files cannot remain runtime dependencies')
    require(frozen.sha(frozen.logical(overlays[WORLD])) == spec['sceneContainerProof']['logicalSha256'], 'Saved resource decoded bytes')
    main = (SIDE / 'cached-main.gd').read_bytes()
    source_record = json.loads((SIDE / 'prepared.json').read_bytes())['cachedSource']
    require(frozen.sha(main) == source_record['sha256'], 'Actual compiled private main source')
    input_pins[SIDE / 'cached-main.gd'] = source_record['sha256']
    original = inputs['data'][frozen.SOURCE / 'meadow_scene.progressive.gd']
    tail = b'\tvar weather := WEATHER_CONTROLLER.new()\n'
    ready = b'func _ready() -> void:\n'
    require(original[:original.index(ready)] == main[:main.index(ready)] and
            original[original.index(tail):] == main[main.index(tail):], 'All nonstatic setup source bytes exact')
    inputs.update(overlay=overlays, staticManifest=spec, runtime=runtime, removals=removals,
                  staticMain=main, inputPins=input_pins)
    return inputs


def validate_runtime(entries):
    spec = json.loads(entries[RUNTIME])
    require(spec['sceneSha256'] == frozen.sha(entries[WORLD]), 'Actual world must match runtime hash')
    for path, hashes in spec['dependencies'].items():
        require(path.startswith('res://') and path[6:] in entries, 'Runtime dependency exists: ' + path)
        require(frozen.sha(entries[path[6:]]) in hashes, 'Actual dependency hash is permitted: ' + path)


def verify_twins(native, mode5):
    require(list(native) == list(mode5), 'All twin paths and order match')
    for name in native:
        if name == 'progressive/manifest.json':
            require(frozen.sha(native[name]) == frozen.EMBEDDED_MANIFEST_PINS['native'] and
                    frozen.sha(mode5[name]) == frozen.EMBEDDED_MANIFEST_PINS['mode5'], 'Frozen detail transport manifest')
        elif name == RUNTIME:
            a, b = json.loads(native[name]), json.loads(mode5[name])
            require(a.pop('sceneSha256') == frozen.sha(native[WORLD]) and
                    b.pop('sceneSha256') == frozen.sha(mode5[WORLD]) and a == b, 'Only world transport hash may differ')
        else:
            require(native[name] == mode5[name] or frozen.logical(native[name]) == frozen.logical(mode5[name]), 'Twin logical parity: ' + name)


def write(path, data):
    require(any(path.resolve().is_relative_to(root.resolve()) for root in (OUT, BOOT)), 'Owned output only')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def record(path, value):
    write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def build():
    require(not OUT.exists() and not BOOT.exists(), 'New candidate14 and boot14 only')
    inputs = preflight()
    raw = frozen.logical(inputs['overlay'][WORLD])
    compressed, filters = encode(raw)
    require(decode(compressed) == raw, 'Exact full-world mode5 decode')
    print(json.dumps({'worldNativeBytes': len(inputs['overlay'][WORLD]), 'worldMode5Bytes': len(compressed),
                      'worldDecodedSha256': frozen.sha(raw), 'filters': filters}), flush=True)
    results, entries_after, changes = {}, {}, {}
    for kind in ('native', 'mode5'):
        before = inputs['entries'][kind]
        values = {n: b for n, b in before.items() if n not in inputs['removals']}
        values.update(inputs['overlay'])
        if kind == 'mode5':
            values[WORLD] = compressed
            runtime = copy.deepcopy(inputs['runtime'])
            runtime['sceneSha256'] = frozen.sha(compressed)
            values[RUNTIME] = (json.dumps(runtime, ensure_ascii=False, indent=2) + '\n').encode()
        values = dict(sorted(values.items()))
        validate_runtime(values)
        blob = packer.pack((frozen.SOURCE / kind / 'index-lite.pck').read_bytes()[:112], values)
        path = OUT / kind / 'index-lite.pck'
        write(path, blob)
        _, actual = frozen.pack_entries(path, blob)
        require(list(actual) == list(values) and actual == values, 'Actual PCK entry bytes/MD5/order')
        require(set(before) - set(actual) == set(inputs['removals']), 'Only pinned obsolete entries removed')
        require(all(actual[n] == b for n, b in before.items() if n not in inputs['removals'] and n not in inputs['overlay']),
                'Every untouched source entry byte exact')
        entries_after[kind] = actual
        changes[kind] = [{'path': n, 'beforeSha256': frozen.sha(before[n]) if n in before else None,
                          'afterSha256': frozen.sha(actual[n]) if n in actual else None}
                         for n in sorted(set(before) | set(actual)) if before.get(n) != actual.get(n)]
        for row in inputs['chunks'][kind]:
            write(OUT / kind / row['file'], frozen.pinned(frozen.SOURCE / kind / row['file'], row['sha256']))
        write(OUT / kind / 'progressive-manifest.json', (frozen.SOURCE / kind / 'progressive-manifest.json').read_bytes())
        proof = copy.deepcopy(inputs['sourceProofs'][kind])
        proof.update(profile='progressive-v135-static-preassembled', sourceCoreSha256=frozen.CORE_PINS[kind],
                     coreSha256=frozen.sha(blob), coreBytes=len(blob),
                     coreGzipBytes=len(gzip.compress(blob, compresslevel=6, mtime=0)),
                     staticOverlaySha256=MANIFEST_SHA, worldSha256=frozen.sha(values[WORLD]),
                     worldLogicalSha256=frozen.sha(raw), removedEntryCount=26,
                     sameSceneObjectsAndOriginalDynamicTail=True, chunksAndTexturesAndShadersByteExactTo10=True,
                     nativeRuntimeValidation='pending-independent-actual-pack', visualAcceptance='pending', tenSecondTarget='unverified')
        results[kind] = proof
    verify_twins(entries_after['native'], entries_after['mode5'])
    script = copy.deepcopy(inputs['scriptProof'])
    script.update(mainSourceSha256=frozen.sha(inputs['staticMain']), mainGdcSha256=frozen.sha(inputs['overlay'][PRIVATE_MAIN]),
                  mainSourceBeforeSha256=script['mainSourceSha256'], staticOverlaySha256=MANIFEST_SHA,
                  nativeRuntimeValidation='pending-independent-actual-pack', retainedDynamicTailByteExact=True,
                  offlineStaticWorld=True, allOtherMainSourceBytesExact=True)
    record(OUT / 'script-proof.json', script)
    write(OUT / 'meadow_scene.progressive.gd', inputs['staticMain'])
    write(OUT / 'water-proof.json', inputs['data'][frozen.SOURCE / 'water-proof.json'])
    write(BOOT / 'bootstrap.pck', inputs['data'][frozen.BOOT_SOURCE / 'bootstrap.pck'])
    boot = copy.deepcopy(inputs['bootManifest'])
    boot.update(coreSha256=results['mode5']['coreSha256'], bootstrapBytesExactToBoot10=True,
                originalMainSceneNameUnchanged=True, reportsSceneReady=False)
    record(BOOT / 'bootstrap-manifest.json', boot)
    for path, digest in inputs['inputPins'].items():
        frozen.pinned(path, digest)
    for kind, proof in results.items():
        record(OUT / kind / 'proof.json', proof)
        record(OUT / (kind + '-allowed-changes.json'), {'sourceSha256': frozen.CORE_PINS[kind],
               'candidateSha256': proof['coreSha256'], 'staticOverlaySha256': MANIFEST_SHA, 'changes': changes[kind]})
    record(OUT / 'proof.json', results)
    record(OUT / 'static-overlay-proof.json', {'status': 'PACK_BYTES_VERIFIED_ACTUAL_RUNTIME_PENDING',
           'sourceOverlaySha256': MANIFEST_SHA, 'decodedWorldExact': True,
           'worldMode5Sha256': frozen.sha(compressed), 'worldFilters': filters,
           'frozenDetailChunksPerVariant': 12, 'inputPins': {str(p): h for p, h in inputs['inputPins'].items()},
           'allowedChanges': changes, 'bootstrapReadyGateUnchanged': True})
    print(json.dumps({k: {field: v[field] for field in ('coreSha256', 'coreBytes', 'coreGzipBytes')} for k, v in results.items()}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--build', action='store_true')
    args = parser.parse_args()
    if args.check:
        checked = preflight()
        print(json.dumps({'status': 'READ_ONLY_PREFLIGHT_PASS', 'overlayEntries': len(checked['overlay']),
                          'removedEntries': len(checked['removals'])}))
    else:
        build()
