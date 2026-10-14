"""Synthetic-only contracts for the public camp Web assembler.

Run: python -B -m unittest discover -s godot/tools -p test_stage_camp_web.py -v
No exports, engine builds, real artwork, backend, accounts or private imports.
All sources and outputs are tiny fixtures inside an owned temporary directory.
Negative tests are ordinary assertions, not expectedFailure exceptions.
"""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import copy
import gzip
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import brotli
import stage_camp_web as stager


PROJECT = Path(__file__).resolve().parents[2]


def checksum(data):
    return hashlib.sha256(data).hexdigest()


class EntryHTML(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.scripts, self.links, self.inline, self.handlers = [], [], [], []
        self.in_inline = False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.handlers.extend(name for name in values if name.lower().startswith("on"))
        if tag == "script":
            self.in_inline = "src" not in values
            self.scripts.append(values.get("src"))
        elif tag == "link":
            self.links.append(values)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_inline = False

    def handle_data(self, data):
        if self.in_inline and data.strip():
            self.inline.append(data)


class StageCampWebTests(unittest.TestCase):
    def setUp(self):
        cache = PROJECT / ".pytest_cache"
        cache.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="camp-web-unit-", dir=cache)
        self.addCleanup(temporary.cleanup)
        self.owned = Path(temporary.name).resolve()
        self.root = self.owned / "public"
        self.frozen = self.root / "artifacts/v153"
        self.helpers = self.root / "godot/web"
        self.boot = self.root / "artifacts/camp-bootstrap/synthetic"
        self.art = self.root / "artifacts/camp-presentation/synthetic"
        for directory in (self.frozen, self.helpers, self.boot, self.art):
            directory.mkdir(parents=True)
        self.output = self.root / "artifacts/v999-synthetic"
        self.binding_path = self.boot / "selected-pack-bindings.json"
        self.presentation_path = self.art / "presentation-pack.json"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        self.pins = {}
        for tier, name in (("bootstrap", "bootstrap.pck"), ("original", "index.pck"),
                           ("balanced", "index-balanced.pck"), ("lite", "index-lite.pck")):
            self.pins[tier] = self.file(self.frozen, name, ("synthetic frozen " + tier).encode(), compressed=True)
        engine = {}
        for name in ("index.js", "index.wasm", "index.png", "detail-1-0123456789ab.pck", "meadow-controls.css"):
            spec = self.file(self.frozen, name, ("synthetic frozen " + name).encode(), compressed=True)
            if name in stager.ENGINE_PINS:
                engine[name] = spec["sha256"]
        # Deliberately no worklet sidecars in the source: the assembler may add
        # compressed OUTPUTS without creating or changing source files.
        self.file(self.frozen, "index.audio.worklet.js", b"/* synthetic worklet */")
        for name in stager.UPDATED:
            self.file(self.frozen, name, ("/* old " + name + " */").encode(), compressed=True)
            self.file(self.helpers, name, ("/* updated " + name + " */").encode())

        runtime = self.pack(self.art, "camp-presentation", b"synthetic no-art runtime")
        full = self.pack(self.boot, "camp-bootstrap-full", b"synthetic full wrapper")
        lite = self.pack(self.boot, "camp-bootstrap-lite", b"synthetic lite wrapper")
        ids, shards = {role: [] for role in ("hero", "pet", "boss")}, []
        # Exercise 6+6+1 without copying actual artwork or embedding real IDs.
        for role, count in (("hero", 6), ("pet", 6), ("boss", 1)):
            for index in range(count):
                asset_id = f"synthetic_{role}_{index}"
                ids[role].append(asset_id)
                spec = self.pack(self.art, "camp-actor", asset_id.encode())
                shards.append({"role": role, "assetIds": [asset_id], "pack": spec})
        self.config = {"version": 1, "source": "frozen-v153", "optionalPack": runtime,
                       "actorShards": shards, "assetIds": ids, "bindings": {}}
        for tier in ("original", "balanced", "lite"):
            self.config["bindings"][tier] = {"mainPack": self.pins[tier]["file"],
                "selectedPack": self.pins[tier], "bootstrap": lite if tier == "lite" else full}
        self.presentation = {"version": 2, "pack": copy.deepcopy(runtime),
                             "actorShards": copy.deepcopy(shards), "assetIds": copy.deepcopy(ids)}
        self.quality = {tier: {"label": tier, "file": self.pins[tier]["file"]}
                        for tier in ("original", "balanced", "lite")}
        self.engine_build = {"engine": "synthetic", "threaded": False}
        self.contracts = {"lite": {"syntheticOnly": True}}
        self.engine_config = {"executable": "index", "canvasResizePolicy": 2}
        self.preload = '\nwindow.syntheticEnginePreload = "verbatim";\n'
        inline = "\n".join([
            "window.MEADOW_ENGINE_BUILD = " + json.dumps(self.engine_build) + ";",
            "window.MEADOW_QUALITY = " + json.dumps(self.quality) + ";",
            "window.MEADOW_RENDER_CONTRACTS = " + json.dumps(self.contracts) + ";",
            "window.meadowQuality.mount(" + json.dumps(self.engine_config) + ");",
        ])
        self.html = ('<!doctype html><html><head>\n<link href="meadow-controls.css?v=old" rel="stylesheet">\n'
            '<script data-meadow-engine-preload>' + self.preload + '</script>\n'
            + "\n".join(f'  <script src="{name}"></script>' for name in stager.UPDATED[:4])
            + '\n  <script src="index.js"></script>\n</head><body>\n'
            '<div id="scene-controls">\n'
            '    <button id="quality-control" type="button">quality</button>\n'
            '</div>\n'
            '<p>中央保留未来行走和 Boss 战区域。</p><p>不含 HTML 和响应头。</p>\n'
            '<script>\n' + inline + '\n</script>\n</body></html>')
        self.file(self.frozen, "index.html", self.html.encode())
        # Non-runtime/source fixtures must never leak into the assembled tree.
        for name in (".env", "project.godot", "source.gd", "index.js.map", "audit.json", "notes.md", "preview.png"):
            self.file(self.frozen, name, b"SYNTHETIC_NOT_FOR_PUBLIC_RUNTIME")
        self.file(self.frozen / "nested", "index.js", b"SYNTHETIC_NESTED_SOURCE")
        self.write_manifests()
        for name, value in (("ROOT", self.root), ("FROZEN", self.frozen), ("HELPERS", self.helpers),
                            ("PINS", self.pins), ("ENGINE_PINS", engine)):
            self.stack.enter_context(patch.object(stager, name, value))

    def file(self, directory, name, data, *, compressed=False):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(data)
        if compressed:
            path.with_name(name + ".gz").write_bytes(gzip.compress(data, mtime=0))
            path.with_name(name + ".br").write_bytes(brotli.compress(data, quality=1))
        return {"file": name, "bytes": len(data), "sha256": checksum(data)}

    def pack(self, directory, prefix, data):
        return self.file(directory, f"{prefix}-{checksum(data)[:12]}.pck", data, compressed=True)

    def write_manifests(self):
        self.binding_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.presentation_path.write_text(json.dumps(self.presentation), encoding="utf-8")

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for directory in (self.frozen, self.boot, self.art, self.helpers)
                for path in directory.rglob("*") if path.is_file()}

    def assemble(self, *, output=None, binding=None, presentation=None):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            stager.stage(binding or self.binding_path, presentation or self.presentation_path,
                         output or self.output)
        return json.loads(stdout.getvalue())

    def refused(self, pattern, **kwargs):
        before = self.snapshot()
        with self.assertRaisesRegex((ValueError, OSError), pattern):
            self.assemble(**kwargs)
        self.assertFalse(self.output.exists(), "Input rejection should precede output creation")
        self.assertEqual(self.snapshot(), before)

    def test_success_preserves_every_source_byte_and_mtime(self):
        before = self.snapshot()
        summary = self.assemble()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(summary["actorShards"], 13)
        self.assertEqual(summary["optionalRuntimeBytes"], self.config["optionalPack"]["bytes"])
        self.assertTrue((self.output / "index.html").is_file())

    def test_copies_all_frozen_engine_core_and_detail_bytes_exactly(self):
        self.assemble()
        for source in self.frozen.iterdir():
            if source.is_file() and stager.RUNTIME.fullmatch(source.name):
                if source.name.removesuffix(".br").removesuffix(".gz") not in stager.UPDATED:
                    with self.subTest(name=source.name):
                        self.assertEqual((self.output / source.name).read_bytes(), source.read_bytes())

    def test_excludes_source_maps_dotfiles_docs_and_nested_content(self):
        self.assemble()
        for name in (".env", "project.godot", "source.gd", "index.js.map", "audit.json", "notes.md", "preview.png", "nested"):
            with self.subTest(name=name):
                self.assertFalse((self.output / name).exists())

    def test_replaces_only_named_helpers_and_recompresses_exact_new_bytes(self):
        self.assemble()
        for name in stager.UPDATED:
            with self.subTest(name=name):
                raw = (self.helpers / name).read_bytes()
                self.assertEqual((self.output / name).read_bytes(), raw)
                self.assertEqual(gzip.decompress((self.output / (name + ".gz")).read_bytes()), raw)
                self.assertEqual(brotli.decompress((self.output / (name + ".br")).read_bytes()), raw)

    def test_adds_missing_worklet_compression_without_modifying_source(self):
        self.assemble()
        for suffix, decode in ((".gz", gzip.decompress), (".br", brotli.decompress)):
            self.assertFalse((self.frozen / ("index.audio.worklet.js" + suffix)).exists())
            self.assertEqual(decode((self.output / ("index.audio.worklet.js" + suffix)).read_bytes()),
                             (self.frozen / "index.audio.worklet.js").read_bytes())

    def test_deduplicates_identical_full_wrapper_and_keeps_all_thirteen_actor_shards(self):
        self.assemble()
        self.assertEqual(len(list(self.output.glob("camp-bootstrap-*.pck"))), 2)
        self.assertEqual(len(list(self.output.glob("camp-actor-*.pck"))), 13)
        packs = [self.config["optionalPack"], *(row["pack"] for row in self.config["actorShards"])]
        for spec in packs:
            for suffix in ("", ".br", ".gz"):
                with self.subTest(file=spec["file"], suffix=suffix):
                    self.assertEqual((self.output / (spec["file"] + suffix)).read_bytes(),
                                     (self.art / (spec["file"] + suffix)).read_bytes())

    def test_all_tiers_can_share_an_identical_bootstrap_with_one_copy_per_file(self):
        spec = self.config["bindings"]["original"]["bootstrap"]
        for binding in self.config["bindings"].values():
            binding["bootstrap"] = copy.deepcopy(spec)
        self.write_manifests()
        before = self.snapshot()
        with patch.object(stager.shutil, "copyfile", wraps=stager.shutil.copyfile) as copied:
            self.assemble()
        wrapper_sources = [call.args[0] for call in copied.call_args_list if call.args[0].parent == self.boot]
        self.assertCountEqual(wrapper_sources, [self.boot / (spec["file"] + suffix) for suffix in ("", ".gz", ".br")])
        self.assertEqual(len(list(self.output.glob("camp-bootstrap-*.pck"))), 1)
        self.assertEqual(self.snapshot(), before)

    def test_distinct_pack_filenames_can_contain_identical_bytes(self):
        runtime = self.config["optionalPack"]
        data = (self.art / runtime["file"]).read_bytes()
        wrapper = self.pack(self.boot, "camp-bootstrap-same-content", data)
        self.config["bindings"]["lite"]["bootstrap"] = wrapper
        self.write_manifests()
        before = self.snapshot()
        self.assemble()
        for spec in (runtime, wrapper):
            self.assertEqual((self.output / spec["file"]).read_bytes(), data)
        self.assertEqual(self.snapshot(), before)

    def test_manifest_hashes_cover_exact_outputs_without_self_reference(self):
        self.assemble()
        report = json.loads((self.output / "camp-web-manifest.json").read_text("utf-8"))
        expected = {path.name: {"bytes": path.stat().st_size, "sha256": checksum(path.read_bytes())}
                    for path in self.output.iterdir() if path.name != "camp-web-manifest.json"}
        self.assertEqual(report["files"], expected)
        self.assertEqual(report["bindings"], self.config)
        self.assertEqual(report["initialArtworkDownloads"], 0)
        self.assertEqual(report["updatedHelpers"], list(stager.UPDATED))
        self.assertEqual(report["source"], "frozen-v153")
        for name, digest in report["preserved"].items():
            self.assertEqual(checksum((self.output / name).read_bytes()), digest)
        self.assertNotIn(str(self.root), (self.output / "camp-web-manifest.json").read_text("utf-8"))

    def test_externalizes_both_inline_scripts_and_preserves_preload_body(self):
        self.assemble()
        html = (self.output / "index.html").read_text("utf-8")
        self.assertEqual(html.count('id="scene-fps"'), 1)
        self.assertIn('id="scene-fps" aria-live="off" hidden', html)
        parsed = EntryHTML(html)
        self.assertTrue(parsed.scripts)
        self.assertNotIn(None, parsed.scripts)
        self.assertEqual(parsed.inline, [])
        self.assertEqual(parsed.handlers, [])
        self.assertEqual((self.output / "meadow-engine-preload.js").read_text("utf-8"), self.preload)
        self.assertNotIn("window.MEADOW_ENGINE_BUILD", html)
        self.assertNotIn("window.meadowQuality.mount", html)

    def test_content_cache_keys_match_actual_javascript_and_stylesheet_hashes(self):
        self.assemble()
        parsed = EntryHTML((self.output / "index.html").read_text("utf-8"))
        urls = parsed.scripts + [link["href"] for link in parsed.links]
        for url in urls:
            with self.subTest(url=url):
                name, query = url.split("?", 1)
                self.assertEqual(query, "v=" + checksum((self.output / name).read_bytes())[:16])
                self.assertNotIn("old", query)

    def test_bridge_and_integration_are_loaded_once_before_engine_and_entry(self):
        self.assemble()
        scripts = [url.split("?")[0] for url in EntryHTML((self.output / "index.html").read_text("utf-8")).scripts]
        for name in ("meadow-camp-bridge.js", "meadow-camp-integration.js", "index.js", "meadow-camp-entry.js"):
            self.assertEqual(scripts.count(name), 1)
        self.assertLess(scripts.index("meadow-camp-bridge.js"), scripts.index("meadow-camp-integration.js"))
        self.assertLess(scripts.index("meadow-camp-integration.js"), scripts.index("index.js"))
        self.assertLess(scripts.index("index.js"), scripts.index("meadow-camp-entry.js"))

    def test_entry_preserves_engine_quality_contracts_and_mount_arguments(self):
        self.assemble()
        entry = (self.output / "meadow-camp-entry.js").read_text("utf-8")
        self.assertEqual(stager.assignment(entry, "MEADOW_ENGINE_BUILD"), self.engine_build)
        self.assertEqual(stager.assignment(entry, "MEADOW_QUALITY"), self.quality)
        self.assertEqual(stager.assignment(entry, "MEADOW_RENDER_CONTRACTS"), self.contracts)
        mount = re.search(r"window\.meadowQuality\.mount\((\{[^\n]+\})\);", entry)
        self.assertEqual(json.loads(mount[1]), self.engine_config)
        self.assertIn("if (campEnabled)", entry)
        self.assertIn("window.meadowCampIntegration.retryActors()", entry)
        self.assertNotRegex(entry, r"\beval\s*\(|\bnew\s+Function\s*\(")

    def test_shared_download_accounting_excludes_all_actor_and_optional_packs(self):
        self.assemble()
        entry = (self.output / "meadow-camp-entry.js").read_text("utf-8")
        shared = stager.assignment(entry, "MEADOW_QUALITY_SHARED")
        self.assertIn("index.wasm", shared)
        self.assertIn("meadow-engine-preload.js", shared)
        self.assertNotIn("meadow-camp-entry.js", shared)
        for name, actual in shared.items():
            self.assertFalse(name.endswith(".pck"))
            self.assertEqual(actual, stager.sizes(self.output / name))
        html = (self.output / "index.html").read_text("utf-8")
        self.assertNotRegex(html, r"(?:src|href)=['\"][^'\"]*camp-(?:actor|presentation)-")
        self.assertIn('id="camp-assets-retry" type="button" hidden', html)
        self.assertIn("账户进度与奖励由网站服务器确认", html)

    def test_wrapper_download_accounting_includes_each_tier_own_sizes_and_pin(self):
        self.assemble()
        entry = (self.output / "meadow-camp-entry.js").read_text("utf-8")
        match = re.search(r"Object\.entries\((\{[^\n]+\})\)\)", entry)
        self.assertIsNotNone(match)
        wrappers = json.loads(match[1])
        self.assertEqual(set(wrappers), {"original", "balanced", "lite"})
        for tier, actual in wrappers.items():
            spec = self.config["bindings"][tier]["bootstrap"]
            self.assertEqual(actual, {**spec, **stager.sizes(self.output / spec["file"])})

    def test_output_must_be_new_direct_versioned_child_of_artifacts(self):
        for output in (self.root, self.frozen, self.root / "artifacts", self.root / "v999",
                       self.root / "artifacts/latest", self.root / "artifacts/V999", self.root / "artifacts/v999.BAD",
                       self.root / "artifacts/nested/v999", self.owned / "v999"):
            with self.subTest(path=output):
                self.refused("New versioned artifact", output=output)

    def test_existing_empty_or_populated_output_is_never_overwritten(self):
        self.output.mkdir()
        for populated in (False, True):
            if populated:
                (self.output / "keep.txt").write_bytes(b"synthetic existing bytes")
            before = {p.name: p.read_bytes() for p in self.output.iterdir()}
            with self.subTest(populated=populated), self.assertRaisesRegex(ValueError, "New versioned artifact"):
                self.assemble()
            self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, before)

    def test_wrapper_and_presentation_manifests_must_resolve_inside_their_public_roots(self):
        outside = self.owned / "synthetic-outside.json"
        outside.write_text("{}")
        self.refused("Public wrapper input only", binding=outside)
        self.refused("Public presentation input only", presentation=outside)
        self.refused("Public wrapper input only", binding=self.presentation_path)
        self.refused("Public presentation input only", presentation=self.binding_path)

    def test_local_pin_rejects_traversal_absolute_paths_urls_and_alternate_streams(self):
        for name in ("../escape.pck", "..\\escape.pck", "/absolute.pck", "E:/absolute.pck", "pack.pck:stream",
                     "nested/pack.pck", "https://invalid.test/pack.pck", "pack.pck?x=1", "pack.pck#part", "", None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Local pinned file only"):
                stager.pin(self.art, {"file": name, "bytes": 1, "sha256": "0" * 64})

    def test_local_pin_requires_matching_file_size_and_digest(self):
        original = self.config["optionalPack"]
        for mutation in ({"file": "missing.pck"}, {"bytes": original["bytes"] + 1}, {"sha256": "0" * 64}):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "Pinned file mismatch"):
                stager.pin(self.art, {**original, **mutation})

    def test_local_pin_accepts_an_independent_regular_copy_without_modifying_sources(self):
        outside = self.owned / "synthetic-copy-source.pck"
        data = b"synthetic independently copied public input"
        outside.write_bytes(data)
        source_mtime = outside.stat().st_mtime_ns
        copied = self.art / "camp-presentation-independent.pck"
        stager.shutil.copyfile(outside, copied)
        spec = {"file": copied.name, "bytes": len(data), "sha256": checksum(data)}
        before = self.snapshot()
        self.assertEqual(stager.pin(self.art, spec), copied)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((outside.read_bytes(), outside.stat().st_mtime_ns), (data, source_mtime))

    def test_version_and_frozen_source_contracts_are_required(self):
        for key, value in (("version", 2), ("source", "not-frozen")):
            original = self.config[key]
            self.config[key] = value
            self.write_manifests()
            self.refused("Sharded frozen binding")
            self.config[key] = original
        self.presentation["version"] = 1
        self.write_manifests()
        self.refused("Sharded frozen binding")

    def test_wrapper_and_art_runtime_shards_and_ids_must_agree(self):
        for key, replacement in (("pack", {"file": "other.pck"}), ("actorShards", []), ("assetIds", {})):
            original = self.presentation[key]
            self.presentation[key] = replacement
            self.write_manifests()
            self.refused("Wrapper and actor library must agree")
            self.presentation[key] = original

    def test_selected_tier_pin_cannot_be_replaced_even_with_valid_alternative_bytes(self):
        self.config["bindings"]["lite"]["selectedPack"] = self.config["bindings"]["original"]["selectedPack"]
        self.write_manifests()
        self.refused("Frozen selected scene pin changed")

    def test_corrupt_frozen_selected_pack_is_refused_before_output(self):
        (self.frozen / "index-lite.pck").write_bytes(b"synthetic corruption")
        self.refused("Pinned file mismatch")

    def test_corrupt_frozen_engine_is_refused_before_output(self):
        for name in ("index.js", "index.wasm"):
            path = self.frozen / name
            original = path.read_bytes()
            path.write_bytes(b"synthetic changed engine")
            self.refused("Frozen engine changed")
            path.write_bytes(original)

    def test_corrupt_runtime_actor_and_wrapper_pins_are_refused_before_output(self):
        for directory, spec in ((self.art, self.config["optionalPack"]), (self.art, self.config["actorShards"][0]["pack"]),
                                (self.boot, self.config["bindings"]["lite"]["bootstrap"])):
            path = directory / spec["file"]
            original = path.read_bytes()
            path.write_bytes(b"synthetic changed payload")
            self.refused("Pinned file mismatch")
            path.write_bytes(original)

    def test_gzip_and_brotli_must_decode_to_pinned_raw_bytes(self):
        spec = self.config["actorShards"][0]["pack"]
        for suffix, encode, message in ((".gz", gzip.compress, "gzip integrity"), (".br", brotli.compress, "brotli integrity")):
            path = self.art / (spec["file"] + suffix)
            original = path.read_bytes()
            path.write_bytes(encode(b"synthetic different decoded bytes"))
            self.refused(message)
            path.write_bytes(original)

    def test_missing_compressed_pack_sidecars_are_refused_before_output(self):
        spec = self.config["optionalPack"]
        for suffix in (".gz", ".br"):
            path = self.art / (spec["file"] + suffix)
            original = path.read_bytes()
            path.unlink()  # Exact synthetic fixture file only.
            self.refused("No such file|cannot find|系统找不到")
            path.write_bytes(original)

    def test_missing_assignment_and_mount_config_fail_before_output(self):
        for name in ("MEADOW_ENGINE_BUILD", "MEADOW_QUALITY", "MEADOW_RENDER_CONTRACTS", "meadowQuality.mount"):
            (self.frozen / "index.html").write_text(self.html.replace("window." + name, "window.syntheticRemoved"), encoding="utf-8")
            self.refused("Missing source assignment|Frozen mount config required")

    def test_extra_inline_script_is_refused_without_publishing_an_entry(self):
        (self.frozen / "index.html").write_text(self.html.replace("</body>", "<script>syntheticExtra()</script></body>"), encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Exactly two inline source scripts"):
            self.assemble()
        self.assertFalse((self.output / "index.html").exists())
        self.assertFalse((self.output / "camp-web-manifest.json").exists())
        self.assertEqual(self.snapshot(), before)

    def test_exclusive_write_helper_never_overwrites_existing_bytes(self):
        target = self.owned / "existing.txt"
        target.write_bytes(b"synthetic keep")
        with self.assertRaises(FileExistsError):
            stager.write(target, b"synthetic replace")
        self.assertEqual(target.read_bytes(), b"synthetic keep")

    def test_source_mutation_during_copy_is_detected_and_never_certified(self):
        original_copy = stager.shutil.copyfile
        target = self.frozen / "detail-1-0123456789ab.pck"

        def change_after_copy(source, destination):
            result = original_copy(source, destination)
            if source == target:
                target.write_bytes(b"synthetic concurrent source writer")
            return result

        with patch.object(stager.shutil, "copyfile", side_effect=change_after_copy):
            with self.assertRaisesRegex(ValueError, "Source v153 changed during staging"):
                self.assemble()
        self.assertFalse((self.output / "camp-web-manifest.json").exists())

    def test_corrupt_copied_frozen_output_is_never_certified(self):
        original_copy = stager.shutil.copyfile

        def corrupt_copy(source, destination):
            result = original_copy(source, destination)
            if source == self.frozen / "index.wasm":
                Path(destination).write_bytes(b"synthetic corrupted destination")
            return result

        with patch.object(stager.shutil, "copyfile", side_effect=corrupt_copy):
            with self.assertRaisesRegex(ValueError, "Frozen payload changed"):
                self.assemble()
        self.assertFalse((self.output / "camp-web-manifest.json").exists())

    # Security regressions: reject conflicting pins rather than silently trusting
    # whichever copy/dictionary entry happened last. No real input is involved.
    def test_conflicting_same_filename_bootstrap_pins_are_rejected(self):
        for tier in ("original", "balanced"):
            selected = self.config["bindings"][tier]["bootstrap"]
            for mutation in ({"sha256": "0" * 64}, {"bytes": selected["bytes"] + 1}):
                with self.subTest(tier=tier, mutation=mutation):
                    self.config["bindings"][tier]["bootstrap"] = {**selected, **mutation}
                    self.write_manifests()
                    self.refused("[Pp]in|[Cc]onflict|[Dd]uplicate")
            self.config["bindings"][tier]["bootstrap"] = selected

    def test_different_pack_roles_cannot_overwrite_one_another_by_filename(self):
        optional = self.config["optionalPack"]
        conflicting = self.file(self.boot, optional["file"], b"synthetic different bootstrap bytes", compressed=True)
        self.config["bindings"]["original"]["bootstrap"] = conflicting
        self.config["bindings"]["balanced"]["bootstrap"] = conflicting
        self.write_manifests()
        self.refused("[Pp]in|[Cc]onflict|[Dd]uplicate")

    def test_cross_role_aliases_and_sidecar_filenames_are_rejected(self):
        optional = self.config["optionalPack"]
        data = (self.art / optional["file"]).read_bytes()
        for name in (optional["file"], optional["file"].upper(), optional["file"] + ".gz"):
            with self.subTest(name=name):
                conflicting = self.file(self.boot, name, data, compressed=True)
                self.config["bindings"]["original"]["bootstrap"] = conflicting
                self.config["bindings"]["balanced"]["bootstrap"] = conflicting
                self.write_manifests()
                self.refused("Conflicting pack output filename")

    def test_packs_cannot_replace_frozen_or_generated_entry_filenames(self):
        for name in ("index.wasm", "index.audio.worklet.js.gz", "meadow-boot.js", "meadow-camp-entry.js",
                     "meadow-engine-preload.js.br", "index.html", "camp-web-manifest.json"):
            with self.subTest(name=name):
                conflicting = self.file(self.boot, name, b"synthetic filename collision", compressed=True)
                self.config["bindings"]["lite"]["bootstrap"] = conflicting
                self.write_manifests()
                self.refused("Conflicting pack output filename")

    def test_linked_pack_or_compressed_sidecar_is_refused_before_output(self):
        spec = self.config["optionalPack"]
        for suffix in ("", ".gz", ".br"):
            path = self.art / (spec["file"] + suffix)
            original = path.read_bytes()
            outside = self.owned / ("synthetic-link-source.pck" + suffix)
            outside.write_bytes(original)
            path.unlink()  # Exact owned fixture; restored as an independent file below.
            try:
                os.link(outside, path)
            except OSError as error:
                path.write_bytes(original)
                self.skipTest("Filesystem cannot create a synthetic hardlink: " + str(error))
            with self.subTest(suffix=suffix):
                self.refused("Unlinked regular input required")
                self.assertEqual(outside.read_bytes(), original)
            path.unlink()
            path.write_bytes(original)

    def test_payload_link_cannot_import_bytes_from_outside_public_input_root(self):
        outside = self.owned / "synthetic-nonpublic.pck"
        outside.write_bytes(b"synthetic outside boundary, no real private data")
        linked = self.art / "camp-presentation-0123456789ab.pck"
        try:
            os.link(outside, linked)
        except OSError as error:
            self.skipTest("Filesystem cannot create a synthetic hardlink: " + str(error))
        spec = {"file": linked.name, "bytes": outside.stat().st_size, "sha256": checksum(outside.read_bytes())}
        with self.assertRaisesRegex(ValueError, "[Ll]ink|[Rr]egular|[Pp]ath|[Bb]ound"):
            stager.pin(self.art, spec)
        self.assertEqual(outside.read_bytes(), b"synthetic outside boundary, no real private data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
