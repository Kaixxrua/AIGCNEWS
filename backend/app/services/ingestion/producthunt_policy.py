from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))
# PH 日榜的自然日界：featuredAt 落在哪个太平洋日期，就属于哪天的榜。
_PT_ZONE = ZoneInfo("America/Los_Angeles")
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
    """解析 featuredAt 为太平洋（PT）日期——PH 日榜的自然日界。

    带时区偏移的时间串先换算 America/Los_Angeles 再取日期（UTC 深夜
    时间戳实际是 PT 当天傍晚，按原偏移取日期会错归后一天）；裸日期/
    无偏移串按原样取 date（视为已在 PT 口径）。无法解析返回 None。
    """
    if not feat_str:
        return None
    try:
        dt = datetime.fromisoformat(feat_str)
        if dt.tzinfo is not None:
            return dt.astimezone(_PT_ZONE).date()
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
    """投影 featured 日期为 published_date：恒取 PT featured 日期本身。

    行为变化（PR2）：删除旧的 daily clamp——不再把早于爬取锚点的
    featured 日期改写为锚点日（旧逻辑会把 PT 昨日榜伪装成 CST 今日
    数据）。period/anchor 保留在签名中仅为调用方兼容，不再参与计算。
    """
    if feat_date is not None:
        return feat_date.isoformat()
    return crawl_date_str


def resolve_board_date(feat_dates: Iterable[Optional[date]]) -> Optional[date]:
    """取 featured 日期的众数作为整页榜单归属日（PT 口径）。

    PH 首页同一时刻只展示一个 PT 日榜，但个别推广/陈旧条目可能带
    其他日期；按出现次数取众数，平票取较新日期。全部为空返回 None，
    由调用方回退爬取日。
    """
    counts: Dict[date, int] = {}
    for feat_date in feat_dates:
        if feat_date is None:
            continue
        counts[feat_date] = counts.get(feat_date, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda d: (counts[d], d.toordinal()))
