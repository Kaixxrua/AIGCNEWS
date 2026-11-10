"""Strict, bounded GIF-prefix preview; the decoder runs in a killable worker.

Only complete image blocks with an exact LZW raster and end code reach Pillow.
Pillow alone accepts some missing-end-code rasters, even in strict mode. An
incomplete trailing block is usable only for an explicitly partial HTTP range.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import struct
import subprocess
import sys
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFile

GIF_BYTES = 8 * 1024 * 1024
GIF_PIXELS = 16_000_000
GIF_TOTAL_PIXELS = 64_000_000
GIF_FRAMES = 120
GIF_SECONDS = 3.0
_OUTPUT_BYTES = 2 * 1024 * 1024


class GifPreviewError(ValueError):
    pass


class _Incomplete(ValueError):
    pass


@dataclass(frozen=True)
class GifFrame:
    end: int
    width: int
    height: int


def _invalid() -> None:
    raise GifPreviewError("invalid_image")


def _lzw(data: bytes, minimum: int, expected: int, colors: int, transparent: int | None = None) -> None:
    """Validate without expanding the raster or retaining unbounded strings."""
    if not 2 <= minimum <= 8:
        _invalid()
    clear = 1 << minimum
    end = clear + 1
    lengths = [1] * clear + [0] * (4096 - clear)
    heads = list(range(clear)) + [0] * (4096 - clear)
    size, available, previous, bit, pixels = minimum + 1, end + 1, None, 0, 0
    first = True
    while bit + size <= len(data) * 8:
        offset, shift = divmod(bit, 8)
        code = (int.from_bytes(data[offset:offset + 3], "little") >> shift) & ((1 << size) - 1)
        bit += size
        if first and code != clear:
            _invalid()
        first = False
        if code == clear:
            size, available, previous = minimum + 1, end + 1, None
            continue
        if code == end:
            if pixels != expected or len(data) * 8 - bit >= 8:
                _invalid()
            return
        if previous is None:
            if code >= clear:
                _invalid()
            length, head = 1, code
        elif code < available:
            length, head = lengths[code], heads[code]
            if length <= 0:
                _invalid()
        elif code == available and available < 4096:
            length, head = lengths[previous] + 1, heads[previous]
        else:
            _invalid()
        # Dictionary strings contain only previously validated strings and
        # their first symbols, so checking literal/head indices is sufficient.
        # Transparency does not perform an RGB lookup. Optimized encoders
        # may reserve a transparent symbol just beyond the actual palette.
        # Only this frame's explicit GCE symbol receives that exception.
        if head >= colors and head != transparent:
            _invalid()
        pixels += length
        if pixels > expected:
            _invalid()
        if previous is not None and available < 4096:
            lengths[available], heads[available] = lengths[previous] + 1, heads[previous]
            available += 1
            if available == 1 << size and size < 12:
                size += 1
        previous = code
    _invalid()  # EOI is mandatory even if Pillow already filled the raster.


def _frames(payload: bytes, *, partial: bool) -> tuple[int, int, list[GifFrame]]:
    if not payload or len(payload) > GIF_BYTES:
        raise GifPreviewError("image_too_large" if payload else "invalid_image")
    if len(payload) < 13 or payload[:6] not in (b"GIF87a", b"GIF89a"):
        _invalid()
    width, height = struct.unpack_from("<HH", payload, 6)
    if min(width, height) < 160 or width * height > GIF_PIXELS:
        _invalid()
    position = 13

    def take(count: int) -> bytes:
        nonlocal position
        if position + count > len(payload):
            raise _Incomplete
        value = payload[position:position + count]
        position += count
        return value

    def blocks() -> bytes:
        data = bytearray()
        while True:
            count = take(1)[0]
            if not count:
                return bytes(data)
            data.extend(take(count))

    frames: list[GifFrame] = []
    colors = 2 ** ((payload[10] & 7) + 1) if payload[10] & 128 else 0
    transparent: int | None = None
    control = False
    try:
        take(colors * 3)
        if colors and payload[11] >= colors:
            _invalid()
        while len(frames) < GIF_FRAMES and (len(frames) + 1) * width * height <= GIF_TOTAL_PIXELS:
            marker = take(1)[0]
            if marker == 0x3B:
                if position != len(payload) or control:
                    _invalid()
                break
            if marker == 0x21:
                label = take(1)[0]
                if label == 0xF9:
                    if control or take(1)[0] != 4:
                        _invalid()
                    value = take(4)
                    if take(1)[0] != 0 or value[0] & 0xE0 or ((value[0] >> 2) & 7) > 3:
                        _invalid()
                    transparent = value[3] if value[0] & 1 else None
                    control = True
                elif label == 0xFF:
                    if take(1)[0] != 11:
                        _invalid()
                    take(11)
                    blocks()
                elif label == 0xFE:
                    blocks()
                else:
                    # Plain-text rendering and unknown extension semantics
                    # cannot be reproduced safely by the raster compositor.
                    _invalid()
                continue
            if marker != 0x2C:
                _invalid()
            left, top, frame_width, frame_height, flags = struct.unpack("<HHHHB", take(9))
            if (not frame_width or not frame_height or left + frame_width > width
                    or top + frame_height > height or flags & 0x18):
                _invalid()
            frame_colors = 2 ** ((flags & 7) + 1) if flags & 128 else colors
            if flags & 128:
                take(frame_colors * 3)
            if not frame_colors:
                _invalid()
            minimum = take(1)[0]
            _lzw(blocks(), minimum, frame_width * frame_height, frame_colors, transparent)
            frames.append(GifFrame(position, frame_width, frame_height))
            transparent, control = None, False
    except _Incomplete:
        if not partial or not frames:
            _invalid()
    if not frames:
        _invalid()
    return width, height, frames


def _decode(payload: bytes, *, partial: bool) -> tuple[bytes, dict]:
    """Worker-only: bounded sequential seek preserves deltas and disposal."""
    width, height, frames = _frames(payload, partial=partial)
    prefix = payload[:frames[-1].end] + b";"
    best, selected, best_score = None, -1, -1.0
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(prefix)) as source:
            for index in range(len(frames)):
                source.seek(index)
                source.load()
                raster = source.convert("RGB")
                raster.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                sample = raster.copy()
                sample.thumbnail((160, 160), Image.Resampling.BILINEAR)
                low, high = sample.convert("L").getextrema()
                score = sample.entropy()
                # This is only a blank-frame rejection/selection heuristic.
                # Identity, logos and diagrams still require the existing
                # vision review; a detailed frame is not proof of gameplay.
                if high <= 8 or high - low <= 3:
                    continue
                if score >= best_score:
                    clean = Image.new("RGB", raster.size)
                    clean.paste(raster)
                    output = BytesIO()
                    clean.save(output, format="JPEG", quality=88)
                    best, selected, best_score = output.getvalue(), index, score
    if best is None or len(best) > _OUTPUT_BYTES:
        _invalid()
    return best, {"type": "gif_frame", "frameIndex": selected, "frameEnd": frames[selected].end,
                  "framesValidated": len(frames), "validatedBytes": frames[-1].end,
                  "decodedPixels": width * height * len(frames), "canvasWidth": width, "canvasHeight": height,
                  "downloadedBytes": len(payload), "sourcePrefixSha256": hashlib.sha256(payload).hexdigest(),
                  "partial": partial, "width": clean.width, "height": clean.height}


def _start_worker():
    # Isolated Python, no inherited service credentials/proxy, no URL input.
    try:
        return subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--worker"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env={"LANG": "C.UTF-8"})
    except OSError as exc:
        raise GifPreviewError("image_preview_unavailable") from exc


def _input(payload: bytes, partial: bool) -> bytes:
    if len(payload) > GIF_BYTES:
        raise GifPreviewError("image_too_large")
    return bytes([bool(partial)]) + payload


def _result(output: bytes, returncode: int) -> tuple[bytes, dict]:
    if returncode != 0 or len(output) > _OUTPUT_BYTES + 2048:
        raise GifPreviewError("invalid_image")
    try:
        header, jpeg = output.split(b"\n", 1)
        evidence = json.loads(header)
        if (not isinstance(evidence, dict) or evidence.get("type") != "gif_frame"
                or not jpeg.startswith(b"\xff\xd8\xff") or len(header) > 2048 or len(jpeg) > _OUTPUT_BYTES):
            raise ValueError
        return jpeg, evidence
    except (ValueError, TypeError) as exc:
        raise GifPreviewError("invalid_image") from exc


def _stop(process) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=2)
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            stream.close()


def preview_gif_sync(payload: bytes, *, partial: bool = False) -> tuple[bytes, dict]:
    data = _input(payload, partial)
    process = _start_worker()
    try:
        output, _ = process.communicate(data, timeout=GIF_SECONDS)
        return _result(output, process.returncode)
    except subprocess.TimeoutExpired as exc:
        raise GifPreviewError("image_preview_timeout") from exc
    finally:
        _stop(process)


async def preview_gif(payload: bytes, *, partial: bool = False) -> tuple[bytes, dict]:
    """Nonblocking bounded pipes; cancellation kills and reaps this worker."""
    data = _input(payload, partial)
    process = _start_worker()
    try:
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        output = bytearray()
        sent, eof = 0, False
        deadline = asyncio.get_running_loop().time() + GIF_SECONDS
        while True:
            if not process.stdin.closed:
                try:
                    sent += os.write(process.stdin.fileno(), data[sent:sent + 65536])
                except BlockingIOError:
                    pass
                except BrokenPipeError:
                    process.stdin.close()
                if sent == len(data) and not process.stdin.closed:
                    process.stdin.close()
            try:
                chunk = os.read(process.stdout.fileno(), 65536)
            except BlockingIOError:
                chunk = None
            if chunk:
                output.extend(chunk)
                if len(output) > _OUTPUT_BYTES + 2048:
                    _invalid()
            elif chunk == b"":
                eof = True
            if process.poll() is not None and eof:
                return _result(bytes(output), process.returncode)
            if asyncio.get_running_loop().time() >= deadline:
                raise GifPreviewError("image_preview_timeout")
            await asyncio.sleep(0.005)
    finally:
        _stop(process)


def _main() -> None:
    # The wall deadline is enforced by the parent; CPU/address-space limits
    # are defense in depth for malicious dictionaries and native decoders.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    data = sys.stdin.buffer.read(GIF_BYTES + 2)
    if not data or data[0] not in (0, 1):
        _invalid()
    jpeg, evidence = _decode(data[1:], partial=bool(data[0]))
    sys.stdout.buffer.write(json.dumps(evidence, separators=(",", ":")).encode() + b"\n" + jpeg)


if __name__ == "__main__":
    try:
        _main()
    except Exception:
        sys.exit(1)
