"""Pinned one-condition renderer guard tests; no build, browser or GL surrogate."""
from pathlib import Path
import hashlib
import itertools
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / ".tools/godot-web-v126/src"
CPP = SRC / "drivers/gles3/rasterizer_scene_gles3.cpp"
OLD_SHA = "6d0719c9cd2caf685a9825028183bdf058081d7bc92d4b27ed2587f39b081221"
OLD = b"\t// If SSAO is enabled, we definitely need the depth buffer.\n\tif (ssao_enabled) {\n\t\tscene_state.used_depth_texture = true;\n\t}"
NEW = OLD.replace(b"if (ssao_enabled)", b"if (ssao_enabled && !is_reflection_probe)")


class ReflectionDepthTests(unittest.TestCase):
    def test_only_one_condition_changed(self):
        data = CPP.read_bytes()
        self.assertEqual(data.count(NEW), 1)
        self.assertNotIn(OLD, data)
        self.assertEqual(hashlib.sha256(data.replace(NEW, OLD)).hexdigest(), OLD_SHA)

    def test_durable_patch_matches_exact_context(self):
        patch = (Path(__file__).parent / "reflection-depth-web-v128.patch").read_text()
        lines = patch.splitlines()
        removed = [line[1:] for line in lines if line.startswith("-") and not line.startswith("---")]
        added = [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]
        self.assertEqual(removed, ["\tif (ssao_enabled) {"])
        self.assertEqual(added, ["\tif (ssao_enabled && !is_reflection_probe) {"])
        body = lines[4:]
        old = "\n".join(line[1:] for line in body if line.startswith((" ", "-"))) + "\n"
        new = "\n".join(line[1:] for line in body if line.startswith((" ", "+"))) + "\n"
        candidate = CPP.read_text()
        self.assertEqual(candidate.count(new), 1)
        self.assertEqual(hashlib.sha256(candidate.replace(new, old).encode()).hexdigest(), OLD_SHA)

    def test_material_depth_consumers_and_main_ssao_truth_table(self):
        for material_depth, ssao, reflection in itertools.product((False, True), repeat=3):
            old = material_depth or ssao
            new = material_depth or (ssao and not reflection)
            if material_depth or not reflection or not ssao:
                self.assertEqual(new, old)
            else:
                self.assertTrue(old)
                self.assertFalse(new)
        source = CPP.read_text()
        self.assertIn("if (surf->flags & GeometryInstanceSurface::FLAG_USES_DEPTH_TEXTURE) {\n\t\t\t\t\tscene_state.used_depth_texture = true;", source)

    def test_probe_has_no_ssao_post_consumer(self):
        source = CPP.read_text()
        self.assertIn("if (!is_reflection_probe) {\n\t\t_render_post_processing(&render_data);", source)
        self.assertIn("ssao_enabled = environment_get_ssao_enabled(p_environment);", source)
        self.assertIn("GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT, GL_NEAREST);", source)

    def test_no_shader_loop_or_codec_changes(self):
        self.assertEqual(hashlib.sha256((SRC / "drivers/gles3/shader_gles3.cpp").read_bytes()).hexdigest(),
                         "bef3d081a1e8ef8769f11148821edea70ca0830fc29bab7660a252862c97c9d8")
        extension = json.loads((ROOT / "artifacts/startup-v128/engine/source-extension-02.json").read_text())
        for row in extension["files"]:
            self.assertEqual(hashlib.sha256((SRC / row["path"]).read_bytes()).hexdigest(), row["afterSha256"])

    def test_build_flags_and_generated_features_stay_text_gui(self):
        stage = ROOT / "artifacts/startup-v128/engine"
        previous = json.loads((stage / "text-gui-01/build.log.json").read_text())
        current = json.loads((stage / "reflection-depth-01/preflight.json").read_text())
        self.assertEqual(previous["command"], current["command"])
        classes = (SRC / "core/disabled_classes.gen.h").read_text()
        self.assertEqual(re.findall(r"struct is_class_enabled<(\w+)>", classes), ["ImporterMesh", "ImporterMeshInstance3D"])
        self.assertIn("-j4", current["command"])
        self.assertIn("linkflags=-Wl,--threads=4 -Wl,--thinlto-jobs=4", current["command"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
