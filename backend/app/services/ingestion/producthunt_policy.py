from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))
_PERIOD_DAYS: Dict[str, int] = {"daily": 2, "weekly": 7, "monthly": 30}


def today_cst() -> date:
    """返回 UTC+8 当前日期。"""
    return datetime.now(_CST).date()


def crawl_date_cst() -> str:
    """返回 UTC+8 当前爬取日期字符串。"""
    crawl_dt = datetime.now(_CST)
    return crawl_dt.date().isoformat()


def normalize_period(period: str) -> str:
    """保留 Product Hunt 入口既有的周期规范化规则。"""
    return (period or "daily").lower().strip()


def resolve_anchor(target_date: Optional[str]) -> date:
    """按既有 fallback 和日志语义解析抓取锚点日期。"""
    anchor = today_cst()
    if target_date:
        try:
            anchor = date.fromisoformat(target_date)
        except ValueError:
            logger.warning("[ProductHunt] target_date 解析失败: %s", target_date)
    return anchor


def parse_featured_at(feat_str: str) -> Optional[date]:
    """解析 featuredAt 字符串（带时区偏移）为 date 对象。"""
    if not feat_str:
        return None
    try:
        dt = datetime.fromisoformat(feat_str)
        return dt.date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(feat_str[:10])
    except ValueError:
        return None


def within_period(feat_date: Optional[date], period: str, anchor: date) -> bool:
    """判断产品的 featuredAt 日期是否在指定周期窗口内。"""
    if feat_date is None:
        return True
    days = _PERIOD_DAYS.get(period, 2)
    start = anchor - timedelta(days=days)
    end = anchor + timedelta(days=1)
    return start <= feat_date <= end


def published_date(
    feat_date: Optional[date],
    period: str,
    anchor: date,
    crawl_date_str: str,
) -> str:
    """投影 Product Hunt featured 日期为既有 published_date 语义。"""
    feat_date_str = feat_date.isoformat() if feat_date else crawl_date_str
    if period == "daily" and feat_date and feat_date < anchor:
        return anchor.isoformat()
    return feat_date_str or crawl_date_str
