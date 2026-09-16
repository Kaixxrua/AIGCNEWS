"""Compose reviewed v134 resources into a core + exact deferred packs.

Artifact-only builds. Original/balanced/engine and all accepted source art are
untouched. Main GD gets one explicit controller hook in its compiled lite copy.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import struct
import sys

sys.dont_write_bytecode = True
from inspect_web_pack import read_pack
from build_lite_pack import decode_ctex
import compile_lite_startup as compiler

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "artifacts/startup-v135/build"
BASE = ROOT / "artifacts/v134/index-lite.pck"
TWIN = ROOT / "artifacts/startup-v128/combined-01/native-audit-twin.pck"
SCENES = ROOT / "artifacts/startup-v135/scenes/candidate-02"
BASE_SHA = "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3"
TWIN_SHA = "83caf8ac1126ccacea3a2146109d234193a3de60a887cff2d383e4cfb21c6ce6"
ROCK_AO_ENTRY = "assets/baked/v110/rock-occlusion.bin"
ROCK_AO_SHA = "bb2fe3c1abd30b2092cdb17ca0bc0a6b634438ab82a18b52ded2ece8646261b2"
PARENTS = {"crown-edge": "MeadowEdgeGrowth"}
ROOTS = {
    "detail": ["LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
    "brush": ["MiddleMeadowBrush"], "foothill": ["CastleFoothillWoodland"],
    "riverbank": ["RootedRiparianCover"],
    "crown-edge": ["CrownToTurfFringe", "CrownTransitionBranchlets"],
    "far-sward": ["DistantMeadowSward"],
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def entries(path, expected):
    data = path.read_bytes()
    require(sha(data) == expected, f"Frozen pack changed: {path}")
    return data[:112], {row['path']: data[row['offset']:row['offset']+row['bytes']]
                       for row in read_pack(path, verify=True)['entries']}


def pack(header, values):
    result = bytearray(header)
    require(len(result) == 112 and result[:4] == b'GDPC', 'Observed v4 header')
    struct.pack_into('<Q', result, 24, 112)
    rows = []
    for name, data in sorted(values.items()):
        require(name and not name.startswith('/') and '..' not in name and '\\' not in name, 'Relative safe entry')
        result.extend(b'\0' * (-len(result) % 16))
        rows.append((name, len(result)-112, len(data), hashlib.md5(data).digest()))
        result.extend(data)
    result.extend(b'\0' * (-len(result) % 16))
    struct.pack_into('<Q', result, 32, len(result))
    result.extend(struct.pack('<I', len(rows)))
    for name, offset, length, md5 in rows:
        encoded = name.encode() + b'\0'
        encoded += b'\0' * (-len(encoded) % 4)
        result.extend(struct.pack('<I', len(encoded)) + encoded + struct.pack('<QQ', offset, length)
                      + md5 + struct.pack('<I', 0))
    return bytes(result)


def write(path, data):
    require(path.resolve().is_relative_to(SCOPE.resolve()) and not path.exists(), f'New scoped output: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def json_write(path, value):
    write(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())


def defer_full_rock_data(core, full_chunk):
    # The compiled progressive main explicitly skips full-mesh AO on proxies.
    # Both the initial proxy and final carrier already contain the baked vertex
    # values. Preserve the original data for later use, without a first-load copy.
    data = core[ROCK_AO_ENTRY]
    require(sha(data) == ROCK_AO_SHA and ROCK_AO_ENTRY not in full_chunk,
            'Only the pinned full rock AO data may move to its full-mesh chunk')
    full_chunk[ROCK_AO_ENTRY] = core.pop(ROCK_AO_ENTRY)


def water_mips(blob, drop=2):
    logical, fmt, levels = decode_ctex(blob)
    require(len(levels) > drop, 'Source water has retained mips')
    width, height = levels[drop][1].size
    result = bytearray(blob[:52])
    struct.pack_into('<IHHII', result, 36, 2, width, height, len(levels)-drop-1, fmt)
    for encoded, image in levels[drop:]:
        result.extend(struct.pack('<I', len(encoded))+encoded)
    new_logical, _, new_levels = decode_ctex(bytes(result))
    require(new_logical == logical and [e for e, _ in new_levels] == [e for e, _ in levels[drop:]],
            'Logical dimensions and retained mip bytes exact')
    return bytes(result), {'sourceBytes': len(blob), 'coreBytes': len(result), 'drop': drop,
                          'logicalSize': logical, 'corePhysical': [width, height],
                          'retainedMipsByteExact': True, 'fullTextureRestoredInFinalChunk': True}


def root_conform_hook(source):
    newline = b'\r\n' if b'\r\n' in source else b'\n'
    anchor = b'func _conform_root_line(instance: MeshInstance3D, follow_whole_column: bool = false) -> void:' + newline
    hook = (b'\tif preload("res://scripts/meadow_root_conform_cache.gd").restore(self, instance, follow_whole_column):'
            + newline + b'\t\treturn' + newline)
    require(source.count(anchor) == 1 and hook not in source, 'Unique untouched root-conform function')
    patched = source.replace(anchor, anchor + hook, 1)
    require(patched.replace(hook, b'', 1) == source, 'Exact original root-conform fallback retained')
    return patched


def repin_static_main(entries, actual_gdc):
    key = 'progressive/static-cache/manifest.json'
    previous = entries[key]
    require(sha(previous) == 'ea49462ec067e9e2e5ce8193fd967e5f38900865043402f2675f08fbdf9113db',
            'Only repin the independently reviewed static-cache contract')
    value = json.loads(previous)
    dependency = 'res://scripts/meadow_scene.gdc'
    require(value['dependencies'][dependency] == '1f35a8946ffd947565b4e71728c2f5e0569e6d0206e9fb9ab4c49e2a08ea712a',
            'Expected original private main dependency')
    value['dependencies'][dependency] = sha(actual_gdc)
    entries[key] = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def compile_sources(output, reuse=None, root_cache=False):
    compiler.SCOPE = SCOPE / 'compiler'
    original = (ROOT / 'godot/scripts/meadow_scene.gd').read_bytes()
    newline = b'\r\n' if b'\r\n' in original else b'\n'
    anchor = b'\tground_atmosphere.setup(self)' + newline
    require(original.count(anchor) == 1, 'Unique integration point after real weather/atmosphere')
    hook = (b'\tvar progressive: Node = load("res://scripts/meadow_progressive.gd").new()' + newline
            + b'\tprogressive.name = "ProgressiveDetails"' + newline
            + b'\tadd_child(progressive)' + newline + b'\tprogressive.setup(self)' + newline)
    patched = original.replace(anchor, anchor + hook, 1)
    require(patched.replace(hook, b'', 1) == original, 'Only scoped ready integration hook')
    ao_original = b'\tif not ROCK_OCCLUSION.apply(self):' + newline
    ao_proxy = (b'\t# The temporary mesh retains its selected baked AO; the full cache is only valid for the full mesh.' + newline
                + b'\tif not get_node("SolidLimestoneGeology").get_meta("progressive_visual_proxy", false) and not ROCK_OCCLUSION.apply(self):' + newline)
    require(patched.count(ao_original) == 1, 'Unique full-mesh AO check')
    patched = patched.replace(ao_original, ao_proxy, 1)
    require(patched.replace(ao_proxy, ao_original, 1).replace(hook, b'', 1) == original,
            'Only progressive hook and explicit temporary-proxy AO branch')
    if root_cache:
        patched = root_conform_hook(patched)
    controller_source = (ROOT / 'godot/scripts/meadow_progressive.gd').read_bytes()
    if reuse:
        previous = json.loads((reuse/'script-proof.json').read_bytes())
        require(previous['mainSourceSha256'] == sha(patched) and previous['controllerSourceSha256'] == sha(controller_source),
                'Only reuse exactly identical compiled sources')
        compiled = (compiler.SCOPE/f'{reuse.name}-main'/'meadow_scene.gdc').read_bytes()
        controller = (compiler.SCOPE/f'{reuse.name}-controller'/'meadow_scene.gdc').read_bytes()
        require(sha(compiled) == previous['mainGdcSha256'] and sha(controller) == previous['controllerGdcSha256'], 'Compiled pins')
    else:
        compiled = compiler.compile_single(compiler.SCOPE / f'{output.name}-main', patched)
        controller = compiler.compile_single(compiler.SCOPE / f'{output.name}-controller', controller_source)
    json_write(output/'script-proof.json', {'originalSourceSha256': sha(original), 'mainSourceSha256': sha(patched),
               'mainGdcSha256': sha(compiled), 'controllerSourceSha256': sha(controller_source),
               'controllerGdcSha256': sha(controller), 'rootConformHook': root_cache,
               'allOtherMainSourceBytesExact': True})
    write(output/'meadow_scene.progressive.gd', patched)
    return {'scripts/meadow_scene.gdc': compiled, 'scripts/meadow_progressive.gdc': controller,
            'scripts/meadow_progressive.gd.remap': b'[remap]\n\npath="res://scripts/meadow_progressive.gdc"\n'}


def build(output, reuse=None, proxy=None, textures=None, support=None, alpha=None, root_cache=None):
    output = output.resolve()
    require(output.is_relative_to(SCOPE) and output != SCOPE and not output.exists(), 'New build directory')
    header, source = entries(BASE, BASE_SHA)
    _, native = entries(TWIN, TWIN_SHA)
    require((SCENES/'manifest.json').is_file(), 'Reviewed scene partition manifest required')
    manifest = json.loads((SCENES/'manifest.json').read_bytes())
    overlay = None
    if proxy:
        overlay = json.loads((proxy/'manifest.json').read_bytes())
        require(sha((proxy/'manifest.json').read_bytes()) in (
            '7fde5df9fa7230ce112ce412d9763198ad2b6bc881da73cd58624193633a4210',
            'dc01a9e7b19b2f4a1e3a16770cd4364dc76a7ff134825edf801cd8be4752c040',
            'b1eaa033475161cf985b8bf139a6c8afd20b9eb69ef023c202144ee957f2210c'), 'Reviewed proxy manifest')
        require(sha((SCENES/'manifest.json').read_bytes()) == 'bc603c646147535d85e88f7a9754a4c1061d4d11bfe5f7ce011f4748fbf02ad0', 'Proxy matching partition')
    texture_overlay = None
    if textures:
        texture_overlay = json.loads((textures/'manifest.json').read_bytes())
        require(sha((textures/'manifest.json').read_bytes()) in (
            'd459c5a8f37c97d35d5d3f0dc8ff9b6218a11a0bdd840694f88100d43758b478',
            '3124f4925e7b318ab3bb9b2d16a59030b09a36afca9548e7afe48d8fa791f362'), 'Reviewed existing-mip overlay')
        require(texture_overlay['sourcePackSha256'] == BASE_SHA, 'Texture source matches frozen pack')
    output.mkdir(parents=True)
    compiled = compile_sources(output, reuse, bool(root_cache))
    extra_entries = {}
    if support:
        support_manifest = json.loads((support/'manifest.json').read_bytes())
        require(support_manifest['sourcePackSha256'] == BASE_SHA and support_manifest['baselineCompilerAllExact'],
                'Private support sources compile exactly to the frozen originals before substitution')
        for row in support_manifest['entries']:
            path = Path(row['path']).resolve(strict=True)
            require(path.is_relative_to(support), 'Scoped support input')
            data = path.read_bytes()
            require(sha(data) == row['sha256'], 'Support script pin')
            require((row['entry'].startswith('scripts/meadow_') or row['entry'].startswith('progressive/static-cache/'))
                    and row['entry'] not in compiled, 'Only reviewed support scripts/static cache')
            require((sha(source[row['entry']]) if row['entry'] in source else None) == row['beforeSha256'],
                    'Support overlay cannot overwrite a different source GDC')
            extra_entries[row['entry']] = data
    if root_cache:
        require(support is not None, 'Root memoization requires its validated static support')
        raw_manifest = (root_cache/'validated-manifest.json').read_bytes()
        require(sha(raw_manifest) == '5f7c2b75634e94245069793f494029c64e870509871e59a082f991323ed23c3c',
                'Reviewed 50-mesh cache overlay')
        added = 0
        for row in json.loads(raw_manifest)['entries']:
            if row['entry'] in extra_entries:
                require(sha(extra_entries[row['entry']]) == row['sha256'], 'All 44 existing support entries exact')
                continue
            path = Path(row['path']).resolve(strict=True)
            require(path.is_relative_to(root_cache) and row['beforeSha256'] is None,
                    'Only four additive scoped root cache entries')
            require(row['entry'].startswith(('progressive/root-conform/', 'scripts/meadow_root_conform_cache.')),
                    'No unrelated cache entry or script substitution')
            data = path.read_bytes()
            require(sha(data) == row['sha256'], 'Root cache exact encoded bytes')
            extra_entries[row['entry']] = data
            added += 1
        require(added == 4, 'Exactly four root cache entries')
        repin_static_main(extra_entries, compiled['scripts/meadow_scene.gdc'])
    # CPU alpha data is integrated separately from visual texture mip upgrades.
    # Its tiny full-resolution planes keep all derived feet/rotor geometry exact.
    if alpha:
        alpha_manifest = json.loads((alpha/'manifest.json').read_bytes())
        require(alpha_manifest['sourcePackSha256'] == BASE_SHA, 'CPU alpha source matches texture source')
        for row in alpha_manifest['entries']:
            path = Path(row['path']).resolve(strict=True)
            require(path.is_relative_to(alpha), 'Scoped alpha input')
            data = path.read_bytes()
            require(sha(data) == row['sha256'], 'CPU alpha data pin')
            require(row['entry'].startswith('progressive/'), 'Only progressive CPU alpha resources')
            extra_entries[row['entry']] = data
    water_name = next(name for name in source if name.startswith('.godot/imported/river-ripples-v37.') and name.endswith('.ctex'))
    water, water_proof = water_mips(source[water_name])
    json_write(output/'water-proof.json', water_proof)
    results = {}
    for variant, original in (('mode5', source), ('native', native)):
        core = dict(original)
        core.update(compiled)
        core.update(extra_entries)
        core[water_name] = water
        chunks = []
        # Large grass last; earlier small groups visibly refine the whole scene.
        for group in ('brush', 'foothill', 'riverbank', 'crown-edge', 'far-sward', 'detail'):
            row = next(row for row in manifest['groups'] if row['group'] == group)
            core[row['sourceEntry']] = (SCENES/variant/'core'/f'{group}.scn').read_bytes()
            resource = f'assets/baked/progressive-v135/{group}.scn'
            chunk_values = {resource: (SCENES/variant/'deferred'/f'{group}.scn').read_bytes()}
            spec = {'resource': 'res://'+resource, 'parent': PARENTS.get(group, '.'),
                    'roots': ROOTS[group], 'rootScene': False}
            chunk = {'index': len(chunks), 'scenes': [spec], 'textures': []}
            blob = pack(header, chunk_values)
            digest = sha(blob)
            chunk.update(file=f'detail-{chunk["index"]}-{digest[:12]}.pck', sha256=digest, bytes=len(blob))
            write(output/variant/chunk['file'], blob)
            chunks.append(chunk)
        texture_proof = []
        if texture_overlay:
            full_values, specs = {}, []
            for row in texture_overlay['replacements']:
                initial_contract = row['keepOriginalUntilInitialConditionsHandled']
                # Dragon shader uses physical textureSize for its registered
                # pixel anchors. Keep this atlas exact even in the bootstrap.
                if 'castle-dragon-turns-v57' in row['source']:
                    continue
                if initial_contract and not (support and alpha):
                    continue
                data = Path(row['initialFile']).read_bytes()
                full = Path(row['full']['path']).read_bytes()
                require(sha(core[row['entry']]) == row['sourceSha256'], 'Original texture unchanged before mip selection')
                require(sha(data) == row['initial']['sha256'] and sha(full) == row['sourceSha256'], 'Texture overlay pins')
                require(sha(core[row['importEntry']]) == row['importSha256'], 'Original atlas import map unchanged')
                core[row['entry']] = data
                full_values[row['full']['entry']] = full
                specs.append({**row['textureSpec'], 'inPlace': True})
                texture_proof.append({'source': row['source'], 'coreSha256': sha(data), 'fullSha256': sha(full)})
            # Keep upgrade groups bounded; each texture uses an existing live
            # object and yields a game frame before the next texture upload.
            for start in range(0, len(specs), 8):
                selected = specs[start:start+8]
                blob = pack(header, {spec['resource'].removeprefix('res://'): full_values[spec['resource'].removeprefix('res://')]
                                     for spec in selected})
                digest = sha(blob)
                chunk = {'index': len(chunks), 'file': f'detail-{len(chunks)}-{digest[:12]}.pck',
                         'sha256': digest, 'bytes': len(blob), 'scenes': [], 'textures': selected}
                write(output/variant/chunk['file'], blob)
                chunks.append(chunk)
        if overlay:
            def proxy_bytes(key):
                encoding = overlay['resources'][key]['encodings'][variant]
                path = Path(encoding['path']).resolve(strict=True)
                require(path.is_relative_to(proxy) or (key == 'world-visuals' and
                    path.is_relative_to(ROOT/'artifacts/startup-v135/scenes/proxy-02') and
                    overlay.get('fullCarrierReusedByteExact') is True), 'Scoped proxy input or exact frozen final carrier')
                data = path.read_bytes()
                require(len(data) == encoding['bytes'] and sha(data) == encoding['sha256'], 'Proxy resource pin')
                return data
            for key in ('terrain-core', 'detail-core'):
                core[overlay['resources'][key]['entry']] = proxy_bytes(key)
            spec = overlay['sceneSpec']
            full_chunk = {spec['resource'].removeprefix('res://'): proxy_bytes('world-visuals')}
            defer_full_rock_data(core, full_chunk)
            blob = pack(header, full_chunk)
            digest = sha(blob)
            chunk = {'index': len(chunks), 'file': f'detail-{len(chunks)}-{digest[:12]}.pck',
                     'sha256': digest, 'bytes': len(blob), 'scenes': [spec], 'textures': []}
            write(output/variant/chunk['file'], blob)
            chunks.append(chunk)
        full_water = 'progressive/textures/river-ripples-full.ctex'
        blob = pack(header, {full_water: source[water_name]})
        digest = sha(blob)
        chunk = {'index': len(chunks), 'file': f'detail-{len(chunks)}-{digest[:12]}.pck',
                 'sha256': digest, 'bytes': len(blob), 'scenes': [],
                 'textures': [{'source': 'res://assets/materials/river-ripples-v37.png', 'resource': 'res://'+full_water}]}
        write(output/variant/chunk['file'], blob)
        chunks.append(chunk)
        core_manifest = {'version': 1, 'chunks': chunks}
        core['progressive/manifest.json'] = json.dumps(core_manifest, separators=(',', ':')).encode()
        core_blob = pack(header, core)
        path = output/variant/'index-lite.pck'
        write(path, core_blob)
        read_pack(path, verify=True)
        json_write(output/variant/'progressive-manifest.json', core_manifest)
        proof = {'profile': 'progressive-v135', 'sourcePackSha256': BASE_SHA,
                 'coreSha256': sha(core_blob), 'coreBytes': len(core_blob),
                 'coreGzipBytes': len(gzip.compress(core_blob, compresslevel=6, mtime=0)),
                 'detailBytes': sum(chunk['bytes'] for chunk in chunks), 'chunks': len(chunks),
                 'proxyManifestSha256': sha((proxy/'manifest.json').read_bytes()) if proxy else None,
                 'deferredRockAoBytes': len(original[ROCK_AO_ENTRY]) if overlay else 0,
                 'textureUpgrades': texture_proof,
                 'supportManifestSha256': sha((support/'manifest.json').read_bytes()) if support else None,
                 'alphaManifestSha256': sha((alpha/'manifest.json').read_bytes()) if alpha else None,
                 'rootCacheManifestSha256': sha((root_cache/'validated-manifest.json').read_bytes()) if root_cache else None,
                 'visualAcceptance': 'pending', 'tenSecondTarget': 'unverified'}
        json_write(output/variant/'proof.json', proof)
        results[variant] = proof
    json_write(output/'proof.json', results)
    print(json.dumps({variant:{key:value for key,value in proof.items() if key != 'textureUpgrades'}
                      for variant,proof in results.items()}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--reuse-compiled', type=Path)
    parser.add_argument('--scenes', type=Path)
    parser.add_argument('--proxy', type=Path)
    parser.add_argument('--textures', type=Path)
    parser.add_argument('--support', type=Path)
    parser.add_argument('--alpha', type=Path)
    parser.add_argument('--root-cache', type=Path)
    args = parser.parse_args()
    if args.scenes:
        SCENES = args.scenes.resolve(strict=True)
        require(SCENES.is_relative_to(ROOT/'artifacts/startup-v135/scenes'), 'Partition artifact scope')
    if args.proxy:
        args.proxy = args.proxy.resolve(strict=True)
        require(args.proxy.is_relative_to(ROOT/'artifacts/startup-v135/scenes'), 'Proxy artifact scope')
    for key in ('textures', 'support', 'alpha', 'root_cache'):
        if getattr(args, key):
            path = getattr(args, key).resolve(strict=True)
            require(path.is_relative_to(ROOT/'artifacts/startup-v135'), 'Progressive artifact scope')
            setattr(args, key, path)
    build(args.output, args.reuse_compiled, args.proxy, args.textures, args.support, args.alpha, args.root_cache)
