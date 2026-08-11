from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))
# PH 日榜的自然日界：featuredAt 落在哪个太平洋日期，就属于哪天的榜。
_PT_ZONE = ZoneInfo("America/Los_Angeles")
# weekly/monthly 窗口天数（daily 已切换为单榜日等值过滤，不再查表）。
_PERIOD_DAYS: Dict[str, int] = {"weekly": 7, "monthly": 30}


def today_cst() -> date:
    """返回 UTC+8 当前日期。"""
    return datetime.now(_CST).date()


def today_pt() -> date:
    """返回太平洋当前日期——PH 首页正在展示的榜日。"""
    return datetime.now(_PT_ZONE).date()


def crawl_date_cst() -> str:
    """返回 UTC+8 当前爬取日期字符串。"""
    crawl_dt = datetime.now(_CST)
    return crawl_dt.date().isoformat()


def normalize_period(period: str) -> str:
    """保留 Product Hunt 入口既有的周期规范化规则。"""
    return (period or "daily").lower().strip()


def resolve_anchor(target_date: Optional[str]) -> date:
    """解析抓取锚点：显式 target_date（回填）优先；缺省锚定 PT 当日。

    行为变化（PR5）：缺省锚点由 CST 当日改为 PT 当日——PH 日榜按
    太平洋日界翻页，CST 上午抓到的仍是 PT 昨日榜，锚点必须与榜日
    同口径，严格过滤才不会把整榜误杀。
    """
    if target_date:
        try:
            return date.fromisoformat(target_date)
        except ValueError:
            logger.warning("[ProductHunt] target_date 解析失败: %s", target_date)
    return today_pt()


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
    """严格榜日过滤（PR5）。

    行为变化：
      - featuredAt 缺失/不可解析（None）一律拒绝——无日界证据的条目
        不再被当作当期产品放行；
      - daily 锚定单个 PT 榜日（feat_date == anchor），取代旧的
        [anchor-2, anchor+1] 四天窗口——PH 首页同一时刻只展示一个
        PT 日榜，窗口过滤会把相邻榜日的条目混进当期；
      - weekly/monthly 保留既有窗口语义。
    """
    if feat_date is None:
        return False
    if period == "daily":
        return feat_date == anchor
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


def all_zero_votes(items: Iterable[Dict[str, Any]]) -> bool:
    """整批条目 votes 全为 0 → 新榜日开榜窗口的退化样本。

    PH 新榜日于 PT 00:00 翻页，开榜头几十分钟内 API/HTML 两个通道
    返回的票数全为 0：榜单尚未沉淀任何投票，排名无信息量。此时写库
    会把当日快照污染成全 0 票，协调层应诚实回空（PR7 语义），保留
    上一片好数据，待票数成熟后由后续轮次落地。
    空批不判退化（交由既有空结果语义处理）；混合批次（部分条目 0 票
    属开榜常态）不判退化，如实放行。
    """
    batch = list(items)
    return bool(batch) and all(int(item.get("votes") or 0) == 0 for item in batch)
