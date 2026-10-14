"""Small format/transport guards; no Godot, server, browser or full builds."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import build_progressive_web_v135 as builder
from inspect_web_pack import read_pack
import stage_lite_web as stager


def header():
    data = bytearray(112)
    struct.pack_into('<4sIIIII', data, 0, b'GDPC', 4, 4, 7, 2, 0)
    return data


class ProgressiveWebTests(unittest.TestCase):
    def test_root_hook_preserves_exact_fallback_with_both_line_endings(self):
        for newline in (b'\n', b'\r\n'):
            source = (b'func _conform_root_line(instance: MeshInstance3D, follow_whole_column: bool = false) -> void:'
                      + newline + b'\tprint("original untouched")' + newline)
            revised = builder.root_conform_hook(source)
            self.assertTrue(revised.endswith(b'\tprint("original untouched")' + newline))
            self.assertEqual(revised.count(b'meadow_root_conform_cache.gd'), 1)
            with self.assertRaises(ValueError):
                builder.root_conform_hook(revised)
        with self.assertRaises(ValueError):
            builder.root_conform_hook(b'wrong source')

    def test_full_rock_data_moves_byte_exact_and_only_after_pin_check(self):
        data = b'pinned offline AO bytes'
        core = {builder.ROCK_AO_ENTRY: data, 'unrelated': b'keep'}
        chunk = {'full-world.scn': b'full mesh'}
        with patch.object(builder, 'ROCK_AO_SHA', builder.sha(data)):
            builder.defer_full_rock_data(core, chunk)
        self.assertNotIn(builder.ROCK_AO_ENTRY, core)
        self.assertEqual(chunk[builder.ROCK_AO_ENTRY], data)
        self.assertEqual(core['unrelated'], b'keep')

    def test_full_rock_data_refuses_unknown_or_duplicate_payload(self):
        for duplicate in (False, True):
            data = b'unknown' if not duplicate else b'pinned'
            core = {builder.ROCK_AO_ENTRY: data}
            chunk = {builder.ROCK_AO_ENTRY: data} if duplicate else {}
            with patch.object(builder, 'ROCK_AO_SHA', builder.sha(b'pinned')):
                with self.assertRaises(ValueError):
                    builder.defer_full_rock_data(core, chunk)
            self.assertEqual(core[builder.ROCK_AO_ENTRY], data)

    def test_pack_roundtrip_checksums_offsets_utf8_and_empty_resource(self):
        values = {'progressive/manifest.json': b'{"version":1}', 'scripts/中文.bin': b'\0\1\xff', 'empty': b''}
        blob = builder.pack(header(), values)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'core.pck'
            path.write_bytes(blob)
            rows = read_pack(path, verify=True)['entries']
        self.assertEqual({row['path']: blob[row['offset']:row['offset']+row['bytes']] for row in rows}, values)
        self.assertTrue(all(row['offset'] % 16 == 0 for row in rows))

    def test_pack_rejects_absolute_parent_and_windows_paths(self):
        for name in ('/x', '../x', 'a/../x', 'a\\x', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                builder.pack(header(), {name:b'x'})

    def test_artifact_write_refuses_overwrite_and_outside_scope(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(builder, 'SCOPE', Path(directory)/'allowed'):
            target = builder.SCOPE/'new.bin'
            builder.write(target, b'original')
            with self.assertRaises(ValueError):
                builder.write(target, b'replacement')
            with self.assertRaises(ValueError):
                builder.write(Path(directory)/'outside.bin', b'x')
            self.assertEqual(target.read_bytes(), b'original')

    def exercise_manifest(self, packed, external, files=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, packs, dest = root/'old', root/'packs', root/'v999'
            source.mkdir(); packs.mkdir()
            for name in stager.ENGINE_NAMES:
                (source/name).write_bytes(b'synthetic')
            contents = {'dummy':b'x'}
            if packed is not None:
                contents['progressive/manifest.json'] = json.dumps(packed).encode()
            core = packs/'index-lite.pck'
            core.write_bytes(builder.pack(header(), contents))
            if external is not None:
                (packs/'progressive-manifest.json').write_text(json.dumps(external))
            for name, data in (files or {}).items():
                (packs/name).write_bytes(data)
            with patch.object(stager, 'validate_pack_engine'), self.assertRaises(ValueError):
                stager.stage(source, core, dest)
            self.assertFalse(dest.exists(), 'A bad manifest must fail before creating a release')

    def test_stage_rejects_missing_adjacent_or_missing_embedded_manifest(self):
        value = {'version':1, 'chunks':[{'index':0}]}
        self.exercise_manifest(value, None)
        self.exercise_manifest(None, value)

    def test_stage_rejects_manifest_from_different_core(self):
        self.exercise_manifest({'version':1,'chunks':[1]}, {'version':1,'chunks':[2]})

    def test_stage_rejects_wrong_chunk_content_before_creating_version(self):
        blob = b'expected'
        digest = hashlib.sha256(blob).hexdigest()
        name = f'detail-0-{digest[:12]}.pck'
        value = {'version':1,'chunks':[{'index':0,'file':name,'sha256':digest,'bytes':len(blob)}]}
        self.exercise_manifest(value, value, {name:b'corrupt!'})

    def test_stage_rejects_chunk_name_not_bound_to_hash_and_index(self):
        value = {'version':1,'chunks':[{'index':0,'file':'detail-1-000000000000.pck','sha256':'1'*64,'bytes':8}]}
        self.exercise_manifest(value, value)


if __name__ == '__main__':
    unittest.main()
