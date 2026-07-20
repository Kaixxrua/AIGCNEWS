from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

DevelopmentRoute = Literal["existing_rag", "direct", "light_search", "search_and_ask", "clarify"]

_BUILD_ACTIONS = (
    "build", "create", "develop", "implement", "add", "integrate", "migrate", "refactor",
    "开发", "实现", "构建", "新增", "修改", "调整", "修复", "接入", "迁移", "重构", "做一个", "做个",
)
_ARTIFACTS = (
    "app", "application", "service", "api", "backend", "frontend", "plugin", "platform",
    "system", "workflow", "agent", "module", "component", "feature", "项目", "应用", "服务",
    "接口", "后端", "前端", "插件", "平台", "系统", "工作流", "模块", "组件", "功能", "按钮", "页面",
)
_LOCAL_SIGNALS = (
    "typo", "copy", "css", "style", "label", "rename", "validation", "field", "mapping",
    "serialize", "unit test", "log", "type hint", "bug", "文案", "样式", "按钮", "重命名",
    "校验", "字段", "映射", "序列化", "单元测试", "日志", "类型", "修复", "局部", "小改",
)
_CODE_ANCHOR = re.compile(r"(?:[\w./-]+\.(?:py|ts|tsx|js|jsx|vue|java|go|rs|cs)|`[^`]+`|\b(?:function|class|method|route|component)\b|函数|类|方法|路由|组件)", re.I)
_EXPLICIT_OPEN_SOURCE = (
    "open source", "github project", "existing project", "avoid reinventing", "don't reinvent",
    "开源", "现成项目", "类似项目", "不要重复造轮子", "避免造轮子", "基于 github", "查找项目",
)
_COMPLETE_PRODUCT = (
    "complete product", "entire product", "full platform", "full system", "完整产品", "完整平台",
    "完整系统", "独立子系统", "从零开发一个", "从头开发一个",
)
_MATURE_CAPABILITIES = (
    "authentication", "authorization", "billing", "payment", "permission", "workflow engine",
    "search engine", "message queue", "real-time collaboration", "sandbox", "cryptography",
    "身份认证", "鉴权", "支付", "计费", "权限系统", "工作流引擎", "搜索引擎", "消息队列",
    "实时协作", "沙箱", "密码学", "协议实现", "文件解析",
)
_ARCHITECTURE = ("architecture", "deployment", "database", "schema", "架构", "部署", "数据库", "数据模型")
_INTEGRATIONS = ("oauth", "webhook", "third-party", "external service", "同步", "第三方", "外部服务", "协议")
_MULTI_SURFACE = ("frontend", "backend", "database", "前端", "后端", "数据库")
_AI_MARKERS = ("ai", "rag", "llm", "agent", "mcp", "模型", "智能体", "知识库")
_GREENFIELD_PRODUCT_TARGETS = (
    "agent", "platform", "system", "application", "app", "service", "平台", "系统", "应用", "服务",
    "智能体", "商城", "电商", "客服", "项目管理", "crm", "erp", "saas",
)
_GREENFIELD_ACTIONS = ("做个", "做一个", "开发一个", "开发个", "构建一个", "创建一个", "build a", "create a", "develop a")
_SELF_BUILD = ("build from scratch", "from scratch", "自己实现", "自行实现", "自己造轮子", "从零开发")
_RESEARCH_WORDS = ("论文", "新闻", "排行榜", "排名", "多少文档", "paper", "news", "ranking", "top ")


@dataclass(frozen=True)
class ComplexityScores:
    scope: int = 0
    standardization: int = 0
    integration: int = 0
    risk: int = 0
    effort: int = 0
    reuse_potential: int = 0

    @property
    def total(self) -> int:
        return sum((self.scope, self.standardization, self.integration, self.risk, self.effort, self.reuse_potential))


@dataclass(frozen=True)
class DevelopmentDecision:
    is_development: bool
    route: DevelopmentRoute
    scores: ComplexityScores = field(default_factory=ComplexityScores)
    reasons: tuple[str, ...] = ()
    search_mode: Literal["generic", "ai"] = "generic"
    query_hint: str = ""
    language_hint: str = ""

    @property
    def score(self) -> int:
        return self.scores.total


@dataclass(frozen=True)
class CandidateAssessment:
    score: float
    worthwhile: bool
    requires_user_choice: bool
    reasons: tuple[str, ...]


def _contains(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)


def _clamp(value: int) -> int:
    return max(0, min(3, value))


def _language_hint(text: str) -> str:
    options = ("TypeScript", "JavaScript", "Python", "Java", "Rust", "Golang", "Go", "C#", "Vue", "React")
    lowered = text.lower()
    for option in options:
        if re.search(rf"(?<![\w]){re.escape(option.lower())}(?![\w])", lowered):
            return "Go" if option == "Golang" else option
    return ""


def build_search_query(text: str) -> str:
    cleaned = re.sub(
        r"(?:请|帮我|我想要|我想|想要|can you|please|help me|build|create|develop|implement|开发|实现|构建|做一个|做个)",
        " ", text, flags=re.I,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。,.!?；;:")
    return (cleaned or text.strip())[:120]


def classify_development_request(query: str, history: Sequence[dict[str, Any]] | None = None) -> DevelopmentDecision:
    text = query.strip()
    lower = text.lower()
    history = history or []

    pending = parse_follow_up_choice(text, history)
    if pending == "scratch":
        return DevelopmentDecision(True, "direct", reasons=("user_chose_scratch",), query_hint=build_search_query(text))
    if pending == "refine":
        return DevelopmentDecision(True, "search_and_ask", reasons=("user_requested_refine",), query_hint=build_search_query(text))
    if pending == "reuse":
        return DevelopmentDecision(True, "direct", reasons=("user_chose_reuse",), query_hint=build_search_query(text))

    explicit_search = _contains(lower, _EXPLICIT_OPEN_SOURCE)
    is_dev = explicit_search or (_contains(lower, _BUILD_ACTIONS) and _contains(lower, _ARTIFACTS))
    if not is_dev or (_contains(lower, _RESEARCH_WORDS) and not explicit_search):
        return DevelopmentDecision(False, "existing_rag")

    local_signal = _contains(lower, _LOCAL_SIGNALS)
    code_anchor = bool(_CODE_ANCHOR.search(text))
    self_build = _contains(lower, _SELF_BUILD)
    if self_build or (local_signal and (code_anchor or len(text) < 100)):
        reason = "explicit_self_build" if self_build else "narrow_local_change"
        return DevelopmentDecision(True, "direct", reasons=(reason,), query_hint=build_search_query(text), language_hint=_language_hint(text))

    mature = _contains(lower, _MATURE_CAPABILITIES)
    complete = _contains(lower, _COMPLETE_PRODUCT)
    greenfield_product = (
        not code_anchor
        and _contains(lower, _GREENFIELD_ACTIONS)
        and _contains(lower, _GREENFIELD_PRODUCT_TARGETS)
    )
    reference_product = bool(re.search(r"(?:like|similar to|类似|像)\s*[A-Za-z0-9_-]+", text, re.I))
    hard_reasons = []
    if explicit_search:
        hard_reasons.append("explicit_open_source_request")
    if complete:
        hard_reasons.append("complete_product_or_subsystem")
    if greenfield_product:
        hard_reasons.append("greenfield_product_without_local_anchor")
    if mature:
        hard_reasons.append("mature_or_high_risk_capability")
    if reference_product:
        hard_reasons.append("reference_product")

    surfaces = sum(1 for term in _MULTI_SURFACE if term in lower)
    integrations = sum(1 for term in _INTEGRATIONS if term in lower)
    architecture = _contains(lower, _ARCHITECTURE)

    scope = 3 if complete else (2 if greenfield_product or surfaces >= 2 else (1 if any(x in lower for x in ("page", "flow", "页面", "流程")) else 0))
    standardization = 3 if mature else (2 if any(x in lower for x in ("editor", "chart", "upload", "编辑器", "图表", "上传")) else (1 if not code_anchor else 0))
    integration = 3 if integrations >= 2 else (2 if integrations == 1 else (1 if "依赖" in lower or "library" in lower else 0))
    risk = 3 if mature and any(x in lower for x in ("auth", "payment", "security", "认证", "支付", "安全", "隐私")) else (2 if mature or any(x in lower for x in ("并发", "持久化", "permission")) else (1 if "数据" in lower else 0))
    effort = 3 if any(x in lower for x in ("超过一周", "长期", "完整产品")) else (2 if complete or surfaces >= 2 or architecture else (1 if not code_anchor else 0))
    reuse = 3 if mature or explicit_search else (2 if standardization >= 2 else (1 if not code_anchor else 0))
    scores = ComplexityScores(*map(_clamp, (scope, standardization, integration, risk, effort, reuse)))

    mode = "ai" if _contains(lower, _AI_MARKERS) else "generic"
    if hard_reasons:
        route: DevelopmentRoute = "search_and_ask"
    elif scores.total <= 4:
        route = "direct"
    elif scores.total <= 8:
        route = "light_search" if len(build_search_query(text).split()) >= 2 else "clarify"
    else:
        route = "search_and_ask"
    return DevelopmentDecision(
        True, route, scores, tuple(hard_reasons or (f"score_{scores.total}",)), mode,
        build_search_query(text), _language_hint(text),
    )


def parse_follow_up_choice(query: str, history: Sequence[dict[str, Any]]) -> Literal["reuse", "scratch", "refine"] | None:
    recent = "\n".join(str(item.get("content") or "") for item in history[-4:]).lower()
    if not any(marker in recent for marker in ("复用", "从零", "重新搜索", "调整条件", "请选择下一步")):
        return None
    text = query.strip().lower()
    if text in {"b", "b。", "从零", "自研"} or _contains(text, ("从零", "自研", "自己开发", "自己造轮子")):
        return "scratch"
    if text in {"c", "c。", "重搜"} or _contains(text, ("重新搜索", "调整条件", "换一批")):
        return "refine"
    if text in {"a", "a。", "复用"} or _contains(text, ("复用", "二次开发", "第1", "第2", "第3", "项目1", "项目2", "项目3")):
        return "reuse"
    return None


def assess_candidate(candidate: dict[str, Any], *, high_risk: bool = False) -> CandidateAssessment:
    description = str(candidate.get("description_zh") or candidate.get("description") or "")
    stars = int(candidate.get("stars") or 0)
    pushed_at = str(candidate.get("pushed_at") or "")
    tags = candidate.get("tags") or candidate.get("topics") or []
    match = 0.85 if description and tags else (0.75 if description else 0.5)
    maintenance = 0.8 if pushed_at else 0.4
    community = 0.9 if stars >= 5000 else (0.75 if stars >= 500 else 0.5)
    score = round(0.55 * match + 0.25 * maintenance + 0.20 * community, 3)
    route_markers = " ".join(map(str, tags)).lower() + " " + description.lower()
    high_impact = any(x in route_markers for x in ("platform", "server", "database", "agpl", "gpl", "平台", "服务端", "数据库"))
    worthwhile = score >= 0.75 or high_risk
    reasons = ["candidate_quality_threshold_met" if score >= 0.75 else "candidate_quality_below_threshold"]
    if high_impact:
        reasons.append("route_impact_requires_choice")
    return CandidateAssessment(score, worthwhile, worthwhile and high_impact, tuple(reasons))
