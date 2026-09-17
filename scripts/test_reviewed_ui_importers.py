import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scripts import import_reviewed_ui_sources as reviewed

import import_batch4_demo_sources as batch4
import import_batch_directory_sources as batch_directory
import import_batch_json_registry_sources as batch_json
import import_batch_registry_sources as batch_registry
import ui_import_common as common


class ReviewedUiImportersTest(unittest.TestCase):
    def test_every_selected_component_id_is_unique(self) -> None:
        ids = (
            [f"agent-elements-{slug}" for slug, *_ in reviewed.AGENT_SPECS]
            + [f"smoothui-{slug}" for slug, *_ in reviewed.SMOOTH_SPECS]
            + [f"kibo-{slug}" for slug, *_ in reviewed.KIBO_SPECS]
            + [f"diceui-{slug}" for slug, *_ in reviewed.DICE_SPECS]
            + [f"ai-elements-{slug}" for slug, *_ in reviewed.AI_SPECS]
        )
        self.assertEqual(len(ids), 19)
        self.assertEqual(len(ids), len(set(ids)))

    def test_sources_are_commit_pinned_with_license_hashes(self) -> None:
        for source in reviewed.SOURCES.values():
            self.assertRegex(source["revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(source["license_sha256"], r"^[0-9a-f]{64}$")

    def test_media_validation_rejects_network_and_embeds(self) -> None:
        unsafe = [
            b'fetch("https://example.com/data")',
            b'<img src="/remote.png">',
            b'<iframe title="remote"></iframe>',
        ]
        for raw in unsafe:
            with self.assertRaises(ValueError):
                reviewed.validate("component.tsx", raw)

    def test_media_validation_allows_documentation_urls_in_comments(self) -> None:
        reviewed.validate("component.tsx", b"/* See https://example.com/spec */\nexport const value = 1")


class BatchSourcesPinningTest(unittest.TestCase):
    """Every batch importer source keeps a pinned revision and license hash."""

    def _assert_pinned(self, sources: dict, label: str) -> None:
        self.assertTrue(sources, f"{label} exposes no sources")
        for name, source in sources.items():
            with self.subTest(source=f"{label}:{name}"):
                self.assertRegex(source["revision"], r"^[0-9a-f]{40}$")
                self.assertRegex(source["license_sha256"], r"^[0-9a-f]{64}$")

    def test_registry_batch_sources(self) -> None:
        self._assert_pinned(batch_registry.SOURCES, "registry")

    def test_json_registry_batch_sources(self) -> None:
        self._assert_pinned(batch_json.SOURCES, "json-registry")

    def test_directory_batch_sources(self) -> None:
        self._assert_pinned(batch_directory.SOURCES, "directory")

    def test_demo_batch_sources(self) -> None:
        self._assert_pinned(batch4.SOURCES, "demo")

    def test_reviewed_allow_files_are_repo_relative(self) -> None:
        for sources in (
            batch_registry.SOURCES,
            batch_json.SOURCES,
            batch_directory.SOURCES,
            batch4.SOURCES,
        ):
            for name, source in sources.items():
                for allowed in source.get("reviewed_allow_files", ()):
                    with self.subTest(source=name, file=allowed):
                        self.assertFalse(allowed.startswith("/"))
                        self.assertNotIn("..", allowed.split("/"))


class Batch4CandidateDiscoveryTest(unittest.TestCase):
    """Candidate enumeration against synthetic pinned-checkout layouts."""

    def test_visx_candidates_discovers_examples_and_optional_css(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sandboxes = root / "packages/visx-demo/src/sandboxes"
            alpha = sandboxes / "visx-alpha"
            alpha.mkdir(parents=True)
            (alpha / "Example.tsx").write_text("export default function A() {}", encoding="utf-8")
            (alpha / "sandbox-styles.css").write_text(".a{}", encoding="utf-8")
            beta = sandboxes / "visx-beta"
            beta.mkdir(parents=True)
            (beta / "Example.tsx").write_text("export default function B() {}", encoding="utf-8")
            # Missing Example.tsx and non visx-* directories are skipped.
            (sandboxes / "visx-gamma").mkdir()
            (sandboxes / "template").mkdir()
            pairs = batch4.visx_candidates(root, "packages/visx-demo/src/sandboxes")
            self.assertEqual(
                pairs,
                [
                    ("alpha", "packages/visx-demo/src/sandboxes/visx-alpha/Example.tsx",
                     "packages/visx-demo/src/sandboxes/visx-alpha/sandbox-styles.css"),
                    ("beta", "packages/visx-demo/src/sandboxes/visx-beta/Example.tsx", None),
                ],
            )

    def test_base_ui_candidates_only_take_tailwind_demos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            components = root / "docs/src/app/(docs)/react/components"
            dialog = components / "dialog/demos/hero/tailwind"
            dialog.mkdir(parents=True)
            (dialog / "index.tsx").write_text("export default function D() {}", encoding="utf-8")
            css_variant = components / "dialog/demos/hero/css"
            css_variant.mkdir(parents=True)
            (css_variant / "index.tsx").write_text("export default function D() {}", encoding="utf-8")
            menu = components / "navigation-menu/demos/nested-inline/tailwind"
            menu.mkdir(parents=True)
            (menu / "index.tsx").write_text("export default function N() {}", encoding="utf-8")
            pairs = batch4.base_ui_candidates(root, "docs/src/app/(docs)/react/components")
            self.assertEqual(
                pairs,
                [
                    ("dialog-hero",
                     "docs/src/app/(docs)/react/components/dialog/demos/hero/tailwind/index.tsx"),
                    ("navigation-menu-nested-inline",
                     "docs/src/app/(docs)/react/components/navigation-menu/demos/nested-inline/tailwind/index.tsx"),
                ],
            )


class CommonGuardsTest(unittest.TestCase):
    def test_media_guard_allows_w3c_svg_namespaces(self) -> None:
        self.assertFalse(common.has_external_media(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"/>'))

    def test_media_guard_rejects_external_and_site_root_assets(self) -> None:
        unsafe = [
            'fetch("https://example.com/api")',
            '<img src="/static/logo.png">',
            "const url = 'https://cdn.example.com/x.js'",
            '<video src="movie.mp4"></video>',
        ]
        for text in unsafe:
            with self.subTest(text=text):
                self.assertTrue(common.has_external_media(text))

    def test_imports_of_ignores_comments_and_template_literals(self) -> None:
        text = (
            'import real from "./real";\n'
            '// import fake from "./fake";\n'
            '/* from "./also-fake" */\n'
            'const sample = `from "./template-fake"`;\n'
        )
        self.assertEqual(common.imports_of(text), ["./real"])

    def test_append_unique_file_skips_duplicate_paths(self) -> None:
        files = [{"name": "a.css", "path": "sources/p/a.css", "sha256": "1"}]
        common.append_unique_file(files, {"name": "a.css", "path": "sources/p/a.css", "sha256": "1"})
        common.append_unique_file(files, {"name": "b.css", "path": "sources/p/b.css", "sha256": "2"})
        self.assertEqual([entry["path"] for entry in files],
                         ["sources/p/a.css", "sources/p/b.css"])

    def test_detect_export_prefers_default_then_slug_match(self) -> None:
        self.assertEqual(common.detect_export("export default function Demo() {}", "demo"), "default")
        self.assertEqual(common.detect_export("export function ZoomI() {}", "zoom-i"), "ZoomI")
        with self.assertRaises(common.Reject):
            common.detect_export("const internal = 1", "demo")


if __name__ == "__main__":
    unittest.main()
