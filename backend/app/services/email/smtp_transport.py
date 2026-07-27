"""SMTP MIME construction and delivery boundary."""

from __future__ import annotations

import logging
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class SmtpDeliveryError(RuntimeError):
    """SMTP delivery failed while retaining the original exception type."""

    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


class SmtpTransport:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        use_tls: bool,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._from_name = from_name
        self._use_tls = use_tls

    @property
    def configured(self) -> bool:
        return bool(self._host)

    def tls_options(self) -> tuple[bool, bool]:
        if self._port == 465:
            return True, False
        if self._port == 587:
            return False, True
        return False, self._use_tls

    def build_message(
        self, to_email: str, subject: str, body: str, *, subtype: str
    ) -> MIMEText:
        message = MIMEText(body, subtype, "utf-8")
        message["Subject"] = subject
        message["From"] = f"{self._from_name} <{self._from_email}>"
        message["To"] = to_email
        return message

    async def send_plain(self, to_email: str, subject: str, body: str) -> None:
        await self._send(to_email, subject, body, subtype="plain")

    async def send_html(self, to_email: str, subject: str, body: str) -> None:
        await self._send(to_email, subject, body, subtype="html")

    async def _send(
        self, to_email: str, subject: str, body: str, *, subtype: str
    ) -> None:
        import aiosmtplib

        message = self.build_message(to_email, subject, body, subtype=subtype)
        use_tls, start_tls = self.tls_options()
        try:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._username or None,
                password=self._password or None,
                use_tls=use_tls,
                start_tls=start_tls,
            )
        except Exception as exc:
            raise SmtpDeliveryError(type(exc).__name__) from exc
