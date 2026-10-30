"""激活码邮件：发到 PayPal 付款邮箱，复用站点 SMTP / 邮件池（EmailService）。

claim_email 条件更新保证并发入口只有一个在发；失败记 failed，最多 3 次
（下次 confirm/status/webhook 入口或 Ops resend 会再试）。SMTP 未配置记 skipped，
买家仍可在付款完成页与找回页拿到码。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlencode

from backend.app.repositories.shinydesk_order_repository import ShinyDeskOrderRepository
from backend.app.services.email_service import EmailServiceError

logger = logging.getLogger(__name__)

SendPlain = Callable[[str, str, str], Awaitable[None]]


def render_license_email(order: Mapping[str, Any], *, site_url: str) -> tuple[str, str]:
    site = site_url.split("?", 1)[0].split("#", 1)[0]
    english = f"{site}?{urlencode({'lang': 'en'})}"
    subject = "Your ShinyDesk activation code"
    body = f"""Thanks for buying ShinyDesk.

Activation code:
{order['license_code']}

Order number: {order['order_no']}
PayPal transaction ID: {order.get('paypal_capture_id') or '-'}

What you get: a lifetime license for 1 Windows PC and 1 Android phone,
with up to 2 game accounts running at the same time.

1. Download ShinyDesk: {english}
2. Open it and enter the code when asked.

Lost this email? Look your code up again at {english}#lookup
with your order number (or PayPal transaction ID) and this email address.

Please keep the code private. Each code activates one PC and one phone.
"""
    return subject, body


async def send_license_email(
    *,
    orders: ShinyDeskOrderRepository,
    order: Mapping[str, Any],
    site_url: str,
    send_plain: SendPlain | None,
) -> str:
    """返回最终 email_status；未抢到发送权（已发/正在发/次数用尽）返回 'unchanged'。"""
    claimed = await asyncio.to_thread(orders.claim_email, order_id=int(order["id"]))
    if claimed is None:
        return "unchanged"
    if send_plain is None:
        await asyncio.to_thread(orders.finish_email, order_id=int(order["id"]), status="skipped")
        return "skipped"
    subject, body = render_license_email(claimed, site_url=site_url)
    try:
        await send_plain(str(claimed["payer_email"]), subject, body)
    except EmailServiceError as exc:
        logger.warning("[ShinyDesk] license email failed: order_no=%s error=%s", claimed["order_no"], exc)
        await asyncio.to_thread(orders.finish_email, order_id=int(order["id"]), status="failed")
        return "failed"
    except Exception:
        logger.exception("[ShinyDesk] license email crashed: order_no=%s", claimed["order_no"])
        await asyncio.to_thread(orders.finish_email, order_id=int(order["id"]), status="failed")
        return "failed"
    await asyncio.to_thread(orders.finish_email, order_id=int(order["id"]), status="sent")
    return "sent"
