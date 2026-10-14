"""Read-only integration gates; never invokes writer, native or compressor."""
import copy
import json
import unittest

import build_static_overlay_v135 as build


class StaticOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = build.preflight()
        cls.values = {n: b for n, b in cls.inputs['entries']['native'].items()
                      if n not in cls.inputs['removals']}
        cls.values.update(cls.inputs['overlay'])

    def test_native_runtime_dependencies_resolve(self):
        build.validate_runtime(self.values)

    def test_wrong_world_rejected(self):
        values = dict(self.values)
        values[build.WORLD] = values[build.WORLD] + b'x'
        with self.assertRaises(ValueError):
            build.validate_runtime(values)

    def test_missing_dependency_rejected(self):
        values = dict(self.values)
        del values['scripts/meadow_scene.gdc']
        with self.assertRaises(ValueError):
            build.validate_runtime(values)

    def test_wrong_dependency_rejected(self):
        values = dict(self.values)
        values['scripts/meadow_scene.gdc'] += b'x'
        with self.assertRaises(ValueError):
            build.validate_runtime(values)

    def test_no_shader_texture_controller_or_water_change(self):
        for name, value in self.inputs['entries']['native'].items():
            if name.startswith(('shaders/', '.godot/imported/')) or name == 'scripts/meadow_progressive.gdc':
                self.assertEqual(self.values[name], value, name)

    def test_original_dynamic_tail_exact(self):
        token = b'\tvar weather := WEATHER_CONTROLLER.new()\n'
        original = self.inputs['data'][build.frozen.SOURCE / 'meadow_scene.progressive.gd']
        candidate = self.inputs['staticMain']
        self.assertEqual(original[original.index(token):], candidate[candidate.index(token):])

    def test_real_thin_entry_selected(self):
        self.assertEqual(self.values[build.REMAPPING].decode().strip(),
                         '[remap]\npath="res://progressive/static-core/entry.tscn"')
        entry = self.values['progressive/static-core/entry.tscn'].decode()
        self.assertEqual(entry.count('[node '), 3)
        self.assertNotIn('SubResource', entry)
        self.assertNotIn('PackedScene', entry)

    def test_required_remaining_files(self):
        for name in ('assets/baked/lite-v128/crown-edge-controller.scn',
                     'assets/baked/v113/far-sward.scn', 'progressive/alpha-manifest.json',
                     'project.binary', 'progressive/manifest.json'):
            self.assertEqual(self.values[name], self.inputs['entries']['native'][name])
        self.assertEqual(len(self.inputs['removals']), 26)

    def test_boot_does_not_claim_ready(self):
        self.assertFalse(self.inputs['bootManifest']['reportsSceneReady'])
        self.assertFalse(self.inputs['bootManifest']['sceneVisualsInBoot'])


if __name__ == '__main__':
    unittest.main()
