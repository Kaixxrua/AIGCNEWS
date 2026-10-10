"""Pure, allowlisted diagnostic projections shared by services and repositories.

Raw messages never leave this module.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

SUMMARIES = {
    "auth": "上游拒绝鉴权或访问权限，需核对凭据状态",
    "rate_limit": "上游限流，需遵守冷却时间",
    "quota": "上游额度不足，重复请求不能解决",
    "query_timeout": "数据库查询被取消或超时，需核对耗时与锁等待",
    "db_lock": "数据库锁等待或死锁，需核对阻塞事务",
    "timeout": "请求或模型响应超时，需核对依赖和重试预算",
    "connection": "连接、DNS 或 TLS 失败，需核对网络路径",
    "program": "程序或数据契约异常，需按堆栈位置修复代码",
    "upstream": "上游服务异常，需核对服务状态",
    "unknown": "错误原因未分类，需要进一步证据",
}


def error_category(exception_type="", message=""):
    # Classify locally; neither matching text nor capture groups are returned.
    text = f"{exception_type or ''} {message or ''}"[:9000].lower()
    for category, pattern in (
        ("auth", r"\b(401|403|unauthorized|forbidden)\b|authentication|鉴权"),
        ("rate_limit", r"\b429\b|rate.?limit|too many requests|限流"),
        ("quota", r"\b402\b|insufficient.*(quota|credit|balance)|额度不足"),
        ("db_lock", r"deadlock|lock timeout|locknotavailable"),
        ("query_timeout", r"querycanceled|statement timeout"),
        ("program", r"typeerror|valueerror|keyerror|integrityerror|attributeerror"),
        ("timeout", r"timeout|timed out|超时"),
        ("connection", r"connect|dns|name resolution|ssl|tls|连接"),
        ("upstream", r"\b50[0234]\b|twitterapierror"),
    ):
        if re.search(pattern, text):
            return category
    return "unknown"


def source_for(logger_name):
    for fragment, source in ((".sources.x", "x"), ("x_translation", "x"),
                             ("arxiv", "arxiv"), ("email", "email"),
                             ("briefing", "briefing"), ("model", "model")):
        if fragment in (logger_name or ""):
            return source
    return "other"


def safe_error(row):
    category = error_category(row.get("exception_type"), row.get("message"))
    logger = str(row.get("logger_name") or "")
    logger = logger if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,180}", logger) else "unknown"
    exc = str(row.get("exception_type") or "")
    exc = exc if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,80}", exc) else None
    frames = [{"file": path, "line": int(line), "function": function}
              for path, line, function in re.findall(
                  r'File "[^"\n]*?(backend/app/[A-Za-z0-9_/]+\.py)", line (\d{1,6}), in ([A-Za-z_][A-Za-z0-9_]*)',
                  str(row.get("stack_trace") or "")[:16000])][-3:]
    identity = (logger, exc, category, [(f["file"], f["function"]) for f in frames])
    return {"fingerprint": hashlib.sha256(repr(identity).encode()).hexdigest()[:20],
            "source": source_for(logger), "logger_name": logger, "exception_type": exc,
            "category": category, "summary": SUMMARIES[category], "frames": frames}


def aggregate_errors(rows, total):
    groups = {}
    for row in rows:
        safe = safe_error(row)
        group = groups.setdefault(safe["fingerprint"], {
            **safe, "sample_count": 0, "first_seen": row["occurred_at"], "last_seen": row["occurred_at"]})
        group["sample_count"] += 1
        group["first_seen"] = min(group["first_seen"], row["occurred_at"])
        group["last_seen"] = max(group["last_seen"], row["occurred_at"])
    return {"window_hours": 24, "total": total, "sampled": len(rows), "truncated": total > len(rows),
            "group_count": len(groups), "groups_truncated": len(groups) > 20,
            "groups": sorted(groups.values(), key=lambda g: g["sample_count"], reverse=True)[:20]}


def translation_evidence(summary):
    # The queue previously exposed last_error verbatim, including relay bodies.
    fields = ("pending", "running", "succeeded", "failed", "skipped", "retryable", "stale_running",
              "oldest_pending_at", "latest_success_at", "latest_failure_at")
    result = {key: summary[key] for key in fields if key in summary}
    result["latest_failure_category"] = error_category(message=summary.get("latest_failure_error"))
    result["scope"] = "队列任务状态；不能据此确认页面语言或全站故障"
    return result


def fallback_report(evidence, error_type):
    lines = [f"模型报告不可用（{error_type}）。以下为程序采集摘要，未生成 AI 分析结论。"]
    for name, item in evidence.items():
        if not isinstance(item, dict) or "observed_at" not in item:
            continue
        result = item["result"]
        status = result.get("status", "已采集") if isinstance(result, dict) else "已采集"
        lines.append(f"{name} · {item['observed_at']}：{status}")
    errors = evidence.get("errors", {}).get("result", {})
    if isinstance(errors, dict):
        lines.extend(f"{g['source']}：{g['summary']}（样本 {g['sample_count']} 次）"
                     for g in errors.get("groups", [])[:5])
    results = evidence.get("actions", {}).get("results", [])
    outcomes = dict(Counter(r.get("status", "uncertain") for r in results))
    lines.append(f"本轮动作结果：{outcomes}；公共资讯补跑：{evidence.get('recovery', {}).get('status', '未执行')}。")
    lines.append("submitted/scheduled 仅表示提交；请查看修复回访。证据不足时不能判定根因或恢复。")
    return "\n".join(lines)
