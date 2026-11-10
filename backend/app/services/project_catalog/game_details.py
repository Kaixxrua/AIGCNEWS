"""Evidence-only game identities and bounded README image candidates.

No image URL is fetched here. Only references already present in the public
repository README can reach the model; the model returns an opaque candidate ID,
never a URL. Normalization rejects arbitrary hosts, credentials and path escapes.
"""

from __future__ import annotations

import html
import posixpath
import re
import string
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from backend.app.services.project_catalog.game_identity_context import (
    binary_qualified_title,
    contradicted_runtime_identity,
    identity_evidence,
    repository_title_is_game,
    title_separators,
)

MAX_CANDIDATES = 12
_RASTER = re.compile(r"\.(?:png|jpe?g|webp)$", re.I)
_DECORATION = re.compile(
    r"badge|logo|avatar|icon|sponsor|donat|tracking|tracker|pixel|counter|visitor|shields|"
    r"readme[-_]stats|github[-_]stats|workflow|build[-_]status|social[-_]card", re.I,
)
_UNSAFE = re.compile(r"[\x00-\x20\x7f\\]")
_ATTACHMENT = re.compile(r"/user-attachments/assets/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_IDENTITY_PUNCTUATION = str.maketrans({
    **{chr(ord(char) + 0xFEE0): char for char in string.punctuation},
    "‘": "'", "’": "'", "“": '"', "”": '"',
})
_IDENTITY_EMPHASIS = tuple(
    re.compile(
        rf"(?<![\w\\{marker[0]}]){re.escape(marker)}(?!\s)"
        rf"([^{marker[0]}\n]+?)(?<!\s){re.escape(marker)}(?![\w{marker[0]}])"
    )
    for marker in ("***", "___", "**", "__", "*", "_")
)


def safe_repository_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 500 or _UNSAFE.search(value):
        return ""
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")) or any(char in value for char in "%?#"):
        return ""
    return value


def readme_source_url(repo: str, branch: str, path: str) -> str:
    if not safe_repository_path(branch) or not safe_repository_path(path):
        return ""
    return f"https://github.com/{repo}/blob/{quote(branch, safe='/')}/{quote(path, safe='/')}"


def normalize_image_url(value: str, *, repo: str, branch: str, readme_path: str) -> str:
    if not isinstance(value, str) or len(value) > 1500:
        return ""
    value = html.unescape(value.strip())
    if not value or _UNSAFE.search(value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.username is not None or parts.password is not None or parts.port is not None or parts.fragment:
            return ""
    except ValueError:
        return ""
    path = unquote(parts.path)
    if _UNSAFE.search(path) or any(char in path for char in "%?#"):
        return ""
    if parts.scheme or parts.netloc:
        if parts.scheme != "https" or parts.query:
            return ""
        if any(part in {".", ".."} for part in path.split("/")) or "//" in path:
            return ""
        host = parts.hostname
        if host == "github.com" and _ATTACHMENT.fullmatch(path):
            return "https://github.com" + path
        if host == "github.com":
            for kind in ("blob", "raw"):
                prefix = f"/{repo}/{kind}/{branch}/"
                if safe_repository_path(branch) and path.casefold().startswith(prefix.casefold()):
                    path = f"/{repo}/{branch}/" + path[len(prefix):]
                    host = "raw.githubusercontent.com"
                    break
        if not _RASTER.search(path):
            return ""
        if host == "raw.githubusercontent.com":
            if not path.casefold().startswith("/" + repo.casefold() + "/") or len(path.split("/")) < 5:
                return ""
        elif host == "user-images.githubusercontent.com":
            if not re.fullmatch(r"/\d+/[A-Za-z0-9_.-]+", path):
                return ""
        else:
            return ""
        return f"https://{host}{quote(path, safe='/')}"
    if parts.query or not safe_repository_path(branch) or not safe_repository_path(readme_path) or path.startswith("/"):
        return ""
    normalized = posixpath.normpath(posixpath.join(posixpath.dirname(readme_path), path))
    if not safe_repository_path(normalized) or not _RASTER.search(normalized):
        return ""
    return f"https://raw.githubusercontent.com/{repo}/{quote(branch, safe='/')}/{quote(normalized, safe='/')}"


class _ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        for dimension in ("width", "height"):
            value = values.get(dimension, "")
            if len(value) <= 6 and value.isdigit() and int(value) <= 96:
                return
        self.images.append((values.get("src", ""), values.get("alt", ""), values.get("title", "")))


def image_candidates(repo: str, branch: str, readme_path: str, readme: str) -> list[dict[str, str]]:
    source = readme_source_url(repo, branch, readme_path)
    if not source:
        return []
    # Comments/code are not rendered images and may contain malicious examples.
    text = re.sub(r"<!--[\s\S]*?-->|```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`", "", readme[:12000])
    found: list[tuple[str, str, str]] = []
    for match in re.finditer(r"!\[([^\]\n]{0,200})\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+[\"'][^\n]*?[\"'])?\s*\)", text):
        found.append((match[2].strip("<>"), match[1], text[max(0, match.start() - 100):match.end() + 100]))
    references = {
        match[1].strip().casefold(): match[2].strip("<>")
        for match in re.finditer(r"(?m)^\s{0,3}\[([^\]\n]+)\]:\s*(<[^>\n]+>|\S+)", text)
    }
    for match in re.finditer(r"!\[([^\]\n]{0,200})\]\[([^\]\n]*)\]", text):
        target = references.get((match[2] or match[1]).strip().casefold())
        if target:
            found.append((target, match[1], text[max(0, match.start() - 100):match.end() + 100]))
    parser = _ImageParser()
    parser.feed(text)
    found.extend(parser.images)
    result, seen = [], set()
    for value, alt, context in found:
        if _DECORATION.search(value + " " + alt):
            continue
        url = normalize_image_url(value, repo=repo, branch=branch, readme_path=readme_path)
        if not url or url in seen:
            continue
        seen.add(url)
        result.append({"id": f"image-{len(result) + 1}", "url": url, "sourceUrl": source, "alt": alt[:160], "context": context[:400]})
        if len(result) >= MAX_CANDIDATES:
            break
    return result


def _name(value: Any, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > limit or re.search(r"[\x00-\x1f\x7f<>]|https?://", value):
        return ""
    return value


def _identity_evidence(value: str) -> str:
    # Compare displayed words without changing the returned name. Only paired
    # inline emphasis and equivalent punctuation are folded; titles, numbers,
    # editions, platform qualifiers and literal in-word underscores stay intact.
    for pattern in _IDENTITY_EMPHASIS:
        value = pattern.sub(r"\1", value)
    value = html.unescape(value).translate(_IDENTITY_PUNCTUATION)
    return title_separators(value).casefold()


def _identity_in_facts(name: str, facts: str) -> bool:
    if not name:
        return False
    # A short numeric title/version must not match the prefix of another one
    # (Game 2 vs Game 20, or Game 1.4 vs Game 1.4.3). Chinese prose need not have
    # whitespace around a title, so these guards apply only to ASCII tokens.
    start = r"(?<![a-z0-9_])" if name[0] in string.ascii_lowercase + string.digits else ""
    end = ""
    if name[-1] in string.digits:
        end = r"(?![a-z0-9_]|\.\d)"
    elif name[-1] in string.ascii_lowercase:
        end = r"(?![a-z0-9_])"
    return re.search(start + re.escape(name) + end, facts) is not None


def normalize_game_details(data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Refuse invented identities/URLs while caching a completed empty attempt."""
    result: dict[str, Any] = {
        "gameNameZh": "", "gameNameOriginal": "", "posterUrl": "",
        "posterSourceUrl": "", "posterKind": "", "detailsVersion": 1,
        "identityEvidenceVersion": 2,
    }
    original = _name(data.get("game_name_original"))
    chinese = _name(data.get("game_name_zh"), 100)
    facts = " ".join(str(metadata.get(key) or "") for key in ("description", "readme_text"))
    normalized_facts = _identity_evidence(facts)
    normalized_name = _identity_evidence(original)
    repo = str(metadata.get("full_name") or "")
    if (
        data.get("game_identity") != "single_game" or len(original) < 3
        or not _identity_in_facts(normalized_name, normalized_facts)
        or normalized_name == _identity_evidence(repo)
        or (normalized_name == _identity_evidence(repo.rsplit("/", 1)[-1]) and not repository_title_is_game(original, metadata))
        or contradicted_runtime_identity(original, identity_evidence(metadata))
        or binary_qualified_title(original, identity_evidence(metadata))
    ):
        return result
    result["gameNameOriginal"] = original
    if re.search(r"[\u3400-\u9fff]", chinese) and not re.search(r"[\u3040-\u30ff]", chinese):
        result["gameNameZh"] = chinese
    selected = data.get("poster_candidate_id")
    if not isinstance(selected, str) or data.get("poster_kind") not in {"cover", "screenshot"}:
        return result
    for candidate in metadata.get("image_candidates", []):
        if candidate.get("id") == selected:
            # Revalidate at the model boundary as well as during extraction.
            url = normalize_image_url(candidate["url"], repo=repo, branch=str(metadata.get("default_branch") or ""), readme_path=str(metadata.get("readme_path") or ""))
            source = readme_source_url(repo, str(metadata.get("default_branch") or ""), str(metadata.get("readme_path") or ""))
            if url and source and source == candidate.get("sourceUrl"):
                result.update(posterUrl=url, posterSourceUrl=source, posterKind=data["poster_kind"])
            break
    return result
