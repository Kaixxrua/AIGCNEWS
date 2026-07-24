from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Mapping

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
_PROTECTED_PROJECT_TOKENS = frozenset({"c++", "c#", ".net", "mcp", "rag", "langgraph"})
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
ProjectIntentClass = Literal[
    "exact_lookup",
    "learning",
    "examples",
    "sdk",
    "framework",
    "self_hosted",
    "general_discovery",
]


@dataclass(frozen=True)
class ProjectSearchIntent:
    schema_version: str
    normalized_query: str
    language: ProjectQueryLanguage
    lexical_terms: tuple[str, ...]
    semantic_queries: tuple[str, ...]
    intent_class: ProjectIntentClass = "general_discovery"
    topics: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    artifact_types: tuple[str, ...] = ()
    must_have: tuple[str, ...] = ()
    should_have: tuple[str, ...] = ()


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
    terms = tuple(project_search_terms(cleaned))
    lowered = cleaned.casefold()
    intent_class: ProjectIntentClass = "general_discovery"
    if len(terms) == 1 or "/" in cleaned:
        intent_class = "exact_lookup"
    elif any(value in lowered for value in ("学习", "教程", "入门", "learn", "tutorial", "beginner")):
        intent_class = "learning"
    elif any(value in lowered for value in ("example", "sample", "示例")):
        intent_class = "examples"
    elif "sdk" in lowered:
        intent_class = "sdk"
    elif any(value in lowered for value in ("framework", "框架")):
        intent_class = "framework"
    elif any(value in lowered for value in ("本地部署", "self-hosted", "self hosted")):
        intent_class = "self_hosted"
    return ProjectSearchIntent(
        schema_version="project-search-intent-v1",
        normalized_query=cleaned,
        language=language,
        lexical_terms=terms,
        semantic_queries=tuple(variants),
        intent_class=intent_class,
    )


def normalize_client_intent_values(
    values: list[str] | tuple[str, ...],
    *,
    max_items: int,
    max_chars: int,
) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values[:max_items]:
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("intent values must be non-empty, bounded text without control characters")
        clean = normalize_search_query(value)
        if not clean or len(clean) > max_chars:
            raise ValueError("intent values must be non-empty, bounded text without control characters")
        key = clean.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(clean)
    return tuple(normalized)


def client_intent_preserves_protected_tokens(
    query: str,
    lexical_terms: tuple[str, ...],
    semantic_queries: tuple[str, ...],
) -> bool:
    protected = {
        token.casefold()
        for token in TECHNICAL_TOKEN_RE.findall(normalize_search_query(query))
        if token.casefold() in _PROTECTED_PROJECT_TOKENS
    }
    output_tokens = {
        token.casefold()
        for token in TECHNICAL_TOKEN_RE.findall(
            " ".join((*lexical_terms, *semantic_queries))
        )
    }
    return protected.issubset(output_tokens)


def build_client_project_search_intent(
    query: str,
    payload: Mapping[str, Any],
) -> ProjectSearchIntent:
    deterministic = build_project_search_intent(query)
    lexical_terms = normalize_client_intent_values(
        list(payload.get("lexical_terms") or ()),
        max_items=8,
        max_chars=40,
    )
    semantic_queries = normalize_client_intent_values(
        list(payload.get("semantic_queries") or ()),
        max_items=3,
        max_chars=120,
    )
    if not lexical_terms or not semantic_queries:
        raise ValueError("client intent requires lexical_terms and semantic_queries")
    if not client_intent_preserves_protected_tokens(
        deterministic.normalized_query,
        lexical_terms,
        semantic_queries,
    ):
        raise ValueError("client intent must preserve protected technical tokens from q")
    return ProjectSearchIntent(
        schema_version="project-search-intent-client-v1",
        normalized_query=deterministic.normalized_query,
        language=payload["language"],
        lexical_terms=lexical_terms,
        semantic_queries=semantic_queries,
        intent_class=payload.get("intent_class", "general_discovery"),
        topics=normalize_client_intent_values(
            list(payload.get("topics") or ()), max_items=6, max_chars=40
        ),
        languages=normalize_client_intent_values(
            list(payload.get("languages") or ()), max_items=3, max_chars=30
        ),
        artifact_types=normalize_client_intent_values(
            list(payload.get("artifact_types") or ()), max_items=6, max_chars=40
        ),
        must_have=normalize_client_intent_values(
            list(payload.get("must_have") or ()), max_items=6, max_chars=40
        ),
        should_have=normalize_client_intent_values(
            list(payload.get("should_have") or ()), max_items=8, max_chars=40
        ),
    )


def escape_like_literal(value: str, *, escape: str = "=") -> str:
    return value.replace(escape, escape * 2).replace("%", f"{escape}%").replace("_", f"{escape}_")
