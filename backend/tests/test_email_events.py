from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.monitoring.email_events import configure_email_event_writer, record_email_event
from backend.app.services.email.smtp_transport import SmtpDeliveryError
from backend.app.services.email_service import BriefingDeliveryError, EmailService


@pytest.fixture(autouse=True)
def clear_event_writer():
    yield
    configure_email_event_writer(None)


@pytest.mark.asyncio
async def test_accepted_briefing_and_failed_delivery_are_audited_without_content():
    writer = MagicMock()
    configure_email_event_writer(writer)
    transport = MagicMock()
    transport.send_html = AsyncMock()
    service = EmailService(None, transport=transport)
    await service.send_briefing("private@example.test", "private briefing")
    writer.assert_called_once_with("briefing", "accepted", None)
    transport.send_html.side_effect = SmtpDeliveryError("SMTPConnectError")
    with pytest.raises(BriefingDeliveryError):
        await service.send_briefing("private@example.test", "private briefing")
    assert writer.call_args.args == ("briefing", "failed", "SMTPConnectError")


@pytest.mark.asyncio
async def test_audit_database_failure_does_not_fail_accepted_mail():
    configure_email_event_writer(MagicMock(side_effect=RuntimeError("offline")))
    transport = MagicMock()
    transport.send_html = AsyncMock()
    service = EmailService(None, transport=transport)
    await service.send_briefing("private@example.test", "briefing")
    transport.send_html.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_writer_is_safe_for_standalone_scripts():
    configure_email_event_writer(None)
    await record_email_event("otp", "accepted")
