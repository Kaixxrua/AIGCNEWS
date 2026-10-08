from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from backend.app.services.dashboard import hotword_sources as sources, hotword_web as web
from backend.app.services.dashboard.new_words import can_be_primary, eligible_documents, publisher

NOW = datetime(2026, 10, 8, 8, tzinfo=timezone.utc)
FEED = sources.FEEDS[0]


def rss(*, link="https://openai.com/index/new-feature", date="Wed, 07 Oct 2026 12:00:00 GMT"):
    return f'''<rss version="2.0"><channel><title>OpenAI</title><item>
      <title>AI Canvas Actions launched</title><link>{link}</link><pubDate>{date}</pubDate>
      <description>We launch Canvas Actions, a new feature for our AI assistant.</description>
      </item></channel></rss>'''.encode()


def test_first_party_feed_preserves_publication_date_and_cannot_be_primary():
    rows = sources.parse_feed(rss(), FEED, NOW)
    assert rows and rows[0]["published_at"] == "2026-10-07T12:00:00+00:00"
    doc = dict(rows[0], id=web.web_id(rows[0]["url"]), source="web", verified_at=NOW.isoformat())
    assert web.verified_citation(doc, NOW)
    assert not can_be_primary(doc)
    assert not web.verified_citation({**doc, "feed_url": "https://fake.example/rss"}, NOW)


def test_aggregated_foreign_links_future_items_and_old_posts_are_not_votes():
    assert sources.parse_feed(rss(link="https://other.example/reposted"), FEED, NOW) == []
    assert sources.parse_feed(rss(link="https://openai.com.evil.example/story"), FEED, NOW) == []
    assert sources.parse_feed(rss(date="Wed, 01 Oct 2025 12:00:00 GMT"), FEED, NOW) == []
    assert sources.parse_feed(rss(date="Fri, 09 Oct 2026 12:00:00 GMT"), FEED, NOW) == []
    assert sources.parse_feed(b"<html>Access challenge</html>", FEED, NOW) is None


def test_atom_updated_time_is_not_a_publication_date():
    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>AI</title><entry>
      <id>test</id><title>AI release</title><link href="https://openai.com/index/new"/>
      <updated>2026-10-07T12:00:00Z</updated></entry></feed>'''
    assert sources.parse_feed(atom, FEED, NOW) == []
    with_publication = atom.replace(b"<updated>", b"<published>").replace(b"</updated>", b"</published>")
    assert len(sources.parse_feed(with_publication, FEED, NOW)) == 1


def test_feed_and_full_page_cannot_double_count_an_article():
    row = sources.parse_feed(rss(), FEED, NOW)[0]
    doc = dict(row, id=web.web_id(row["url"]), source="web", verified_at=NOW.isoformat())
    full = {key: value for key, value in doc.items() if key not in {"evidence_kind", "feed_url"}}
    assert eligible_documents([full, doc], NOW) == [full]
    assert publisher({"url": "https://blogs.microsoft.com/ai/new"}) == publisher({"url": "https://www.microsoft.com/en-us/research/new"})


def test_one_failed_feed_does_not_erase_other_channels_and_reports_real_coverage(monkeypatch):
    monkeypatch.setattr(web, "FEEDS", sources.FEEDS[:2])
    monkeypatch.setattr(web, "fetch_resource", AsyncMock(side_effect=[(FEED.url, rss()), None]))
    result = asyncio.run(web.PublicWebResearch().read_feeds(NOW))
    assert result.available and len(result.documents) == 1
    assert {c["name"]: c["available"] for c in result.channels} == {"OpenAI": True, "Google AI": False}
    assert sum(c["recent_items"] for c in result.channels) == 1


def test_empty_healthy_feed_is_not_reported_as_a_failure(monkeypatch):
    monkeypatch.setattr(web, "FEEDS", (FEED,))
    monkeypatch.setattr(web, "fetch_resource", AsyncMock(return_value=(FEED.url, rss(date="Wed, 01 Oct 2025 12:00:00 GMT"))))
    result = asyncio.run(web.PublicWebResearch().read_feeds(NOW))
    assert result.available and result.documents == []
    assert result.channels[0]["available"] and result.channels[0]["recent_items"] == 0


def test_feed_failure_still_allows_public_search(monkeypatch):
    monkeypatch.setattr(web.PublicWebResearch, "read_feeds", AsyncMock(return_value=web.WebEvidence()))
    research = web.PublicWebResearch()
    research._search = AsyncMock(return_value=[])
    result = asyncio.run(research.discover(NOW))
    assert result.available
    assert any("qbitai.com" in call.args[0] for call in research._search.await_args_list)


def test_publisher_group_does_not_change_when_a_link_arrives_through_hacker_news():
    assert sources.source_group({"url": "https://openai.com/index/feature", "source": "hackernews"}) == "official"
    assert sources.source_group({"url": "https://www.theverge.com/ai/story", "source": "hackernews"}) == "media"


def test_feed_leads_leave_room_for_web_search_and_full_pages_win(monkeypatch):
    monkeypatch.setattr(web, "MAX_PAGES", 6)
    rows = sources.parse_feed(rss(), FEED, NOW)
    docs = [{**rows[0], "url": f"https://openai.com/index/story{i}", "id": web.web_id(f"https://openai.com/index/story{i}"),
             "source": "web", "verified_at": NOW.isoformat()} for i in range(5)]
    monkeypatch.setattr(web.PublicWebResearch, "read_feeds", AsyncMock(return_value=web.WebEvidence(docs, True)))
    fetched = AsyncMock(side_effect=lambda url, now: {**docs[0], "id": web.web_id(url), "url": url, "evidence_kind": "page"})
    monkeypatch.setattr(web, "fetch_page", fetched)
    research = web.PublicWebResearch()
    research._search = AsyncMock(return_value=["https://media.example/search-found"])
    result = asyncio.run(research.discover(NOW))
    assert any(call.args[0] == "https://media.example/search-found" for call in fetched.await_args_list)
    assert fetched.await_count == 3
    assert result.documents[0]["evidence_kind"] == "page"
