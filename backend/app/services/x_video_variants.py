"""Choose an advertised MP4 for inline playback without guessing CDN URLs."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

_SIZE = re.compile(r"/(\d+)x(\d+)/")


def select_playback_url(variants: Any) -> str:
    """Prefer the best <=720p / 2.5Mbps MP4, otherwise the lowest bitrate.

    Keep the original media URL separately for compatibility. X variant filenames
    differ across resolutions, so replacing dimensions in a URL is not valid.
    """
    candidates: list[tuple[int, int, str]] = []
    if not isinstance(variants, list):
        return ""
    for variant in variants:
        if not isinstance(variant, dict) or variant.get("content_type") != "video/mp4":
            continue
        url = variant.get("url")
        bitrate = variant.get("bitrate")
        if not isinstance(url, str) or not isinstance(bitrate, int) or bitrate <= 0:
            continue
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != "video.twimg.com"
                    or parsed.port not in (None, 443) or parsed.username or parsed.password
                    or not parsed.path.endswith(".mp4")):
                continue
        except ValueError:
            continue
        size = _SIZE.search(parsed.path)
        longest = max(map(int, size.groups())) if size else 0
        candidates.append((bitrate, longest, url))
    suitable = [c for c in candidates if 0 < c[1] <= 1280 and c[0] <= 2_500_000]
    if suitable:
        return max(suitable)[2]
    return min(candidates)[2] if candidates else ""
