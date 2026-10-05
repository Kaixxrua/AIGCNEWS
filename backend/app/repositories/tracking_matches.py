"""Read existing public documents/catalog only; never fetch arbitrary URLs."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from backend.app.domain.project_visibility import PUBLIC_PROJECT_MIN_STARS
from backend.app.domain.tracking import CST, DIGEST_ITEM_LIMIT, clean_item
from backend.app.domain.tracking_terms import english_equivalents

# X 帖子另存中文译文，中文关键词也能命中英文原帖。
_HAYSTACK = "concat_ws(' ', title, summary, translation_zh)"


def _timestamp(column: str) -> str:
    # Legacy dates are text. PostgreSQL 16 validates malformed dates before casts.
    return f"CASE WHEN pg_input_is_valid({column}, 'timestamptz') THEN {column}::timestamptz END"


def _literal_pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _text_match(term: str, *, exclude: bool = False) -> tuple[str, list[str]]:
    if term.isascii() and any(char.isalpha() for char in term):
        # ASCII word edges reject storage/coverage for RAG while allowing RAG系统.
        # Escape metacharacters: user input is always literal, never a regex.
        checks = [("~*", r"(^|[^a-z0-9_])" + re.escape(term) + r"($|[^a-z0-9_])")]
    else:
        # Chinese and other non-ASCII phrases retain substring matching.
        checks = [("ILIKE", _literal_pattern(term))]
    if aliases := english_equivalents(term):
        # 中文词整词在词表里时也匹配英文同义词：同样守词边界，允许复数 s。
        alternatives = "|".join(re.escape(alias) for alias in aliases)
        checks.append(("~*", r"(^|[^a-z0-9_])(" + alternatives + r")s?($|[^a-z0-9_])"))
    predicate = "(" + " OR ".join(f"{_HAYSTACK} {operator} %s" for operator, _ in checks) + ")"
    return ("NOT " + predicate if exclude else predicate), [pattern for _, pattern in checks]


def _match_query(
    rule: dict[str, Any], *, user_id: int, since: datetime, until: datetime, include_seen: bool,
) -> tuple[str, list[Any]]:
    params: list[Any] = []
    if rule["kind"] == "project":
        timestamp = _timestamp("m.updated_at")
        base = f"""
            SELECT 'growth:' || g.repo_id || ':' || m.metric_date AS key,
                   g.full_name AS title, g.url,
                   m.metric_date || ' · Stars +' || m.daily_star_growth::text AS summary,
                   NULL::text AS translation_zh, 'github' AS source, {timestamp} AS observed_at
            FROM github_repo_candidates g
            JOIN github_repo_daily_metrics m ON m.repo_id = g.repo_id
            WHERE lower(g.full_name) = lower(%s) AND m.daily_growth_available
              AND m.daily_star_growth >= %s AND g.stars >= {PUBLIC_PROJECT_MIN_STARS}
              AND m.metric_date >= %s AND m.metric_date <= %s
        """
        params.extend([rule["query"], rule["star_threshold"], since.astimezone(CST).date().isoformat(), until.astimezone(CST).date().isoformat()])
    else:
        base = f"""
            SELECT 'document:' || d.id AS key, d.title, d.url, d.summary, d.translation_zh, d.source,
                   {_timestamp("d.created_at")} AS observed_at
            FROM documents d
            WHERE d.source IN ('arxiv', 'news', 'producthunt', 'hackernews', 'x', 'dailyhot')
            UNION ALL
            SELECT 'project:' || g.repo_id AS key, g.full_name AS title, g.url,
                   concat_ws(' ', e.description_zh, g.description) AS summary, NULL::text AS translation_zh,
                   'github' AS source, GREATEST({_timestamp("g.first_seen_at")}, {_timestamp("e.enriched_at")}) AS observed_at
            FROM github_repo_candidates g
            JOIN github_repo_enrichments e ON e.repo_id = g.repo_id
            WHERE g.stars >= {PUBLIC_PROJECT_MIN_STARS} AND e.status = 'succeeded'
              AND NOT EXISTS (SELECT 1 FROM github_repo_quarantine gq WHERE gq.repo_id = g.repo_id)
        """
    window = ["observed_at > %s", "observed_at <= %s"]
    params.extend([since, until])
    if rule["source"] != "all":
        window.append("source = %s")
        params.append(rule["source"])
    filters: list[str] = []
    terms = [(term, False) for term in rule["query"].split()] if rule["kind"] == "keyword" else []
    for term, exclude in (*terms, *((term, True) for term in rule["excludes"])):
        predicate, patterns = _text_match(term, exclude=exclude)
        filters.append(predicate)
        params.extend(patterns)
    if not include_seen:
        filters.append("NOT EXISTS (SELECT 1 FROM tracking_seen s WHERE s.user_id = %s AND s.item_key = content.key)")
        params.append(user_id)
    # Window first: MATERIALIZED keeps the planner from running the text patterns over every row.
    query = f"WITH content AS MATERIALIZED (SELECT * FROM ({base}) windowed WHERE {' AND '.join(window)}) SELECT * FROM content"
    return (f"{query} WHERE {' AND '.join(filters)}" if filters else query), params


def find_matches(
    connection: Any, rule: dict[str, Any], *, user_id: int,
    since: datetime, until: datetime, include_seen: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    query, params = _match_query(rule, user_id=user_id, since=since, until=until, include_seen=include_seen)
    rows = connection.execute(
        f"{query} ORDER BY observed_at DESC, key LIMIT %s", (*params, DIGEST_ITEM_LIMIT + 1),
    ).fetchall()
    items = [item for row in rows if (item := clean_item(dict(row), rule["query"])) is not None]
    return items[:DIGEST_ITEM_LIMIT], len(rows) > DIGEST_ITEM_LIMIT


def count_matches(
    connection: Any, rule: dict[str, Any], *, user_id: int,
    since: datetime, until: datetime, include_seen: bool = False,
) -> dict[str, int]:
    """与 find_matches 同一条件按来源计数，不受 50 条上限影响。"""
    query, params = _match_query(rule, user_id=user_id, since=since, until=until, include_seen=include_seen)
    rows = connection.execute(
        f"SELECT source, count(*) AS total FROM ({query}) matched GROUP BY source", params,
    ).fetchall()
    return {str(row["source"]): int(row["total"]) for row in rows}
