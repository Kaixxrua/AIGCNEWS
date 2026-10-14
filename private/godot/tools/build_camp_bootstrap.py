"""New, tiny two-settings-variant wrappers around byte-frozen v153 packs.

Never export a scene, copy a selected scene PCK, run an engine build, edit a
shared loader/stager, or overwrite an artifact. The output binding manifest is
for main's integration; original/balanced share the full-settings wrapper, lite
keeps the EXACT accepted bootstrap project.binary (including core15's hash).

Usage: python -B godot/tools/build_camp_bootstrap.py
  --output artifacts/camp-bootstrap/candidate-01
  [--presentation-manifest artifacts/camp-presentation/ART/presentation-pack.json]

Without art, optionalPack is null and native camp mounting is disabled. Supply
the public presentation manifest later and regenerate ONLY these small wrappers.
No public asset key, parent origin or pack pin is ever taken from a URL query.
Version-2 presentation manifests keep the tiny runtime in optionalPack and pin
one PNG-only actorShards entry per original atlas. Both generated wrappers embed
that exact library. selected-pack-bindings.json stays version 1. Main's stager
copies all actor PCKs/.br/.gz but MUST NOT preload them; the current three public
asset IDs select their shards only after both actual core and runtime readiness.
--self-test and --native-test GODOT_EXE use only small isolated test projects.
--actual-core-test GODOT_EXE --probe-output artifacts/camp-bootstrap/actual-core-01
is an opt-in real, frozen core15 scene runtime probe, still without any export.
Stock native Godot cannot decode the private Web mode5 resources: explicitly
add --native-twin to use the already-reviewed, byte-pinned native core15 twin.
The report identifies the actual input; this never silently replaces a failed
Web test or changes the production selected-pack bindings.
Add --presentation-manifest to that probe to mount the existing public runtime
and ONLY its first hero/pet/Boss shards through the real Host. The probe copies
those small PCK bytes to its isolated user directory, not into a staged export.
Both wrappers retain the byte-exact empty global script class cache from v153.
Export templates require this file before the selected scene pack is mounted;
editor binaries otherwise hide its absence behind TOOLS_ENABLED.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
from inspect_web_pack import read_pack
from audit_lite_contract import project_records
from build_progressive_web_v135 import pack as pack_v4
import build_camp_presentation as presentation

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "artifacts/v153"
OUT_ROOT = ROOT / "artifacts/camp-bootstrap"
HOST = ROOT / "godot/scripts/camp_pack_host.gd"
PINS = {
    "bootstrap": {"file": "bootstrap.pck", "bytes": 8540,
        "sha256": "fd5727057ca877d5d4efb6635495df5a80926a85195d4766d090a4f08c162885"},
    "original": {"file": "index.pck", "bytes": 123983036,
        "sha256": "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d"},
    "balanced": {"file": "index-balanced.pck", "bytes": 111244748,
        "sha256": "68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33"},
    "lite": {"file": "index-lite.pck", "bytes": 6968456,
        "sha256": "4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c"},
}
PROJECT_PINS = {
    "bootstrap": "ab0dc16bf8ed9dcb14f2a5bc9003d9ce15693db063dfd6ca9c3f5623500d78e0",
    "original": "e606fac9b5b1e6db1027e42119647bf68e9ab7d6fd252c3f9b9b967583c9eb75",
    "balanced": "e606fac9b5b1e6db1027e42119647bf68e9ab7d6fd252c3f9b9b967583c9eb75",
    "lite": "4b5d0661e9358d10a6811faeba8058b97cec70d908fa097fbaf9f1db0d417c41",
    "fullWrapper": "a7e4203a243a16ecdbd3af07e628b086c3f29c905c2229070d454a379e2c1565",
}
BOOT_PATH = "res://progressive/boot.tscn"
MAIN_PATH = "res://scenes/main.tscn"
CORE_PATH = "/meadow-core.pck"
GLOBAL_CLASS_CACHE = ".godot/global_script_class_cache.cfg"
GLOBAL_CLASS_CACHE_SHA = "f61aa7ad3097022d6a9d110ca3f73fa7bb348ec2cf9a6e7c9523574dc75f5a16"
NATIVE_TWIN = ROOT / "artifacts/startup-v135/build/candidate-15/native/index-lite.pck"
NATIVE_TWIN_SHA = "8d7a9e04209cd0154029634d7d8a8c92b90d5ec7f009b821bb1e4b4afe86df95"
require = presentation.require
sha = presentation.sha
write_new = presentation.write_new

# This is the complete generated startup source, NOT a patch to meadow_boot.gd.
# Existing meadowBoot.bind(callback) / mounted(bool, fixed_code) is retained.
BOOT_GD = '''extends Node
var _web: JavaScriptObject
var _callback: JavaScriptObject
var _entered := false

func _ready() -> void:
\tif OS.has_feature("web"):
\t\t_web = JavaScriptBridge.get_interface("meadowBoot")
\t\tif _web != null:
\t\t\t_callback = JavaScriptBridge.create_callback(_request)
\t\t\t_web.bind(_callback)

func _request(arguments: Array) -> void:
\tif arguments.size() == 1 and arguments[0] is String and arguments[0] == "/meadow-core.pck" and not _entered:
\t\t_enter.call_deferred(arguments[0])

func _reply(success: bool, code: String) -> void:
\tif _web != null:
\t\t_web.mounted(success, code)

func _enter(path: String) -> void:
\tif _entered or path != "/meadow-core.pck":
\t\treturn
\t_entered = true
\tvar bindings: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://camp_bootstrap/bindings.json"))
\tif not bindings is Dictionary or bindings.get("version") != 1 or not bindings.get("selectedPacks") is Array:
\t\t_reply(false, "wrapper_config")
\t\treturn
\tvar file := FileAccess.open(path, FileAccess.READ)
\tif file == null:
\t\t_reply(false, "selected_pack_missing")
\t\treturn
\tvar length := file.get_length()
\tfile.close()
\tvar digest := FileAccess.get_sha256(path)
\tvar matched := false
\tfor selected: Dictionary in bindings.selectedPacks:
\t\tmatched = matched or (length == int(selected.bytes) and digest == selected.sha256)
\tif not matched:
\t\t_reply(false, "selected_pack_pin")
\t\treturn
\tif not ProjectSettings.load_resource_pack(path, false):
\t\t_reply(false, "selected_pack_mount")
\t\treturn
\tProjectSettings.set_setting("application/run/main_scene", "res://scenes/main.tscn")
\t# Deferred from JS: root is not busy adding the disposable bootstrap scene.
\t# Ordinary root sibling survives change_scene; never touch MeadowPlain here.
\tvar code: Script = load("res://camp_bootstrap/camp_pack_host.gd")
\tif code == null or not code.can_instantiate() or get_tree().root.has_node("CampPackHost"):
\t\t_reply(false, "host_config")
\t\treturn
\tvar host: Node = code.new()
\tif not host.configure({"version": 1, "optionalPack": bindings.optionalPack, "actorShards": bindings.get("actorShards", [])}):
\t\thost.free()
\t\t_reply(false, "host_config")
\t\treturn
\tget_tree().root.add_child(host)
\tvar error := get_tree().change_scene_to_file("res://scenes/main.tscn")
\t_reply(error == OK, "scene_entered" if error == OK else "scene_enter_failed")
'''
BOOT_TSCN = b'''[gd_scene load_steps=2 format=3]
[ext_resource type="Script" path="res://camp_bootstrap/boot.gd" id="1"]
[node name="MeadowCampBootstrap" type="Node"]
script = ExtResource("1")
'''


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def selected_entry(path, name, maximum=4 * 1024 * 1024):
    rows = read_pack(Path(path), verify=False)["entries"]
    matches = [row for row in rows if row["path"] == name]
    require(len(matches) == 1, f"Exactly one source entry: {name}")
    row = matches[0]
    require(row["bytes"] <= maximum, "Bounded wrapper input entry")
    with Path(path).open("rb") as stream:
        stream.seek(row["offset"])
        blob = stream.read(row["bytes"])
    require(hashlib.md5(blob).hexdigest() == row["md5"], f"Entry checksum: {name}")
    return blob


def frozen_global_class_cache():
    # This is real startup metadata, not an error filter or generated editor
    # cache. The four frozen sources have the same empty public class list.
    # Fail closed if that assumption ever changes: do not mask nonempty classes
    # when later scene/actor packs mount with replace_files=False.
    cache = selected_entry(FROZEN / PINS["bootstrap"]["file"], GLOBAL_CLASS_CACHE, 128)
    require(cache == b"list=[]\n" and sha(cache) == GLOBAL_CLASS_CACHE_SHA,
            "Exact frozen empty global script class cache required")
    return cache


def string_variant(value):
    blob = value.encode()
    return struct.pack("<II", 4, len(blob)) + blob + b"\0" * (-len(blob) % 4)


def with_boot_entry(project):
    before = project_records(project)
    require(before["application/run/main_scene"] == string_variant(MAIN_PATH), "Exact frozen main scene")
    after = dict(before)
    after["application/run/main_scene"] = string_variant(BOOT_PATH)
    result = bytearray(b"ECFG" + struct.pack("<I", len(after)))
    for key, value in after.items():
        encoded = key.encode()
        result.extend(struct.pack("<I", len(encoded)) + encoded + struct.pack("<I", len(value)) + value)
    parsed = project_records(result)
    require(list(parsed) == list(before) and [key for key in before if before[key] != parsed[key]] == ["application/run/main_scene"],
            "Only initial main scene may differ, including record order")
    return bytes(result)


def frozen_inputs():
    projects = {}
    cache = frozen_global_class_cache()
    for tier, pin in PINS.items():
        path = FROZEN / pin["file"]
        require(path.stat().st_size == pin["bytes"] and file_sha(path) == pin["sha256"], f"Frozen v153 {tier} pin")
        projects[tier] = selected_entry(path, "project.binary")
        require(sha(projects[tier]) == PROJECT_PINS[tier], f"Frozen {tier} settings")
        require(selected_entry(path, GLOBAL_CLASS_CACHE, 128) == cache, f"Frozen {tier} global script classes identical")
    require(projects["original"] == projects["balanced"], "Full tiers share EXACT settings")
    require(with_boot_entry(projects["lite"]) == projects["bootstrap"], "Frozen bootstrap has exact lite boot settings")
    require(sha(with_boot_entry(projects["original"])) == PROJECT_PINS["fullWrapper"], "Full boot settings proof")
    core15 = json.loads(selected_entry(FROZEN / PINS["lite"]["file"], "progressive/static-core/manifest.json"))
    require(PROJECT_PINS["bootstrap"] in core15["dependencies"]["res://project.binary"], "Actual core15 settings dependency accepts lite wrapper")
    with (FROZEN / PINS["bootstrap"]["file"]).open("rb") as stream:
        header = stream.read(112)
    require(struct.unpack_from("<I", header, 4)[0] == 4, "Frozen bootstrap PCK v4")
    return header, projects


def optional_library(manifest_path):
    if manifest_path is None:
        return None, {role: [] for role in ("hero", "pet", "boss")}, []
    path = Path(manifest_path).resolve(strict=True)
    require(path.is_relative_to(ROOT) and path.stat().st_size <= 1024 * 1024, "Small public presentation manifest only")
    manifest = json.loads(path.read_bytes())
    require(type(manifest) is dict and type(manifest.get("version")) is int and manifest["version"] in (1, 2), "Presentation manifest version")
    sharded = manifest["version"] == 2
    spec = manifest.get("pack")
    require(type(spec) is dict and set(spec) == {"file", "bytes", "sha256"}, "Exact optional pack pin")
    digest = spec["sha256"]
    require(type(digest) is str and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "Optional SHA256")
    require(spec["file"] == f"camp-presentation-{digest[:12]}.pck" and type(spec["bytes"]) is int
            and 0 < spec["bytes"] <= presentation.MAX_PACK, "Bounded content-addressed optional pack")
    pack_path = path.parent / spec["file"]
    require(pack_path.resolve(strict=True).is_relative_to(path.parent), "Optional pack stays beside manifest")
    require(pack_path.stat().st_size == spec["bytes"] and file_sha(pack_path) == digest, "Actual optional pack matches pin")
    rows = read_pack(pack_path, verify=True)["entries"]
    names = {row["path"] for row in rows}
    entry, catalogue = "camp_presentation/camp_presentation.gd", "camp_presentation/manifest.json"
    reviewed_scripts = {presentation.NAMESPACE + name: source for name, source in presentation.RUNTIME_SCRIPTS.items()}
    reviewed_assets = {presentation.NAMESPACE + name: source for name, source in presentation.RUNTIME_ASSETS.items()}
    runtime_names = {catalogue} | set(reviewed_scripts) | set(reviewed_assets)
    require(runtime_names.issubset(names) and len(names) <= len(runtime_names) + 64, "Small presentation-only pack")
    require(not sharded or (names == runtime_names and spec["bytes"] <= presentation.MAX_RUNTIME_PACK), "Sharded runtime contains no PNG or full library")
    for name in names - runtime_names:
        require(name.startswith("camp_presentation/atlases/atlas-") and name.endswith(".png")
                and "/" not in name.removeprefix("camp_presentation/atlases/") and ".." not in name and "\\" not in name,
                "Only public atlas entries, never settings, caches or other scripts")
    for name, source in reviewed_scripts.items():
        require(selected_entry(pack_path, name) == source.read_bytes(), "Pinned reviewed renderer/skill/HUD/layout/travel source")
    for name, source in reviewed_assets.items():
        require(selected_entry(pack_path, name) == source.read_bytes(), "Pinned reviewed runtime font/license asset")
    art = json.loads(selected_entry(pack_path, catalogue))
    require(type(art) is dict and set(art) == {"version", "assets"} and type(art["version"]) is int and art["version"] == 1
            and type(art["assets"]) is list and 1 <= len(art["assets"]) <= 64, "Public art catalogue")
    ids = {role: [] for role in ("hero", "pet", "boss")}
    seen = set()
    for actor in art["assets"]:
        require(type(actor) is dict and set(actor) in (presentation.KEYS, presentation.KEYS | {"frameAnchors"})
                and actor.get("role") in ids and type(actor.get("id")) is str
                and presentation.ID.fullmatch(actor["id"]) and actor["id"] not in seen, "Unique public catalogue keys")
        require(type(actor.get("atlas")) is str and presentation.re.fullmatch(
                r"res://camp_presentation/atlases/atlas-[a-f0-9]{16}\.png", actor["atlas"]), "Fixed public PNG resource path")
        if not sharded:
            require(actor.get("atlas", "").removeprefix("res://") in names, "Every art texture is in the pinned pack")
        ids[actor["role"]].append(actor["id"]); seen.add(actor["id"])
    require(manifest.get("assetIds") == ids, "Manifest asset allowlists match actual packed catalogue")
    if not sharded:
        require(not manifest.get("actorShards"), "Legacy monolithic pack cannot silently add actor shards")
        return dict(spec), ids, []
    shards = manifest.get("actorShards")
    require(type(shards) is list and 1 <= len(shards) <= 64, "Explicit bounded actor shard library")
    actor_map = {actor["id"]: actor for actor in art["assets"]}
    covered, textures, files, total = set(), set(), set(), 0
    checked = []
    for shard in shards:
        require(type(shard) is dict and set(shard) == {"pack", "assetIds"}, "Exact public shard fields")
        pin = shard["pack"]
        require(type(pin) is dict and set(pin) == {"file", "bytes", "sha256"}, "Exact shard pin")
        digest = pin["sha256"]
        require(type(digest) is str and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "Shard SHA256")
        require(pin["file"] == f"camp-actor-{digest[:12]}.pck" and pin["file"] not in files and type(pin["bytes"]) is int
                and 0 < pin["bytes"] <= presentation.MAX_ACTOR_PACK, "Bounded unique content-addressed actor shard")
        shard_path = (path.parent / pin["file"]).resolve(strict=True)
        require(shard_path.is_relative_to(path.parent) and shard_path.stat().st_size == pin["bytes"]
                and file_sha(shard_path) == digest, "Actual shard bytes match fixed pin")
        keys = shard["assetIds"]
        require(type(keys) is list and 1 <= len(keys) <= 64 and all(type(key) is str and key in actor_map and key not in covered for key in keys)
                and len(set(keys)) == len(keys), "Known public asset keys assigned to one shard")
        resources = {actor_map[key]["atlas"] for key in keys}
        require(len(resources) == 1, "Each shard contains one whole original PNG")
        resource = resources.pop()
        require(type(resource) is str and resource.startswith("res://camp_presentation/atlases/atlas-") and resource.endswith(".png"), "Fixed actor texture namespace")
        name = resource.removeprefix("res://")
        require(name not in textures, "Shared PNG must use one shared shard, never overlapping pack entries")
        rows = read_pack(shard_path, verify=True)["entries"]
        require(len(rows) == 1 and rows[0]["path"] == name and rows[0]["bytes"] <= 8 * 1024 * 1024,
                "Actor shard is PNG-only: no scripts, settings, manifests or removal/override entries")
        png = selected_entry(shard_path, name, 8 * 1024 * 1024)
        require(png.startswith(b"\x89PNG\r\n\x1a\n"), "Actor resource must contain original PNG bytes")
        require(name == f"camp_presentation/atlases/atlas-{sha(png)[:16]}.png", "Texture resource name binds exact PNG bytes")
        files.add(pin["file"]); textures.add(name); covered.update(keys); total += pin["bytes"]
        checked.append({"pack": dict(pin), "assetIds": list(keys)})
    require(covered == set(actor_map) and total <= presentation.MAX_LIBRARY, "Shards cover catalogue exactly within bounded library budget")
    return dict(spec), ids, checked


def optional_pack(manifest_path):
    """Legacy reader interface retained; build uses the full validated library."""
    pin, ids, _ = optional_library(manifest_path)
    return pin, ids


def wrapper_entries(project, variant, optional, actor_shards=None):
    tiers = ["lite"] if variant == "lite" else ["original", "balanced"]
    require(variant in ("lite", "full"), "Two explicit settings variants")
    bindings = {"version": 1, "variant": variant,
        "selectedPacks": [PINS[tier] for tier in tiers], "optionalPack": optional, "actorShards": actor_shards or []}
    return {"project.binary": project, "progressive/boot.tscn": BOOT_TSCN,
        GLOBAL_CLASS_CACHE: frozen_global_class_cache(),
        "camp_bootstrap/boot.gd": BOOT_GD.encode(),
        "camp_bootstrap/camp_pack_host.gd": HOST.read_bytes(),
        "camp_bootstrap/bindings.json": (json.dumps(bindings, separators=(",", ":")) + "\n").encode()}


def build(output, presentation_manifest=None):
    output = Path(output).resolve()
    require(output.is_relative_to(OUT_ROOT) and output != OUT_ROOT and not output.exists(), "New camp-bootstrap output directory only")
    header, projects = frozen_inputs()
    optional, ids, actor_shards = optional_library(presentation_manifest)
    settings = {"lite": projects["bootstrap"], "full": with_boot_entry(projects["original"])}
    pending, variants = {}, {}
    import brotli
    for variant, project in settings.items():
        entries = wrapper_entries(project, variant, optional, actor_shards)
        blob = pack_v4(header, entries)
        require(len(blob) < 128 * 1024, "Tiny wrapper only; no scene or art payloads")
        digest = sha(blob)
        name = f"camp-bootstrap-{variant}-{digest[:12]}.pck"
        compressed, zipped = brotli.compress(blob, quality=6), gzip.compress(blob, mtime=0)
        pending.update({name: blob, name + ".br": compressed, name + ".gz": zipped})
        variants[variant] = {"file": name, "bytes": len(blob), "sha256": digest,
            "projectBinarySha256": sha(project), "transferBytes": {"br": len(compressed), "gzip": len(zipped)},
            "entries": {key: {"bytes": len(value), "sha256": sha(value)} for key, value in entries.items()}}
    bindings = {}
    for tier in ("original", "balanced", "lite"):
        variant = "lite" if tier == "lite" else "full"
        wrapper = variants[variant]
        bindings[tier] = {"mainPack": PINS[tier]["file"], "selectedPack": PINS[tier],
            "bootstrap": {key: wrapper[key] for key in ("file", "bytes", "sha256")},
            "coreSha256": PINS[tier]["sha256"], "settingsVariant": variant,
            "virtualCorePath": CORE_PATH, "mainScene": MAIN_PATH, "progressive": tier == "lite"}
    manifest = {"version": 1, "source": "frozen-v153", "sourcePins": PINS, "variants": variants,
        "bindings": bindings, "optionalPack": optional, "assetIds": ids, "actorShards": actor_shards,
        "host": {"path": "res://camp_bootstrap/camp_pack_host.gd", "parent": "/root", "autoload": False,
            "callback": "meadowCampMount", "coreChildrenBeforeReady": 0},
        "settingsProof": {"initialChangeOnly": "application/run/main_scene", "liteCore15ProjectBinaryExact": True,
            "fullProjectSettingsExactAfterMainSceneRestore": True},
        "notes": ["No selected scene pack copied or modified", "No core readiness emitted by wrapper",
            "Camp art fetch starts only after the existing actual core gate", "Main must remeasure the integrated 10s Web gate"]}
    # Assemble/validate everything first, create once, never overwrite anything.
    output.mkdir(parents=True, exist_ok=False)
    for name, blob in pending.items():
        write_new(output / name, blob)
    write_new(output / "boot-template.gd", BOOT_GD.encode())
    write_new(output / "selected-pack-bindings.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest


class BootstrapTests(unittest.TestCase):
    def shard_build(self, stage):
        fixture = presentation.test_shard_fixture(stage / "input")
        source = stage / "input/public-art.json"
        write_new(source, json.dumps(fixture).encode())
        result = presentation.build(source, stage / "library", sharded=True)
        return stage / "library/presentation-pack.json", result, fixture

    def test_frozen_settings_and_namespace(self):
        header, projects = frozen_inputs()
        self.assertEqual(projects["original"], projects["balanced"])
        for variant, project in (("lite", projects["bootstrap"]), ("full", with_boot_entry(projects["original"]))):
            entries = wrapper_entries(project, variant, None)
            self.assertEqual(len(entries), 6)
            self.assertNotIn("autoload/", str(project_records(project).keys()))
            self.assertNotIn("scripts/meadow_scene.gd", entries)
            self.assertLess(len(pack_v4(header, entries)), 128 * 1024)
        self.assertEqual(sha(projects["bootstrap"]), PROJECT_PINS["bootstrap"])

    def test_global_class_cache_exists_before_selected_pack_and_matches_frozen_bytes(self):
        expected = frozen_global_class_cache()
        self.assertEqual(expected, b"list=[]\n")
        for pin in PINS.values():
            self.assertEqual(selected_entry(FROZEN / pin["file"], GLOBAL_CLASS_CACHE), expected)
        for variant in ("lite", "full"):
            entries = wrapper_entries(b"test-settings", variant, None)
            self.assertEqual(entries[GLOBAL_CLASS_CACHE], expected)
            self.assertEqual([name for name in entries if name.startswith(".godot/")], [GLOBAL_CLASS_CACHE])
            self.assertEqual(entries["project.binary"], b"test-settings")

    def test_missing_or_nonempty_cache_is_not_silently_replaced_with_empty_metadata(self):
        for cache in (b"", b"list=[{}]\n", b"list=\"invalid\"\n", b"list=[]\nextra=true\n"):
            with self.subTest(cache=cache), patch(__name__ + ".selected_entry", return_value=cache), \
                    self.assertRaisesRegex(ValueError, "Exact frozen empty"):
                wrapper_entries(b"test", "lite", None)
        with patch(__name__ + ".selected_entry", side_effect=ValueError("missing source entry")), \
                self.assertRaisesRegex(ValueError, "missing source entry"):
            wrapper_entries(b"test", "full", None)

    def test_bindings_are_selected_pack_pins_not_copies(self):
        for variant, tiers in (("lite", ["lite"]), ("full", ["original", "balanced"])):
            entries = wrapper_entries(b"test", variant, None)
            value = json.loads(entries["camp_bootstrap/bindings.json"])
            self.assertEqual(value["selectedPacks"], [PINS[tier] for tier in tiers])
            self.assertIsNone(value["optionalPack"])
        self.assertNotIn("JavaScriptBridge.eval", BOOT_GD)
        self.assertIn("load_resource_pack(path, false)", BOOT_GD)
        self.assertNotIn("sceneReady", BOOT_GD)

    def test_output_and_optional_manifest_fail_closed(self):
        for output in (ROOT, FROZEN, OUT_ROOT, ROOT.parent):
            with self.assertRaisesRegex(ValueError, "New camp-bootstrap"):
                build(output)
        with tempfile.TemporaryDirectory(prefix="camp-wrapper-negative-") as temporary:
            path = Path(temporary) / "outside.json"
            write_new(path, b'{}')
            with self.assertRaisesRegex(ValueError, "public presentation"):
                optional_pack(path)
        self.assertEqual(optional_pack(None), (None, {"hero": [], "pet": [], "boss": []}))

    def test_actual_optional_pin_and_allowlists(self):
        # Scoped temporary synthetic fixture, automatically removed. Not art.
        with tempfile.TemporaryDirectory(prefix="camp-pin-test-", dir=ROOT / "artifacts") as temporary:
            stage = Path(temporary).resolve()
            entries, actors = presentation.prepare(presentation.test_fixture(stage), stage)
            blob = presentation.pack_resources(entries)
            spec = {"file": f"camp-presentation-{sha(blob)[:12]}.pck", "bytes": len(blob), "sha256": sha(blob)}
            ids = {role: [a["id"] for a in actors if a["role"] == role] for role in ("hero", "pet", "boss")}
            write_new(stage / spec["file"], blob)
            good = stage / "public.json"
            write_new(good, json.dumps({"version": 1, "pack": spec, "assetIds": ids}).encode())
            self.assertEqual(optional_pack(good), (spec, ids))
            for index, value in enumerate((
                    {"version": 1, "pack": {**spec, "file": "../outside.pck"}, "assetIds": ids},
                    {"version": 1, "pack": {**spec, "bytes": spec["bytes"] + 1}, "assetIds": ids},
                    {"version": 1, "pack": {**spec, "sha256": "0" * 64}, "assetIds": ids},
                    {"version": 1, "pack": spec, "assetIds": {**ids, "hero": ["hero/injected"]}})):
                invalid = stage / f"invalid-{index}.json"; write_new(invalid, json.dumps(value).encode())
                with self.subTest(index=index), self.assertRaises(ValueError):
                    optional_pack(invalid)

    def test_foreign_resource_or_script_cannot_become_a_pinned_optional_pack(self):
        header, _ = frozen_inputs()
        with tempfile.TemporaryDirectory(prefix="camp-pin-negative-", dir=ROOT / "artifacts") as temporary:
            stage = Path(temporary).resolve()
            entries, actors = presentation.prepare(presentation.test_fixture(stage), stage)
            ids = {role: [a["id"] for a in actors if a["role"] == role] for role in ("hero", "pet", "boss")}
            for index, change in enumerate(({"project.binary": b"foreign"},
                    {GLOBAL_CLASS_CACHE: b"list=[]\n"}, {"camp_presentation/extra.gd": b"foreign"},
                    {"camp_presentation/camp_presentation.gd": b"unreviewed"},
                    {"camp_presentation/camp_combat_effects.gd": b"unreviewed"},
                    {"camp_presentation/camp_boss_hud.gd": b"unreviewed"},
                    {"camp_presentation/camp_spawn_layout.gd": b"unreviewed"},
                    {"camp_presentation/camp_travel_path.gd": b"unreviewed"},
                    {"camp_presentation/fonts/camp_ui_zh.ttf": b"unreviewed"},
                    {"camp_presentation/fonts/OFL.txt": b"unreviewed"})):
                blob = pack_v4(header, {**entries, **change})
                spec = {"file": f"camp-presentation-{sha(blob)[:12]}.pck", "bytes": len(blob), "sha256": sha(blob)}
                write_new(stage / spec["file"], blob)
                path = stage / f"invalid-{index}.json"
                write_new(path, json.dumps({"version": 1, "pack": spec, "assetIds": ids}).encode())
                with self.subTest(index=index), self.assertRaises(ValueError):
                    optional_pack(path)

    def test_repin_cannot_omit_the_fifth_reviewed_travel_script(self):
        with tempfile.TemporaryDirectory(prefix="camp-travel-pin-test-", dir=ROOT / "artifacts") as temporary:
            stage = Path(temporary).resolve()
            entries, actors = presentation.prepare(presentation.test_fixture(stage), stage)
            travel = presentation.NAMESPACE + "camp_travel_path.gd"
            self.assertEqual(entries.pop(travel), presentation.RUNTIME_SCRIPTS["camp_travel_path.gd"].read_bytes())
            blob = presentation.pack_resources(entries)
            pin = {"file": f"camp-presentation-{sha(blob)[:12]}.pck", "bytes": len(blob), "sha256": sha(blob)}
            ids = {role: [a["id"] for a in actors if a["role"] == role] for role in ("hero", "pet", "boss")}
            write_new(stage / pin["file"], blob)
            manifest = stage / "missing-travel.json"
            write_new(manifest, json.dumps({"version": 1, "pack": pin, "assetIds": ids}).encode())
            with self.assertRaisesRegex(ValueError, "Small presentation-only pack"):
                optional_library(manifest)

    def test_sharded_build_pins_exact_pngs_and_two_wrapper_settings(self):
        # Exercise the actual two builders, using only four tiny TEST fixtures.
        # No scene export or retained synthetic "production" artwork.
        presentation.OUT_ROOT.mkdir(parents=True, exist_ok=True)
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="sharded-build-test-", dir=presentation.OUT_ROOT) as temporary, \
                tempfile.TemporaryDirectory(prefix="sharded-wrapper-test-", dir=OUT_ROOT) as wrapper_temporary:
            stage = Path(temporary).resolve()
            path, manifest, fixture = self.shard_build(stage)
            pin, ids, shards = optional_library(path)
            self.assertEqual(manifest["version"], 2)
            self.assertEqual((pin, ids, shards), (manifest["pack"], manifest["assetIds"], manifest["actorShards"]))
            self.assertEqual(len(shards), 4)
            runtime = path.parent / pin["file"]
            self.assertEqual({entry["path"] for entry in read_pack(runtime)["entries"]},
                {"camp_presentation/manifest.json"}
                | {presentation.NAMESPACE + name for name in presentation.RUNTIME_SCRIPTS}
                | {presentation.NAMESPACE + name for name in presentation.RUNTIME_ASSETS})
            for name, source in presentation.RUNTIME_ASSETS.items():
                self.assertEqual(selected_entry(runtime, presentation.NAMESPACE + name), source.read_bytes())
            self.assertLess(pin["bytes"], presentation.MAX_RUNTIME_PACK)
            self.assertEqual(manifest["libraryBytes"], sum(row["pack"]["bytes"] for row in shards))
            for row in shards:
                pack_path = path.parent / row["pack"]["file"]
                entries = read_pack(pack_path)["entries"]
                self.assertEqual(len(entries), 1)
                actor = next(actor for actor in fixture["assets"] if actor["id"] in row["assetIds"])
                source = (stage / "input" / actor["atlas"]).read_bytes()
                self.assertEqual(selected_entry(pack_path, entries[0]["path"]), source)
                self.assertEqual(file_sha(pack_path), row["pack"]["sha256"])
                self.assertEqual(gzip.decompress(Path(str(pack_path) + ".gz").read_bytes()), pack_path.read_bytes())
            output = Path(wrapper_temporary) / "wrappers"
            wrappers = build(output, path)
            self.assertEqual(wrappers["optionalPack"], pin)
            self.assertEqual(wrappers["actorShards"], shards)
            self.assertEqual(wrappers["bindings"]["original"]["bootstrap"], wrappers["bindings"]["balanced"]["bootstrap"])
            for variant, item in wrappers["variants"].items():
                packed = output / item["file"]
                config = json.loads(selected_entry(packed, "camp_bootstrap/bindings.json"))
                self.assertEqual(config["actorShards"], shards)
                self.assertEqual(config["optionalPack"], pin)
                self.assertEqual(file_sha(packed), item["sha256"])
                self.assertEqual(selected_entry(packed, GLOBAL_CLASS_CACHE), frozen_global_class_cache())
                self.assertEqual(item["entries"][GLOBAL_CLASS_CACHE], {"bytes": 8, "sha256": GLOBAL_CLASS_CACHE_SHA})
                self.assertEqual(sha(selected_entry(packed, "project.binary")),
                    PROJECT_PINS["bootstrap" if variant == "lite" else "fullWrapper"])
            self.assertFalse(list(output.glob("index*.pck")))
            self.assertIn('"actorShards": bindings.get("actorShards", [])', (output / "boot-template.gd").read_text())

    def test_shard_mapping_pins_and_library_limits_fail_closed(self):
        presentation.OUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="sharded-pin-test-", dir=presentation.OUT_ROOT) as temporary:
            path, manifest, _ = self.shard_build(Path(temporary).resolve())
            first, second = manifest["actorShards"][:2]
            cases = [
                {"version": True}, {"version": 1}, {"actorShards": []},
                {"actorShards": manifest["actorShards"][:-1]},
                {"actorShards": [first, first, *manifest["actorShards"][2:]]},
                {"actorShards": [{**first, "assetIds": ["hero/unknown"]}, *manifest["actorShards"][1:]]},
                {"actorShards": [{**first, "assetIds": first["assetIds"] + second["assetIds"]}, *manifest["actorShards"][2:]]},
                {"actorShards": [{**first, "private": "forbidden"}, *manifest["actorShards"][1:]]},
            ]
            for change in ({"bytes": True}, {"bytes": presentation.MAX_ACTOR_PACK + 1},
                    {"bytes": first["pack"]["bytes"] + 1}, {"file": "../outside.pck"},
                    {"sha256": first["pack"]["sha256"][:63] + ("1" if first["pack"]["sha256"][-1] == "0" else "0")},
                    {"token": "forbidden"}):
                cases.append({"actorShards": [{**first, "pack": {**first["pack"], **change}}, *manifest["actorShards"][1:]]})
            for index, change in enumerate(cases):
                invalid = path.parent / f"invalid-{index}.json"
                write_new(invalid, json.dumps({**manifest, **change}).encode())
                with self.subTest(index=index), self.assertRaises(ValueError):
                    optional_library(invalid)
            # Test the aggregate guard without allocating a 128 MB fixture.
            with patch.object(presentation, "MAX_LIBRARY", manifest["libraryBytes"] - 1), \
                    self.assertRaisesRegex(ValueError, "bounded library budget"):
                optional_library(path)

    def test_repinned_actor_shards_cannot_smuggle_resources_or_bad_payloads(self):
        presentation.OUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="sharded-resource-test-", dir=presentation.OUT_ROOT) as temporary:
            path, manifest, _ = self.shard_build(Path(temporary).resolve())
            first = manifest["actorShards"][0]
            source = path.parent / first["pack"]["file"]
            name = read_pack(source)["entries"][0]["path"]
            png = selected_entry(source, name)
            with (FROZEN / "bootstrap.pck").open("rb") as stream:
                header = stream.read(112)
            bad_packs = [pack_v4(header, {name: png, **extra}) for extra in (
                {"project.binary": b"forbidden"}, {"camp_presentation/extra.gd": b"forbidden"},
                {"camp_presentation/camp_spawn_layout.gd": b"forbidden"},
                {"camp_presentation/camp_travel_path.gd": b"forbidden"},
                {"camp_presentation/fonts/camp_ui_zh.ttf": b"forbidden"},
                {"camp_presentation/fonts/OFL.txt": b"forbidden"},
                {GLOBAL_CLASS_CACHE: b"list=[]\n"},
                {"camp_presentation/manifest.json": b"{}"},
                {"camp_presentation/atlases/atlas-0000000000000000.png": png})]
            bad_packs.append(presentation.pack_resources({name: b"not a PNG"}))
            bad_packs.append(source.read_bytes()[:-1] + bytes([source.read_bytes()[-1] ^ 1]))
            for index, blob in enumerate(bad_packs):
                pin = {"file": f"camp-actor-{sha(blob)[:12]}.pck", "bytes": len(blob), "sha256": sha(blob)}
                write_new(path.parent / pin["file"], blob)
                invalid = path.parent / f"foreign-{index}.json"
                write_new(invalid, json.dumps({**manifest, "actorShards": [
                    {**first, "pack": pin}, *manifest["actorShards"][1:]]}).encode())
                with self.subTest(index=index), self.assertRaises(ValueError):
                    optional_library(invalid)
            runtime_path = path.parent / manifest["pack"]["file"]
            entries = {row["path"]: selected_entry(runtime_path, row["path"]) for row in read_pack(runtime_path)["entries"]}
            blob = presentation.pack_resources({**entries, name: png})
            pin = {"file": f"camp-presentation-{sha(blob)[:12]}.pck", "bytes": len(blob), "sha256": sha(blob)}
            write_new(path.parent / pin["file"], blob)
            invalid = path.parent / "hidden-runtime-png.json"
            write_new(invalid, json.dumps({**manifest, "pack": pin}).encode())
            with self.assertRaisesRegex(ValueError, "runtime contains no PNG"):
                optional_library(invalid)


def run_engine(engine, stage, arguments, name, gpu=False):
    env = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = stage / key.lower(); directory.mkdir(exist_ok=True); env[key] = str(directory)
    display = ["--rendering-method", "gl_compatibility", "--rendering-driver", "opengl3", "--windowed",
               "--resolution", "2560x1440", "--position", "-10000,-10000", "--audio-driver", "Dummy"] if gpu else ["--headless"]
    result = subprocess.run([str(engine), *display, "--path", str(stage), "--log-file", str(stage / (name + ".log")), *arguments],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60 if gpu else 45, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log = result.stdout + result.stderr
    require(result.returncode == 0 and "SCRIPT ERROR" not in log and "ERROR:" not in log, log)
    return log


def native_test(engine):
    engine = Path(engine).resolve(strict=True)
    header, projects = frozen_inputs()
    # Synthetic public atlas ONLY for tests, never delivered or substituted.
    with tempfile.TemporaryDirectory(prefix="camp-wrapper-native-") as temporary:
        stage = Path(temporary).resolve()
        write_new(stage / "project.godot", b'config_version=5\n[application]\nconfig/name="CampWrapperTestOnly"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
        # Negative control for the old five-entry composition: the editor build
        # does not print the export-only error, so exercise ConfigFile directly.
        # No scene is started and no failure log is filtered or suppressed.
        missing = wrapper_entries(projects["bootstrap"], "lite", None)
        del missing[GLOBAL_CLASS_CACHE]
        missing_path = stage / "missing-cache-control.pck"
        write_new(missing_path, pack_v4(header, missing))
        log = run_engine(engine, stage, ["--main-pack", str(missing_path), "--script",
            str(ROOT / "godot/tools/test_camp_bootstrap.gd"), "--", "cache-missing-control"], "missing-cache-control")
        require("CAMP_GLOBAL_CACHE_NEGATIVE_CONTROL: PASS" in log, log)
        print(log.strip())
        fixture = presentation.test_fixture(stage)
        art_entries, _ = presentation.prepare(fixture, stage)
        art = presentation.pack_resources(art_entries)
        optional = {"file": f"camp-presentation-{sha(art)[:12]}.pck", "bytes": len(art), "sha256": sha(art)}
        write_new(stage / optional["file"], art)
        # Runtime tests open exact virtual /filename via an isolated scoped pack
        # entry, not by writing to a filesystem root or the real scene workspace.
        for tier in ("original", "balanced", "lite"):
            project = projects["bootstrap"] if tier == "lite" else with_boot_entry(projects[tier])
            entries = wrapper_entries(project, "lite" if tier == "lite" else "full", optional)
            entries["camp_bootstrap/probe-scene.tscn"] = b'[gd_scene format=3]\n[node name="MeadowPlain" type="Node3D"]\n'
            wrapper = stage / (tier + ".pck"); write_new(wrapper, pack_v4(header, entries))
            config = {"tier": tier, "selectedPack": (FROZEN / PINS[tier]["file"]).as_posix(),
                "selectedPackSha256": PINS[tier]["sha256"], "bootProjectSha256": sha(project),
                "globalScriptCacheSha256": GLOBAL_CLASS_CACHE_SHA,
                "settings": {key: value.hex() for key, value in project_records(projects[tier]).items()},
                "optionalPack": optional, "testArtPath": (stage / optional["file"]).as_posix()}
            config_path = stage / (tier + ".json"); write_new(config_path, json.dumps(config).encode())
            # Parse the EXACT generated raw startup script without loading the
            # heavy meadow. Native settings/host probes use the real frozen PCK.
            run_engine(engine, stage, ["--main-pack", str(wrapper), "--check-only", "--script", "res://camp_bootstrap/boot.gd"], tier + "-parse")
            log = run_engine(engine, stage, ["--main-pack", str(wrapper), "--script",
                str(ROOT / "godot/tools/test_camp_bootstrap.gd"), "--", str(config_path)], tier)
            require("CAMP_BOOTSTRAP_TEST: PASS" in log, log)
            print(log.strip())
        # One extra tiny process verifies real individual PCK mounts/swaps and
        # stale-state handling, not another large scene build or export.
        shard_fixture = stage / "sharded-test"
        shard_fixture.mkdir()
        manifest = presentation.test_shard_fixture(shard_fixture)
        entries, catalogue = presentation.prepare(manifest, shard_fixture, sharded=True)
        runtime, library = presentation.sharded_resources(entries, catalogue)
        runtime_blob = presentation.pack_resources(runtime)
        runtime_pin = {"file": f"camp-presentation-{sha(runtime_blob)[:12]}.pck", "bytes": len(runtime_blob), "sha256": sha(runtime_blob)}
        write_new(shard_fixture / runtime_pin["file"], runtime_blob)
        for descriptor, blob in library:
            write_new(shard_fixture / descriptor["pack"]["file"], blob)
        shards = [descriptor for descriptor, _ in library]
        wrapper = shard_fixture / "probe-wrapper.pck"
        write_new(wrapper, pack_v4(header, wrapper_entries(projects["bootstrap"], "lite", runtime_pin, shards)))
        config_path = shard_fixture / "request.json"
        write_new(config_path, json.dumps({"runtime": runtime_pin, "actorShards": shards, "directory": shard_fixture.as_posix()}).encode())
        log = run_engine(engine, shard_fixture, ["--main-pack", str(wrapper), "--script",
            str(ROOT / "godot/tools/test_camp_actor_shards.gd"), "--", str(config_path)], "actor-shards")
        require("CAMP_ACTOR_SHARDS_TEST: PASS" in log, log)
        print(log.strip())


def placement_probe_data(manifest_path):
    """Read-only public art bounds for native terrain/camera diagnostics, no PCK build.

    This does not relax optional_library's current-script pin, mount old runtime
    code, copy PNGs, or make a visual acceptance claim.
    """
    path = Path(manifest_path).resolve(strict=True)
    require(path.is_relative_to(ROOT / "godot/assets/camp") and path.stat().st_size <= 1024 * 1024,
            "Placement audit uses an explicit small public camp art manifest only")
    entries, catalogue = presentation.prepare(json.loads(path.read_bytes()), path.parent, sharded=True)
    actors = []
    for asset in catalogue:
        png = entries[asset["atlas"].removeprefix("res://")]
        image = presentation.Image.open(presentation.io.BytesIO(png))
        bounds = [presentation.visible_frame_info(image.crop((x, y, x + w, y + h)))[0]
                  for x, y, w, h in asset["frameRects"]]
        actors.append({"asset": asset, "visibleFrameBounds": bounds, "sourcePngSha256": sha(png)})
    return {"manifestSha256": file_sha(path), "actors": actors,
            "note": "Read-only alpha>=32 bounds and actual core camera/terrain; no PNG edits or rendered screenshot"}


def actual_core_test(engine, output, native_twin=False, presentation_manifest=None, placement_manifest=None, gpu_lighting_probe=False, details_probe=False):
    require(presentation_manifest is None or placement_manifest is None, "Keep actual mounted-art and read-only placement probes separate")
    require(not gpu_lighting_probe or (native_twin and presentation_manifest is not None), "GPU lighting probe requires explicit native twin and pinned actual art")
    require(not details_probe or (native_twin and presentation_manifest is not None), "All-details probe requires explicit native twin and pinned actual art")
    engine, output = Path(engine).resolve(strict=True), Path(output).resolve()
    require(output.is_relative_to(OUT_ROOT) and output != OUT_ROOT and not output.exists(), "New camp-bootstrap runtime probe directory only")
    header, projects = frozen_inputs()
    selected = NATIVE_TWIN if native_twin else FROZEN / PINS["lite"]["file"]
    digest = NATIVE_TWIN_SHA if native_twin else PINS["lite"]["sha256"]
    require(file_sha(selected) == digest, "Exact reviewed runtime input pin")
    require(selected_entry(selected, "project.binary") == projects["lite"], "Runtime twin settings identical to Web core15")
    if native_twin:
        # Verify runtime code identity, not just a similarly named scene/node.
        for entry in ("scripts/meadow_scene.gdc", "scripts/meadow_wildlife.gdc", "scripts/meadow_weather.gdc"):
            require(selected_entry(selected, entry) == selected_entry(FROZEN / PINS["lite"]["file"], entry),
                    "Twin actual runtime script must match frozen Web: " + entry)
    # Same production wrapper settings/Host, no fixture world or scene PCK copy.
    optional, ids, actor_shards = optional_library(presentation_manifest)
    wrapper = pack_v4(header, wrapper_entries(projects["bootstrap"], "lite", optional, actor_shards))
    config = {"selectedPack": selected.as_posix(), "selectedPackSha256": digest,
        "sourceVariant": "reviewed-native-twin" if native_twin else "mode5-web",
        "targetWebPackSha256": PINS["lite"]["sha256"],
        "projectBinarySha256": PROJECT_PINS["bootstrap"], "renderer": presentation.SCRIPT.as_posix(),
        "globalScriptCacheSha256": GLOBAL_CLASS_CACHE_SHA,
        "rendererSha256": file_sha(presentation.SCRIPT), "wrapperSha256": sha(wrapper), "gpuLightingProbe": gpu_lighting_probe}
    if details_probe:
        details = json.loads(selected_entry(selected, "progressive/manifest.json"))
        require(len(details["chunks"]) == 12, "Actual core pins all twelve native detail chunks")
        for chunk in details["chunks"]:
            detail_path = (selected.parent / chunk["file"]).resolve(strict=True)
            require(detail_path.is_relative_to(selected.parent) and detail_path.stat().st_size == chunk["bytes"]
                    and file_sha(detail_path) == chunk["sha256"], "Exact already-existing native detail pin")
        config["detailDirectory"] = selected.parent.as_posix()
    if placement_manifest is not None:
        config["placement"] = placement_probe_data(placement_manifest)
    if optional is not None:
        require(all(ids[role] for role in ("hero", "pet", "boss")), "Actual art probe needs a public trio")
        directory = Path(presentation_manifest).resolve(strict=True).parent
        selected_ids = {role: ids[role][0] for role in ("hero", "pet", "boss")}
        if gpu_lighting_probe:
            require("pet_dragon" in ids["pet"], "Actual Ranger/dragon lighting probe requires public pet_dragon art")
            selected_ids["pet"] = "pet_dragon"
        selected_shards = [row for row in actor_shards if set(row["assetIds"]) & set(selected_ids.values())]
        catalogue = json.loads(selected_entry(directory / optional["file"], "camp_presentation/manifest.json"))
        packed_actors = []
        for actor in catalogue["assets"]:
            if actor["id"] not in selected_ids.values():
                continue
            pin = next((row["pack"] for row in selected_shards if actor["id"] in row["assetIds"]), optional)
            png = selected_entry(directory / pin["file"], actor["atlas"].removeprefix("res://"), 8 * 1024 * 1024)
            image = presentation.Image.open(presentation.io.BytesIO(png))
            bounds = [presentation.visible_frame_info(image.crop((x, y, x + w, y + h)))[0]
                for x, y, w, h in actor["frameRects"]]
            require(all(box is not None and box[0] >= 4 and box[1] >= 4
                and box[2] <= actor["frameSize"][0] - 4 and box[3] <= actor["frameSize"][1] - 4 for box in bounds),
                "Actual packed art retains the visible four-pixel guard")
            packed_actors.append({"asset": actor, "sourcePngSha256": sha(png), "visibleFrameBounds": bounds})
        config["presentation"] = {"directory": directory.as_posix(), "runtime": optional,
            "actorShards": actor_shards, "selectedShards": selected_shards, "selectedAssetIds": selected_ids,
            "packedActors": packed_actors, "manifestSha256": file_sha(presentation_manifest)}
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "probe-wrapper.pck", wrapper)
    write_new(output / "probe-request.json", json.dumps(config, indent=2).encode())
    log = run_engine(engine, output, ["--main-pack", str(output / "probe-wrapper.pck"), "--script",
        str(ROOT / "godot/tools/test_camp_actual_core.gd"), "--", str(output / "probe-request.json")], "actual-core", gpu=gpu_lighting_probe)
    report = json.loads((output / "actual-core-result.json").read_bytes())
    require(report["status"] == "PASS" and "MEADOW_STATIC_CORE_RESTORED" in log and "MEADOW_CORE_CONFIGURED" in log, log)
    require(file_sha(FROZEN / PINS["lite"]["file"]) == PINS["lite"]["sha256"], "Core15 remains byte-frozen after actual runtime")
    print(log.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--presentation-manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--native-test", type=Path, metavar="GODOT_EXE")
    parser.add_argument("--actual-core-test", type=Path, metavar="GODOT_EXE")
    parser.add_argument("--probe-output", type=Path)
    parser.add_argument("--native-twin", action="store_true", help="Explicit reviewed native core15 twin for the real-runtime probe ONLY")
    parser.add_argument("--placement-manifest", type=Path, help="Actual-core probe ONLY: read public art bounds to audit flying stations without building art/runtime packs")
    parser.add_argument("--gpu-lighting-probe", action="store_true", help="Actual-core native twin ONLY: isolated OpenGL actor-light A/B captures at recorded native texture dimensions, not Web QHD acceptance")
    parser.add_argument("--details-probe", action="store_true", help="Actual-core native twin ONLY: mount all twelve existing pinned detail chunks and audit live weather identity")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BootstrapTests))
        if not result.wasSuccessful():
            raise SystemExit(1)
    if args.native_test:
        native_test(args.native_test)
    if args.actual_core_test or args.probe_output:
        require(args.actual_core_test and args.probe_output, "Both actual-core-test and a new probe-output required")
        actual_core_test(args.actual_core_test, args.probe_output, args.native_twin, args.presentation_manifest, args.placement_manifest, args.gpu_lighting_probe, args.details_probe)
    elif args.native_twin:
        parser.error("--native-twin is only for --actual-core-test")
    elif args.placement_manifest:
        parser.error("--placement-manifest is only for --actual-core-test")
    elif args.gpu_lighting_probe:
        parser.error("--gpu-lighting-probe is only for --actual-core-test")
    elif args.details_probe:
        parser.error("--details-probe is only for --actual-core-test")
    if args.output:
        result = build(args.output, args.presentation_manifest)
        print(json.dumps({"manifest": str(args.output / "selected-pack-bindings.json"),
            "wrappers": {key: {field: value[field] for field in ("file", "bytes", "sha256", "transferBytes")} for key, value in result["variants"].items()},
            "optionalPack": result["optionalPack"]}, indent=2))
    elif args.presentation_manifest and not args.actual_core_test:
        parser.error("--presentation-manifest requires a new --output or --actual-core-test probe")
    elif not (args.self_test or args.native_test or args.actual_core_test):
        parser.print_help()
