"""Derive one internal project display name from bounded, read repository facts.

This is a conservative naming aid, not an image or URL approval. It never
changes the original game's identity and deliberately abstains on ambiguity.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from backend.app.models.schema_project_descriptions import normalize_description_repo
from backend.app.services.project_catalog.game_identity_context import cached_identity_evidence
from backend.app.services.project_catalog.game_poster_resources import PosterResourceError, safe_web_url

_STOP = re.compile(r"^(?:credits?|original inspiration|inspirations?|supported games?|dependencies|"
                   r"contribut\w*|acknowledg\w*|licen[cs]e|building|installation|migration|successors?|"
                   r"鸣谢|致谢|依赖|支持的游戏|版权声明|贡献|快速开始)(?:\b|$)", re.I)
_RELATION = re.compile(r"\b(?:inspired by|based on|clone of|supports?|successor|continuation|"
                       r"replaced by|migrat\w*|moved to|formerly|renamed|for example|such as)\b|"
                       r"(?:受.*启发|基于|支持|继任|迁移|更名|例如)", re.I)
_PURPOSE = re.compile(r"\b(?:game|game engine|source port|reimplementation|recreation)\b|游戏", re.I)
_OTHER_SUBJECT = re.compile(r"\b(?:supported by|inspiration for|dependency of|example of|used by this|we support)\b|本项目支持|本项目依赖", re.I)
_NAME = r"[\w][\w .:'’+()/\-]{1,119}"
_SUBJECT = re.compile(r"^(?P<name>" + _NAME + r")\s+(?:is|—|–|-)\s+(?P<purpose>.{3,300})$", re.I)
_ZH_SUBJECT = re.compile(r"^(?P<name>" + _NAME + r")\s*是一款(?P<purpose>.{3,300})$")
_APPOSE = re.compile(r"\b(?:in|play|playing) (?P<name>[A-Z0-9][\w’'()+/\-]*(?: [A-Z0-9][\w’'()+/\-]*){0,9}),\s+an?\s+[^.!?]{3,180}\bgame\b")


def _plain(raw: str) -> str:
    raw = re.sub(r"!\[[^\n]*?\]\([^\n]*?\)", "", raw)
    raw = re.sub(r"\[([^\]\n]+)\]\([^\n]*?\)", r"\1", raw)
    soup = BeautifulSoup("<div>" + raw + "</div>", "html.parser")
    for tag in soup(["script", "style", "code", "pre", "img"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).replace("**", "").replace("__", "").strip(" >*_").split())


def _key(value: str) -> str:
    # Corroboration permits whitespace/case only; no edition or number loss.
    return " ".join(value.casefold().split())


def _intro(raw: str) -> tuple[list[tuple[str, int, int]], list[str], str]:
    blocks: list[tuple[str, int, int]] = []
    headings: list[str] = []
    end = len(raw)
    fenced = False
    offset = 0
    overview_seen = False
    for piece in re.split(r"(\n[ \t]*\n)", raw):
        start, offset = offset, offset + len(piece)
        if not piece.strip():
            continue
        if re.search(r"(?m)^\s*(?:```|~~~)", piece):
            # A fenced block may contain arbitrary fake headings/names.
            if len(re.findall(r"(?m)^\s*(?:```|~~~)", piece)) % 2:
                fenced = not fenced
            continue
        if fenced:
            continue
        markdown = list(re.finditer(r"(?m)^ {0,3}(#{1,3})[ \t]+([^\n]+)", piece))
        markup = list(re.finditer(r"<h([1-3])\b[^>]*>(.*?)</h\1>", piece, re.I | re.S))
        found = sorted([(match.start(), match.end(), len(match[1]), _plain(match[2].rstrip(" #")))
                        for match in markdown] +
                       [(match.start(), match.end(), int(match[1]), _plain(match[2])) for match in markup])
        if len(found) > 1 or any(_STOP.search(heading[3]) for heading in found):
            end = start
            break
        if found:
            heading_start, heading_end, level, title = found[0]
            if not title:
                continue
            if not headings:
                # A project title must precede substantive prose. A later
                # example/sponsor/game heading cannot become the own title.
                if any(_plain(block) for block, _, _ in blocks) or _plain(piece[:heading_start]):
                    end = start
                    break
                headings.append(title[:160])
            elif level == 1:
                # Multiple top-level subjects are ambiguous; do not pick one
                # game from a collection or a document describing projects.
                return [], [], ""
            elif not overview_seen and re.fullmatch(
                r"(?:about(?: the project)?|overview|introduction|简介|项目介绍|概述)", title, re.I,
            ):
                overview_seen = True
            else:
                end = start
                break
            # Preserve an introduction written immediately after its heading,
            # including its exact source offset; do not add section titles as
            # alternative project names.
            piece = piece[heading_end:]
            start += heading_end
        if piece.strip() and not re.match(r"\s*\[[^\]]+\]:", piece):
            blocks.append((piece, start, offset))
    return blocks[:16], headings, raw[:end]


def _release_intro(raw: str, paragraph: str, name: str) -> bool:
    """No-heading apposition needs both actual home and release links.

    The URLs only corroborate the leading self-presentation. They are never
    fetched, inferred from a name, or promoted into tool results.
    """
    if not re.search(r"\b(?:play|become|survive|leaderboards|challenge)\b", paragraph, re.I):
        return False
    if not re.search(r"\b(?:now available|play now|download|releases?)\b", paragraph, re.I):
        return False
    def links(text: str) -> list:
        # Only links actually present in the intro, never bare text, image
        # sources or a URL reconstructed from the proposed name.
        urls = [tag["href"] for tag in BeautifulSoup("<div>" + text + "</div>", "html.parser").find_all("a", href=True)[:30]]
        urls += re.findall(r"(?<!!)\[[^\]\n]+\]\((https://[^\s)]+)\)", text)[:30]
        result = []
        for url in urls[:30]:
            try:
                result.append(urlsplit(safe_web_url(url)))
            except (PosterResourceError, ValueError):
                continue
        return result

    # A collection/toolkit homepage plus a game's store link is not evidence
    # that the game names the project. Require the complete name on an actual
    # homepage host label, preserving every letter and number. Never derive or
    # fetch a domain from a name. Ambiguous promotional copy simply abstains.
    if re.search(r"\b(?:collection|toolkit|library|framework|companion demo|example game|sample game)\b", _plain(paragraph), re.I):
        return False
    compact_name = "".join(char for char in name.casefold() if char.isalnum())
    homes = {url.hostname for url in links(raw) if url.path in {"", "/"} and not url.query
             and compact_name and any(
                 "".join(char for char in label.casefold() if char.isalnum()) == compact_name
                 for label in (url.hostname or "").split(".")[:-1]
             )}
    releases = {url.hostname for url in links(paragraph) if url.path not in {"", "/"}}
    return any(home != release for home in homes for release in releases)


def project_display_aliases(item: dict) -> list[dict]:
    """Return at most one literal name, exact source span, and source digest.

    Only the existing internal evidence envelope is trusted as provenance;
    model/caller-proposed aliases and public description translations are not.
    """
    if type(item.get("detailsVersion")) is not int or item["detailsVersion"] != 1:
        return []
    try:
        normalize_description_repo(item.get("repo"))
    except ValueError:
        return []
    evidence = cached_identity_evidence(item)
    readme = evidence.get("readme", "")
    blocks, headings, intro = _intro(readme)
    first_prose_start = next((start for raw, start, _ in blocks if _plain(raw)), None)
    candidates: dict[str, dict] = {}
    sources = [("readme", raw, start, end) for raw, start, end in blocks]
    description = evidence.get("description", "")
    if description:
        sources.append(("description", description, 0, len(description)))
    for source, raw, start, end in sources:
        if len(raw) > 1200:
            continue
        paragraph = _plain(raw)
        subject = _SUBJECT.match(paragraph) or _ZH_SUBJECT.match(paragraph)
        name = subject["name"].strip() if subject else ""
        # The *whole* own subject must agree with a heading. A heading alone
        # or an ancestor name in the predicate cannot become an alias.
        corroborated = any(_key(heading) in {_key(name), _key(name + " Development README"), _key(name + " README")} for heading in headings)
        reason = "heading_and_own_subject"
        if not (subject and corroborated and _PURPOSE.search(subject["purpose"])
                and not _RELATION.search(name) and not _OTHER_SUBJECT.search(subject["purpose"])):
            name = ""
            if (source == "readme" and not headings and start == first_prose_start
                    and not _RELATION.search(paragraph)):
                matches = list(_APPOSE.finditer(paragraph))
                if len(matches) == 1 and _release_intro(intro, raw, matches[0]["name"]):
                    name = matches[0]["name"]
                    reason = "leading_game_apposition_and_release_links"
        if not name or len(name) > 120 or not re.fullmatch(_NAME, name):
            continue
        # Announcing a successor is not a self-name even with a stale heading.
        if re.search(r"\b(?:successor|continuation|replaced by|migrat\w*|moved to|renamed)\b|迁移|继任|更名", paragraph, re.I):
            continue
        full_source = evidence[source]
        candidates.setdefault(_key(name), {"name": name, "source": source,
            "sourceSha256": hashlib.sha256(full_source.encode()).hexdigest(),
            "spanStart": start, "spanEnd": end, "evidence": full_source[start:end], "reason": reason})
    return list(candidates.values()) if len(candidates) == 1 else []
