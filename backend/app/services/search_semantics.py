from __future__ import annotations

import re
import unicodedata

TECHNICAL_TOKEN_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_+#-]|\.(?=[A-Za-z0-9]))*|\.[A-Za-z][A-Za-z0-9]*|[㐀-䶿一-鿿]+"
)
_PROJECT_TRANSPORT_TERMS = {
    "github",
    "repo",
    "repository",
    "repositories",
    "project",
    "projects",
    "项目",
    "仓库",
    "工具",
}


def normalize_search_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").strip().split())


def search_terms(
    value: str,
    *,
    max_terms: int = 8,
    blocked_terms: set[str] | None = None,
) -> list[str]:
    normalized = normalize_search_query(value)
    blocked = {term.casefold() for term in (blocked_terms or set())}
    terms: list[str] = []
    seen: set[str] = set()
    for token in TECHNICAL_TOKEN_RE.findall(normalized):
        key = token.casefold()
        if key in blocked or key in seen:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        seen.add(key)
        terms.append(token)
        if len(terms) >= max(1, max_terms):
            break
    return terms


def project_search_terms(value: str, *, max_terms: int = 8) -> list[str]:
    return search_terms(value, max_terms=max_terms, blocked_terms=_PROJECT_TRANSPORT_TERMS)


def escape_like_literal(value: str, *, escape: str = "=") -> str:
    return value.replace(escape, escape * 2).replace("%", f"{escape}%").replace("_", f"{escape}_")
