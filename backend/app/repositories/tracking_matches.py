"""Read existing public documents/catalog only; never fetch arbitrary URLs."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from backend.app.domain.project_visibility import PUBLIC_PROJECT_MIN_STARS
from backend.app.domain.tracking import CST, DIGEST_ITEM_LIMIT, clean_item


def _timestamp(column: str) -> str:
    # Legacy dates are text. PostgreSQL 16 validates malformed dates before casts.
    return f"CASE WHEN pg_input_is_valid({column}, 'timestamptz') THEN {column}::timestamptz END"


def _literal_pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _text_match(term: str, *, exclude: bool = False) -> tuple[str, str]:
    if term.isascii() and any(char.isalpha() for char in term):
        # ASCII word edges reject storage/coverage for RAG while allowing RAG系统.
        # Escape metacharacters: user input is always literal, never a regex.
        pattern = r"(^|[^a-z0-9_])" + re.escape(term) + r"($|[^a-z0-9_])"
        operator = "!~*" if exclude else "~*"
    else:
        # Chinese and other non-ASCII phrases retain substring matching.
        pattern = _literal_pattern(term)
        operator = "NOT ILIKE" if exclude else "ILIKE"
    return f"concat_ws(' ', title, summary) {operator} %s", pattern


def find_matches(
    connection: Any, rule: dict[str, Any], *, user_id: int,
    since: datetime, until: datetime, include_seen: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    params: list[Any] = []
    if rule["kind"] == "project":
        timestamp = _timestamp("m.updated_at")
        base = f"""
            SELECT 'growth:' || g.repo_id || ':' || m.metric_date AS key,
                   g.full_name AS title, g.url,
                   m.metric_date || ' · Stars +' || m.daily_star_growth::text AS summary,
                   'github' AS source, {timestamp} AS observed_at
            FROM github_repo_candidates g
            JOIN github_repo_daily_metrics m ON m.repo_id = g.repo_id
            WHERE lower(g.full_name) = lower(%s) AND m.daily_growth_available
              AND m.daily_star_growth >= %s AND g.stars >= {PUBLIC_PROJECT_MIN_STARS}
              AND m.metric_date >= %s AND m.metric_date <= %s
        """
        params.extend([rule["query"], rule["star_threshold"], since.astimezone(CST).date().isoformat(), until.astimezone(CST).date().isoformat()])
    else:
        base = f"""
            SELECT 'document:' || d.id AS key, d.title, d.url, d.summary, d.source,
                   {_timestamp("d.created_at")} AS observed_at
            FROM documents d
            WHERE d.source IN ('arxiv', 'news', 'producthunt', 'hackernews', 'x', 'dailyhot')
            UNION ALL
            SELECT 'project:' || g.repo_id AS key, g.full_name AS title, g.url,
                   concat_ws(' ', e.description_zh, g.description) AS summary,
                   'github' AS source, GREATEST({_timestamp("g.first_seen_at")}, {_timestamp("e.enriched_at")}) AS observed_at
            FROM github_repo_candidates g
            JOIN github_repo_enrichments e ON e.repo_id = g.repo_id
            WHERE g.stars >= {PUBLIC_PROJECT_MIN_STARS} AND e.status = 'succeeded'
              AND NOT EXISTS (SELECT 1 FROM github_repo_quarantine gq WHERE gq.repo_id = g.repo_id)
        """
    filters = ["observed_at > %s", "observed_at <= %s"]
    params.extend([since, until])
    if rule["source"] != "all":
        filters.append("source = %s")
        params.append(rule["source"])
    if rule["kind"] == "keyword":
        for term in rule["query"].split():
            predicate, pattern = _text_match(term)
            filters.append(predicate)
            params.append(pattern)
    for term in rule["excludes"]:
        predicate, pattern = _text_match(term, exclude=True)
        filters.append(predicate)
        params.append(pattern)
    if not include_seen:
        filters.append("NOT EXISTS (SELECT 1 FROM tracking_seen s WHERE s.user_id = %s AND s.item_key = content.key)")
        params.append(user_id)
    rows = connection.execute(
        f"SELECT * FROM ({base}) content WHERE {' AND '.join(filters)} ORDER BY observed_at DESC, key LIMIT %s",
        (*params, DIGEST_ITEM_LIMIT + 1),
    ).fetchall()
    items = [item for row in rows if (item := clean_item(dict(row), rule["query"])) is not None]
    return items[:DIGEST_ITEM_LIMIT], len(rows) > DIGEST_ITEM_LIMIT
