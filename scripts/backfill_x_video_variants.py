#!/usr/bin/env python3
"""Backfill advertised playback URLs in recent X media; default is dry-run.

Run inside the backend environment after deployment. Original URLs and all other
metadata are preserved. Concurrent ingestion wins via compare-and-swap updates.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.services.x_video_variants import select_playback_url  # noqa: E402


def variant_mapping(payload: Any) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if isinstance(payload, dict):
        info = payload.get("video_info")
        if isinstance(info, dict):
            variants = info.get("variants")
            selected = select_playback_url(variants)
            if selected:
                for variant in variants:
                    if isinstance(variant, dict) and isinstance(variant.get("url"), str):
                        mapping[variant["url"]] = selected
        for value in payload.values():
            mapping.update(variant_mapping(value))
    elif isinstance(payload, list):
        for value in payload:
            mapping.update(variant_mapping(value))
    return mapping


def rewrite_media(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [rewrite_media(item, mapping) for item in value]
    if isinstance(value, dict):
        result = {key: rewrite_media(item, mapping) for key, item in value.items()}
        if value.get("type") in ("video", "animated_gif") and value.get("url") in mapping:
            result["playback_url"] = mapping[value["url"]]
        return result
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--hours", type=int, default=48)
    args = parser.parse_args()
    if not 1 <= args.hours <= 720:
        parser.error("hours must be between 1 and 720")
    if not 1 <= args.limit <= 1000:
        parser.error("limit must be between 1 and 1000")
    from backend.app.core.postgres_database import postgres_database
    from backend.app.repositories.postgres_x_credentials_repository import PostgresXCredentialRepository
    from backend.app.services.ingestion.sources.x_transport import XTransport, _fetch_tweet_result_raw

    repository = PostgresXCredentialRepository(postgres_database)
    client = XTransport(credential_provider=repository.list_enabled_x_credentials)._translation_client()
    with postgres_database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, url, media, quote FROM documents WHERE source = 'x' "
                "AND published_at >= %s "
                "AND (media LIKE %s OR quote LIKE %s) ORDER BY published_at DESC LIMIT %s",
                ((datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat(),
                 '%video.twimg.com%', '%video.twimg.com%', args.limit),
            )
            rows = list(cursor.fetchall())
    changed = 0
    fetched: set[str] = set()
    mapping: dict[str, str] = {}
    for row in rows:
        fields = {key: json.loads(row[key]) if row[key] else None for key in ('media', 'quote')}
        urls = [row['url'], (fields['quote'] or {}).get('url', '')]
        for url in urls:
            match = re.search(r'/status/(\d+)', url or '')
            if not match or match[1] in fetched:
                continue
            if fetched:
                time.sleep(2)
            # Fail closed on authentication / rate-limit errors; never print payloads or cookies.
            try:
                for attempt in range(2):
                    try:
                        payload = _fetch_tweet_result_raw(client, match[1])
                        mapping.update(variant_mapping(payload))
                        break
                    except Exception as exc:
                        status = getattr(exc, "status_code", 0) or 0
                        if (attempt or status in (401, 403, 429)
                                or type(exc).__name__ in ("AuthenticationError", "RateLimitError")
                                or 400 <= status < 500):
                            raise
                        time.sleep(3)
            except Exception as exc:
                print(f"stopped: {type(exc).__name__} status={getattr(exc, 'status_code', None)}", flush=True)
                return 1
            fetched.add(match[1])
        for key, value in fields.items():
            updated = rewrite_media(value, mapping)
            if updated == value:
                continue
            encoded = json.dumps(updated, ensure_ascii=False)
            if args.apply:
                with postgres_database.transaction() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"UPDATE documents SET {key} = %s WHERE id = %s AND {key} = %s",
                            (encoded, row['id'], row[key]),
                        )
                        changed += cursor.rowcount
            else:
                changed += 1
        print(f"processed={len(fetched)} changed_fields={changed} apply={args.apply}", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
