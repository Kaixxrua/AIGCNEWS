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
        "summary": "We introduce Prism Routing, a novel training mechanism for sparse networks.",
        "url": "https://arxiv.org/abs/2610.12345",
        "published_at": (NOW - timedelta(hours=36)).isoformat(),
        **overrides,
    }


def candidate(term="Prism Routing", **overrides):
    return service.Candidate(
        term=term, primary_id="paper",
        primary_quote=f"We introduce {term}, a novel training mechanism for sparse networks.",
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
    assert [e["id"] for e in words[0]["evidence"]] == ["paper", "discussion"]
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
    assert len(words[0]["evidence"]) == 6
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
            document(f"news{i}", title=f"Testing {term}", summary=term,
                     url=f"https://news{i}.example/story", published_at=(NOW - timedelta(hours=2)).isoformat()),
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
    assert repo.snapshots[service.today(NOW)]["items"] == prior
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


def test_global_candidates_publish_without_any_indexed_documents():
    repo = Repository()
    repo.docs = []
    original = web_document()
    discussion = web_document("https://discussion.example/prism", title="Testing Prism Routing")
    web = web_research([original, discussion])
    proposal = candidate().model_copy(update={"primary_id": original["id"]})
    model = model_response({"candidates": [proposal.model_dump()]})
    assert asyncio.run(service.refresh_new_words(repo, now=NOW, model=model, web=web))
    snapshot = service.public_snapshot(repo, service.today(NOW))
    assert snapshot["status"] == "ready"
    assert snapshot["items"][0]["term"] == "Prism Routing"
    assert {e["url"] for e in snapshot["items"][0]["evidence"]} == {original["url"], discussion["url"]}
    assert all(e["source"] == "web" and "verified_at" not in e for e in snapshot["items"][0]["evidence"])
    payload = json.loads(model.ainvoke.call_args.args[0][1].content)
    assert {d["id"] for d in payload["documents"]} == {original["id"], discussion["id"]}


def test_targeted_search_can_complete_evidence_for_one_indexed_primary():
    repo = Repository()
    repo.docs = repo.docs[:1]
    discussion = web_document("https://discussion.example/prism", title="Testing Prism Routing")
    web = web_research(investigated=[discussion])
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
    original = web_document()
    discussion = web_document("https://discussion.example/prism", title="Testing Prism Routing")
    proposal = candidate().model_copy(update={"primary_id": original["id"]})
    words = service.select_words([proposal], [original, discussion], repo, NOW, [])
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
