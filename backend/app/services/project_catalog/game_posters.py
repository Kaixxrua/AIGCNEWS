"""Anonymous exact-title PageImages fallback; no search or arbitrary URL fetches."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit

import httpx

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
MAX_POSTER_RESPONSE_BYTES = 128 * 1024
POSTER_MISSING_SECONDS = 86400
POSTER_UNAVAILABLE_SECONDS = 300
_RASTER = re.compile(r"\.(?:jpe?g|png|webp)$", re.I)
_DECORATION = re.compile(r"logo|badge|icon|avatar|tracking|tracker|pixel|counter|visitor|shields|\.svg(?:[./]|$)", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f\\]")
_UTM = {"utm_source", "utm_campaign", "utm_content"}
_TITLE_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


class PosterUnavailable(RuntimeError):
    pass


def normalized_game_title(value: str) -> str:
    return " ".join(value.replace("_", " ").translate(_TITLE_QUOTES).split()).casefold()


def exact_game_titles(original: Any) -> list[str]:
    if not isinstance(original, str) or len(original) > 160 or len(original.strip()) < 3 or _CONTROL.search(original):
        return []
    original = " ".join(original.replace("_", " ").translate(_TITLE_QUOTES).split())
    # A vertical bar is MediaWiki's multi-title separator, not part of a query
    # we accept from repository evidence. Namespace/query delimiters stay out.
    if any(char in original for char in "|#<>[]{}") or re.search(r"https?://", original, re.I):
        return []
    titles = [original]
    if not original.casefold().endswith("(video game)"):
        titles.append(original + " (video game)")
    return titles


def normalize_wikimedia_image(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2000 or _CONTROL.search(value) or re.search(r"\s", value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.hostname != "upload.wikimedia.org" or parts.username is not None or parts.password is not None or parts.port is not None or parts.fragment:
            return ""
        tracking = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        if len(tracking) > len(_UTM) or len({key for key, _ in tracking}) != len(tracking):
            return ""
        if any(key not in _UTM or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) for key, value in tracking):
            return ""
        path = unquote(parts.path)
    except (ValueError, UnicodeError):
        return ""
    if _CONTROL.search(path) or any(char in path for char in "%?#") or "//" in path or any(segment in {".", ".."} for segment in path.split("/")):
        return ""
    if not re.match(r"^/wikipedia/(?:en|commons)/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/", path) or not _RASTER.search(path) or _DECORATION.search(path):
        return ""
    segments = path.lstrip("/").split("/")
    if len(segments) != (7 if segments[2] == "thumb" else 5):
        return ""
    return "https://upload.wikimedia.org" + quote(path, safe="/()'_,-")


def wikipedia_cover(page: Any, original: str) -> dict[str, str] | None:
    if not isinstance(page, dict) or type(page.get("ns")) is not int or page["ns"] != 0 or page.get("missing"):
        return None
    if type(page.get("pageid")) is not int or page["pageid"] <= 0:
        return None
    title = page.get("title")
    if not isinstance(title, str) or _CONTROL.search(title) or normalized_game_title(title) not in {normalized_game_title(value) for value in exact_game_titles(original)}:
        return None
    properties = page.get("pageprops", {})
    if not isinstance(properties, dict) or "disambiguation" in properties:
        return None
    categories = page.get("categories", [])
    # An exact title alone can still be a namesake film or novel. The API's
    # bounded category data or an explicit article suffix must identify a game.
    game_category = isinstance(categories, list) and any(
        isinstance(row, dict) and isinstance(row.get("title"), str)
        and re.match(r"^Category:(?:\d{4} )?Video games(?: |$)", row["title"], re.I)
        for row in categories[:50]
    )
    if not game_category and not re.search(r"\((?:\d{4} )?video game\)$", title, re.I):
        return None
    try:
        source = urlsplit(page.get("fullurl", ""))
        if source.scheme != "https" or source.hostname != "en.wikipedia.org" or source.username is not None or source.password is not None or source.port is not None or source.query or source.fragment:
            return None
        if not source.path.startswith("/wiki/") or normalized_game_title(unquote(source.path[len("/wiki/"):])) != normalized_game_title(title):
            return None
    except (ValueError, TypeError, UnicodeError):
        return None
    thumbnail = page.get("thumbnail")
    filename = page.get("pageimage")
    if not isinstance(thumbnail, dict) or not isinstance(filename, str) or _DECORATION.search(filename) or not _RASTER.search(filename):
        return None
    width, height = thumbnail.get("width"), thumbnail.get("height")
    if type(width) is not int or type(height) is not int or min(width, height) < 180 or max(width, height) > 2000:
        return None
    image = normalize_wikimedia_image(thumbnail.get("source"))
    if not image:
        return None
    # PageImages itself supplies the selected file. Ensure the image path names
    # that file (the optional thumb suffix may have a size prefix).
    image_path = unquote(urlsplit(image).path)
    if filename.replace(" ", "_") not in image_path.split("/"):
        return None
    return {
        "posterUrl": image,
        "posterSourceUrl": "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe=":()'_,-"),
        "posterKind": "cover",
    }


async def fetch_wikipedia_poster(original: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, str] | None:
    titles = exact_game_titles(original)
    if not titles:
        return None
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "pageimages|info|pageprops|categories", "ppprop": "disambiguation",
        "piprop": "thumbnail|name", "pilicense": "any", "pithumbsize": "600",
        "cllimit": "50", "clshow": "!hidden",
        "inprop": "url", "redirects": "1", "titles": "|".join(titles),
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False, trust_env=True,
            transport=transport, headers={"User-Agent": "AIGCNEWS-PortShelf/1.0 (https://aigcnews.cn)", "Accept": "application/json"},
        ) as client:
            async with client.stream("GET", WIKIPEDIA_API, params=params) as response:
                if response.status_code != 200:
                    raise PosterUnavailable("封面来源暂时不可用。")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_POSTER_RESPONSE_BYTES:
                        raise PosterUnavailable("封面来源返回内容过大。")
        data = json.loads(body)
        pages = data.get("query", {}).get("pages") if isinstance(data, dict) else None
        if not isinstance(pages, list) or len(pages) > 4 or data.get("error"):
            raise PosterUnavailable("封面来源返回资料无效。")
        # Prefer an exact base title over the explicitly allowed disambiguation
        # suffix. Never use another returned series, sequel or year variant.
        for title in titles:
            for page in pages:
                if isinstance(page, dict) and isinstance(page.get("title"), str) and normalized_game_title(page["title"]) == normalized_game_title(title):
                    if result := wikipedia_cover(page, original):
                        return result
        return None
    except PosterUnavailable:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, UnicodeError) as exc:
        raise PosterUnavailable("封面来源暂时不可用。") from exc
