from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.app.domain.project_taxonomy import (
    CATEGORY_BY_SLUG,
    DEFAULT_SUBCATEGORY_BY_CATEGORY,
    ENGLISH_LABEL_BY_SLUG,
    PROJECT_TAXONOMY,
    SUBCATEGORY_BY_CATEGORY_SLUG,
    WEBSITE_CATEGORY_BY_SLUG,
    WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
    WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG,
)


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def normalize_project_row(row: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the public project catalog row shape without coupling adapters."""
    item = dict(row)
    # Keep the nullable response field for clients, but never expose retired data.
    item.pop("assessment_json", None)
    item["assessment"] = None
    item["topics"] = _json_list(item.pop("topics_json", None))
    tags = _json_list(item.pop("tags_json", None))
    tags_zh = _json_list(item.pop("tags_zh_json", None))
    tags_en = _json_list(item.pop("tags_en_json", None))
    tags_origin = "user" if item.pop("tags_origin", None) == "user" else "system"
    item["tags"] = tags
    item["tags_zh"] = [] if tags_origin == "user" else (tags_zh or tags)
    item["tags_en"] = [] if tags_origin == "user" else tags_en
    item["tags_origin"] = tags_origin
    for key in ("stars", "forks", "watchers", "open_issues", "daily_star_growth"):
        item[key] = _integer(item.get(key))
    item["rank_in_period"] = _integer(item.get("rank_in_period")) or None
    for key in (
        "raw_score", "score", "confidence", "hot_score",
        "scale_corrected_growth_score", "growth_acceleration_score",
        "absolute_growth_score", "maintenance_activity_score",
        "community_engagement_score",
    ):
        item[key] = _number(item.get(key))
    item["daily_growth_available"] = bool(_integer(item.get("daily_growth_available")))
    item["daily_growth_source"] = str(item.get("daily_growth_source") or "unavailable")
    # 滚动 24h 星增保留 NULL：NULL 表示取不到窗口起点，与「涨了 0」不同。
    rolling = item.get("rolling_24h_star_growth")
    item["rolling_24h_star_growth"] = None if rolling is None else _integer(rolling)
    item["rolling_24h_growth_source"] = item.get("rolling_24h_growth_source") or None
    item["availability_status"] = (
        "not_found" if item.get("availability_status") == "not_found" else "active"
    )
    for key in (
        "daily_growth_observed_at", "rolling_24h_observed_at",
        "favorited_at", "recommended_at", "user_added_at",
    ):
        item[key] = _iso(item.get(key))
    for key in ("is_favorited", "is_recommended", "user_added"):
        item[key] = bool(item.get(key))

    website = item.get("source") == "website"
    category_names = WEBSITE_CATEGORY_BY_SLUG if website else CATEGORY_BY_SLUG
    subcategory_names = WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG if website else SUBCATEGORY_BY_CATEGORY_SLUG
    defaults = WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY if website else DEFAULT_SUBCATEGORY_BY_CATEGORY
    category_slug = item.get("category_slug") or "other"
    subcategory_slug = item.get("subcategory_slug") or defaults.get(category_slug, "")
    item["category_slug"] = category_slug
    item["subcategory_slug"] = subcategory_slug
    category_name_zh = category_names.get(
        category_slug, item.get("category_name_zh") or item.get("category_name") or ("其他网站" if website else "其他")
    )
    subcategory_name_zh = subcategory_names.get(category_slug, {}).get(
        subcategory_slug, item.get("subcategory_name_zh") or item.get("subcategory_name") or "未分类"
    )
    item["category_name_zh"] = category_name_zh
    item["category_name_en"] = item.get("category_name_en") or ENGLISH_LABEL_BY_SLUG.get(category_slug, "Other")
    item["subcategory_name_zh"] = subcategory_name_zh
    item["subcategory_name_en"] = item.get("subcategory_name_en") or ENGLISH_LABEL_BY_SLUG.get(subcategory_slug, "Uncategorized")
    # Generic aliases remain Chinese until consumers explicitly select a locale.
    item["category_name"] = category_name_zh
    item["subcategory_name"] = subcategory_name_zh
    return item


def format_project_category_counts(
    rows: list[dict[str, Any]],
    today_count: int = 0,
    *,
    taxonomy: list[dict[str, Any]] | None = None,
    recommended_count: int = 0,
) -> dict[str, Any]:
    """Format aggregate rows exactly like the compatibility repository."""
    active = taxonomy or PROJECT_TAXONOMY
    by_slug = {item["slug"]: item for item in active}
    defaults: dict[str, dict[str, str]] = {}
    for category in active:
        children = category.get("children", [])
        if children:
            defaults[category["slug"]] = next((child for child in children if child.get("default")), children[-1])

    category_counts: dict[str, int] = {}
    category_names: dict[str, str] = {}
    child_counts: dict[tuple[str, str], int] = {}
    child_names: dict[tuple[str, str], str] = {}
    for row in rows:
        slug = row.get("category_slug") or "other"
        name = row.get("category_name") or by_slug.get(slug, {}).get("name") or "其他"
        count = int(row.get("count") or 0)
        child_slug = row.get("subcategory_slug") or ""
        child_name = row.get("subcategory_name") or ""
        if not child_slug:
            child = defaults.get(slug) or defaults.get("other")
            if child:
                child_slug, child_name = child["slug"], child["name"]
        category_counts[slug] = category_counts.get(slug, 0) + count
        category_names[slug] = name
        if child_slug:
            key = (slug, child_slug)
            child_counts[key] = child_counts.get(key, 0) + count
            child_names[key] = child_name or child_slug

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in active:
        slug = category["slug"]
        seen.add(slug)
        items.append({
            "slug": slug, "name": category["name_zh"], "name_zh": category["name_zh"],
            "name_en": category["name_en"], "count": category_counts.get(slug, 0),
            "kind": "category",
            "children": [{"slug": child["slug"], "name": child["name_zh"], "name_zh": child["name_zh"], "name_en": child["name_en"], "count": child_counts.get((slug, child["slug"]), 0)} for child in category.get("children", [])],
        })
    for slug in sorted((key for key in category_counts if key not in seen), key=lambda key: (-category_counts[key], category_names.get(key, key))):
        children = [
            {"slug": child, "name": child_names.get((slug, child), child), "name_zh": child_names.get((slug, child), child), "name_en": ENGLISH_LABEL_BY_SLUG.get(child, child), "count": count}
            for (parent, child), count in child_counts.items() if parent == slug
        ]
        name_zh = category_names.get(slug, "其他")
        items.append({"slug": slug, "name": name_zh, "name_zh": name_zh, "name_en": ENGLISH_LABEL_BY_SLUG.get(slug, "Other"), "count": category_counts[slug], "kind": "category", "children": children})
    return {"items": items, "total": sum(category_counts.values()), "today_count": int(today_count or 0), "recommended_count": int(recommended_count or 0)}
