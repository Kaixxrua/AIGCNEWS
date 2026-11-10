"""Conservative project-name formatting and evidenced artwork page links."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from backend.app.models.schema_project_descriptions import normalize_description_repo
from backend.app.services.project_catalog.game_poster_resources import PosterResourceError, safe_web_url

_WORD = r"[^\W_]"
_SEPARATOR = r"[\W_]*"
_FOLLOWING_NUMBER = re.compile(_SEPARATOR + r"(?:[0-9]+|[ivx]+)(?!" + _WORD + r")")
_ITCH_AUTHOR = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.itch\.io")
_ITCH_GAME = re.compile(r"/[a-z0-9][a-z0-9_.-]*/?", re.I)
_MEDIA_DIRECTORY = re.compile(r"screenshots?|images?|galler(?:y|ies)|media|artwork|pictures?|posters?", re.I)


def _project_media_path(url: str, project_repo: str) -> tuple[str, str, tuple[str, ...]] | None:
    try:
        parts = urlsplit(safe_web_url(url))
        repo = normalize_description_repo(project_repo)
    except (PosterResourceError, ValueError):
        return None
    # A slash-encoded ref/path is ambiguous in GitHub's tree route. Never
    # turn it into a different repository/ref or an invented raw URL.
    if parts.hostname != "github.com" or parts.query or re.search(r"%2f", parts.path, re.I):
        return None
    path = unquote(parts.path).strip("/").split("/")
    if (len(path) < 5 or "/".join(path[:2]).lower() != repo or path[2] not in {"tree", "blob"}
            or not any(_MEDIA_DIRECTORY.fullmatch(part) for part in path[4:])):
        return None
    return path[2], path[3], tuple(path[4:])


def project_media_directory(url: str, project_repo: str) -> bool:
    path = _project_media_path(url, project_repo)
    return bool(path and path[0] == "tree")


def project_media_descendant(source: str, target: str, project_repo: str) -> bool:
    """Classify an actual DOM link down a single repository/ref's media tree.

    Only tree pages may lead to another directory or a supported image's HTML
    blob detail. The caller enforces the two-hop and overall read budgets.
    """
    parent = _project_media_path(source, project_repo)
    child = _project_media_path(target, project_repo)
    return bool(parent and child and parent[0] == "tree" and parent[1] == child[1]
                and len(child[2]) > len(parent[2]) and child[2][:len(parent[2])] == parent[2]
                and (child[0] == "tree" or project_image_detail(target, project_repo)))


def project_image_detail(url: str, project_repo: str) -> bool:
    """A same-repository GitHub blob is an HTML detail page, not its image.

    This only classifies a URL already present in the source DOM. The caller
    still fetches that exact page and extracts its actual image references.
    """
    try:
        parts = urlsplit(safe_web_url(url))
        repo = normalize_description_repo(project_repo)
    except (PosterResourceError, ValueError):
        return False
    return bool(parts.hostname == "github.com"
                and re.fullmatch("/" + re.escape(repo) + r"/blob/[^/]+/.+\.(?:png|jpe?g|webp|gif)", unquote(parts.path), re.I)
                and not any(value.lower() in {"true", "1"} for value in parse_qs(parts.query).get("raw", [])))


def has_project_identity(text: str, name: str) -> bool:
    """Match the entire project spelling, allowing only presentation changes.

    Separators may move between letters, as in ``NSMB-MarioVsLuigi`` and
    ``NSMB: Mario vs. Luigi``. Letters and digits cannot be added, removed or
    reordered. Outer word/slug boundaries prevent matching a different name
    such as ``SuperOpenRA`` or ``OpenRA-fork``; numbered variants stay distinct.
    This does not supply semantic aliases for a related commercial game.
    """
    if not isinstance(text, str) or not isinstance(name, str) or len(name) > 200:
        return False
    value = unicodedata.normalize("NFKC", text[:20000]).casefold()
    name = unicodedata.normalize("NFKC", name).casefold()
    # Keep each contiguous number intact. Presentation changes cannot turn
    # Project 14 into Project 1.4, or join the version 1.2 into version 12.
    atoms = re.findall(r"\d+|[^\W_\d]", name)
    if len("".join(atoms)) < 3:
        return False
    pieces = []
    for index, atom in enumerate(atoms):
        if index:
            pieces.append(r"[\W_]+" if atoms[index - 1].isdecimal() and atom.isdecimal() else _SEPARATOR)
        pieces.append(re.escape(atom))
    pattern = r"(?<!" + _WORD + r")" + "".join(pieces) + r"(?!" + _WORD + r")"
    for match in re.finditer(pattern, value):
        before, after = value[:match.start()], value[match.end():]
        # Hyphen/underscore-attached prefixes and suffixes remain part of a
        # slug. A separated prose dash ("OpenRA - official site") is harmless.
        if re.search(_WORD + r"[-_]+$", before) or re.match(r"[-_]+" + _WORD, after):
            continue
        if _FOLLOWING_NUMBER.match(after):
            continue
        return True
    return False


def project_artwork_links(
    soup: BeautifulSoup, page_url: str, project_repo: str, project_name: str,
) -> list[dict[str, str]]:
    """Return up to three evidenced project home, repo, wiki or itch.io links.

    The caller must already have verified this page's project identity and
    remains responsible for the one-hop budget. No URLs are invented and no
    network requests are made. Destination pages still need identity checks.
    """
    try:
        source = safe_web_url(page_url)
        repo = normalize_description_repo(project_repo)
    except (PosterResourceError, ValueError):
        return []
    links: list[dict[str, str]] = []
    seen = {source}
    wiki_path = "/" + repo + "/wiki"
    for tag in soup.find_all("a", href=True)[:500]:
        reference = tag.get("href")
        if not isinstance(reference, str):
            continue
        try:
            address = safe_web_url(urljoin(source, reference))
        except (PosterResourceError, ValueError, UnicodeError):
            continue
        if address in seen:
            continue
        parts = urlsplit(address)
        path = unquote(parts.path)
        label = tag.get_text(" ", strip=True)[:200]
        title = str(tag.get("title") or "")[:200]
        same_wiki = parts.hostname == "github.com" and (
            path.lower().rstrip("/") == wiki_path or path.lower().startswith(wiki_path + "/")
        )
        same_repo = parts.hostname == "github.com" and path.lower().rstrip("/") == "/" + repo and not parts.query
        # A named root page in the actual DOM can lead from a news article to
        # the game's own site. This is a candidate, not proof of ownership:
        # the destination still passes URL, DNS and project identity checks.
        project_home = bool(
            path in {"", "/"} and not parts.query
            and any(has_project_identity(value, project_name) for value in (parts.hostname or "", label, title))
        )
        same_itch_game = bool(
            _ITCH_AUTHOR.fullmatch(parts.hostname or "")
            and parts.hostname not in {"www.itch.io", "api.itch.io", "static.itch.io", "img.itch.io"}
            and _ITCH_GAME.fullmatch(path)
            and any(has_project_identity(value, project_name) for value in (path.strip("/"), label, title))
        )
        if not (same_wiki or same_itch_game or same_repo or project_home):
            continue
        seen.add(address)
        links.append({"url": address, "title": label or title or "项目资料页面"})
        if len(links) == 3:
            break
    return links
