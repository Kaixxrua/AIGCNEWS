"""Tiny engine-only boot, with byte-exact selected-core project settings.

No alternate scene is presented and no ready signal is emitted. All project
settings except the first main-scene filename are copied as opaque Variant bytes.
"""
import argparse
import json
from pathlib import Path
import struct

import build_progressive_web_v135 as build
from audit_lite_contract import project_records


def build_boot(core_path, output, probe=None):
    core_path, output = core_path.resolve(strict=True), output.resolve()
    build.require(core_path.is_relative_to(build.SCOPE) and output.is_relative_to(build.SCOPE)
                  and output != build.SCOPE and not output.exists(), 'New scoped bootstrap artifact')
    data = core_path.read_bytes()
    head, values = build.entries(core_path, build.sha(data))
    before = project_records(values['project.binary'])
    old_target = before['application/run/main_scene']
    code, length = struct.unpack_from('<II', old_target)
    build.require(code == 4 and length > 0 and 8 + length <= len(old_target), 'Original main scene is a string Variant')
    target = old_target[8:8+length]
    after = dict(before)
    name = 'res://progressive/boot.tscn'.encode()
    after['application/run/main_scene'] = struct.pack('<II', 4, len(name)) + name + b'\0' * (-len(name) % 4)
    settings = bytearray(b'ECFG' + struct.pack('<I', len(after)))
    for key, value in after.items():
        encoded = key.encode()
        settings.extend(struct.pack('<I', len(encoded)) + encoded + struct.pack('<I', len(value)) + value)
    parsed = project_records(settings)
    build.require({key for key in before if before[key] != parsed[key]} == {'application/run/main_scene'}, 'Only initial entry scene changes')
    source = (build.ROOT/'godot/scripts/meadow_boot.gd').read_bytes()
    build.compiler.SCOPE = build.SCOPE/'compiler'
    gdc = build.compiler.compile_single(build.compiler.SCOPE/f'{output.name}-boot', source)
    contents = {'project.binary': bytes(settings), 'scripts/meadow_boot.gdc': gdc,
                'progressive/boot-main-scene.txt': target,
                'scripts/meadow_boot.gd.remap': b'[remap]\n\npath="res://scripts/meadow_boot.gdc"\n',
                'progressive/boot.tscn': b'[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://scripts/meadow_boot.gd" id="1"]\n[node name="MeadowEngineBoot" type="Node"]\nscript = ExtResource("1")\n'}
    if probe:
        probe = probe.resolve(strict=True)
        build.require(probe.is_relative_to(build.SCOPE), 'Diagnostic helper artifact scope')
        rows = json.loads((probe/'manifest.json').read_bytes())['entries']
        build.require({row['entry'] for row in rows} == {'scripts/meadow_boot_probe.gdc', 'scripts/meadow_boot_probe.gd.remap'}
                      and len(rows) == 2, 'Only the two optional diagnostic script entries')
        for row in rows:
            path = Path(row['path']).resolve(strict=True)
            build.require(path.is_relative_to(probe), 'Scoped diagnostic bytes')
            payload = path.read_bytes()
            build.require(len(payload) == row['bytes'] and len(payload) < 20_000 and build.sha(payload) == row['sha256'],
                          'Diagnostic encoded payload pin')
            contents[row['entry']] = payload
    for key in ('.godot/uid_cache.bin', '.godot/global_script_class_cache.cfg'):
        if key in values:
            contents[key] = values[key]
    blob = build.pack(head, contents)
    build.write(output/'bootstrap.pck', blob)
    proof = {'version':1, 'file':'bootstrap.pck', 'bytes':len(blob), 'sha256':build.sha(blob),
             'coreSha256':build.sha(data), 'sourceSha256':build.sha(source), 'gdcSha256':build.sha(gdc),
             'sourceProjectSha256':build.sha(values['project.binary']),
             'initialSceneOnlySettingChanged':True, 'reportsSceneReady':False,
             'sceneVisualsInBoot':False, 'optionalRootProbe': bool(probe)}
    build.json_write(output/'bootstrap-manifest.json', proof)
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--probe', type=Path)
    args = parser.parse_args()
    build_boot(args.core, args.output, args.probe)
