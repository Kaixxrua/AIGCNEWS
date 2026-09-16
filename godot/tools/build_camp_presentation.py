"""Build only an additional public presentation PCK; no export, engine or core edits.

--specs prints the exact 6-hero / 6-pet / ancient-guardian atlas contract. Capture
and retain four ImageGen candidates, then select the best with the main reviewer;
the builder does NOT generate, retouch, resize, crop, recompress or edit any PNG.
It copies selected PNG bytes exactly, including their alpha. Pillow is used only
to inspect frames. Main owns the art request with explicit '八方旅人2' direction.
Visible bounds use alpha >=32, matching optional Sprite3D cutout at 32/255.
The four-pixel frame guard still applies to ALL surviving pixels. Alpha 1..31
quantization noise is ignored for inspection, not erased from the source PNG.

Manifest input: version=1, assets=[{id, role, atlas, frameSize, frameRects, anchor,
worldHeight, shadowRadius, optional frameAnchors}]. atlas is a relative PNG path below the manifest's
directory. frameRects contains 32 integer [x,y,width,height] rectangles, grouped
idle(0..7), walk(8..15), attack(16..23), hit(24..31). Shared atlases are deduped by
SHA256; UV=(x/PNG_width,y/PNG_height,w/PNG_width,h/PNG_height), never guessed size.
frameAnchors optionally supplies 32 per-cell [footX,footY] pixel anchors without
editing PNG bytes. Intentional airborne frames keep the action's ground baseline.
Public id may be a catalogue asset_key such as hero/ranger; it is NOT a path.
Sparse art can explicitly repeat audited frameRects to fill 32 slots, but each
action row still needs >=2 genuinely distinct frames. Never infer an attack from
a walking/flight row. --allow-incomplete permits single-actor DEMO packs while
art is pending; fighting/paused snapshots still require all three actor roles.

Example: python -B godot/tools/build_camp_presentation.py --manifest PUBLIC.json
  --output artifacts/camp-presentation/candidate-01
The manifest/art must be inside this public workspace. Output must be NEW and
under artifacts/camp-presentation. No existing artifact is modified. PCK v2 is
the documented Godot pack format; only raw public GDScript, JSON, PNG and the
explicit reviewed UI font/license assets are included under camp_presentation/.
No project settings, cache or backend. Binary fonts are assets, never scripts.

--self-test runs small negative/pack tests. --native-test also creates a temporary
synthetic TEST-only atlas, mounts the real resulting PCK in a tiny isolated Godot
project, and exercises the renderer. Fixtures are never delivered as artwork.
This is neither a whole-scene build nor a Web/QHD visual acceptance test.

--sharded builds a tiny renderer/catalogue PCK plus one PNG-only actor PCK per
unique source atlas. The version-2 presentation-pack.json pins every shard and
its public assetIds. No pixel changes, no initial full-library download. Legacy
single-PCK Trio builds remain available without this switch.
--reuse-shards PREVIOUS/presentation-pack.json verifies and copies unchanged
actor PCK/br/gzip bytes from an existing library; only the new small runtime is
recompressed. All source PNG/frame audits still run. A changed art pin, mapping
or transport payload is rejected before creating output, never silently rebuilt.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = ROOT / "artifacts/camp-presentation"
SCRIPT = ROOT / "godot/scripts/camp_presentation.gd"
RUNTIME_SCRIPTS = {name: ROOT / "godot/scripts" / name for name in
                   ("camp_presentation.gd", "camp_combat_effects.gd", "camp_boss_hud.gd", "camp_spawn_layout.gd",
                    "camp_travel_path.gd")}
RUNTIME_ASSETS = {
    "fonts/camp_ui_zh.ttf": ROOT / "godot/assets/camp/ui/camp_ui_zh.ttf",
    "fonts/OFL.txt": ROOT / "godot/assets/camp/ui/OFL.txt",
}
NAMESPACE = "camp_presentation/"
KEYS = {"id", "role", "atlas", "frameSize", "frameRects", "anchor", "worldHeight", "shadowRadius"}
ID = re.compile(r"(?=.{1,64}\Z)[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*)?\Z")
MAX_PACK = 16 * 1024 * 1024
MAX_ACTOR_PACK = 9 * 1024 * 1024
MAX_RUNTIME_PACK = 1024 * 1024
MAX_LIBRARY = 128 * 1024 * 1024
MIN_VISIBLE_ALPHA = 32  # Matches camp_presentation.gd ALPHA_CUTOFF exactly.


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def number(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def frame_rects(cell, origin=(0, 0)):
    return [[origin[0] + column * cell[0], origin[1] + row * cell[1], *cell]
            for row in range(4) for column in range(8)]


def visible_frame_info(frame):
    """Read-only cutout inspection, never saved as an image or packed as art.

    Normal alpha scissor retains >= threshold as opaque pixels. Ignore invisible
    RGB/alpha noise and surviving alpha-only changes when testing real action
    variation; neither may turn repeated stills into an animated action row.
    """
    mask = frame.getchannel("A").point(lambda value: 255 if value >= MIN_VISIBLE_ALPHA else 0)
    displayed_rgb = Image.composite(frame.convert("RGB"), Image.new("RGB", frame.size), mask)
    return mask.getbbox(), sha(mask.tobytes() + displayed_rgb.tobytes())


def art_specs():
    result = {"version": 1, "assets": []}
    # Example IDs only: main supplies actual public asset_key values. One native
    # 1536x1024 sheet per actor avoids requiring ImageGen to hit 3072px exactly.
    # Older square-cell or multi-actor atlases remain fully supported by prepare.
    for role, count, height, radius in (
        ("hero", 6, 2.25, 0.32), ("pet", 6, 1.55, 0.38), ("boss", 1, 5.2, 0.95),
    ):
        for index in range(count):
            identifier = f"{role}-{index + 1:02d}" if role != "boss" else "ancient-guardian"
            result["assets"].append({"id": identifier,
                "role": role, "atlas": identifier + ".png", "frameSize": [192, 256],
                "frameRects": frame_rects((192, 256)), "anchor": [96, 232],
                "worldHeight": height, "shadowRadius": radius})
    return result


def prepare(manifest, art_root, allow_incomplete=False, sharded=False):
    require(type(manifest) is dict and set(manifest) == {"version", "assets"}
            and type(manifest["version"]) is int and manifest["version"] == 1, "Public manifest version/keys")
    require(type(manifest["assets"]) is list and 1 <= len(manifest["assets"]) <= 64, "Bounded public actors")
    art_root = Path(art_root).resolve(strict=True)
    catalogue, images, entries, seen = [], {}, {}, set()
    roles = set()
    for actor in manifest["assets"]:
        require(type(actor) is dict and set(actor) in (KEYS, KEYS | {"frameAnchors"}), "Only public art descriptor fields")
        require(type(actor["id"]) is str and ID.fullmatch(actor["id"]) and actor["id"] not in seen, "Unique asset id")
        require(actor["role"] in ("hero", "pet", "boss"), "Public actor role")
        seen.add(actor["id"]); roles.add(actor["role"])
        cell, anchor, rectangles = actor["frameSize"], actor["anchor"], actor["frameRects"]
        require(type(cell) is list and len(cell) == 2 and all(type(v) is int and 32 <= v <= 512 for v in cell), "Frame dimensions")
        require(type(anchor) is list and len(anchor) == 2
                and all(number(v, 4, cell[i] - 4) for i, v in enumerate(anchor)), "Fixed foot anchor")
        if "frameAnchors" in actor:
            anchors = actor["frameAnchors"]
            require(type(anchors) is list and len(anchors) == 32 and all(type(a) is list and len(a) == 2
                    and all(number(v, 4, cell[i] - 4) for i, v in enumerate(a)) for a in anchors), "32 bounded per-frame foot anchors")
        require(number(actor["worldHeight"], 0.4, 6) and number(actor["shadowRadius"], 0.12, 1.2), "World scale bounds")
        require(type(actor["atlas"]) is str and "\\" not in actor["atlas"], "Relative atlas path")
        relative = Path(actor["atlas"])
        require(not relative.is_absolute() and ".." not in relative.parts and ":" not in actor["atlas"], "Local atlas path")
        source = (art_root / relative).resolve(strict=True)
        require(source.is_relative_to(art_root) and source.suffix.lower() == ".png", "Atlas stays inside public art directory")
        if source not in images:
            require(0 < source.stat().st_size <= 8 * 1024 * 1024, "PNG file size bound")
            blob = source.read_bytes()
            image = Image.open(io.BytesIO(blob))
            require(image.format == "PNG" and image.mode == "RGBA" and image.width * image.height <= 16777216,
                    "Bounded native RGBA PNG required; builder never converts images")
            image.load()
            target = NAMESPACE + f"atlases/atlas-{sha(blob)[:16]}.png"
            if target in entries:
                require(entries[target] == blob, "Truncated hash collision")
            entries[target] = blob
            images[source] = (image, target)
        image, target = images[source]
        require(type(rectangles) is list and len(rectangles) == 32, "32 explicit frame rectangles required")
        row_hashes = [set() for _ in range(4)]
        for index, rect in enumerate(rectangles):
            require(type(rect) is list and len(rect) == 4 and all(type(v) is int and 0 <= v <= 8192 for v in rect), "Integer bounded frame rectangle")
            x, y, width, height = rect
            require([width, height] == cell and x + width <= image.width and y + height <= image.height, "Frame registered within native PNG")
            # Inspect, never save/rewrite the selected artwork or a cropped PNG.
            frame = image.crop((x, y, x + width, y + height))
            bounds, displayed_hash = visible_frame_info(frame)
            require(bounds is not None and bounds[0] >= 4 and bounds[1] >= 4
                    and bounds[2] <= width - 4 and bounds[3] <= height - 4,
                    f"{actor['id']} frame {index}: nonempty visible art (alpha >=32) and >=4 cutout-transparent border pixels required")
            row_hashes[index // 8].add(displayed_hash)
        require(all(len(row) >= 2 for row in row_hashes), "Every action needs real frame variation; repeated stills are not animation")
        catalogue.append({**actor, "atlas": "res://" + target})
    require(allow_incomplete or roles == {"hero", "pet", "boss"}, "Complete presentation needs hero, pet and Boss artwork")
    entries[NAMESPACE + "manifest.json"] = (json.dumps({"version": 1, "assets": catalogue}, separators=(",", ":")) + "\n").encode()
    for name, source in RUNTIME_SCRIPTS.items():
        entries[NAMESPACE + name] = source.read_bytes()
    for name, source in RUNTIME_ASSETS.items():
        require(source.is_file() and 0 < source.stat().st_size <= MAX_RUNTIME_PACK,
                f"Required bounded reviewed runtime asset: {name}")
        entries[NAMESPACE + name] = source.read_bytes()
    require(sum(map(len, entries.values())) < (MAX_LIBRARY if sharded else MAX_PACK) - 65536, "Optional PCK/library byte budget")
    return entries, catalogue


def pack_resources(entries):
    """Unencrypted standalone PCK v2, absolute offsets; no removal/override entries.

    Layout matches core/io/file_access_pack.cpp and the repo's read-only
    inspect_web_pack.py. Raw .gd is supported by Godot's normal resource loader;
    no editor import, tokenizer, engine rebuild or export template is needed.
    """
    rows, directory_bytes = [], 4
    for name, blob in sorted(entries.items()):
        require(name.startswith(NAMESPACE) and ".." not in name and "\\" not in name
                and not name.endswith((".remap", ".binary")), "Additional namespace only")
        encoded = name.encode() + b"\0"
        encoded += b"\0" * (-len(encoded) % 4)
        rows.append((encoded, blob))
        directory_bytes += 4 + len(encoded) + 8 + 8 + 16 + 4
    head = struct.pack("<4sIIIIIQ", b"GDPC", 2, 4, 7, 2, 0, 0) + b"\0" * 64
    start = len(head) + directory_bytes
    start += -start % 32
    directory, contents = bytearray(struct.pack("<I", len(rows))), bytearray()
    for encoded, blob in rows:
        contents.extend(b"\0" * (-len(contents) % 32))
        offset = start + len(contents)
        directory.extend(struct.pack("<I", len(encoded)) + encoded + struct.pack("<QQ", offset, len(blob))
                         + hashlib.md5(blob).digest() + struct.pack("<I", 0))
        contents.extend(blob)
    result = head + directory + b"\0" * (start - len(head) - len(directory)) + contents
    require(len(result) <= MAX_PACK, "PCK file size bound")
    return bytes(result)


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def sharded_resources(entries, catalogue):
    """Split descriptors/code/UI assets from PNGs; shared PNG means one shard.

    Return resource maps, not a preloaded combined PCK. This helper is pure and
    also used by isolated tests; no large Godot world is exported or copied.
    """
    runtime = {name: value for name, value in entries.items() if not name.endswith(".png")}
    require(set(runtime) == {NAMESPACE + "manifest.json"}
            | {NAMESPACE + name for name in RUNTIME_SCRIPTS}
            | {NAMESPACE + name for name in RUNTIME_ASSETS},
            "Runtime is only reviewed presentation/skill/HUD/layout/travel code, UI assets and public catalogue")
    library, filenames = [], set()
    for name, blob in sorted(entries.items()):
        if not name.endswith(".png"):
            continue
        ids = [a["id"] for a in catalogue if a["atlas"] == "res://" + name]
        require(ids, "No unused artwork is shipped")
        raw = pack_resources({name: blob})
        require(len(raw) <= MAX_ACTOR_PACK, "Bounded single-atlas actor PCK")
        spec = {"file": f"camp-actor-{sha(raw)[:12]}.pck", "bytes": len(raw), "sha256": sha(raw)}
        require(spec["file"] not in filenames, "Unique content-addressed shard")
        filenames.add(spec["file"])
        library.append(({"pack": spec, "assetIds": ids}, raw))
    require(1 <= len(library) <= 64 and sum(len(raw) for _, raw in library) <= MAX_LIBRARY, "Bounded immutable actor library")
    return runtime, library


def reused_shard_transports(manifest_path, library):
    """Reuse ONLY exact PNG shard transports, never old renderer or world PCKs.

    New deterministic descriptors/raw shards are the authority. Never use a
    path supplied by the old manifest; validate it against those descriptors.
    The previous renderer may intentionally differ from current source.
    """
    import brotli
    manifest_path = Path(manifest_path).resolve(strict=True)
    require(manifest_path.stat().st_size <= MAX_RUNTIME_PACK, "Bounded reuse manifest")
    previous = json.loads(manifest_path.read_bytes())
    require(type(previous) is dict and type(previous.get("version")) is int and previous["version"] == 2
            and previous.get("actorShards") == [descriptor for descriptor, _ in library], "Reuse requires exact actor shard pins and mapping")
    transfers = previous.get("shardTransferBytes")
    require(type(transfers) is dict and set(transfers) == {d["pack"]["file"] for d, _ in library}, "Exact reuse transfer coverage")
    result = {}
    for descriptor, raw in library:
        name = descriptor["pack"]["file"]  # Generated from current exact PNG bytes.
        payloads = []
        for suffix in ("", ".br", ".gz"):
            path = (manifest_path.parent / (name + suffix)).resolve(strict=True)
            require(path.is_relative_to(manifest_path.parent) and path.is_file()
                    and 0 < path.stat().st_size <= MAX_ACTOR_PACK + 65536, "Bounded local reused shard transport")
            payloads.append(path.read_bytes())
        original, compressed, zipped = payloads
        require(original == raw, "Reused shard must match current exact PNG PCK bytes")
        require(transfers[name] == {"br": len(compressed), "gzip": len(zipped)}, "Exact reused transport lengths")
        try:
            decoded_br, decoded_gz = brotli.decompress(compressed), gzip.decompress(zipped)
        except (brotli.error, OSError, EOFError) as error:
            raise ValueError("Invalid reused shard compression") from error
        require(decoded_br == raw and decoded_gz == raw, "Reused compression must decode to exact pinned shard")
        result[name] = (compressed, zipped)
    return result


def build(manifest_path, output, allow_incomplete=False, sharded=False, reuse_shards=None):
    manifest_path, output = Path(manifest_path).resolve(strict=True), Path(output).resolve()
    require(manifest_path.is_relative_to(ROOT), "Manifest must be in public workspace")
    require(output.is_relative_to(OUT_ROOT) and output != OUT_ROOT and not output.exists(), "New camp-presentation output directory only")
    if reuse_shards is not None:
        reuse_shards = Path(reuse_shards).resolve(strict=True)
        require(sharded and reuse_shards.is_relative_to(OUT_ROOT), "Reuse only an existing public sharded artifact")
    entries, catalogue = prepare(json.loads(manifest_path.read_bytes()), manifest_path.parent, allow_incomplete, sharded)
    runtime, library = sharded_resources(entries, catalogue) if sharded else (entries, [])
    reused = reused_shard_transports(reuse_shards, library) if reuse_shards is not None else {}
    raw = pack_resources(runtime)
    require(not sharded or len(raw) <= MAX_RUNTIME_PACK, "Small renderer/catalogue runtime PCK")
    import brotli
    brotli_bytes = brotli.compress(raw, quality=6)
    digest = sha(raw)
    spec = {"file": f"camp-presentation-{digest[:12]}.pck", "bytes": len(raw), "sha256": digest}
    # Validate the full library before creating a new output. No old artifact
    # or PNG is changed; individual shards are compressed below for transport.
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / spec["file"], raw)
    write_new(output / (spec["file"] + ".br"), brotli_bytes)
    write_new(output / (spec["file"] + ".gz"), gzip.compress(raw, mtime=0))
    manifest = {"version": 2 if sharded else 1, "pack": spec, "entry": "res://camp_presentation/camp_presentation.gd",
        "catalogue": "res://camp_presentation/manifest.json",
        "assetIds": {role: [a["id"] for a in catalogue if a["role"] == role] for role in ("hero", "pet", "boss")},
        "transferBytes": {"br": len(brotli_bytes), "gzip": (output / (spec["file"] + ".gz")).stat().st_size},
        "sourcePngBytesUnchanged": True, "coreReadyRequired": True,
        "completeRoles": {a["role"] for a in catalogue} == {"hero", "pet", "boss"},
        "entries": {name: {"bytes": len(blob), "sha256": sha(blob)} for name, blob in runtime.items()}}
    if sharded:
        manifest["actorShards"] = [descriptor for descriptor, _ in library]
        manifest["shardTransferBytes"] = {}
        for descriptor, blob in library:
            shard = descriptor["pack"]
            compressed, zipped = reused[shard["file"]] if reused else (brotli.compress(blob, quality=6), gzip.compress(blob, mtime=0))
            write_new(output / shard["file"], blob)
            write_new(output / (shard["file"] + ".br"), compressed)
            write_new(output / (shard["file"] + ".gz"), zipped)
            manifest["shardTransferBytes"][shard["file"]] = {"br": len(compressed), "gzip": len(zipped)}
        manifest["loadingPolicy"] = "After real core and runtime readiness: current visible hero/pet/boss only; swaps add missing cached shards, never reload world"
        manifest["libraryBytes"] = sum(item["pack"]["bytes"] for item in manifest["actorShards"])
    write_new(output / "presentation-pack.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest


def test_fixture(directory, seed=0, *, cutout_noise=False, intrusion=None, body_alpha=255, variation=True):
    """Synthetic TEST data, never eligible as delivered art. No existing PNG edits."""
    cell = (32, 32)
    image = Image.new("RGBA", (256, 128))
    for row in range(4):
        for col in range(8):
            for y in range(6, 27):
                for x in range(8, 24):
                    image.putpixel((col * 32 + x, row * 32 + y),
                        (80 + (15 * col if variation else 0) + seed, 70 + row * 40, 70, body_alpha))
            if cutout_noise:
                # New synthetic fixtures only, NEVER edits to selected artwork.
                # Strict nonzero bbox reaches all four borders, but its visible
                # >=32 bbox retains the exact four-pixel minimum guard.
                for x, y, alpha in ((1, 0, 31), (0, 31, 1), (31, 16, (row * 8 + col) % 31 + 1), (4, 4, 32)):
                    image.putpixel((col * 32 + x, row * 32 + y), (70, 80, 90, alpha))
    if intrusion is not None:
        x, y, alpha = intrusion
        image.putpixel((x, y), (255, 230, 100, alpha))
    stream = io.BytesIO(); image.save(stream, format="PNG")
    write_new(directory / "test-only.png", stream.getvalue())
    return {"version": 1, "assets": [{"id": role + "-test", "role": role,
        "atlas": "test-only.png", "frameSize": list(cell), "frameRects": frame_rects(cell),
        "anchor": [16, 28], "worldHeight": 1.8 if role != "boss" else 3.8,
        "shadowRadius": 0.32 if role != "boss" else 0.95} for role in ("hero", "pet", "boss")]}


def test_portrait_fixture(directory):
    """New TEST-only 4x8 portrait atlas; never read or edit any supplied artwork.

    Distinct physical-cell colours let native tests detect guessed UV positions,
    including reordered explicit rectangles and eight-slot logical action rows.
    """
    image = Image.new("RGBA", (1024, 1536))
    rectangles = []
    for index in range(32):
        x, y = (index % 4) * 256, (index // 4) * 192
        rectangles.append([x, y, 256, 192])
        image.paste((40 + index * 6, 80, 120, 254), (x + 4, y + 4, x + 252, y + 188))
        image.putpixel((x, y), (20, 30, 40, 31))
    stream = io.BytesIO(); image.save(stream, format="PNG")
    write_new(directory / "portrait-test-only.png", stream.getvalue())
    return {"id": "pet_dragon", "role": "pet", "atlas": "portrait-test-only.png",
        "frameSize": [256, 192], "frameRects": rectangles, "anchor": [128, 180],
        "frameAnchors": [[124 + index % 3, 180 - index % 4] for index in range(32)],
        "worldHeight": 2.2, "shadowRadius": 0.32}


def test_shard_fixture(directory):
    """Four distinct tiny TEST-only PNGs, including a swappable second hero."""
    result = {"version": 1, "assets": []}
    for index, (role, key) in enumerate((("hero", "hero/first"), ("hero", "hero/second"), ("pet", "pet/first"), ("boss", "boss/first"))):
        folder = Path(directory) / f"fixture-{index}"
        fixture = test_fixture(folder, seed=index * 10)
        actor = next(a for a in fixture["assets"] if a["role"] == role)
        result["assets"].append({**actor, "id": key, "atlas": f"fixture-{index}/test-only.png"})
    return result


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="camp-presentation-test-")
        self.directory = Path(self.temp.name).resolve()
        self.manifest = test_fixture(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_art_spec(self):
        spec = art_specs()["assets"]
        self.assertEqual(len(spec), 13)
        self.assertEqual([sum(a["role"] == role for a in spec) for role in ("hero", "pet", "boss")], [6, 6, 1])
        self.assertEqual(spec[5]["frameRects"][-1], [1344, 768, 192, 256])
        self.assertTrue(all(a["frameSize"] == [192, 256] for a in spec))

    def test_generic_ids_anchors_sparse_frames_and_explicit_demo(self):
        actor = self.manifest["assets"][0]
        actor["id"] = "hero/ranger"
        actor["frameAnchors"] = [[16, 28 - index % 2] for index in range(32)]
        actor["frameRects"][1] = actor["frameRects"][0].copy()
        _, actors = prepare(self.manifest, self.directory)
        self.assertEqual(actors[0]["frameAnchors"], actor["frameAnchors"])
        self.manifest["assets"] = [actor]
        _, actors = prepare(self.manifest, self.directory, allow_incomplete=True)
        self.assertEqual(len(actors), 1)
        for bad in ("../ranger", "/hero/ranger", "hero/ranger/a", "hero//ranger", "hero/..", "hero/", "h" * 65):
            actor["id"] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "asset id"):
                prepare(self.manifest, self.directory, allow_incomplete=True)
        actor["id"] = "hero/ranger"
        actor["frameAnchors"][0] = [True, 28]
        with self.assertRaisesRegex(ValueError, "per-frame"):
            prepare(self.manifest, self.directory, allow_incomplete=True)

    def test_namespace_source_integrity_and_deduplication(self):
        from inspect_web_pack import read_pack
        before = (self.directory / "test-only.png").read_bytes()
        entries, actors = prepare(self.manifest, self.directory)
        self.assertEqual(len([name for name in entries if name.endswith(".png")]), 1)
        self.assertEqual(entries[actors[0]["atlas"].removeprefix("res://")], before)
        path = self.directory / "fixture.pck"
        write_new(path, pack_resources(entries))
        rows = read_pack(path, verify=True)["entries"]
        self.assertEqual({r["path"] for r in rows}, set(entries))
        self.assertTrue(all(row["path"].startswith(NAMESPACE) for row in rows))
        self.assertEqual((self.directory / "test-only.png").read_bytes(), before)

    def test_portrait_256x192_frames_are_explicit_and_source_bytes_unchanged(self):
        actor = test_portrait_fixture(self.directory)
        self.manifest["assets"].append(actor)
        before = (self.directory / actor["atlas"]).read_bytes()
        self.assertEqual(Image.open(io.BytesIO(before)).size, (1024, 1536))
        self.assertEqual(actor["frameRects"][4], [0, 192, 256, 192])
        self.assertEqual(actor["frameRects"][-1], [768, 1344, 256, 192])
        original = [rect.copy() for rect in actor["frameRects"]]
        for order in (list(range(32)), [(index * 7 + 3) % 32 for index in range(32)]):
            actor["frameRects"] = [original[index] for index in order]
            entries, catalogue = prepare(self.manifest, self.directory)
            self.assertEqual(catalogue[-1]["frameRects"], actor["frameRects"])
            self.assertEqual(catalogue[-1]["frameAnchors"], actor["frameAnchors"])
            self.assertEqual(entries[catalogue[-1]["atlas"].removeprefix("res://")], before)
        self.assertEqual((self.directory / actor["atlas"]).read_bytes(), before)

    def test_cutout_ignores_only_low_alpha_noise_and_keeps_exact_source_bytes(self):
        directory = self.directory / "cutout"
        manifest = test_fixture(directory, cutout_noise=True, body_alpha=254)
        before = (directory / "test-only.png").read_bytes()
        image = Image.open(io.BytesIO(before))
        frame = image.crop((0, 0, 32, 32))
        self.assertEqual(frame.getchannel("A").getbbox(), (0, 0, 32, 32))
        self.assertEqual(visible_frame_info(frame)[0], (4, 4, 24, 27))
        self.assertEqual(frame.getchannel("A").getextrema()[1], 254)
        entries, catalogue = prepare(manifest, directory, sharded=True)
        self.assertEqual(entries[catalogue[0]["atlas"].removeprefix("res://")], before)
        _, library = sharded_resources(entries, catalogue)
        self.assertIn(before, library[0][1])
        self.assertEqual((directory / "test-only.png").read_bytes(), before)
        self.assertIn("const ALPHA_CUTOFF := 32.0 / 255.0", SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("CONTENT_SCALE_ASPECT_EXPAND", SCRIPT.read_text(encoding="utf-8"))

    def test_real_visible_crossings_and_four_pixel_guard_are_not_relaxed(self):
        for alpha in (31, 32, 254, 255):
            for x, y in ((0, 15), (3, 15), (28, 15), (15, 0), (15, 3), (15, 28)):
                directory = self.directory / f"intrusion-{alpha}-{x}-{y}"
                manifest = test_fixture(directory, intrusion=(x, y, alpha))
                with self.subTest(alpha=alpha, x=x, y=y):
                    if alpha < MIN_VISIBLE_ALPHA:
                        prepare(manifest, directory)
                    else:
                        with self.assertRaisesRegex(ValueError, "alpha >=32.*>=4"):
                            prepare(manifest, directory)

    def test_invisible_frame_or_noise_only_variation_never_becomes_animation(self):
        directory = self.directory / "invisible"
        manifest = test_fixture(directory, body_alpha=31)
        with self.assertRaisesRegex(ValueError, "nonempty visible art"):
            prepare(manifest, directory)
        directory = self.directory / "noise-only-variation"
        manifest = test_fixture(directory, cutout_noise=True, body_alpha=254, variation=False)
        with self.assertRaisesRegex(ValueError, "real frame variation"):
            prepare(manifest, directory)

    def test_rejects_private_fields_paths_and_missing_roles(self):
        for change in ({"token": "private"}, {"atlas": "../private.png"}, {"atlas": "https://host/x.png"},
                       {"role": "account"}, {"worldHeight": float("nan")}, {"anchor": [True, 28]},
                       {"frameRects": [[0, 0, 32, 32]] * 32}):
            with self.subTest(change=change):
                original = self.manifest["assets"][0]
                self.manifest["assets"][0] = {**original, **change}
                with self.assertRaises((ValueError, FileNotFoundError)):
                    prepare(self.manifest, self.directory)
                self.manifest["assets"][0] = original
        self.manifest["assets"].pop()
        with self.assertRaisesRegex(ValueError, "Complete presentation"):
            prepare(self.manifest, self.directory)

    def test_rejects_bad_frame_bounds_and_foreign_pack_entries(self):
        self.manifest["assets"][0]["frameRects"][0][0] = 1000
        with self.assertRaisesRegex(ValueError, "within native PNG"):
            prepare(self.manifest, self.directory)
        with self.assertRaises(ValueError):
            pack_resources({"scripts/meadow_scene.gd": b"bad"})

    def test_refuses_existing_or_unscoped_output(self):
        manifest_path = self.directory / "public.json"
        write_new(manifest_path, json.dumps(self.manifest).encode())
        with self.assertRaisesRegex(ValueError, "public workspace"):
            build(manifest_path, OUT_ROOT / "unused-test")
        with self.assertRaises(FileExistsError):
            write_new(manifest_path, b"do not overwrite")
        self.assertEqual(json.loads(manifest_path.read_bytes()), self.manifest)

    def test_png_only_shards_and_shared_atlas_deduplication(self):
        entries, catalogue = prepare(self.manifest, self.directory, sharded=True)
        runtime, library = sharded_resources(entries, catalogue)
        self.assertEqual(len(library), 1)  # Three roles share one fixture PNG.
        self.assertEqual(library[0][0]["assetIds"], [a["id"] for a in catalogue])
        self.assertEqual(set(runtime), {NAMESPACE + "manifest.json"}
            | {NAMESPACE + name for name in RUNTIME_SCRIPTS}
            | {NAMESPACE + name for name in RUNTIME_ASSETS})
        self.assertTrue(all(not name.endswith(".png") for name in runtime))
        self.assertLess(len(pack_resources(runtime)), MAX_RUNTIME_PACK)
        manifest = test_shard_fixture(self.directory)
        entries, catalogue = prepare(manifest, self.directory, sharded=True)
        runtime, library = sharded_resources(entries, catalogue)
        self.assertEqual(len(library), 4)
        from inspect_web_pack import read_pack
        for descriptor, blob in library:
            path = self.directory / descriptor["pack"]["file"]
            write_new(path, blob)
            rows = read_pack(path, verify=True)["entries"]
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["path"].endswith(".png"))
            self.assertEqual(sha(blob), descriptor["pack"]["sha256"])

    def test_ui_font_and_license_are_exact_runtime_assets_not_scripts_or_shards(self):
        self.assertEqual(RUNTIME_ASSETS, {
            "fonts/camp_ui_zh.ttf": ROOT / "godot/assets/camp/ui/camp_ui_zh.ttf",
            "fonts/OFL.txt": ROOT / "godot/assets/camp/ui/OFL.txt",
        })
        self.assertEqual(set(RUNTIME_SCRIPTS), {"camp_presentation.gd", "camp_combat_effects.gd",
            "camp_boss_hud.gd", "camp_spawn_layout.gd", "camp_travel_path.gd"})
        entries, catalogue = prepare(self.manifest, self.directory, sharded=True)
        runtime, library = sharded_resources(entries, catalogue)
        original_shards = [(descriptor.copy(), blob) for descriptor, blob in library]
        for name, source in RUNTIME_ASSETS.items():
            self.assertEqual(runtime[NAMESPACE + name], source.read_bytes())
            self.assertNotIn(name, RUNTIME_SCRIPTS)
            changed = {**entries, NAMESPACE + name: b"test-only changed runtime asset"}
            self.assertEqual(sharded_resources(changed, catalogue)[1], original_shards)

    def test_fifth_travel_script_is_exact_required_runtime_only_source(self):
        name = NAMESPACE + "camp_travel_path.gd"
        original = RUNTIME_SCRIPTS["camp_travel_path.gd"].read_bytes()
        entries, catalogue = prepare(self.manifest, self.directory, sharded=True)
        runtime, library = sharded_resources(entries, catalogue)
        self.assertEqual(runtime[name], original)
        self.assertEqual(len(RUNTIME_SCRIPTS), 5)
        changed = {**entries, name: b"test-only changed travel source"}
        self.assertEqual(sharded_resources(changed, catalogue)[1], library)
        with self.assertRaisesRegex(ValueError, "Runtime is only reviewed"):
            sharded_resources({key: value for key, value in entries.items() if key != name}, catalogue)
        self.assertEqual(RUNTIME_SCRIPTS["camp_travel_path.gd"].read_bytes(), original)

    def test_missing_or_empty_ui_assets_fail_closed(self):
        empty = self.directory / "empty-test-asset"
        write_new(empty, b"")
        for name in RUNTIME_ASSETS:
            for source in (self.directory / "missing-test-asset", empty):
                with self.subTest(name=name, source=source.name), \
                        patch.dict(RUNTIME_ASSETS, {name: source}), \
                        self.assertRaisesRegex(ValueError, "Required bounded reviewed runtime asset"):
                    prepare(self.manifest, self.directory, sharded=True)

    def test_runtime_rejects_extra_or_missing_ui_entries(self):
        entries, catalogue = prepare(self.manifest, self.directory, sharded=True)
        for name in RUNTIME_ASSETS:
            missing = {key: blob for key, blob in entries.items() if key != NAMESPACE + name}
            with self.subTest(missing=name), self.assertRaisesRegex(ValueError, "Runtime is only reviewed"):
                sharded_resources(missing, catalogue)
        with self.assertRaisesRegex(ValueError, "Runtime is only reviewed"):
            sharded_resources({**entries, NAMESPACE + "fonts/unreviewed.ttf": b"font"}, catalogue)

    def reuse_fixture(self, name, library, *, change=None, corrupt=None):
        import brotli
        directory = self.directory / name
        previous = {"version": 2, "actorShards": [d for d, _ in library], "shardTransferBytes": {}}
        # Deliberately different compression settings: reuse must copy bytes,
        # not secretly recompress actor assets while rebuilding a renderer.
        for descriptor, raw in library:
            filename = descriptor["pack"]["file"]
            compressed, zipped = brotli.compress(raw, quality=1), gzip.compress(raw, compresslevel=1, mtime=1)
            previous["shardTransferBytes"][filename] = {"br": len(compressed), "gzip": len(zipped)}
            for suffix, payload in (("", raw), (".br", compressed), (".gz", zipped)):
                if suffix == corrupt:
                    payload = bytes([payload[0] ^ 255]) + payload[1:]
                write_new(directory / (filename + suffix), payload)
        if change:
            change(previous)
        write_new(directory / "presentation-pack.json", json.dumps(previous).encode())
        return directory / "presentation-pack.json"

    def test_reuse_keeps_every_actor_transport_byte_without_old_renderer_binding(self):
        entries, catalogue = prepare(test_shard_fixture(self.directory), self.directory, sharded=True)
        _, library = sharded_resources(entries, catalogue)
        source = self.reuse_fixture("old-library", library)
        reused = reused_shard_transports(source, library)
        self.assertEqual(len(reused), 4)
        for descriptor, _ in library:
            name = descriptor["pack"]["file"]
            self.assertEqual(reused[name], ((source.parent / (name + ".br")).read_bytes(),
                                           (source.parent / (name + ".gz")).read_bytes()))
        self.assertFalse((source.parent / "camp_presentation.gd").exists())

    def test_reuse_rejects_changed_pins_mapping_and_transfer_lengths(self):
        entries, catalogue = prepare(self.manifest, self.directory, sharded=True)
        _, library = sharded_resources(entries, catalogue)
        name = library[0][0]["pack"]["file"]
        changes = [lambda p: p.update(version=True), lambda p: p.update(actorShards=[]),
            lambda p: p["actorShards"][0]["pack"].update(file="../world.pck"),
            lambda p: p["actorShards"][0].update(assetIds=["hero-other"]),
            lambda p: p["actorShards"][0]["pack"].update(sha256="0" * 64),
            lambda p: p["shardTransferBytes"].update(foreign={"br": 1, "gzip": 1}),
            lambda p: p["shardTransferBytes"][name].update(br=1)]
        for index, change in enumerate(changes):
            # Deep-copy test descriptors so corrupting the old manifest cannot
            # also change the newly derived pins used as validation authority.
            copied = [(json.loads(json.dumps(d)), blob) for d, blob in library]
            source = self.reuse_fixture(f"invalid-pin-{index}", copied, change=change)
            with self.subTest(index=index), self.assertRaises(ValueError):
                reused_shard_transports(source, library)

    def test_reuse_rejects_tampered_raw_and_compressed_bytes(self):
        entries, catalogue = prepare(self.manifest, self.directory, sharded=True)
        _, library = sharded_resources(entries, catalogue)
        for index, suffix in enumerate(("", ".br", ".gz")):
            source = self.reuse_fixture(f"invalid-transport-{index}", library, corrupt=suffix)
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                reused_shard_transports(source, library)


def native_test(engine):
    engine = Path(engine).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="camp-presentation-native-") as temporary:
        stage = Path(temporary).resolve()
        manifest = test_fixture(stage, cutout_noise=True, body_alpha=254)
        manifest["assets"].append(test_portrait_fixture(stage))
        entries, _ = prepare(manifest, stage)
        write_new(stage / "fixture.pck", pack_resources(entries))
        write_new(stage / "project.godot", b'config_version=5\n[application]\nconfig/name="CampPresentationTestOnly"\n[debug]\nfile_logging/enable_file_logging=false\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
        # With --script/--headless, there is no editor/import/export. The selected
        # existing portable runtime is read only; its user paths are isolated.
        env = dict(os.environ)
        for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
            target = stage / key.lower(); target.mkdir()
            env[key] = str(target)
        command = [str(engine), "--headless", "--path", str(stage), "--log-file", str(stage / "native.log"),
            "--script", str(ROOT / "godot/tools/test_camp_presentation.gd"), "--", str(stage / "fixture.pck")]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=45, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log = result.stdout + result.stderr
        require(result.returncode == 0 and "CAMP_PRESENTATION_TEST: PASS" in log
                and "SCRIPT ERROR" not in log and "ERROR:" not in log, log)
        print(log.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--specs", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true", help="Explicit single-role demo pack; no missing-actor substitutes")
    parser.add_argument("--sharded", action="store_true", help="Tiny runtime plus on-demand pinned PNG-only actor shards")
    parser.add_argument("--reuse-shards", type=Path, metavar="PREVIOUS_MANIFEST", help="Verify and reuse exact existing actor PCK/br/gzip bytes; rebuild only runtime")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--native-test", type=Path, metavar="GODOT_EXE")
    arguments = parser.parse_args()
    if arguments.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PresentationTests))
        if not result.wasSuccessful():
            raise SystemExit(1)
    if arguments.native_test:
        native_test(arguments.native_test)
    if arguments.specs:
        print(json.dumps(art_specs(), indent=2))
    if arguments.manifest or arguments.output or arguments.reuse_shards:
        require(arguments.manifest and arguments.output, "Both manifest and output required")
        print(json.dumps(build(arguments.manifest, arguments.output, arguments.allow_incomplete, arguments.sharded, arguments.reuse_shards), indent=2))
    elif not (arguments.self_test or arguments.native_test or arguments.specs):
        parser.print_help()
