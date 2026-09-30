"""文档检索的查询意图解析：时间窗口 + 问句外壳剥离。

自然语言提问（"简洁总结昨晚openai发布了什么"）整句 ILIKE 必然零命中。
这里把提问拆成两部分：
  - 时间意图（昨晚/今天/最近3天/上周/last week…）→ published_date 闭开区间；
  - 问句外壳（总结/发布了什么/有哪些/summarize/what…）→ 从关键词里剥掉。

口径约定：
  - "今天"锚在调度时区（Asia/Shanghai）；各源 published_date 时区不一
    （UTC/PT/上海），窗口下沿统一多放一天吸收日界错位（宁宽勿漏）。
  - 所有匹配都在 ASCII 小写副本上做（逐字符等长，跨度可直接回写原串）；
    纯 ASCII 短语要求两侧不是 ASCII 字母数字（what 不命中 whatsapp），
    中文短语保持子串匹配。
  - mcp-go/internal/postgres/document_intent.go 逐项镜像本模块，
    共享向量 backend/tests/fixtures/document_search_intent_vectors.json 双向钉住。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# 时间短语 → 窗口种类。同一位置先试更长的短语。
_TIME_PHRASES: tuple[tuple[str, str], ...] = (
    ("今天", "today"), ("今日", "today"), ("今早", "today"), ("今晨", "today"),
    ("今晚", "today"), ("今夜", "today"), ("今儿", "today"), ("刚刚", "today"),
    ("刚才", "today"), ("today", "today"), ("tonight", "today"),
    ("this morning", "today"),
    ("昨天", "yesterday"), ("昨日", "yesterday"), ("昨晚", "yesterday"),
    ("昨夜", "yesterday"), ("昨儿", "yesterday"), ("yesterday", "yesterday"),
    ("last night", "yesterday"),
    ("前天", "day_before_yesterday"), ("前日", "day_before_yesterday"),
    ("前晚", "day_before_yesterday"),
    ("最近", "recent"), ("近期", "recent"), ("近日", "recent"), ("最新", "recent"),
    ("这几天", "recent"), ("这两天", "recent"), ("近几天", "recent"), ("近来", "recent"),
    ("recently", "recent"), ("recent", "recent"), ("latest", "recent"),
    ("lately", "recent"), ("past week", "recent"),
    ("本周", "this_week"), ("这周", "this_week"), ("这一周", "this_week"),
    ("这个星期", "this_week"), ("本星期", "this_week"), ("这星期", "this_week"),
    ("this week", "this_week"),
    ("上周", "last_week"), ("上星期", "last_week"), ("上个星期", "last_week"),
    ("上一周", "last_week"), ("last week", "last_week"),
    ("本月", "this_month"), ("这个月", "this_month"), ("这月", "this_month"),
    ("this month", "this_month"),
    ("上个月", "last_month"), ("上月", "last_month"), ("last month", "last_month"),
)

# "最近3天 / 近三天 / 过去24小时 / 7天内"：前缀或后缀至少出现一个。
_ZH_RELATIVE_RE = re.compile(
    r"(最近|过去|近|前)? ?([0-9]+|[一二两三四五六七八九十]+) ?个? ?"
    r"(小时|天|日|周|星期|礼拜|月)(之内|以内|以来|内|里)?"
)
# "past 3 days / last 24 hours"。
_EN_RELATIVE_RE = re.compile(r"(past|last|previous) ([0-9]+) (hours|hour|days|day|weeks|week|months|month)")

# 触发"问句外壳剥离"的提问词：只有命中它们（或命中时间意图）才拆句。
_ASK_TRIGGERS = (
    "什么", "哪些", "啥", "总结", "概括", "汇总", "盘点", "梳理", "介绍",
    "有没有", "讲讲", "说说", "告诉我", "请问",
    "what", "which", "summarize", "summarise", "summary", "tell me", "any news",
)

# 问句外壳：剥离后剩下的才是检索关键词。按长度降序剥离。
_ASK_FILLERS = (
    "简洁地", "简洁", "简要", "简单", "一下", "请问", "请", "告诉我", "给我", "帮忙",
    "总结", "概括", "汇总", "盘点", "梳理", "介绍", "讲讲", "说说", "了解", "有没有",
    "发布会上", "发布会", "都发布了", "发布了", "发布", "推出了", "推出", "宣布了",
    "宣布", "上线了", "上线", "更新了", "更新", "开源了", "有什么", "有哪些", "有啥",
    "是什么", "什么", "哪些", "啥", "新闻", "消息", "资讯", "动态", "进展", "大事",
    "事情", "晚上", "早上", "上午", "下午", "凌晨", "夜里", "深夜", "半夜", "关于",
    "的", "了", "吗", "呢", "吧", "啊", "呀", "都", "和", "与", "及",
    "please", "summarize", "summarise", "summary of", "summary", "briefly", "brief",
    "concisely", "concise", "tell me about", "tell me", "what's new", "what is new",
    "what did", "what has", "what have", "what's", "what", "which", "any news",
    "news", "updates", "update", "released", "release", "announced",
    "announcements", "announcement", "announce", "launched", "launch", "shipped",
    "new", "the", "of", "from", "in", "on", "at", "by", "for", "is", "are", "was",
    "were", "has", "have", "did", "do", "does", "and", "about",
)

_ZH_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_MAX_WINDOW_DAYS = 365
_MAX_COUNT = 100000
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


@dataclass(frozen=True)
class DateWindow:
    """published_date 闭开区间 [since, until)，均为 YYYY-MM-DD。"""

    since: str
    until: str


@dataclass(frozen=True)
class QueryIntent:
    window: DateWindow | None
    asks: bool
    # 剥掉时间短语后的查询（未剥问句外壳；多余空白已折叠）。
    remainder: str


def ascii_lower(value: str) -> str:
    return value.translate(_ASCII_LOWER)


def _is_ascii_alnum(char: str) -> bool:
    return ("a" <= char <= "z") or ("A" <= char <= "Z") or ("0" <= char <= "9")


def _bounded(text: str, start: int, end: int) -> bool:
    """ASCII 短语两侧不得紧贴 ASCII 字母数字（短语首尾均为字母）。"""
    if start > 0 and _is_ascii_alnum(text[start - 1]):
        return False
    return not (end < len(text) and _is_ascii_alnum(text[end]))


def find_phrase(lowered: str, phrase: str) -> list[int]:
    """phrase 在 lowered 中的非重叠命中起点（左到右）。"""
    hits: list[int] = []
    ascii_phrase = phrase.isascii()
    start = 0
    while True:
        index = lowered.find(phrase, start)
        if index < 0:
            return hits
        end = index + len(phrase)
        if not ascii_phrase or _bounded(lowered, index, end):
            hits.append(index)
            start = end
        else:
            start = index + 1


def contains_phrase(lowered: str, phrase: str) -> bool:
    return bool(find_phrase(lowered, phrase))


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def strip_phrases(text: str, phrases: tuple[str, ...]) -> str:
    """按长度降序把命中短语替换为等长空白（稳定排序：等长保持声明序）。"""
    lowered = ascii_lower(text)
    for phrase in sorted(phrases, key=len, reverse=True):
        for index in find_phrase(lowered, phrase):
            end = index + len(phrase)
            text = _blank(text, index, end)
            lowered = _blank(lowered, index, end)
    return text


def _zh_number(raw: str) -> int:
    if raw.isdigit():
        return int(raw)
    if "十" in raw:
        head, _, tail = raw.partition("十")
        tens = _ZH_DIGITS.get(head, 0) if head else 1
        ones = _ZH_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return _ZH_DIGITS.get(raw, 0) if len(raw) == 1 else 0


def _unit_days(count: int, unit: str) -> int:
    if unit in {"小时", "hour", "hours"}:
        return max(1, -(-count // 24))
    if unit in {"周", "星期", "礼拜", "week", "weeks"}:
        return count * 7
    if unit in {"月", "month", "months"}:
        return count * 30
    return count


def _window(since: date, until_inclusive: date) -> DateWindow:
    return DateWindow(since.isoformat(), (until_inclusive + timedelta(days=1)).isoformat())


def _kind_window(kind: str, today: date) -> DateWindow:
    monday = today - timedelta(days=today.weekday())
    first = today.replace(day=1)
    if kind in {"today", "yesterday"}:
        # 昨晚的海外发布多落在上海日界两侧；今天的 PT/UTC 源条目常标成昨天。
        return _window(today - timedelta(days=1), today)
    if kind == "day_before_yesterday":
        return _window(today - timedelta(days=2), today - timedelta(days=1))
    if kind == "recent":
        return _window(today - timedelta(days=7), today)
    if kind == "this_week":
        return _window(monday - timedelta(days=1), today)
    if kind == "last_week":
        return _window(monday - timedelta(days=8), monday - timedelta(days=1))
    if kind == "this_month":
        return _window(first - timedelta(days=1), today)
    # last_month
    previous_first = (first - timedelta(days=1)).replace(day=1)
    return _window(previous_first - timedelta(days=1), first - timedelta(days=1))


def _days_window(days: int, today: date) -> DateWindow:
    days = max(1, min(days, _MAX_WINDOW_DAYS))
    return _window(today - timedelta(days=days), today)


def parse_query_intent(normalized: str, today: date) -> QueryIntent:
    """normalized 须已 NFKC + 空白折叠。窗口取查询中最靠前的时间表达。"""
    text = normalized
    lowered = ascii_lower(text)
    matches: list[tuple[int, DateWindow]] = []

    for match in _ZH_RELATIVE_RE.finditer(lowered):
        prefix, raw_count, unit, suffix = match.groups()
        count = min(_zh_number(raw_count), _MAX_COUNT)
        if not (prefix or suffix) or count <= 0:
            continue
        # 无前缀时数字不得是 ASCII 词尾（llama3个月内 的 3 属于型号）。
        if not prefix and match.start() > 0 and _is_ascii_alnum(lowered[match.start() - 1]):
            continue
        matches.append((match.start(), _days_window(_unit_days(count, unit), today)))
        text = _blank(text, match.start(), match.end())
    lowered = ascii_lower(text)
    for match in _EN_RELATIVE_RE.finditer(lowered):
        if not _bounded(lowered, match.start(), match.end()):
            continue
        count = min(int(match.group(2)), _MAX_COUNT)
        if count <= 0:
            continue
        matches.append((match.start(), _days_window(_unit_days(count, match.group(3)), today)))
        text = _blank(text, match.start(), match.end())
    lowered = ascii_lower(text)
    for phrase, kind in sorted(_TIME_PHRASES, key=lambda item: len(item[0]), reverse=True):
        for index in find_phrase(lowered, phrase):
            matches.append((index, _kind_window(kind, today)))
            end = index + len(phrase)
            text = _blank(text, index, end)
            lowered = _blank(lowered, index, end)

    window = min(matches, key=lambda item: item[0])[1] if matches else None
    asks = any(contains_phrase(ascii_lower(normalized), trigger) for trigger in _ASK_TRIGGERS)
    return QueryIntent(window=window, asks=asks, remainder=" ".join(text.split()))


def strip_ask_fillers(text: str) -> str:
    return strip_phrases(text, _ASK_FILLERS)
