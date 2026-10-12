from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from backend.app.api.dependencies import get_application_repositories
from backend.app.api.routes_new_words import router
from backend.app.services.dashboard import new_words as service
from backend.app.services.dashboard.hotword_web import WebEvidence, web_id

NOW = datetime(2026, 10, 8, 8, tzinfo=timezone.utc)


def web_research(discovered=None, investigated=None, available=True):
    return SimpleNamespace(
        discover=AsyncMock(return_value=WebEvidence(discovered or [], available=available)),
        investigate=AsyncMock(return_value=WebEvidence(investigated or [], available=available)),
    )


@pytest.fixture(autouse=True)
def isolate_public_network(monkeypatch):
    monkeypatch.setattr(service, "PublicWebResearch", web_research)


def web_document(url="https://research.example/prism", **overrides):
    return document(web_id(url), source="web", url=url, verified_at=NOW.isoformat(), **overrides)


def document(identity="paper", **overrides):
    return {
        "id": identity, "source": "arxiv", "title": "A new training mechanism",
        "summary": "We introduce Prism Routing, a novel training mechanism for sparse neural networks.",
        "url": "https://arxiv.org/abs/2610.12345",
        "published_at": (NOW - timedelta(hours=36)).isoformat(),
        **overrides,
    }


def candidate(term="Prism Routing", **overrides):
    return service.Candidate(
        term=term, primary_id="paper",
        primary_quote=f"We introduce {term}, a novel training mechanism for sparse neural networks.",
        definition_zh="用于稀疏网络的训练机制。", definition_en="A training mechanism for sparse networks.",
        reason_zh="引入新的路由训练步骤。", reason_en="Introduces a new routing training step.",
        **overrides,
    )


class Repository:
    def __init__(self):
        self.docs = [
            document(),
            document("discussion", source="hackernews", title="Testing Prism Routing",
                     url="https://discussion.example/prism", published_at=(NOW - timedelta(hours=2)).isoformat()),
            document("coverage", source="news", title="Prism Routing explained",
                     summary="A closer look at Prism Routing for neural networks.", url="https://coverage.example/prism",
                     published_at=(NOW - timedelta(hours=3)).isoformat()),
        ]
        self.history = []
        self.snapshots = {}
        self.history_calls = []
        self.save_calls = []

    def recent_documents(self, *_):
        return self.docs

    def historical_mentions(self, aliases, before, sources):
        self.history_calls.append((aliases, before, sources))
        return self.history

    def existing_ids(self, ids, sources):
        return {d["id"] for d in self.docs if d["id"] in ids and d["source"] in sources}

    def get_snapshot(self, day):
        return self.snapshots.get(day)

    def snapshot_dates(self, before, limit):
        return sorted((day for day, snapshot in self.snapshots.items() if day < before and snapshot["items"]),
                      reverse=True)[:limit]

    def save_snapshot(self, day, items, now):
        self.save_calls.append(day)
        self.snapshots[day] = {"items": items, "generated_at": now}


def select(repo, proposals=None, now=NOW, previous=None):
    return service.select_words(proposals or [candidate()], service.eligible_documents(repo.docs, now),
                                repo, now, previous or [])


def test_specific_new_concept_requires_verified_primary_and_independent_discussion():
    repo = Repository()
    words = select(repo)
    assert [word["term"] for word in words] == ["Prism Routing"]
    assert [e["id"] for e in words[0]["evidence"]] == ["paper", "discussion", "coverage"]
    # A next-day selection can keep the same concept; there is no daily novelty reset.
    assert select(repo, now=NOW + timedelta(days=1), previous=words)[0]["id"] == words[0]["id"]


@pytest.mark.parametrize("term", ["Claude Code", "MCP", "多模态", "智能体", "RAG"])
def test_perennial_terms_are_never_fallbacks(term):
    repo = Repository()
    repo.docs = [{**d, "summary": d["summary"].replace("Prism Routing", term)} for d in repo.docs]
    assert select(repo, [candidate(term)]) == []


@pytest.mark.parametrize("change", [
    {"primary_id": "invented"},
    {"primary_quote": "We introduce Prism Routing with a fabricated detail."},
    {"primary_quote": "Prism Routing, a novel training mechanism for dense networks."},
    {"aliases": ["MCP"]},
])
def test_unverifiable_or_generic_alias_candidates_do_not_publish(change):
    assert select(Repository(), [candidate().model_copy(update=change)]) == []


def test_old_concept_is_rejected_even_when_recent_articles_propose_it_again():
    repo = Repository()
    repo.history = [document("original", published_at="2025-10-01T00:00:00+00:00")]
    assert select(repo) == []
    assert repo.history_calls


def test_short_acronym_does_not_match_an_ordinary_word_in_older_papers():
    repo = Repository()
    repo.docs = [{**d, "summary": d["summary"].replace("Prism Routing", "WISE")} for d in repo.docs]
    repo.history = [document("old", title="Layer-wise training", summary="Token-wise gradients.",
                             published_at="2025-10-01T00:00:00+00:00")]
    assert select(repo, [candidate("WISE")])[0]["term"] == "WISE"
    repo.history[0]["summary"] = "We introduced WISE in 2025."
    assert select(repo, [candidate("WISE")]) == []


@pytest.mark.parametrize("update", [
    {"url": "https://arxiv.org/abs/2610.12345?utm_source=copy"},
    {"title": "A new training mechanism"},
    {"retweeted_by": "reposter"},
    {"url": "https://export.arxiv.org/abs/2610.12345"},
    {"url": "javascript:alert(1)"},
])
def test_copies_reposts_same_publisher_and_unsafe_links_do_not_count_as_independent(update):
    repo = Repository()
    repo.docs[1].update(update)
    assert select(repo) == []


@pytest.mark.parametrize("stamp", ["2020-01-01", "2026-10-09", "", "not-a-date"])
def test_original_publication_date_controls_novelty_not_ingestion_time(stamp):
    doc = document(published_at=stamp, created_at=NOW.isoformat())
    assert service.eligible_documents([doc], NOW) == []


def test_legitimate_query_parameters_survive_tracking_dedup():
    assert service.safe_url("https://news.ycombinator.com/item?id=123&utm_source=x#comments") == "https://news.ycombinator.com/item?id=123"


def test_no_recent_discussion_retires_the_word():
    repo = Repository()
    for doc in repo.docs:
        doc["published_at"] = (NOW - timedelta(days=3)).isoformat()
    assert select(repo) == []


def test_citations_keep_independent_and_earliest_evidence_when_one_publisher_dominates():
    repo = Repository()
    repo.docs[1]["published_at"] = (NOW - timedelta(days=6)).isoformat()
    for i in range(10):
        repo.docs.append(document(f"extra{i}", title=f"Prism Routing experiment {i}",
                                  url=f"https://arxiv.org/abs/{i}", published_at=(NOW - timedelta(hours=1)).isoformat()))
    words = select(repo)
    assert len(words[0]["evidence"]) == 12
    assert "discussion" in {e["id"] for e in words[0]["evidence"]}
    assert words[0]["first_seen"] == "2026-10-02"


def test_card_returns_at_most_two_distinct_concepts_and_preserves_close_ties():
    repo = Repository()
    repo.docs = []
    proposals = []
    for i, term in enumerate(["Amber Routing", "Cobalt Routing", "Prism Routing"]):
        proposal = candidate(term).model_copy(update={"primary_id": f"paper{i}"})
        proposals.append(proposal)
        repo.docs.extend([
            document(f"paper{i}", title=term, url=f"https://papers{i}.example/paper", summary=proposal.primary_quote),
            document(f"news{i}", source="news", title=f"Testing {term}", summary=term,
                     url=f"https://news{i}.example/story", published_at=(NOW - timedelta(hours=2)).isoformat()),
            document(f"community{i}", source="hackernews", title=f"Discussing {term}", summary=term,
                     url=f"https://community{i}.example/story", published_at=(NOW - timedelta(hours=3)).isoformat()),
        ])
    words = select(repo, proposals)
    assert len(words) == 2
    reversed_words = words[::-1]
    assert select(repo, proposals, previous=reversed_words) == reversed_words


def model_response(data):
    return SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(data))))


def test_generation_saves_daily_snapshot_and_avoids_repeated_model_calls():
    repo = Repository()
    model = model_response({"candidates": [candidate().model_dump()]})
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model))
    assert asyncio.run(service.refresh_new_words(repo, now=NOW + timedelta(minutes=10), model=model))
    assert model.ainvoke.await_count == 1
    assert repo.snapshots[service.today(NOW)]["items"][0]["term"] == "Prism Routing"


def test_empty_cached_snapshot_does_not_delay_recovery_after_startup():
    repo = Repository()
    repo.save_snapshot(service.today(NOW), [], NOW - timedelta(minutes=2))
    model = model_response({"candidates": [candidate().model_dump()]})
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model))
    assert service.public_snapshot(repo, service.today(NOW))["status"] == "ready"


def test_recent_proven_words_can_repeat_when_new_search_yields_no_candidates():
    repo = Repository()
    prior = select(repo)
    repo.save_snapshot(service.today(NOW) - timedelta(days=1), prior, NOW - timedelta(hours=1))
    repo.save_snapshot(service.today(NOW), [], NOW - timedelta(minutes=1))
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model_response({"candidates": []})))
    assert [{k: v for k, v in item.items() if k != "sampling"} for item in repo.snapshots[service.today(NOW)]["items"]] == prior
    assert service.reusable_words(repo, {"items": prior}, NOW + timedelta(days=3)) == []
    repo.docs.pop()
    assert service.reusable_words(repo, {"items": prior}, NOW) == []


@pytest.mark.parametrize("result", [None, {"wrong": []}, {"candidates": [{"bad": "schema"}]}])
def test_failure_does_not_overwrite_successful_snapshot(result):
    repo = Repository()
    old = {"items": select(repo), "generated_at": NOW - timedelta(hours=2)}
    repo.snapshots[service.today(NOW)] = old
    model = model_response(result) if result is not None else SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError))
    with pytest.raises((ValueError, TimeoutError)):
        asyncio.run(service.refresh_new_words(repo, now=NOW, model=model))
    assert repo.snapshots[service.today(NOW)] is old
    assert repo.save_calls == []


def test_valid_empty_result_is_saved_but_missing_ingestion_is_not():
    repo = Repository()
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model_response({"candidates": []})))
    assert repo.snapshots[service.today(NOW)]["items"] == []
    repo.docs = []
    assert not asyncio.run(service.refresh_new_words(repo, now=NOW + timedelta(hours=2), model=model_response({})))
    assert len(repo.save_calls) == 1


def test_public_snapshot_rechecks_deleted_evidence_and_source_switch(monkeypatch):
    repo = Repository()
    repo.save_snapshot(service.today(NOW), select(repo), NOW)
    assert service.public_snapshot(repo, service.today(NOW))["status"] == "ready"
    repo.docs[1]["source"] = "x"
    monkeypatch.setattr(service.settings, "x_source_enabled", False)
    assert service.public_snapshot(repo, service.today(NOW))["items"] == []
    repo.docs = []
    assert service.public_snapshot(repo, service.today(NOW))["status"] == "empty"


def test_endpoint_is_read_only_date_scoped_and_validates_dates(monkeypatch):
    repo = Repository()
    repo.save_snapshot(date(2026, 10, 8), select(repo), NOW)
    repo.save_calls.clear()
    monkeypatch.setattr(service, "today", lambda: date(2026, 10, 8))
    monkeypatch.setattr("backend.app.api.routes_new_words.today", lambda: date(2026, 10, 8))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_application_repositories] = lambda: SimpleNamespace(new_words=repo)
    with TestClient(app) as client:
        result = client.get("/dashboard/new-words").json()
        assert result["date"] == "2026-10-08"
        assert result["status"] == "ready"
        assert "score" not in result["items"][0]
        assert "primary_id" not in result["items"][0]
        assert client.get("/dashboard/new-words?date=2026-10-07").json()["items"] == []
        assert client.get("/dashboard/new-words?date=2026-10-09").status_code == 422
        assert client.get("/dashboard/new-words?date=bad").status_code == 422
    assert repo.save_calls == []


def test_history_lists_saved_selections_with_exclusive_date_pagination(monkeypatch):
    repo = Repository()
    words = select(repo)
    for day in (1, 6, 8, 9):
        repo.save_snapshot(date(2026, 10, day), words, NOW)
    repo.save_snapshot(date(2026, 10, 7), [], NOW)
    repo.save_calls.clear()
    monkeypatch.setattr("backend.app.api.routes_new_words.today", lambda: date(2026, 10, 8))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_application_repositories] = lambda: SimpleNamespace(new_words=repo)
    with TestClient(app) as client:
        first = client.get("/dashboard/new-words/history?limit=1").json()
        assert [row["date"] for row in first["items"]] == ["2026-10-08"]
        assert first["next_before"] == "2026-10-08"
        second = client.get("/dashboard/new-words/history?before=2026-10-08&limit=1").json()
        assert [row["date"] for row in second["items"]] == ["2026-10-06"]
        last = client.get("/dashboard/new-words/history?before=2026-10-06&limit=1").json()
        assert [row["date"] for row in last["items"]] == ["2026-10-01"]
        assert last["next_before"] is None
        assert "primary_id" not in first["items"][0]["items"][0]
        for query in ("before=bad", "before=2026-10-10", "limit=0", "limit=32"):
            assert client.get("/dashboard/new-words/history?" + query).status_code == 422
        repo.docs = []
        assert client.get("/dashboard/new-words/history").json()["items"] == []
    assert repo.save_calls == []


def test_global_candidates_publish_without_any_indexed_documents():
    repo = Repository()
    repo.docs = []
    original = web_document("https://openai.com/index/prism")
    discussion = web_document("https://discussion.example/prism", title="Testing Prism Routing")
    coverage = web_document("https://coverage.example/prism", title="Prism Routing in practice")
    web = web_research([original, discussion, coverage])
    proposal = candidate().model_copy(update={"primary_id": original["id"]})
    model = model_response({"candidates": [proposal.model_dump()]})
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model, web=web))
    snapshot = service.public_snapshot(repo, service.today(NOW))
    assert snapshot["status"] == "ready"
    assert snapshot["items"][0]["term"] == "Prism Routing"
    assert {e["url"] for e in snapshot["items"][0]["evidence"]} == {original["url"], discussion["url"], coverage["url"]}
    assert all(e["source"] == "web" and "verified_at" not in e for e in snapshot["items"][0]["evidence"])
    payload = json.loads(model.ainvoke.call_args.args[0][1].content)
    assert {d["id"] for d in payload["documents"]} == {original["id"], discussion["id"], coverage["id"]}


def test_targeted_search_can_complete_evidence_for_one_indexed_primary():
    repo = Repository()
    repo.docs = repo.docs[:1]
    discussion = web_document("https://discussion.example/prism", title="Testing Prism Routing")
    web = web_research(investigated=[discussion, web_document("https://coverage.example/prism", title="Prism Routing explained")])
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model_response({
        "candidates": [candidate().model_dump()],
    }), web=web))
    assert service.public_snapshot(repo, service.today(NOW))["status"] == "ready"
    web.investigate.assert_awaited_once_with(["Prism Routing"], NOW, contexts={"Prism Routing": repo.docs[0]["title"]})
    # Removing the indexed primary still hides the mixed local/web snapshot.
    repo.docs = []
    assert service.public_snapshot(repo, service.today(NOW))["items"] == []


def test_verified_older_web_mentions_reject_apparently_new_local_terms():
    repo = Repository()
    old = web_document("https://research.example/original", published_at=(NOW - timedelta(days=30)).isoformat())
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model_response({
        "candidates": [candidate().model_dump()],
    }), web=web_research(investigated=[old])))
    assert repo.snapshots[service.today(NOW)]["items"] == []


@pytest.mark.parametrize("changes", [
    {"verified_at": None}, {"id": "made-up-web-id"},
    {"verified_at": (NOW + timedelta(seconds=1)).isoformat()},
])
def test_external_evidence_requires_a_matching_fetch_receipt(changes):
    assert service.eligible_documents([{**web_document(), **changes}], NOW) == []


def test_public_snapshot_rejects_tampered_web_citation_receipts():
    repo = Repository()
    original = web_document("https://openai.com/index/prism")
    discussion = web_document("https://discussion.example/prism", title="Testing Prism Routing")
    proposal = candidate().model_copy(update={"primary_id": original["id"]})
    words = service.select_words([proposal], [original, discussion, repo.docs[2]], repo, NOW, [])
    repo.save_snapshot(service.today(NOW), words, NOW)
    words[0]["evidence"][0]["url"] = "https://other.example/unfetched"
    assert service.public_snapshot(repo, service.today(NOW))["items"] == []


def test_public_search_outage_does_not_erase_a_successful_daily_card():
    repo = Repository()
    old = {"items": select(repo), "generated_at": NOW - timedelta(hours=2)}
    repo.snapshots[service.today(NOW)] = old
    assert not asyncio.run(service.refresh_new_words(repo, now=NOW, model=model_response({
        "candidates": [],
    }), web=web_research(available=False)))
    assert repo.snapshots[service.today(NOW)] is old
    assert repo.save_calls == []


def test_identical_copied_bodies_do_not_count_as_independent_publishers():
    body = "We introduce Prism Routing, a novel training mechanism for sparse networks. " * 4
    docs = [web_document(summary=body), web_document("https://copy.example/prism", title="Repost", summary=body)]
    assert len(service.eligible_documents(docs, NOW)) == 1


def test_hot_ai_feature_with_a_new_release_can_have_an_older_name():
    repo = Repository()
    quote = "We launch Canvas Actions, a new interactive feature for our AI assistant."
    repo.docs = [{**d, "summary": quote} for d in repo.docs]
    repo.history = [document("old", summary="Canvas Actions was an older desktop menu name.",
                             published_at="2025-10-01T00:00:00Z")]
    proposal = candidate("Canvas Actions").model_copy(update={"kind": "feature", "primary_quote": quote})
    assert select(repo, [proposal])[0]["term"] == "Canvas Actions"
    assert select(repo, [proposal.model_copy(update={"kind": "method"})]) == []


def test_non_ai_topic_cannot_publish_despite_novelty_and_multiple_sources():
    repo = Repository()
    quote = "We introduce Prism Routing, a new banking payment settlement mechanism."
    repo.docs = [{**d, "title": "Banking product update", "summary": quote} for d in repo.docs]
    assert select(repo, [candidate().model_copy(update={"primary_quote": quote})]) == []


@pytest.mark.parametrize("term,title,quote", [
    ("SynthSelf", "Continually Post-training Small Models via Synthetic Self-distillation",
     "We introduce Synthetic Self-Distillation (SynthSelf) for continual post-training of small models."),
    ("Reflex", "Reflex: Visually Grounded Reactive Humanoid Control",
     "We present Reflex, a framework for humanoid control that uses reinforcement learning."),
])
def test_training_and_reinforcement_methods_do_not_need_a_literal_ai_keyword(term, title, quote):
    repo = Repository()
    repo.docs = [{**d, "title": f"{title} {i}", "summary": quote} for i, d in enumerate(repo.docs)]
    proposal = candidate(term).model_copy(update={"primary_quote": quote})
    assert select(repo, [proposal])[0]["term"] == term


def reflex_case():
    repo = Repository()
    quote = "We present Reflex, a neural framework for visually grounded humanoid control."
    repo.docs[0].update(title="Reflex: Visually Grounded Reactive Humanoid Control", summary=quote)
    repo.docs[1].update(title="Reflex catches boxes", summary="Reflex brings visual control to humanoids.")
    repo.docs[2].update(title="Trying Reflex", summary="A closer look at Reflex and reactive humanoid control.")
    return repo, candidate("Reflex").model_copy(update={"primary_quote": quote})


@pytest.mark.parametrize("web_history", [False, True])
def test_same_word_in_an_unrelated_old_paper_does_not_date_a_new_method(web_history):
    repo, proposal = reflex_case()
    old = document("old", title="Light-Omni: Reflex over Reasoning in Agentic Video Understanding",
                   summary="A language model uses reflex over reasoning for long-term video memory.",
                   published_at="2026-07-08T01:53:54+00:00")
    repo.history = [] if web_history else [old]
    words = service.select_words([proposal], repo.docs, repo, NOW, [], [old] if web_history else [])
    assert words[0]["term"] == "Reflex"


def test_related_old_single_word_method_still_blocks_republication():
    repo, proposal = reflex_case()
    repo.history = [document("old", title="An earlier Reflex experiment",
                             summary="Reflex already used reactive humanoid control last year.",
                             published_at="2025-10-01T00:00:00Z")]
    assert select(repo, [proposal]) == []


@pytest.mark.parametrize("summary", [
    "NVIDIA Reflex reduces latency in PC games.",
    "Humanoid control is another topic. " + "Unrelated news. " * 60 + "NVIDIA Reflex reduces latency.",
])
def test_unrelated_namesake_cannot_supply_the_third_publisher(summary):
    repo, proposal = reflex_case()
    repo.docs[2].update(title="NVIDIA gaming update", summary=summary)
    assert select(repo, [proposal]) == []


def test_a_full_alias_identifies_the_same_method_without_english_context():
    repo, proposal = reflex_case()
    proposal = proposal.model_copy(update={"aliases": ["Visually Grounded Reactive Humanoid Control"]})
    repo.docs[2].update(title="新方法详解", summary="Visually Grounded Reactive Humanoid Control 的实际效果。")
    assert select(repo, [proposal])[0]["term"] == "Reflex"


def test_empty_selection_reports_why_candidates_were_rejected(caplog):
    repo, proposal = reflex_case()
    repo.docs.pop()
    with caplog.at_level("INFO", logger=service.__name__):
        assert select(repo, [proposal]) == []
    report = json.loads(next(r.message.removeprefix("Hotword selection: ") for r in caplog.records
                             if r.message.startswith("Hotword selection: ")))
    assert report["selected"] == []
    assert report["rejected"] == {"Reflex": "insufficient_independent_sources"}


def test_html_link_spacing_does_not_reject_a_real_quote():
    repo = Repository()
    repo.docs[0]["summary"] = repo.docs[0]["summary"].replace("Routing,", "Routing ,")
    assert select(repo)[0]["term"] == "Prism Routing"


def test_indexed_news_title_is_a_lead_not_a_verified_original():
    repo = Repository()
    repo.docs[0].update(source="hackernews", url="https://openai.com/index/new-feature")
    assert select(repo) == []


@pytest.mark.parametrize("website,account", [
    ("https://openai.com/index/story", "OpenAI"),
    ("https://anthropic.com/news/story", "AnthropicAI"),
    ("https://blog.google/technology/ai/story", "GoogleDeepMind"),
    ("https://mistral.ai/news/story", "MistralAI"),
])
def test_official_website_and_social_account_are_one_publisher(website, account):
    repo = Repository()
    repo.docs[0]["url"] = website
    repo.docs[1]["url"] = f"https://x.com/{account}/status/123"
    assert select(repo) == []
    assert select(repo, [candidate().model_copy(update={"primary_id": "discussion"})]) == []


def test_broad_discussion_outranks_a_two_publisher_paper():
    repo = Repository()
    broad = candidate("Canvas Actions").model_copy(update={"primary_id": "official", "kind": "feature"})
    repo.docs += [document("official", title="New AI feature", summary=broad.primary_quote,
                           url="https://ai.example/feature")]
    for i in range(5):
        repo.docs.append(document(f"news{i}", source="news", title=f"Canvas Actions review {i}",
                                  summary="Canvas Actions improves AI assistant interaction.",
                                  url=f"https://news{i}.example/feature",
                                  published_at=(NOW - timedelta(hours=2)).isoformat()))
    assert [w["term"] for w in select(repo, [candidate(), broad])] == ["Canvas Actions", "Prism Routing"]


def test_indexed_official_social_release_can_anchor_a_feature_but_not_a_new_method():
    repo = Repository()
    repo.docs[0].update(source="x", url="https://x.com/OpenAI/status/123456789")
    proposal = candidate().model_copy(update={"kind": "feature"})
    assert select(repo, [proposal])[0]["primary_id"] == "paper"
    assert select(repo) == []
    repo.docs[0]["url"] = "https://x.com/unverified/status/123456789"
    assert select(repo, [proposal]) == []
    repo.docs[0]["url"] = "https://x.com/OpenAI/status/123456789"
    repo.docs[0]["source"] = "web"
    assert not service.official_social(repo.docs[0])


def test_news_and_community_leads_reach_model_without_paper_feed_crowding():
    repo = Repository()
    repo.docs += [document(f"paper{i}", title=f"Paper {i}", url=f"https://arxiv.org/abs/2610.{i:05}") for i in range(40)]
    repo.docs.append(document("news", source="news", title="AI new feature", url="https://news.example/feature"))
    model = model_response({"candidates": []})
    web = web_research()
    asyncio.run(service.refresh_new_words(repo, now=NOW, model=model, web=web))
    payload = json.loads(model.ainvoke.call_args.args[0][1].content)["documents"]
    assert {d["source"] for d in payload} == {"news", "hackernews", "arxiv"}
    assert sum(d["source"] == "arxiv" for d in payload) <= 8
    assert "https://news.example/feature" in web.discover.call_args.kwargs["seed_urls"]


def test_fetched_official_full_text_replaces_an_indexed_title_only_lead():
    repo = Repository()
    original = web_document("https://ai.example/feature")
    repo.docs[0] = {**original, "source": "hackernews", "id": "indexed", "summary": "AI new feature"}
    model = model_response({"candidates": [candidate().model_copy(update={"primary_id": original["id"]}).model_dump()]})
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model, web=web_research([original])))
    payload = json.loads(model.ainvoke.call_args.args[0][1].content)["documents"]
    assert next(d for d in payload if d["url"] == original["url"])["summary"] == original["summary"]
    assert service.public_snapshot(repo, service.today(NOW))["status"] == "ready"


def test_two_publishers_are_insufficient_even_with_a_verified_primary():
    repo = Repository()
    repo.docs = repo.docs[:2]
    assert select(repo) == []


def test_many_media_publishers_without_another_channel_type_do_not_qualify():
    repo = Repository()
    repo.docs = [web_document(f"https://news{i}.example/story", title=f"Prism Routing report {i}") for i in range(5)]
    assert select(repo, [candidate().model_copy(update={"primary_id": repo.docs[0]["id"]})]) == []


def test_named_new_model_release_can_qualify_with_cross_channel_evidence():
    repo = Repository()
    quote = "We release Nimbus 2, our new AI language model for software development."
    repo.docs = [{**doc, "summary": quote, "title": doc["title"].replace("Prism Routing", "Nimbus 2")} for doc in repo.docs]
    proposal = candidate("Nimbus 2").model_copy(update={"kind": "release", "primary_quote": quote})
    assert select(repo, [proposal])[0]["term"] == "Nimbus 2"


def test_two_terms_from_the_same_announcement_do_not_occupy_both_slots():
    repo = Repository()
    second = candidate("Prism Canvas")
    repo.docs = [{**doc, "summary": doc["summary"] + " " + second.primary_quote + " " + doc["title"]} for doc in repo.docs]
    words = select(repo, [candidate(), second])
    assert len(words) == 1


def test_public_support_counts_publishers_not_urls_and_tracks_actual_sample():
    repo = Repository()
    web = web_research()
    web.discover.return_value.channels = [
        {"available": True, "recent_items": 5}, {"available": False, "recent_items": 0},
        {"available": True, "recent_items": 0},
    ]
    asyncio.run(service.refresh_new_words(repo, now=NOW, model=model_response({"candidates": [candidate().model_dump()]}), web=web))
    result = service.public_snapshot(repo, service.today(NOW))["items"][0]
    assert result["support"] == {"publishers": 3, "channels": 3}
    assert result["sampling"] == {"feeds_checked": 3, "feeds_available": 2, "feeds_with_recent_items": 1, "documents": 3, "publishers": 3}


def test_previous_algorithm_cache_is_refreshed_at_startup():
    repo = Repository()
    prior = select(repo)
    for item in prior:
        item.pop("selection_version")
    repo.save_snapshot(service.today(NOW), prior, NOW - timedelta(minutes=1))
    model = model_response({"candidates": [candidate().model_dump()]})
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model))
    model.ainvoke.assert_awaited_once()
    assert repo.snapshots[service.today(NOW)]["items"][0]["selection_version"] == 2
