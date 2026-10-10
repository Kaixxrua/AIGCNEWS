import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.app.monitoring import email_monitor as module
from backend.app.monitoring.email_monitor import (
    EmailMonitor,
    notification_due,
    parse_usage,
    quota_condition,
    reconcile_alerts,
)
from backend.app.services.email.pool_transport import EmailPoolEntry

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("used, limit, level", [(79, 100, None), (80, 100, 80), (95, 100, 95),
                                              (100, 100, 100), (101, 100, 100), (0, 0, 100), (100, None, None)])
def test_quota_thresholds_use_provider_limits(used, limit, level):
    result = quota_condition({"used": used, "limit": limit, "resets_at": "2026-10-11T00:00:00Z"})
    assert (result["level"] if result else None) == level


def test_bad_usage_does_not_become_zero_usage():
    with pytest.raises((KeyError, ValueError, TypeError)):
        parse_usage({"emails": {"daily": {"used": "0", "limit": 100, "resets_at": "bad"}}})


def test_incident_survives_restart_and_escalates_only_once():
    observations = {"smtp/daily": {"level": 80, "fingerprint": "period1", "detail": "80 / 100"}}
    first = reconcile_alerts([], observations, NOW)
    first[0]["notified_at"] = NOW.isoformat()
    next_check = reconcile_alerts(copy.deepcopy(first), {
        "smtp/daily": {**observations["smtp/daily"], "detail": "82 / 100"},
    }, NOW + timedelta(minutes=5))
    assert next_check == first  # stable body as well as key across retries
    assert not notification_due(next_check[0], NOW + timedelta(hours=1))
    next_check = reconcile_alerts(next_check, {"smtp/daily": {
        "level": 95, "fingerprint": "period1", "detail": "95 / 100",
    }}, NOW)
    assert next_check[0]["id"] != first[0]["id"]
    assert notification_due(next_check[0], NOW)


def test_failed_read_cannot_resolve_old_alert_and_recovery_rearms():
    first = reconcile_alerts([], {"smtp": {"level": 100, "detail": "failed"}}, NOW)
    assert reconcile_alerts(first, {}, NOW)[0]["active"]
    cleared = reconcile_alerts(first, {"smtp": None}, NOW)
    assert not cleared[0]["active"]
    reopened = reconcile_alerts(cleared, {"smtp": {"level": 100, "detail": "failed"}}, NOW)
    assert reopened[0]["id"] != first[0]["id"]


def test_resend_retries_stop_before_idempotency_expires():
    alert = reconcile_alerts([], {"smtp": {"level": 100, "detail": "failed"}}, NOW)[0]
    alert.update(first_attempt_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(), transport="resend")
    assert not notification_due(alert, NOW + timedelta(minutes=59))
    assert notification_due(alert, NOW + timedelta(hours=1))
    assert not notification_due(alert, NOW + timedelta(hours=23))
    alert["transport"] = "smtp"
    assert not notification_due(alert, NOW + timedelta(hours=1))


@pytest.mark.asyncio
async def test_provider_failure_is_visible_and_never_leaks_credentials():
    repository = MagicMock()
    repository.delivery_stats.return_value = {"accepted_24h": 3, "failed_24h": 1, "failed_15m": 1}
    monitor = EmailMonitor(repository)
    entry = EmailPoolEntry(name="resend", host="smtp.resend.com", password="secret-credential")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(403, json={"message": "secret-credential must not be displayed"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(module.httpx, "AsyncClient", return_value=client), patch.object(
        module, "probe_smtp", AsyncMock(return_value={"status": "failed", "error": "SMTPConnectError"})
    ), patch.object(module, "ops_recipient", return_value="operator@example.test"):
        snapshot, conditions = await monitor.collect([entry])
    assert snapshot["providers"][0]["usage"] is None
    assert snapshot["providers"][0]["usage_error"] == "HTTP 403"
    assert conditions["send-failed"]["level"] == 100
    assert conditions["resend/smtp"]
    assert "resend/daily" not in conditions
    assert "secret-credential" not in str(snapshot) + str(conditions)
    assert snapshot["recipient"] == "o***@example.test"
    assert all(request.url.host == "api.resend.com" for request in requests)


@pytest.mark.asyncio
async def test_check_persists_before_notification_and_does_not_resend_on_restart():
    stored = {}
    repository = MagicMock()
    repository.claim.return_value = True
    repository.read.side_effect = lambda: copy.deepcopy(stored)
    def save(token, state):
        stored.clear()
        stored.update(copy.deepcopy(state))
    repository.save.side_effect = save
    entry = EmailPoolEntry(name="resend", host="smtp.resend.com", password="secret")
    async def notify(alert, entries):
        assert stored["alerts"][0]["id"] == alert["id"]
        assert stored["alerts"][0]["last_attempt_at"]
    with patch.object(module, "effective_entries", return_value=[entry]):
        for _ in range(2):
            monitor = EmailMonitor(repository)
            monitor.collect = AsyncMock(return_value=({}, {"resend/smtp": {"level": 100, "detail": "failed"}}))
            monitor.notify = AsyncMock(side_effect=notify)
            await monitor.check_once()
            if _ == 0:
                monitor.notify.assert_awaited_once()
            else:
                monitor.notify.assert_not_awaited()
    assert stored["alerts"][0]["notified_at"]
    assert stored["alerts"][0]["active"]


@pytest.mark.asyncio
async def test_healthy_provider_usage_and_delivery_sample_have_separate_scopes():
    repository = MagicMock()
    repository.delivery_stats.return_value = {"accepted_24h": 1, "failed_24h": 0, "failed_15m": 0}
    entry = EmailPoolEntry(name="resend", host="smtp.resend.com", password="secret")
    def handle(request):
        if request.url.path == "/usage":
            return httpx.Response(200, json={"emails": {
                "daily": {"used": 8, "limit": 100, "resets_at": "2026-10-10T23:59:59.999Z"},
                "monthly": {"used": 224, "limit": 3000, "resets_at": "2026-10-17T10:04:59.270Z"},
            }})
        return httpx.Response(200, json={"has_more": True, "data": [
            {"id": "one", "last_event": "delivered", "created_at": NOW.isoformat(), "to": ["private@example.test"]},
            {"id": "two", "last_event": "sent", "created_at": NOW.isoformat()},
        ]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(module.httpx, "AsyncClient", return_value=client), patch.object(
        module, "probe_smtp", AsyncMock(return_value={"status": "ok"})
    ), patch.object(module, "ops_recipient", return_value="operator@example.test"):
        snapshot, conditions = await EmailMonitor(repository).collect([entry])
    provider = snapshot["providers"][0]
    assert provider["usage"]["daily"]["used"] == 8
    assert provider["usage"]["monthly"]["resets_at"] == "2026-10-17T10:04:59.270Z"
    assert provider["recent"] == {"count": 2, "has_more": True, "statuses": {"delivered": 1, "sent": 1}}
    assert snapshot["local"]["accepted_24h"] == 1
    assert all(value is None for value in conditions.values())
    assert "private@example.test" not in str(snapshot)


@pytest.mark.asyncio
async def test_notification_uses_https_and_stable_idempotency_key():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "provider-receipt"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    entry = EmailPoolEntry(name="resend", host="smtp.resend.com", password="secret", from_email="sender@example.test")
    alert = reconcile_alerts([], {"smtp": {"level": 100, "detail": "SMTP failed"}}, NOW)[0]
    with patch.object(module.httpx, "AsyncClient", return_value=client), patch.object(
        module, "ops_recipient", return_value="ops@example.test"
    ), patch.object(module, "transport") as smtp:
        await EmailMonitor(MagicMock()).notify(alert, [entry])
    assert seen[0].url == "https://api.resend.com/emails"
    assert seen[0].headers["Idempotency-Key"] == "email-monitor/" + alert["id"]
    assert b"ops@example.test" in seen[0].content
    smtp.assert_not_called()
