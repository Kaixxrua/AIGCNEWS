from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping

from backend.app.domain.project_search_concepts import (
    PROJECT_CONCEPT_LEXICON as _PROJECT_CONCEPT_LEXICON,
    ProjectConceptSpec as _ProjectConceptSpec,
)

if TYPE_CHECKING:
    from backend.app.repositories.project_catalog import ProjectLexicalRetrievalPlan

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
_PROJECT_QUERY_FILLERS = frozenset({
    "学习", "提升", "的", "和", "与", "及", "以及", "的项目", "的仓库", "的工具",
})


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
    concept_ids: tuple[str, ...] = ()
    bilingual_aliases: tuple[str, ...] = ()


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


def _ascii_phrase_boundary_ok(folded: str, start: int, end: int) -> bool:
    """纯 ASCII 触发词的词边界守卫：相邻字符若是 ASCII 字母/数字/下划线则拒绝命中。

    防止 cli 命中 client、git 命中 digital、otel 命中 hotel；中文邻居不拦截，
    因此 "部署mcp服务" 这类中英混排查询仍能命中 ASCII 触发词。
    """
    for neighbor in (
        folded[start - 1] if start > 0 else "",
        folded[end] if end < len(folded) else "",
    ):
        if neighbor and neighbor.isascii() and (neighbor.isalnum() or neighbor == "_"):
            return False
    return True


def _project_concept_matches(
    value: str,
    *,
    max_concepts: int = 8,
) -> tuple[tuple[int, str, _ProjectConceptSpec], ...]:
    candidates: list[tuple[int, int, str, _ProjectConceptSpec]] = []
    folded = value.casefold()
    for spec in _PROJECT_CONCEPT_LEXICON:
        for phrase in spec.phrases:
            needle = phrase.casefold()
            needs_boundary = needle.isascii()
            start = folded.find(needle)
            while start >= 0:
                end = start + len(needle)
                if not needs_boundary or _ascii_phrase_boundary_ok(folded, start, end):
                    candidates.append((start, end, phrase, spec))
                start = folded.find(needle, start + 1)
    occupied: list[tuple[int, int]] = []
    selected: list[tuple[int, str, _ProjectConceptSpec]] = []
    seen: set[str] = set()
    for start, end, phrase, spec in sorted(
        candidates,
        key=lambda item: (-(item[1] - item[0]), item[0], item[3].concept_id),
    ):
        if spec.concept_id in seen or any(start < stop and end > begin for begin, stop in occupied):
            continue
        seen.add(spec.concept_id)
        occupied.append((start, end))
        selected.append((start, value[start:end] or phrase, spec))
        if len(selected) >= max(1, max_concepts):
            break
    return tuple(sorted(selected, key=lambda item: item[0]))


def han_concept_english_aliases() -> dict[str, tuple[str, ...]]:
    """中文触发词（NFKC 后 casefold）→ 所属概念的英文别名，按概念表顺序去重。

    供关键词追踪做整词中译英扩展；项目搜索不经过这里，行为不变。
    """
    mapping: dict[str, list[str]] = {}
    for spec in _PROJECT_CONCEPT_LEXICON:
        english = [alias for alias in spec.aliases if alias.isascii()]
        for phrase in spec.phrases:
            if not _HAN_RE.search(phrase):
                continue
            bucket = mapping.setdefault(unicodedata.normalize("NFKC", phrase).casefold(), [])
            bucket.extend(alias for alias in english if alias not in bucket)
    return {phrase: tuple(aliases) for phrase, aliases in mapping.items() if aliases}


def _project_literal_terms(
    value: str,
    matches: tuple[tuple[int, str, _ProjectConceptSpec], ...],
) -> list[tuple[int, str]]:
    # Mask only recognized concepts, preserving unknown Han names beside them.
    uncovered = list(value)
    for start, phrase, _ in matches:
        uncovered[start:start + len(phrase)] = " " * len(phrase)
    for token in TECHNICAL_TOKEN_RE.finditer(value):
        if not _HAN_RE.search(token.group()) and any(
            token.start() < start + len(phrase) and token.end() > start
            for start, phrase, _ in matches
        ):
            uncovered[token.start():token.end()] = " " * len(token.group())
    terms: list[tuple[int, str]] = []
    for match in TECHNICAL_TOKEN_RE.finditer("".join(uncovered)):
        token = match.group(0)
        if token.casefold() in _PROJECT_TRANSPORT_TERMS or token in _PROJECT_QUERY_FILLERS:
            continue
        terms.append((match.start(), token))
    return terms


def _project_intent_terms(
    value: str,
    matches: tuple[tuple[int, str, _ProjectConceptSpec], ...],
    *,
    max_terms: int = 8,
) -> tuple[str, ...]:
    terms = [
        *((start, phrase) for start, phrase, _ in matches),
        *_project_literal_terms(value, matches),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for _, term in sorted(terms, key=lambda item: item[0]):
        key = term.casefold()
        if key in seen or (len(term) == 1 and not term.isdigit()):
            continue
        seen.add(key)
        result.append(term)
        if len(result) >= max(1, max_terms):
            break
    return tuple(result or project_search_terms(value, max_terms=max_terms))


def build_project_lexical_retrieval_plan(
    intent: ProjectSearchIntent,
) -> ProjectLexicalRetrievalPlan:
    from backend.app.repositories.project_catalog import (
        ProjectLexicalConcept,
        ProjectLexicalRetrievalPlan,
    )

    inputs = [intent.normalized_query]
    if intent.schema_version == "project-search-intent-client-v1":
        inputs.extend(intent.lexical_terms)
    concepts: dict[str, ProjectLexicalConcept] = {}
    literal_terms: dict[str, str] = {}
    for value in inputs:
        matches = _project_concept_matches(value)
        for _, phrase, spec in matches:
            concepts.setdefault(spec.concept_id, ProjectLexicalConcept(
                concept_id=spec.concept_id, primary_terms=(phrase,), aliases=spec.aliases,
            ))
        for _, term in _project_literal_terms(value, matches):
            if term.casefold() != "ai":
                literal_terms.setdefault(term.casefold(), term)
    return ProjectLexicalRetrievalPlan(
        normalized_query=intent.normalized_query,
        strict_terms=tuple(literal_terms.values()),
        concepts=tuple(concepts.values()),
    )


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
    concept_matches = _project_concept_matches(cleaned)
    aliases = tuple(
        alias
        for _, _, spec in concept_matches
        for alias in (spec.aliases if len(concept_matches) == 1 else spec.aliases[:1])
    )
    expanded = cleaned
    compact_aliases: list[str] = []
    alias_seen: set[str] = set()
    for alias in aliases:
        key = alias.casefold()
        if key not in expanded.casefold() and key not in alias_seen:
            alias_seen.add(key)
            compact_aliases.append(alias)
    if compact_aliases:
        expanded = f"{expanded} {' '.join(compact_aliases)}"
    variants: list[str] = []
    seen: set[str] = set()
    for query in (cleaned, normalize_search_query(expanded)):
        bounded = query[:max_chars].rstrip()
        key = bounded.casefold()
        if bounded and key not in seen:
            seen.add(key)
            variants.append(bounded)
    terms = _project_intent_terms(cleaned, concept_matches)
    lowered = cleaned.casefold()
    intent_class: ProjectIntentClass = "general_discovery"
    raw_terms = tuple(project_search_terms(cleaned))
    if "/" in cleaned or (
        len(raw_terms) == 1
        and raw_terms[0].casefold() == cleaned.casefold()
        and not concept_matches
    ):
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
        concept_ids=tuple(spec.concept_id for _, _, spec in concept_matches),
        bilingual_aliases=tuple(compact_aliases),
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
        concept_ids=deterministic.concept_ids,
        bilingual_aliases=deterministic.bilingual_aliases,
    )


def escape_like_literal(value: str, *, escape: str = "=") -> str:
    return value.replace(escape, escape * 2).replace("%", f"{escape}%").replace("_", f"{escape}_")
