"""Owner-scoped tracking persistence with atomic quotas and delivery claims."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.tracking_matches import find_matches
from backend.app.services.tracking.policy import CST, DIGEST_ITEM_LIMIT, TrackingError, active_rules, rule_limit

_RULE_FIELDS = "id, kind, query, source, excludes, star_threshold, enabled, created_at"
_DIGEST_FIELDS = "id, issue_date, items, truncated, delivery_status, created_at"


class PostgresTrackingRepository:
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    @staticmethod
    def _user(connection: Any, user_id: int, *, lock: bool = False) -> dict[str, Any]:
        row = connection.execute(
            "SELECT id, membership_tier, membership_expires_at FROM users "
            "WHERE id = %s AND NOT disabled" + (" FOR UPDATE" if lock else ""),
            (user_id,),
        ).fetchone()
        if not row:
            raise TrackingError("unauthorized", 401)
        return dict(row)

    @staticmethod
    def _rules(connection: Any, user_id: int) -> list[dict[str, Any]]:
        return [dict(row) for row in connection.execute(
            f"SELECT {_RULE_FIELDS} FROM tracking_rules WHERE user_id = %s ORDER BY id", (user_id,),
        ).fetchall()]

    @staticmethod
    def _channel(connection: Any, user_id: int, channel_id: int | None) -> dict[str, Any] | None:
        if channel_id is None:
            return None
        row = connection.execute(
            "SELECT * FROM push_channels WHERE user_id = %s AND id = %s "
            "AND verified AND status = 'active' AND channel_type IN ('email', 'webhook', 'discord', 'telegram')",
            (user_id, channel_id),
        ).fetchone()
        if not row:
            raise TrackingError("channel_unavailable", 400)
        return dict(row)

    def overview(self, user_id: int) -> dict[str, Any]:
        with self._database.transaction() as connection:
            user = self._user(connection, user_id)
            rules = self._rules(connection, user_id)
            row = connection.execute(
                "SELECT enabled, delivery_hour, channel_id, last_checked_at FROM tracking_settings WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            settings = dict(row) if row else {
                "enabled": True, "delivery_hour": 8, "channel_id": None, "last_checked_at": None,
            }
            limit = rule_limit(user)
            active_ids = {rule["id"] for rule in active_rules(rules, limit)} if settings["enabled"] else set()
            digests = connection.execute(
                f"SELECT {_DIGEST_FIELDS} FROM tracking_digests WHERE user_id = %s ORDER BY issue_date DESC LIMIT 7",
                (user_id,),
            ).fetchall()
            return {
                "limit": limit, "rules": [{**rule, "active": rule["id"] in active_ids} for rule in rules],
                "settings": settings, "digests": [dict(row) for row in digests],
            }

    def save_rule(self, user_id: int, values: dict[str, Any], rule_id: int | None = None) -> None:
        with self._database.transaction() as connection:
            user = self._user(connection, user_id, lock=True)
            rules = self._rules(connection, user_id)
            if rule_id is None and len(rules) >= rule_limit(user):
                raise TrackingError("rule_limit", 409)
            if rule_id is not None and not any(row["id"] == rule_id for row in rules):
                raise TrackingError("rule_not_found", 404)
            connection.execute(
                "INSERT INTO tracking_settings (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,),
            )
            params = (
                values["kind"], values["query"], values["source"], Jsonb(values["excludes"]),
                values["star_threshold"], values["enabled"], user_id,
            )
            if rule_id is None:
                connection.execute(
                    "INSERT INTO tracking_rules (kind, query, source, excludes, star_threshold, enabled, user_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)", params,
                )
            else:
                connection.execute(
                    "UPDATE tracking_rules SET kind = %s, query = %s, source = %s, excludes = %s, "
                    "star_threshold = %s, enabled = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND id = %s",
                    (*params, rule_id),
                )

    @staticmethod
    def _unread(connection: Any, user_id: int) -> dict[str, Any]:
        # One snapshot, indexed lookup, no digest content or matching work.
        row = connection.execute(
            "SELECT COALESCE((SELECT id FROM tracking_digests WHERE user_id = %s "
            "ORDER BY id DESC LIMIT 1), 0) AS latest_digest_id, "
            "COALESCE((SELECT last_read_digest_id FROM tracking_settings WHERE user_id = %s), 0) "
            "AS last_read_digest_id", (user_id, user_id),
        ).fetchone()
        return {**dict(row), "unread": row["latest_digest_id"] > row["last_read_digest_id"]}

    def unread(self, user_id: int) -> dict[str, Any]:
        with self._database.transaction() as connection:
            self._user(connection, user_id)
            return self._unread(connection, user_id)

    def mark_read(self, user_id: int, digest_id: int) -> dict[str, Any]:
        with self._database.transaction() as connection:
            self._user(connection, user_id)
            if not connection.execute(
                "SELECT id FROM tracking_digests WHERE user_id = %s AND id = %s",
                (user_id, digest_id),
            ).fetchone():
                raise TrackingError("digest_not_found", 404)
            # Never acknowledge a newer issue that arrived after the client's fetch.
            # Concurrent devices and retries can only move the cursor forwards.
            connection.execute(
                "INSERT INTO tracking_settings (user_id, last_read_digest_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET last_read_digest_id = "
                "GREATEST(tracking_settings.last_read_digest_id, EXCLUDED.last_read_digest_id)",
                (user_id, digest_id),
            )
            return self._unread(connection, user_id)

    def delete_rule(self, user_id: int, rule_id: int) -> None:
        with self._database.transaction() as connection:
            self._user(connection, user_id, lock=True)
            if not connection.execute(
                "DELETE FROM tracking_rules WHERE user_id = %s AND id = %s", (user_id, rule_id),
            ).rowcount:
                raise TrackingError("rule_not_found", 404)

    def save_settings(self, user_id: int, values: dict[str, Any]) -> None:
        with self._database.transaction() as connection:
            self._user(connection, user_id, lock=True)
            self._channel(connection, user_id, values["channel_id"])
            connection.execute(
                "INSERT INTO tracking_settings (user_id, enabled, delivery_hour, channel_id) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET enabled = EXCLUDED.enabled, "
                "delivery_hour = EXCLUDED.delivery_hour, channel_id = EXCLUDED.channel_id",
                (user_id, values["enabled"], values["delivery_hour"], values["channel_id"]),
            )
            # Changing/turning off delivery cannot reroute or resurrect old queued issues.
            connection.execute(
                "UPDATE tracking_digests SET delivery_status = 'cancelled' WHERE user_id = %s "
                "AND delivery_status = 'pending' AND (channel_id IS DISTINCT FROM %s OR NOT %s)",
                (user_id, values["channel_id"], values["enabled"]),
            )

    def preview(self, user_id: int, rule_id: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._database.transaction() as connection:
            user = self._user(connection, user_id)
            rules = self._rules(connection, user_id)
            rule = next((row for row in rules if row["id"] == rule_id), None)
            if rule is None:
                raise TrackingError("rule_not_found", 404)
            if rule_id not in {row["id"] for row in active_rules(rules, rule_limit(user))}:
                raise TrackingError("rule_inactive", 403)
            items, truncated = find_matches(
                connection, rule, user_id=user_id, since=now - timedelta(days=1), until=now, include_seen=True,
            )
            return {"items": items, "truncated": truncated}

    def due_users(self, now: datetime, after: int = 0) -> list[int]:
        local = now.astimezone(CST)
        with self._database.transaction() as connection:
            return [row["user_id"] for row in connection.execute(
                "SELECT s.user_id FROM tracking_settings s JOIN users u ON u.id = s.user_id "
                "WHERE s.enabled AND NOT u.disabled AND s.user_id > %s AND s.delivery_hour <= %s "
                "AND (s.last_checked_at IS NULL OR s.last_checked_at < %s) "
                "AND EXISTS (SELECT 1 FROM tracking_rules r WHERE r.user_id = s.user_id AND r.enabled) "
                "ORDER BY s.user_id LIMIT 100",
                (after, local.hour, local.replace(hour=0, minute=0, second=0, microsecond=0)),
            ).fetchall()]

    def generate_digest(self, user_id: int, now: datetime) -> dict[str, Any] | None:
        local = now.astimezone(CST)
        with self._database.transaction() as connection:
            settings = connection.execute(
                "SELECT * FROM tracking_settings WHERE user_id = %s FOR UPDATE SKIP LOCKED", (user_id,),
            ).fetchone()
            if not settings or not settings["enabled"] or local.hour < settings["delivery_hour"]:
                return None
            checked = settings["last_checked_at"]
            if checked and checked.astimezone(CST).date() >= local.date():
                return None
            user = self._user(connection, user_id)
            rules = active_rules(self._rules(connection, user_id), rule_limit(user, now))
            items_by_key: dict[str, dict[str, Any]] = {}
            truncated = False
            for rule in rules:
                since = max(checked or now - timedelta(days=1), now - timedelta(days=7))
                found, overflow = find_matches(connection, rule, user_id=user_id, since=since, until=now)
                truncated |= overflow
                for item in found:
                    if item["key"] in items_by_key:
                        labels = items_by_key[item["key"]]["matched_rules"]
                        if rule["query"] not in labels:
                            labels.append(rule["query"])
                    else:
                        items_by_key[item["key"]] = item
            items = sorted(items_by_key.values(), key=lambda item: item["observed_at"], reverse=True)
            truncated |= len(items) > DIGEST_ITEM_LIMIT
            items = items[:DIGEST_ITEM_LIMIT]
            connection.execute("UPDATE tracking_settings SET last_checked_at = %s WHERE user_id = %s", (now, user_id))
            # No matching news: advance the cursor, stay quiet, never send empty mail.
            if not items:
                return None
            channel_id = settings["channel_id"]
            try:
                self._channel(connection, user_id, channel_id)
            except TrackingError:
                channel_id = None
            row = connection.execute(
                f"INSERT INTO tracking_digests (user_id, issue_date, items, truncated, channel_id, delivery_status) "
                f"VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (user_id, issue_date) DO NOTHING RETURNING {_DIGEST_FIELDS}",
                (user_id, local.date(), Jsonb(items), truncated, channel_id, "pending" if channel_id else "none"),
            ).fetchone()
            if not row:
                return None
            for item in items:
                connection.execute(
                    "INSERT INTO tracking_seen (user_id, item_key, seen_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (user_id, item["key"], now),
                )
            connection.execute("DELETE FROM tracking_seen WHERE user_id = %s AND seen_at < %s", (user_id, now - timedelta(days=90)))
            connection.execute("DELETE FROM tracking_digests WHERE user_id = %s AND created_at < %s", (user_id, now - timedelta(days=90)))
            return dict(row)

    def claim_delivery(self, now: datetime) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tracking_digests WHERE delivery_status = 'pending' "
                "OR (delivery_status = 'sending' AND claimed_at < %s) "
                "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1", (now - timedelta(minutes=10),),
            ).fetchone()
            if not row:
                return None
            digest = dict(row)
            eligible = connection.execute(
                "SELECT s.channel_id FROM tracking_settings s JOIN users u ON u.id = s.user_id "
                "WHERE s.user_id = %s AND s.enabled AND NOT u.disabled "
                "AND s.channel_id = %s", (digest["user_id"], digest["channel_id"]),
            ).fetchone()
            channel = None
            if eligible:
                try:
                    channel = self._channel(connection, digest["user_id"], digest["channel_id"])
                except TrackingError:
                    pass
            if not channel or digest["created_at"] < now - timedelta(days=3) or digest["attempts"] >= 3:
                status = "failed" if digest["attempts"] >= 3 else "cancelled"
                connection.execute("UPDATE tracking_digests SET delivery_status = %s WHERE id = %s", (status, digest["id"]))
                return {"cancelled": True}
            connection.execute(
                "UPDATE tracking_digests SET delivery_status = 'sending', attempts = attempts + 1, claimed_at = %s WHERE id = %s",
                (now, digest["id"]),
            )
            return {**digest, "attempts": digest["attempts"] + 1, "channel": channel}

    def finish_delivery(self, digest_id: int, attempts: int, *, sent: bool) -> None:
        # Failure retries are spaced by the next scheduler run, using the same lease timeout.
        status = "sent" if sent else ("failed" if attempts >= 3 else "sending")
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE tracking_digests SET delivery_status = %s WHERE id = %s AND attempts = %s AND delivery_status = 'sending'",
                (status, digest_id, attempts),
            )
