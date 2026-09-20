"""Decode bounded raster uploads into metadata-free, static profile images."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000


def normalize_avatar(payload: bytes) -> bytes:
    if not payload or len(payload) > MAX_AVATAR_BYTES:
        raise ValueError("头像文件不能为空，且不能超过 2 MB")
    try:
        with Image.open(BytesIO(payload)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("请选择 PNG、JPEG 或 WebP 图片")
            if source.width * source.height > MAX_AVATAR_PIXELS:
                raise ValueError("头像分辨率过大，请缩小后上传")
            source.load()
            oriented = ImageOps.exif_transpose(source)
            avatar = ImageOps.fit(oriented.convert("RGBA"), (256, 256), method=Image.Resampling.LANCZOS)
            # Copy pixels to strip EXIF, text chunks, ICC profiles and animation.
            clean = Image.new("RGBA", avatar.size)
            clean.paste(avatar)
            output = BytesIO()
            clean.save(output, format="PNG")
            return output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("图片内容无效，请选择 PNG、JPEG 或 WebP 图片") from exc
