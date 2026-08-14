"""Email subject and body rendering boundary."""

from __future__ import annotations

import re

SOURCE_LABELS = {
    "all": "综合简报",
    "arxiv": "学术报告",
    "github": "工程报告",
    "news": "行业报告",
    "producthunt": "产品报告",
    "hackernews": "社区报告",
    "x": "X 动态报告",
    "dailyhot": "全网热榜报告",
}
PERIOD_LABELS = {
    "daily": "日报",
}


class EmailMessageRenderer:
    """Render legacy email content without escaping user-provided HTML."""

    def registration_otp(self, otp: str) -> tuple[str, str]:
        return "【AIGC_NEWS】您的验证码", self.registration_otp_body(otp)

    def password_reset_otp(self, otp: str) -> tuple[str, str]:
        return "【AIGC_NEWS】密码重置验证码", self.password_reset_otp_body(otp)

    def channel_binding_otp(self, otp: str) -> tuple[str, str]:
        return "【AIGC_NEWS】推送渠道绑定验证码", self.channel_binding_otp_body(otp)

    def channel_binding_otp_body(self, otp: str) -> str:
        return (
            f"您好，\n\n"
            f"您正在将该邮箱绑定为 AIGC_NEWS 的订阅推送渠道，验证码为：\n\n"
            f"    {otp}\n\n"
            f"验证码有效期为 5 分钟，请勿泄露给他人。\n\n"
            f"如非本人操作，请忽略此邮件。\n\n"
            f"— AIGC_NEWS"
        )

    def registration_otp_body(self, otp: str) -> str:
        return (
            f"您好，\n\n"
            f"您正在注册 AIGC_NEWS 账号，验证码为：\n\n"
            f"    {otp}\n\n"
            f"验证码有效期为 5 分钟，请勿泄露给他人。\n\n"
            f"如非本人操作，请忽略此邮件。\n\n"
            f"— AIGC_NEWS"
        )

    def password_reset_otp_body(self, otp: str) -> str:
        return (
            f"您好，\n\n"
            f"您正在重置 AIGC_NEWS 账号密码，验证码为：\n\n"
            f"    {otp}\n\n"
            f"验证码有效期为 5 分钟，请勿泄露给他人。\n\n"
            f"如非本人操作，请忽略此邮件，您的密码不会被更改。\n\n"
            f"— AIGC_NEWS"
        )

    def briefing(
        self,
        content: str,
        source: str,
        period: str,
        date_str: str,
    ) -> tuple[str, str]:
        source_label = SOURCE_LABELS.get(source, source)
        period_label = PERIOD_LABELS.get(period, period)
        subject = f"【AIGC_NEWS】{source_label} · {period_label}"
        if date_str:
            subject += f" ({date_str})"
        return subject, self.briefing_html(
            content, source_label, period_label, date_str
        )

    def briefing_html(
        self, content: str, source_label: str, period_label: str, date_str: str
    ) -> str:
        lines = content.split("\n")
        html_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                html_lines.append("<br/>")
                continue
            if stripped.startswith("### "):
                html_lines.append(
                    f"<h3 style='color:#1a1a2e;margin:16px 0 8px;'>{stripped[4:]}</h3>"
                )
            elif stripped.startswith("## "):
                html_lines.append(
                    f"<h2 style='color:#16213e;margin:20px 0 10px;'>{stripped[3:]}</h2>"
                )
            elif stripped.startswith("# "):
                html_lines.append(
                    f"<h1 style='color:#0f3460;margin:24px 0 12px;'>{stripped[2:]}</h1>"
                )
            elif stripped.startswith("- ") or stripped.startswith("* "):
                html_lines.append(f"<li style='margin:4px 0;'>{stripped[2:]}</li>")
            elif re.match(r"^\d+\.\s", stripped):
                text = re.sub(r"^\d+\.\s*", "", stripped)
                html_lines.append(f"<li style='margin:4px 0;'>{text}</li>")
            elif stripped.startswith("> "):
                html_lines.append(
                    f"<blockquote style='border-left:3px solid #e94560;padding-left:12px;color:#666;margin:8px 0;'>{stripped[2:]}</blockquote>"
                )
            else:
                html_lines.append(
                    f"<p style='margin:6px 0;line-height:1.6;'>{stripped}</p>"
                )

        body_html = "\n".join(html_lines)
        body_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body_html)
        body_html = re.sub(
            r"`([^`]+)`",
            r'<code style="background:#f0f0f0;padding:2px 4px;border-radius:3px;font-size:0.9em;">\1</code>',
            body_html,
        )
        body_html = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            r'<a href="\2" style="color:#e94560;">\1</a>',
            body_html,
        )
        # 标题内的标签行内代码不显示前导 #（与前端渲染约定一致）：
        # ## 标题 `#news` → <code>news</code>；正文代码如 `#define` 不受影响。
        body_html = "\n".join(
            re.sub(r'(<code[^>]*>)#', r"\1", line)
            if line.startswith(("<h1", "<h2", "<h3"))
            else line
            for line in body_html.split("\n")
        )

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#333;background:#fafafa;">
  <div style="background:linear-gradient(135deg,#0f3460,#16213e);color:white;padding:20px 24px;border-radius:12px 12px 0 0;">
    <h1 style="margin:0;font-size:20px;">📋 AIGC_NEWS · {source_label} · {period_label}</h1>
    <p style="margin:8px 0 0;opacity:0.8;font-size:14px;">{date_str}</p>
  </div>
  <div style="background:white;padding:24px;border-radius:0 0 12px 12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    {body_html}
  </div>
  <div style="text-align:center;padding:16px 0;color:#999;font-size:12px;">
    <p>此邮件由 AIGC_NEWS 自动发送，如需退订请在平台简报中心点击「取消订阅」。</p>
    <p>Powered by AIGC_NEWS</p>
  </div>
</body>
</html>"""
