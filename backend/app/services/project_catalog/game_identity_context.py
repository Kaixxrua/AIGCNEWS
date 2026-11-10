"""Bounded source evidence for artwork identity, without inferring game aliases.

This is internal cache/model context, not a new public description schema. The
evidence remains untrusted text; it never approves an image or invents a name.
"""
from __future__ import annotations

import html
import re
from typing import Any

CONTEXT_VERSION = 1
DESCRIPTION_CHARS = 1200
README_CHARS = 6000


def title_separators(value: str) -> str:
    """Fold display separators, retaining words, apostrophes and decimal versions."""
    value = value.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "：": ":"}))
    # A colon separating title words is not a different game. A numeric ratio
    # or version such as 1:2 must not become the separate numbers "1 2".
    value = re.sub(r"(?<!\d):|:(?!\d)", " ", value)
    value = re.sub(r"\s+[-–—]\s+", " ", value)
    return " ".join(value.split())


def _text(value: Any, limit: int) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value[:limit]) if isinstance(value, str) else ""


def identity_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
    """Retain the actual subject/relationship and nearby compatibility wording."""
    return {"version": CONTEXT_VERSION,
            "description": _text(metadata.get("description"), DESCRIPTION_CHARS),
            "readme": _text(metadata.get("readme_text"), README_CHARS)}


def cached_identity_evidence(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("gameIdentityEvidence")
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != CONTEXT_VERSION:
        return {}
    return identity_evidence({"description": value.get("description"), "readme_text": value.get("readme")})


def contradicted_runtime_identity(name: str, evidence: dict[str, Any]) -> bool:
    """Detect explicit negation of an executable requirement, not a new title.

Only dotted versions actually present in the proposed title are considered.
This does not remove version/platform restrictions or turn an inferred alias
into a verified name; the caller must re-enrich or leave identity unconfirmed.
"""
    text = html.unescape(_text(evidence.get("readme"), README_CHARS))
    text = re.sub(r"[*_]+", "", text)
    for version in re.findall(r"(?<![\w.])\d+\.\d+(?:\.\d+)*(?:\s+(?:US|USA|EU|JP|UK))?(?![\w.])", name, re.I):
        negative = r"\b(?:not\s+(?:the\s+same\s+as|compatible\s+with)|(?:do|does)\s+not\s+(?:support|use)|must\s+not\s+use)\s+(?:the\s+)?"
        runtime = r"\s+(?:exe|executable|binary|rom)\b"
        if re.search(negative + re.escape(version) + runtime, text, re.I):
            return True
    return False


def binary_qualified_title(name: str, evidence: dict[str, Any]) -> bool:
    """Recognize an evidenced binary target, never silently strip its suffix.

    Marketing editions, years and platform suffixes do not qualify. A bare
    patch/language suffix also needs nearby machine-code matching evidence;
    the caller must obtain a source-supported canonical title separately.
    """
    suffix = re.search(
        r"\((?:version|ver\.?|v)\s*\d+\.\d+(?:\.\d+)*(?:,\s*(?:English|Japanese|German|French|Spanish|Italian|Chinese|Korean))?\)$",
        name, re.I,
    )
    if not suffix:
        return False
    text = html.unescape(_text(evidence.get("readme"), README_CHARS))
    text = " ".join(re.sub(r"[*_]+", "", text).split()).casefold()
    target = " ".join(name.split()).casefold()
    position = text.find(target)
    if position < 0:
        return False
    context = text[max(0, position - 160):position + len(target) + 600]
    return bool(re.search(r"\b(?:machine code|binar(?:y|ies)|byte[- ]for[- ]byte|abi)\b", context)
                and re.search(r"\b(?:match(?:ing|es)?|reproduc(?:e|es|ing)|exact|requires?|targets?)\b", context))


def repository_title_is_game(name: str, metadata: dict[str, Any]) -> bool:
    """A matching repo slug alone is insufficient; require a declared playable subject."""
    text = _text(metadata.get("readme_text"), 2000)
    text = re.sub(r"<!--[\s\S]*?-->|```[\s\S]*?```|~~~[\s\S]*?~~~", "", text)
    headings = list(re.finditer(r"(?m)^#{1,2}\s+([^\n]+)", text))[:3]
    heading = next((match for match in headings
                    if title_separators(match[1].strip()).casefold() == title_separators(name).casefold()), None)
    if heading is None:
        return False
    intro = text[heading.end():].strip().split("\n\n", 1)[0][:800]
    intro = re.sub(r"^" + re.escape(name) + r"\s+(?:is\s+)?", "", intro, flags=re.I)
    return bool(re.search(
        r"\bplay\s+(?:it|this\s+game|here)\b|^(?:a|an)\s+"
        r"(?:(?:small|open[- ]source|free|simple|classic|traditional|2d|3d|arcade|puzzle|adventure|action|strategy)\s+){0,5}"
        r"(?:game|clone|puzzle|roguelike|platformer|shooter|arcade)\b|^(?:一款|一个).{0,15}游戏", intro, re.I,
    ))
