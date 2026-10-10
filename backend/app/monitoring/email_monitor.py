"""Persisted five-minute email checks and incident notifications.

Resend usage is account-wide (including mail sent outside this application).
Recent provider events are a bounded sample, never a daily delivery total.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiosmtplib
import httpx

from backend.app.core.config import settings
from backend.app.repositories.postgres_email_monitor_repository import PostgresEmailMonitorRepository
from backend.app.services.email.pool_config_provider import resolve_email_pool_config
from backend.app.services.email.pool_transport import EmailPoolEntry, merge_legacy_entry, parse_email_pool_entries
from backend.app.services.email.smtp_config_provider import resolve_smtp_config
from backend.app.services.email.smtp_transport import SmtpTransport

logger = logging.getLogger(__name__)
RESEND_BASE = "https://api.resend.com"


def effective_entries() -> list[EmailPoolEntry]:
    smtp = resolve_smtp_config()
    entries = merge_legacy_entry(
        parse_email_pool_entries(
            resolve_email_pool_config().entries_json,
            default_from_email=smtp.from_email, default_from_name=smtp.from_name,
        ),
        host=smtp.host, port=smtp.port, username=smtp.username, password=smtp.password,
        from_email=smtp.from_email, from_name=smtp.from_name, use_tls=smtp.use_tls,
    )
    return entries or ([EmailPoolEntry(
        name="smtp", host=smtp.host, port=smtp.port, username=smtp.username,
        password=smtp.password, from_email=smtp.from_email, from_name=smtp.from_name,
        use_tls=smtp.use_tls,
    )] if smtp.host else [])


def ops_recipient() -> str:
    # Same recipient policy as scripts/notify_ops_alert.py, using live DB SMTP.
    return settings.AIGCNEWS_OPS_ALERT_TO.strip() or resolve_smtp_config().from_email.strip()


def mask_address(address: str) -> str:
    local, sep, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if sep else "—"


def transport(entry: EmailPoolEntry) -> SmtpTransport:
    return SmtpTransport(
        host=entry.host, port=entry.port, username=entry.username, password=entry.password,
        from_email=entry.from_email, from_name=entry.from_name, use_tls=entry.use_tls,
    )


def is_resend(entry: EmailPoolEntry) -> bool:
    return entry.host.strip().lower() == "smtp.resend.com"


async def probe_smtp(entry: EmailPoolEntry) -> dict:
    implicit, starttls = transport(entry).tls_options()
    client = aiosmtplib.SMTP(
        hostname=entry.host, port=entry.port, use_tls=implicit,
        start_tls=starttls, timeout=10,
    )
    try:
        async with asyncio.timeout(15):
            await client.connect()
            if entry.username:
                await client.login(entry.username, entry.password)
            await client.noop()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "failed", "error": type(exc).__name__}
    finally:
        client.close()


def parse_usage(payload: dict) -> dict:
    result = {}
    for period in ("daily", "monthly"):
        value = payload["emails"][period]
        used, limit, resets = value["used"], value["limit"], value["resets_at"]
        if type(used) is not int or used < 0 or (
            limit is not None and (type(limit) is not int or limit < 0)
        ):
            raise ValueError("invalid quota")
        if datetime.fromisoformat(resets.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("invalid reset time")
        result[period] = {"used": used, "limit": limit, "resets_at": resets}
    return result


def quota_condition(quota: dict) -> dict | None:
    limit, used = quota["limit"], quota["used"]
    if limit is None:
        return None
    percent = 100 if limit == 0 else used * 100 / limit
    level = next((level for level in (100, 95, 80) if percent >= level), None)
    return None if level is None else {
        "level": level, "fingerprint": quota["resets_at"],
        "detail": f"额度已用 {used}/{limit}（达到 {level}%），重置时间 {quota['resets_at']}",
    }


def reconcile_alerts(previous: list[dict], observations: dict, now: datetime) -> list[dict]:
    """None clears; an absent observation means unknown and cannot clear."""
    states = {item["key"]: dict(item) for item in previous}
    for key, condition in observations.items():
        old = states.get(key)
        if condition is None:
            if old and old["active"]:
                old["active"] = False
                old["resolved_at"] = now.isoformat()
            continue
        changed = (
            not old or not old["active"] or condition["level"] > old["level"]
            or condition.get("fingerprint") != old.get("fingerprint")
        )
        if changed:
            states[key] = {
                **condition, "key": key, "id": str(uuid4()), "active": True,
                "opened_at": now.isoformat(), "notified_at": None,
                "last_attempt_at": None, "notification_error": None,
            }
        # Keep the initial detail stable: an idempotent retry must have the
        # identical request body, even when the live quota/count has changed.
    return list(states.values())[-100:]


def notification_due(alert: dict, now: datetime) -> bool:
    if not alert["active"] or alert["notified_at"]:
        return False
    # HTTP transport timeouts have an unknown outcome. Resend idempotency keys
    # expire after 24h; do not blindly resend that uncertain attempt afterwards.
    first = alert.get("first_attempt_at")
    if first and now - datetime.fromisoformat(first) >= timedelta(hours=23):
        return False
    last = alert.get("last_attempt_at")
    if last and alert.get("transport") == "smtp":
        return False  # Plain SMTP has no idempotency receipt; outcome may be unknown.
    return not last or now - datetime.fromisoformat(last) >= timedelta(hours=1)


class EmailMonitor:
    def __init__(self, repository: PostgresEmailMonitorRepository) -> None:
        self.repository = repository

    async def collect(self, entries: list[EmailPoolEntry]) -> tuple[dict, dict]:
        local = await asyncio.to_thread(self.repository.delivery_stats)
        observations: dict = {
            "configuration": None if entries else {"level": 100, "detail": "尚未配置发信通道"},
            "send-failed": {
                "level": 100, "detail": f"最近 15 分钟有 {local['failed_15m']} 次邮件发送失败"
            } if local["failed_15m"] else None,
        }
        providers = []
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, proxy=settings.outbound_proxy or None, trust_env=False) as client:
            for entry in entries:
                smtp = await probe_smtp(entry)
                prefix = entry.name
                row = {"name": prefix, "host": entry.host, "port": entry.port, "smtp": smtp,
                       "usage": None, "usage_error": None, "recent": None, "events_error": None}
                observations[f"{prefix}/smtp"] = None if smtp["status"] == "ok" else {
                    "level": 100, "detail": f"{prefix} SMTP 连接或认证失败：{smtp['error']}"
                }
                if is_resend(entry) and entry.password:
                    headers = {"Authorization": f"Bearer {entry.password}"}
                    try:
                        response = await client.get(f"{RESEND_BASE}/usage", headers=headers)
                        response.raise_for_status()
                        row["usage"] = parse_usage(response.json())
                        observations[f"{prefix}/usage-api"] = None
                        for period, quota in row["usage"].items():
                            condition = quota_condition(quota)
                            if condition:
                                condition["detail"] = f"{prefix} {period} " + condition["detail"]
                            observations[f"{prefix}/{period}"] = condition
                    except Exception as exc:
                        row["usage_error"] = self.safe_error(exc)
                        observations[f"{prefix}/usage-api"] = {
                            "level": 80, "detail": f"{prefix} 无法读取 Resend 额度：{row['usage_error']}"
                        }
                    await asyncio.sleep(0.6)  # Resend's account rate limit is shared.
                    try:
                        response = await client.get(f"{RESEND_BASE}/emails", params={"limit": 100}, headers=headers)
                        response.raise_for_status()
                        payload = response.json()
                        events = payload["data"]
                        if not isinstance(events, list):
                            raise ValueError("invalid events")
                        counts: dict[str, int] = {}
                        bad = 0
                        for event in events:
                            status = event.get("last_event", "unknown")
                            # Project only known states, never provider payloads/addresses.
                            if status not in {
                                "sent", "delivered", "delivery_delayed", "bounced", "complained",
                                "failed", "suppressed", "opened", "clicked", "scheduled", "queued",
                            }:
                                status = "unknown"
                            counts[status] = counts.get(status, 0) + 1
                            created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
                            if created.tzinfo is None:
                                created = created.replace(tzinfo=timezone.utc)
                            if status in {"bounced", "complained", "failed", "suppressed"} and (
                                datetime.now(timezone.utc) - created < timedelta(hours=24)
                            ):
                                bad += 1
                        row["recent"] = {"count": len(events), "has_more": bool(payload.get("has_more")),
                                         "statuses": counts}
                        observations[f"{prefix}/events-api"] = None
                        observations[f"{prefix}/delivery"] = {
                            "level": 100, "detail": f"{prefix} 最近 100 封中有 {bad} 封近 24 小时异常投递"
                        } if bad else None
                    except Exception as exc:
                        row["events_error"] = self.safe_error(exc)
                        observations[f"{prefix}/events-api"] = {
                            "level": 80, "detail": f"{prefix} 无法读取 Resend 投递状态：{row['events_error']}"
                        }
                    await asyncio.sleep(0.6)
                providers.append(row)
        return {"providers": providers, "local": local, "recipient": mask_address(ops_recipient())}, observations

    @staticmethod
    def safe_error(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"HTTP {exc.response.status_code}"
        return type(exc).__name__

    async def notify(self, alert: dict, entries: list[EmailPoolEntry]) -> None:
        recipient = ops_recipient()
        if not recipient:
            raise RuntimeError("OpsRecipientMissing")
        body = f"{alert['detail']}\n首次发现：{alert['opened_at']}\n请查看站点监测页 → 邮件监测。"
        # Prefer HTTPS so an SMTP outage can still notify the operator. Never
        # send a non-Resend credential to Resend, and never follow redirects.
        resend = next((entry for entry in entries if is_resend(entry) and entry.password), None)
        if resend:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False, proxy=settings.outbound_proxy or None, trust_env=False) as client:
                response = await client.post(
                    f"{RESEND_BASE}/emails",
                    headers={"Authorization": f"Bearer {resend.password}",
                             "Idempotency-Key": f"email-monitor/{alert['id']}"},
                    json={"from": f"{resend.from_name} <{resend.from_email}>", "to": [recipient],
                          "subject": "[AIGCNEWS] 邮件告警", "text": body},
                )
                response.raise_for_status()
                if not response.json().get("id"):
                    raise ValueError("MissingProviderReceipt")
            return
        if not entries:
            raise RuntimeError("EmailNotConfigured")
        await asyncio.wait_for(
            transport(entries[0]).send_plain(recipient, "[AIGCNEWS] 邮件告警", body), timeout=15
        )

    async def check_once(self) -> bool:
        token = str(uuid4())
        if not await asyncio.to_thread(self.repository.claim, token):
            return False
        succeeded = False
        try:
            entries = await asyncio.to_thread(effective_entries)
            snapshot, observations = await asyncio.wait_for(self.collect(entries), timeout=120)
            previous = await asyncio.to_thread(self.repository.read)
            configured_keys = {"configuration", "send-failed"}
            for entry in entries:
                configured_keys.add(f"{entry.name}/smtp")
                if is_resend(entry) and entry.password:
                    configured_keys.update(
                        f"{entry.name}/{suffix}" for suffix in
                        ("usage-api", "events-api", "daily", "monthly", "delivery")
                    )
            for alert in previous.get("alerts", []):
                if alert["key"] not in configured_keys:
                    observations[alert["key"]] = None
            now = datetime.now(timezone.utc)
            alerts = reconcile_alerts(previous.get("alerts", []), observations, now)
            state = {**snapshot, "checked_at": now.isoformat(), "alerts": alerts}
            # Persist each incident BEFORE sending, so restart uses the same key.
            await asyncio.to_thread(self.repository.save, token, state)
            due = [alert for alert in alerts if notification_due(alert, now)][:5]
            for alert in due:
                alert["last_attempt_at"] = now.isoformat()
                alert["transport"] = "resend" if any(is_resend(entry) and entry.password for entry in entries) else "smtp"
                alert.setdefault("first_attempt_at", now.isoformat())
                await asyncio.to_thread(self.repository.save, token, state)
                try:
                    await asyncio.wait_for(self.notify(alert, entries), timeout=20)
                    alert["notified_at"] = datetime.now(timezone.utc).isoformat()
                    alert["notification_error"] = None
                except Exception as exc:
                    alert["notification_error"] = self.safe_error(exc)
                await asyncio.to_thread(self.repository.save, token, state)
                await asyncio.sleep(0.6)
            succeeded = True
            return True
        finally:
            await asyncio.to_thread(self.repository.release, token, succeeded=succeeded)

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:
                logger.warning("[EmailMonitor] check failed", exc_info=True)
            await asyncio.sleep(60)
