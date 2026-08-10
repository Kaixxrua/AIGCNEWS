from __future__ import annotations

"""GitHub Trending HTML 解析器契约：stars 与 forks 同构提取。

forks 曾长期缺失（documents.forks 全库为 0），热榜 forks 完全依赖
候选/快照表回退；此处钉死解析层必须同时产出 stars 与 forks。
"""

from backend.app.services.ingestion.source_github_trending import (
    parse_github_trending_html,
)

_TRENDING_HTML = """
<html><body>
<article class="Box-row">
  <h2><a href="/owner-alpha/repo-one">owner-alpha / repo-one</a></h2>
  <p>First repo description</p>
  <div>
    <span itemprop="programmingLanguage">Python</span>
    <a href="/owner-alpha/repo-one/stargazers">12,345</a>
    <a href="/owner-alpha/repo-one/forks">678</a>
    <span>901 stars today</span>
  </div>
</article>
<article class="Box-row">
  <h2><a href="/owner-beta/repo-two">owner-beta / repo-two</a></h2>
  <p>Second repo without forks link</p>
  <div>
    <span itemprop="programmingLanguage">Rust</span>
    <a href="/owner-beta/repo-two/stargazers">2,000</a>
    <span>100 stars today</span>
  </div>
</article>
</body></html>
"""


def test_parse_extracts_stars_and_forks() -> None:
    repos = parse_github_trending_html(_TRENDING_HTML, period="daily", limit=25)

    assert len(repos) == 2
    first, second = repos
    assert first["full_name"] == "owner-alpha/repo-one"
    assert first["stars"] == 12345
    assert first["forks"] == 678
    assert first["period_star_growth"] == 901
    assert second["full_name"] == "owner-beta/repo-two"
    assert second["stars"] == 2000


def test_parse_missing_forks_link_defaults_zero() -> None:
    repos = parse_github_trending_html(_TRENDING_HTML, period="daily", limit=25)

    assert repos[1]["forks"] == 0


def test_parse_weekly_growth_suffix() -> None:
    html = _TRENDING_HTML.replace("901 stars today", "4,321 stars this week")
    repos = parse_github_trending_html(html, period="weekly", limit=25)

    assert repos[0]["period_star_growth"] == 4321
    assert repos[0]["forks"] == 678
