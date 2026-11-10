"""Chinese prose validation with a narrow, source-verified game-title exception."""
from __future__ import annotations

import re
from typing import Any

from backend.app.models.schema_project_descriptions import normalize_description_repo
from backend.app.services.project_catalog.game_details import normalize_game_details
from backend.app.services.project_catalog.game_identity_context import cached_identity_evidence

_HAN = re.compile(r"[\u3400-\u9fff]")
_KANA = re.compile(r"[\u3040-\u30ff\uff66-\uff9f]")
_QUOTES = (("《", "》"), ("〈", "〉"), ("「", "」"), ("『", "』"),
           ("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"))


def _verified_title(game: dict[str, Any]) -> str:
    # A caller-supplied alias list or name alone is not evidence. Both new
    # generation and cached reads use the same bounded internal source record.
    if (type(game.get("detailsVersion")) is not int or game["detailsVersion"] != 1
            or type(game.get("identityEvidenceVersion")) is not int or game["identityEvidenceVersion"] != 2):
        return ""
    evidence = cached_identity_evidence(game)
    name = game.get("gameNameOriginal")
    if not evidence or not isinstance(name, str) or not name or not _KANA.search(name):
        return ""
    try:
        repo = normalize_description_repo(game.get("repo"))
    except ValueError:
        return ""
    verified = normalize_game_details(
        {"game_identity": "single_game", "game_name_original": name},
        {"full_name": repo, "description": evidence["description"], "readme_text": evidence["readme"]},
    )
    return name if verified["gameNameOriginal"] == name else ""


def description_validation_reason(value: Any, *, game: dict[str, Any] | None = None) -> str:
    """Return a code-owned reason, never generated text or provider metadata."""
    if not isinstance(value, str):
        return "invalid_type"
    text = value.strip()
    if not text:
        return "empty"
    if len(text) > 512:
        return "too_long"
    prose = text
    if _KANA.search(text) and isinstance(game, dict) and (name := _verified_title(game)):
        for left, right in _QUOTES:
            prose = prose.replace(left + name + right, "")
    # The title's kanji must not make Japanese-only text pass as Chinese prose.
    if not _HAN.search(prose):
        return "no_han"
    if _KANA.search(prose):
        return "kana_present"
    return ""


def chinese_description(value: Any, *, game: dict[str, Any] | None = None) -> str:
    # Remove the title only for validation; preserve its actual displayed text.
    return "" if description_validation_reason(value, game=game) else value.strip()
