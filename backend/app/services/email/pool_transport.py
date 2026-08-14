"""多服务商邮件池 transport：按优先级 failover + 本地配额护栏。

配置来源：EMAIL_POOL_JSON（JSON 数组，格式见 .env.example）。池非空时
build_email_service 以本 transport 替换单一 SmtpTransport；既有 DB/env
单 SMTP 配置自动并入为最低优先级兜底 entry（按 host 去重）。

配额语义：本地 Redis 计数是防超发护栏，不是服务商账单口径——日/月窗口
按 UTC 划分，与各服务商真实重置时刻可能错位，配置限额时应留余量。
Redis 不可用时配额检查 fail-open（放行发送），熔断标记同时失效，行为
退化为纯优先级 failover；单一 SMTP 路径不受本模块影响。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.app.services.email.smtp_transport import SmtpDeliveryError, SmtpTransport

logger = logging.getLogger(__name__)

# 熔断标记在 UTC 次日零点过后额外保留的缓冲秒数（容忍时钟偏差）
_DOWN_MARKER_GRACE_SECONDS = 300
# 计数器 TTL：日计数多留 2 天便于排障，月计数须跨过月界
_DAY_COUNTER_TTL_SECONDS = 3 * 86400
_MONTH_COUNTER_TTL_SECONDS = 45 * 86400

# 强烈指向配额/限流的 SMTP 响应码：421 服务暂不可用（常见于限流）、
# 429 非标准但多家限流用它、452 超存储/超收件额（多家免费档超量报此码）
_QUOTA_SMTP_CODES = frozenset({421, 429, 452})
_QUOTA_MESSAGE_HINTS = (
    "quota",
    "rate limit",
    "ratelimit",
    "limit exceeded",
    "too many",
    "throttl",
    "daily limit",
    "maximum",
)


@dataclass(frozen=True)
class EmailPoolEntry:
    """池中一个服务商节点。daily/monthly_limit 为 0 表示不做本地限额。"""

    name: str
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "AIGC_NEWS"
    use_tls: bool = True
    daily_limit: int = 0
    monthly_limit: int = 0
    priority: int = 100

    @property
    def configured(self) -> bool:
        return bool(self.host)


def parse_email_pool_entries(
    raw: str,
    *,
    default_from_email: str = "",
    default_from_name: str = "AIGC_NEWS",
) -> list[EmailPoolEntry]:
    """解析 EMAIL_POOL_JSON；非法 JSON 或非法 entry 记警告并跳过，不抛错。

    未知字段被忽略（前向兼容）；缺 from_email/from_name 时继承默认发件
    身份，保证同一域名身份跨服务商一致。非 str 入参按未配置处理。
    """
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except ValueError:
        logger.warning("[EMAIL_POOL] EMAIL_POOL_JSON 不是合法 JSON，邮件池禁用")
        return []
    if not isinstance(payload, list):
        logger.warning("[EMAIL_POOL] EMAIL_POOL_JSON 须为 JSON 数组，邮件池禁用")
        return []

    entries: list[EmailPoolEntry] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            logger.warning("[EMAIL_POOL] 跳过第 %d 项：不是对象", index)
            continue
        name = str(item.get("name") or "").strip()
        host = str(item.get("host") or "").strip()
        if not name or not host:
            logger.warning("[EMAIL_POOL] 跳过第 %d 项：缺少 name 或 host", index)
            continue
        try:
            entries.append(
                EmailPoolEntry(
                    name=name,
                    host=host,
                    port=int(item.get("port", 587)),
                    username=str(item.get("username") or ""),
                    password=str(item.get("password") or ""),
                    from_email=str(item.get("from_email") or default_from_email),
                    from_name=str(item.get("from_name") or default_from_name),
                    use_tls=bool(item.get("use_tls", True)),
                    daily_limit=max(0, int(item.get("daily_limit", 0) or 0)),
                    monthly_limit=max(0, int(item.get("monthly_limit", 0) or 0)),
                    priority=int(item.get("priority", 100)),
                )
            )
        except (TypeError, ValueError):
            logger.warning("[EMAIL_POOL] 跳过 %s：数值字段无法解析", name)
    entries.sort(key=lambda entry: entry.priority)
    return entries


def _quota_keys(name: str, now: datetime) -> tuple[str, str, str]:
    day = now.strftime("%Y%m%d")
    month = now.strftime("%Y%m")
    return (
        f"email_pool:v1:d:{name}:{day}",
        f"email_pool:v1:m:{name}:{month}",
        f"email_pool:v1:down:{name}:{day}",
    )


def _seconds_until_next_utc_day(now: datetime) -> int:
    elapsed = now.hour * 3600 + now.minute * 60 + now.second
    return 86400 - elapsed + _DOWN_MARKER_GRACE_SECONDS


class EmailPoolQuotaStore:
    """Redis 配额计数与熔断标记；Redis 故障一律 fail-open 并记警告。"""

    def __init__(
        self,
        redis_client,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._redis = redis_client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def is_available(self, entry: EmailPoolEntry) -> bool:
        if self._redis is None:
            return True
        day_key, month_key, down_key = _quota_keys(entry.name, self._clock())
        try:
            if await self._redis.get(down_key):
                return False
            if entry.daily_limit > 0:
                sent_today = int(await self._redis.get(day_key) or 0)
                if sent_today >= entry.daily_limit:
                    return False
            if entry.monthly_limit > 0:
                sent_month = int(await self._redis.get(month_key) or 0)
                if sent_month >= entry.monthly_limit:
                    return False
        except Exception:
            logger.warning(
                "[EMAIL_POOL] Redis 配额检查失败，fail-open 放行 %s",
                entry.name,
                exc_info=True,
            )
        return True

    async def record_success(self, entry: EmailPoolEntry) -> None:
        if self._redis is None:
            return
        day_key, month_key, _ = _quota_keys(entry.name, self._clock())
        try:
            if await self._redis.incr(day_key) == 1:
                await self._redis.expire(day_key, _DAY_COUNTER_TTL_SECONDS)
            if await self._redis.incr(month_key) == 1:
                await self._redis.expire(month_key, _MONTH_COUNTER_TTL_SECONDS)
        except Exception:
            # 发送已成功，丢计数只影响护栏精度，不阻断链路
            logger.warning(
                "[EMAIL_POOL] Redis 计数失败，%s 配额护栏可能偏低",
                entry.name,
                exc_info=True,
            )

    async def mark_down(self, entry: EmailPoolEntry, *, reason: str) -> None:
        if self._redis is None:
            return
        now = self._clock()
        _, _, down_key = _quota_keys(entry.name, now)
        try:
            await self._redis.set(
                down_key, reason, ex=_seconds_until_next_utc_day(now)
            )
        except Exception:
            logger.warning(
                "[EMAIL_POOL] Redis 熔断标记失败，%s 仍会逐次尝试",
                entry.name,
                exc_info=True,
            )


def is_quota_error(exc: SmtpDeliveryError) -> bool:
    """判断投递失败是否指向配额/限流（命中则熔断该服务商至 UTC 次日）。"""
    cause = exc.__cause__
    if cause is None:
        return False
    code = getattr(cause, "code", None)
    if isinstance(code, int):
        if code in _QUOTA_SMTP_CODES:
            return True
        # 550/553 多为地址策略问题，仅当文案指向限额时才视为配额错误
        if code in (550, 553) and any(
            hint in str(cause).lower() for hint in _QUOTA_MESSAGE_HINTS
        ):
            return True
        return False
    return any(hint in str(cause).lower() for hint in _QUOTA_MESSAGE_HINTS)


class EmailPoolTransport:
    """按优先级遍历服务商的 failover transport，鸭子类型对齐 SmtpTransport。

    EmailService 仅依赖 configured/host/port/from_email/tls_options/
    send_plain/send_html；描述性属性取首个已配置 entry，仅用于日志。
    """

    def __init__(
        self,
        entries: list[EmailPoolEntry],
        *,
        quota: EmailPoolQuotaStore,
    ) -> None:
        self._entries = [entry for entry in entries if entry.configured]
        self._quota = quota

    @property
    def entries(self) -> list[EmailPoolEntry]:
        return list(self._entries)

    @property
    def configured(self) -> bool:
        return bool(self._entries)

    @property
    def host(self) -> str:
        return self._entries[0].host if self._entries else ""

    @property
    def port(self) -> int:
        return self._entries[0].port if self._entries else 0

    @property
    def from_email(self) -> str:
        return self._entries[0].from_email if self._entries else ""

    def tls_options(self) -> tuple[bool, bool]:
        if not self._entries:
            return False, False
        return _entry_transport(self._entries[0]).tls_options()

    async def send_plain(self, to_email: str, subject: str, body: str) -> str:
        """投递纯文本邮件，返回实际命中的服务商 entry 名。"""
        return await self._send(to_email, subject, body, subtype="plain")

    async def send_html(self, to_email: str, subject: str, body: str) -> str:
        """投递 HTML 邮件，返回实际命中的服务商 entry 名。"""
        return await self._send(to_email, subject, body, subtype="html")

    async def _send(
        self, to_email: str, subject: str, body: str, *, subtype: str
    ) -> str:
        failures: list[str] = []
        for entry in self._entries:
            if not await self._quota.is_available(entry):
                logger.info(
                    "[EMAIL_POOL] 跳过 %s（本地限额已满或当日熔断）", entry.name
                )
                continue
            try:
                transport = _entry_transport(entry)
                if subtype == "html":
                    await transport.send_html(to_email, subject, body)
                else:
                    await transport.send_plain(to_email, subject, body)
            except SmtpDeliveryError as exc:
                cause = exc.__cause__ or exc
                failures.append(f"{entry.name}: {exc.error_type}")
                if is_quota_error(exc):
                    await self._quota.mark_down(
                        entry, reason=f"{exc.error_type}: {cause}"
                    )
                    logger.warning(
                        "[EMAIL_POOL] %s 命中配额/限流（%s），熔断至 UTC 次日",
                        entry.name,
                        exc.error_type,
                    )
                else:
                    logger.warning(
                        "[EMAIL_POOL] %s 投递失败（%s: %s），切换下一服务商",
                        entry.name,
                        exc.error_type,
                        cause,
                    )
                continue
            await self._quota.record_success(entry)
            logger.info(
                "[EMAIL_POOL] ✅ 经 %s 投递至 %s（subtype=%s）",
                entry.name,
                to_email,
                subtype,
            )
            return entry.name
        logger.error(
            "[EMAIL_POOL] ❌ 全部服务商不可用/投递失败 to=%s failures=%s",
            to_email,
            "; ".join(failures) or "无已配置 entry",
        )
        raise SmtpDeliveryError("PoolExhausted")


def _entry_transport(entry: EmailPoolEntry) -> SmtpTransport:
    return SmtpTransport(
        host=entry.host,
        port=entry.port,
        username=entry.username,
        password=entry.password,
        from_email=entry.from_email,
        from_name=entry.from_name,
        use_tls=entry.use_tls,
    )


def merge_legacy_entry(
    entries: list[EmailPoolEntry],
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: str,
    from_name: str,
    use_tls: bool,
) -> list[EmailPoolEntry]:
    """把既有单 SMTP 配置并入池为最低优先级兜底 entry（按 host 去重）。

    工厂（build_email_service）与管理员测试投递链路共用，保证面板上的
    测试邮件走与生产完全一致的 failover 顺序。host 为空或已被池内
    entry 占用时原样返回。
    """
    merged = list(entries)
    if not merged or not host or host in {entry.host for entry in merged}:
        return merged
    merged.append(
        EmailPoolEntry(
            name="legacy-smtp",
            host=host,
            port=port,
            username=username,
            password=password,
            from_email=from_email,
            from_name=from_name,
            use_tls=use_tls,
            priority=max(entry.priority for entry in merged) + 10,
        )
    )
    merged.sort(key=lambda entry: entry.priority)
    return merged
