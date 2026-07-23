from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

TECHNICAL_TOKEN_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_+#-]|\.(?=[A-Za-z0-9]))*|\.[A-Za-z][A-Za-z0-9]*|[㐀-䶿一-鿿]+"
)
_HAN_RE = re.compile(r"[㐀-䶿一-鿿]")
_PROJECT_REQUEST_PHRASES = (
    "帮我找一下",
    "帮我找",
    "给我推荐",
    "我想要学习",
    "我想学习",
    "find me",
    "recommend me",
)
_PROJECT_BILINGUAL_ALIASES = (
    ("智能体", "agent"),
    ("知识库", "knowledge base RAG"),
    ("工作流", "workflow automation"),
    ("本地部署", "local self-hosted"),
    ("开发工具", "developer tools"),
    ("编程助手", "coding assistant"),
    ("教程", "tutorial learning"),
    ("入门", "beginner learning"),
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


ProjectQueryLanguage = Literal["zh", "en", "mixed", "und"]


@dataclass(frozen=True)
class ProjectSearchIntent:
    schema_version: str
    normalized_query: str
    language: ProjectQueryLanguage
    lexical_terms: tuple[str, ...]
    semantic_queries: tuple[str, ...]


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


def build_project_search_intent(value: str, *, max_chars: int = 120) -> ProjectSearchIntent:
    normalized = normalize_search_query(value)[:max_chars]
    cleaned = normalized
    for phrase in _PROJECT_REQUEST_PHRASES:
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    cleaned = normalize_search_query(cleaned) or normalized
    has_han = bool(_HAN_RE.search(cleaned))
    latin_terms = [term for term in TECHNICAL_TOKEN_RE.findall(cleaned) if not _HAN_RE.search(term)]
    prose_latin = [term for term in latin_terms if term.casefold() not in {"ai", "llm", "rag", "mcp"}]
    language: ProjectQueryLanguage = (
        "mixed" if has_han and prose_latin else "zh" if has_han else "en" if latin_terms else "und"
    )
    expanded = cleaned
    for zh, en in _PROJECT_BILINGUAL_ALIASES:
        if zh in expanded and en.casefold() not in expanded.casefold():
            expanded = f"{expanded} {en}"
    variants: list[str] = []
    seen: set[str] = set()
    for query in (cleaned, normalize_search_query(expanded)):
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            variants.append(query[:max_chars])
    return ProjectSearchIntent(
        schema_version="project-search-intent-v1",
        normalized_query=cleaned,
        language=language,
        lexical_terms=tuple(project_search_terms(cleaned)),
        semantic_queries=tuple(variants),
    )


def escape_like_literal(value: str, *, escape: str = "=") -> str:
    return value.replace(escape, escape * 2).replace("%", f"{escape}%").replace("_", f"{escape}_")
