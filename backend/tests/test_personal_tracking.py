from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.routes_tracking import get_tracking_repository, router
from backend.app.core.auth import RequireUser
from backend.app.models.schema_tracking import TrackingRuleInput
from backend.app.repositories.postgres_tracking_repository import PostgresTrackingRepository
from backend.app.services.tracking.content import public_link, render_digest
from backend.app.services.tracking.dispatch import dispatch_tracking
from backend.app.services.tracking.policy import CST, TrackingError
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture(scope="module")
def database():
    with postgres_test_sandbox() as sandbox:
        yield sandbox.database


@pytest.fixture
def setup(database):
    with database.transaction() as connection:
        user_id = connection.execute(
            "INSERT INTO users (email, hashed_password) VALUES (%s, 'unused') RETURNING id",
            (f"tracking-{uuid.uuid4().hex}@example.com",),
        ).fetchone()["id"]
    return database, PostgresTrackingRepository(database), user_id


def now():
    return datetime.now(timezone.utc)


def rule(query="RAG", **kwargs):
    return TrackingRuleInput(query=query, **kwargs).model_dump()


def vip(database, user_id):
    with database.transaction() as connection:
        connection.execute("UPDATE users SET membership_tier = 'member' WHERE id = %s", (user_id,))


def document(database, title, *, when=None, url=None):
    key = uuid.uuid4().hex
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO documents (id, source, title, url, summary, created_at) VALUES (%s, 'news', %s, %s, 'A useful update', %s)",
            (key, title, url or f"https://example.com/{key}", when or now().isoformat()),
        )
    return "document:" + key


def channel(database, user_id, *, verified=True):
    with database.transaction() as connection:
        return connection.execute(
            "INSERT INTO push_channels (user_id, channel_type, target, verified) VALUES (%s, 'email', %s, %s) RETURNING id",
            (user_id, f"{uuid.uuid4().hex}@example.com", verified),
        ).fetchone()["id"]


def schedule(repository, user_id, channel_id=None):
    repository.save_settings(user_id, {"enabled": True, "delivery_hour": 0, "channel_id": channel_id})


def test_input_contract():
    assert rule("  RAG  ")["query"] == "RAG"
    assert rule("https://github.com/owner/repo/", kind="project")["query"] == "owner/repo"
    assert rule(excludes=[" demo ", "demo", ""])["excludes"] == ["demo"]
    for values in ({"query": " "}, {"query": "x", "membership_tier": "member"},
                   {"query": "x", "user_id": 5}, {"query": "owner", "kind": "project"},
                   {"query": "x", "excludes": ["x" * 41]}, {"query": "x", "star_threshold": 0}):
        with pytest.raises(ValidationError):
            TrackingRuleInput(**values)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "//example.com", "https://127.0.0.1/a",
                                     "https://169.254.169.254/", "https://user:pw@example.com", "https://service.internal"])
def test_unsafe_links(url):
    assert public_link(url) is None


def test_email_html_escaping():
    body = render_digest({"issue_date": "2026-09-10", "truncated": False, "items": [{
        "title": '<img src=x onerror="alert(1)">', "url": "https://example.com/a",
        "summary": "<script>bad()</script>", "matched_rules": ["<b>RAG</b>"],
    }]})
    assert "<img" not in body and "<script>" not in body and "<b>" not in body


def test_atomic_quota_and_owner_isolation(setup):
    database, repository, user_id = setup
    def add(_):
        try:
            repository.save_rule(user_id, rule())
            return "created"
        except TrackingError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(add, range(2))) == ["created", "rule_limit"]
    saved = repository.overview(user_id)["rules"][0]
    with pytest.raises(TrackingError, match="rule_not_found"):
        repository.delete_rule(user_id, saved["id"] + 100000)
    with database.transaction() as connection:
        other = connection.execute("INSERT INTO users (hashed_password) VALUES ('unused') RETURNING id").fetchone()["id"]
    assert repository.overview(other)["rules"] == []
    with pytest.raises(TrackingError, match="rule_not_found"):
        repository.save_rule(other, rule("changed"), saved["id"])
    with pytest.raises(TrackingError, match="rule_not_found"):
        repository.preview(other, saved["id"])
    assert repository.overview(user_id)["rules"][0]["query"] == "RAG"


def test_member_expiry_preserves_rules_and_rechecks_live_tier(setup):
    database, repository, user_id = setup
    vip(database, user_id)
    for i in range(10):
        repository.save_rule(user_id, rule(f"topic{i}"))
    with pytest.raises(TrackingError, match="rule_limit"):
        repository.save_rule(user_id, rule("eleventh"))
    with database.transaction() as connection:
        connection.execute("UPDATE users SET membership_expires_at = %s WHERE id = %s", (now() - timedelta(seconds=1), user_id))
    result = repository.overview(user_id)
    assert result["limit"] == 1 and len(result["rules"]) == 10
    assert sum(item["active"] for item in result["rules"]) == 1
    with pytest.raises(TrackingError, match="rule_inactive"):
        repository.preview(user_id, result["rules"][-1]["id"])
    repository.save_rule(user_id, rule("topic0", enabled=False), result["rules"][0]["id"])
    assert repository.overview(user_id)["rules"][1]["active"]


def test_matching_exclusions_literal_patterns_and_bad_dates(setup):
    database, repository, user_id = setup
    term = uuid.uuid4().hex
    repository.save_rule(user_id, rule(term + " 100%", excludes=["demo"]))
    good = document(database, f"{term} 100% release")
    document(database, f"{term} 100% demo")
    document(database, f"{term} 100x")
    document(database, f"{term} 100% malformed", when="2026-99-99")
    document(database, f"{term} 100% private", url="https://127.0.0.1/a")
    saved = repository.overview(user_id)["rules"][0]
    assert [item["key"] for item in repository.preview(user_id, saved["id"])["items"]] == [good]
    assert repository.overview(user_id)["digests"] == []


def test_daily_digest_deduplicates_and_stays_quiet(setup):
    database, repository, user_id = setup
    vip(database, user_id)
    term = uuid.uuid4().hex
    repository.save_rule(user_id, rule(term))
    repository.save_rule(user_id, rule(term + " update"))
    schedule(repository, user_id)
    first = document(database, f"{term} update")
    moment = now()
    result = repository.generate_digest(user_id, moment)
    assert len(result["items"]) == 1 and result["items"][0]["key"] == first
    assert len(result["items"][0]["matched_rules"]) == 2
    assert result["delivery_status"] == "none"
    assert repository.generate_digest(user_id, moment + timedelta(minutes=1)) is None
    assert repository.generate_digest(user_id, moment + timedelta(days=1)) is None
    assert len(repository.overview(user_id)["digests"]) == 1


def test_unread_receipt_is_persistent_owned_and_never_acknowledges_future_updates(setup):
    database, repository, user_id = setup
    assert repository.unread(user_id) == {"latest_digest_id": 0, "last_read_digest_id": 0, "unread": False}
    term = uuid.uuid4().hex
    repository.save_rule(user_id, rule(term))
    schedule(repository, user_id)
    document(database, term)
    moment = now()
    first = repository.generate_digest(user_id, moment)
    assert repository.unread(user_id)["unread"]
    # Fetching the overview and matching preview does not mark results read.
    overview = repository.overview(user_id)
    repository.preview(user_id, overview["rules"][0]["id"])
    assert repository.unread(user_id)["last_read_digest_id"] == 0
    document(database, term, when=(moment + timedelta(hours=1)).isoformat())
    second = repository.generate_digest(user_id, moment + timedelta(days=1))
    status = repository.mark_read(user_id, first["id"])
    assert status == {"latest_digest_id": second["id"], "last_read_digest_id": first["id"], "unread": True}
    assert not repository.mark_read(user_id, second["id"])["unread"]
    assert repository.mark_read(user_id, first["id"])["last_read_digest_id"] == second["id"]
    schedule(repository, user_id)
    assert not PostgresTrackingRepository(database).unread(user_id)["unread"]
    with database.transaction() as connection:
        other = connection.execute("INSERT INTO users (hashed_password) VALUES ('unused') RETURNING id").fetchone()["id"]
    with pytest.raises(TrackingError, match="digest_not_found"):
        repository.mark_read(other, second["id"])
    assert not repository.unread(other)["unread"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda item: repository.mark_read(user_id, item), [first["id"], second["id"]]))
    assert repository.unread(user_id)["last_read_digest_id"] == second["id"]
    with database.transaction() as connection:
        connection.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (user_id,))
    for operation in (lambda: repository.unread(user_id), lambda: repository.mark_read(user_id, first["id"])):
        with pytest.raises(TrackingError, match="unauthorized"):
            operation()


def test_unread_http_contract(setup):
    _, repository, user_id = setup
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_tracking_repository] = lambda: repository
    client = TestClient(app)
    assert client.get("/api/tracking/unread").status_code == 401
    assert client.post("/api/tracking/read", json={"digest_id": 1}).status_code == 401
    app.dependency_overrides[RequireUser] = lambda: {"user_id": user_id}
    assert client.get("/api/tracking/unread").json() == {
        "latest_digest_id": 0, "last_read_digest_id": 0, "unread": False,
    }
    for body in ({"digest_id": 0}, {"digest_id": -1}, {"digest_id": True}, {"digest_id": "1"},
                 {"digest_id": 1, "user_id": user_id}, {}, {"digest_id": 9007199254740992}):
        assert client.post("/api/tracking/read", json=body).status_code == 422
    assert client.post("/api/tracking/read", json={"digest_id": 999999}).status_code == 404


def test_english_word_edges_are_shared_by_preview_and_daily_digest(setup):
    database, repository, user_id = setup
    marker = uuid.uuid4().hex
    repository.save_rule(user_id, rule(f"{marker} RAG"))
    expected = {document(database, f"{marker} {title}") for title in (
        "RAG", "rag tutorial", "(RaG)", "Graph-RAG", "RAG/LLM", "中文RAG知识库",
    )}
    for title in ("storage", "coverage", "drag", "averages", "RAG2", "2RAG", "RAG_model", "GraphRAG"):
        document(database, f"{marker} {title}")
    saved = repository.overview(user_id)["rules"][0]
    preview = repository.preview(user_id, saved["id"])
    assert {item["key"] for item in preview["items"]} == expected
    schedule(repository, user_id)
    digest = repository.generate_digest(user_id, now())
    assert {item["key"] for item in digest["items"]} == expected


@pytest.mark.parametrize("term,matched,unmatched", [
    ("知识库", "企业知识库系统", "企业系统"),
    ("C++", "C++ tutorial", "C tutorial"),
    ("a.b", "a.b library", "axb library"),
    ("x_y", "x_y release", "xay release"),
    ("a|b", "a|b release", "a release"),
    ("[RAG]", "[RAG] release", "R release"),
    ("100%", "100% release", "100x release"),
])
def test_keyword_symbols_remain_literal_and_chinese_keeps_substring_matching(setup, term, matched, unmatched):
    database, repository, user_id = setup
    marker = uuid.uuid4().hex
    repository.save_rule(user_id, rule(f"{marker} {term}"))
    expected = document(database, f"{marker} {matched}")
    document(database, f"{marker} {unmatched}")
    saved = repository.overview(user_id)["rules"][0]
    assert [item["key"] for item in repository.preview(user_id, saved["id"])["items"]] == [expected]


def test_english_exclusions_do_not_remove_words_containing_the_same_letters(setup):
    database, repository, user_id = setup
    marker = uuid.uuid4().hex
    repository.save_rule(user_id, rule(marker, excludes=["RAG", "招聘"]))
    expected = document(database, f"{marker} storage coverage drag")
    document(database, f"{marker} rag")
    document(database, f"{marker} RAG系统")
    document(database, f"{marker} 企业招聘中")
    saved = repository.overview(user_id)["rules"][0]
    assert [item["key"] for item in repository.preview(user_id, saved["id"])["items"]] == [expected]


def test_project_growth_uses_existing_metrics_and_never_repeats(setup):
    database, repository, user_id = setup
    repo_id = uuid.uuid4().hex
    full_name = f"tracking/{repo_id}"
    moment = now()
    repository.save_rule(user_id, rule(full_name, kind="project", star_threshold=30))
    schedule(repository, user_id)
    with database.transaction() as connection:
        connection.execute("INSERT INTO github_repo_candidates (repo_id, full_name, url, stars) VALUES (%s, %s, %s, 900)",
                           (repo_id, full_name, "https://github.com/" + full_name))
        connection.execute(
            "INSERT INTO github_repo_daily_metrics (repo_id, metric_date, daily_star_growth, daily_growth_available, updated_at) "
            "VALUES (%s, %s, 40, TRUE, %s)", (repo_id, moment.astimezone(CST).date().isoformat(), moment.isoformat()),
        )
    assert len(repository.generate_digest(user_id, moment)["items"]) == 1
    with database.transaction() as connection:
        connection.execute("UPDATE github_repo_daily_metrics SET updated_at = %s WHERE repo_id = %s",
                           ((moment + timedelta(days=1)).isoformat(), repo_id))
    assert repository.generate_digest(user_id, moment + timedelta(days=1)) is None


def test_channels_are_opt_in_verified_and_owner_scoped(setup):
    database, repository, user_id = setup
    repository.save_rule(user_id, rule())
    assert repository.overview(user_id)["settings"]["channel_id"] is None
    unverified = channel(database, user_id, verified=False)
    with pytest.raises(TrackingError, match="channel_unavailable"):
        schedule(repository, user_id, unverified)
    with database.transaction() as connection:
        other = connection.execute("INSERT INTO users (hashed_password) VALUES ('unused') RETURNING id").fetchone()["id"]
    with pytest.raises(TrackingError, match="channel_unavailable"):
        schedule(repository, user_id, channel(database, other))
    chosen = channel(database, user_id)
    schedule(repository, user_id, chosen)
    assert repository.overview(user_id)["settings"]["channel_id"] == chosen


def test_delivery_claim_retry_and_cancel(setup):
    database, repository, user_id = setup
    term = uuid.uuid4().hex
    repository.save_rule(user_id, rule(term))
    schedule(repository, user_id, channel(database, user_id))
    document(database, term)
    moment = now()
    repository.generate_digest(user_id, moment)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: repository.claim_delivery(moment), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    claimed = next(claim for claim in claims if claim)
    repository.finish_delivery(claimed["id"], claimed["attempts"], sent=False)
    assert repository.claim_delivery(moment + timedelta(minutes=1)) is None
    again = repository.claim_delivery(moment + timedelta(minutes=11))
    assert again["attempts"] == 2
    repository.finish_delivery(again["id"], 1, sent=True)  # stale sender cannot acknowledge a new lease
    assert repository.overview(user_id)["digests"][0]["delivery_status"] == "sending"
    schedule(repository, user_id)
    assert repository.claim_delivery(moment + timedelta(minutes=22)) == {"cancelled": True}


def test_scheduler_generates_sends_only_selected_channel(setup):
    database, repository, user_id = setup
    term = uuid.uuid4().hex
    repository.save_rule(user_id, rule(term))
    schedule(repository, user_id, channel(database, user_id))
    document(database, term)
    sender = AsyncMock()
    result = asyncio.run(dispatch_tracking(repository, sender))
    assert result["generated"] >= 1
    sender.send_personal_digest.assert_awaited()
    assert repository.overview(user_id)["digests"][0]["delivery_status"] == "sent"


def test_api_contract_and_ownership(setup):
    _, repository, user_id = setup
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_tracking_repository] = lambda: repository
    app.dependency_overrides[RequireUser] = lambda: {"user_id": user_id, "membership_tier": "member"}
    client = TestClient(app)
    assert client.get("/api/tracking").json()["limit"] == 1  # DB tier wins over token/client claims
    assert client.post("/api/tracking/rules", json={"query": "RAG", "user_id": user_id + 1}).status_code == 422
    created = client.post("/api/tracking/rules", json={"query": "RAG"})
    assert created.status_code == 201
    rule_id = created.json()["rules"][0]["id"]
    assert "user_id" not in created.json()["rules"][0]
    assert client.post("/api/tracking/rules", json={"query": "agents"}).status_code == 409
    assert client.put("/api/tracking/settings", json={"delivery_hour": 24}).status_code == 422
    assert client.get("/api/tracking/rules/0/preview").status_code == 422
    assert client.delete(f"/api/tracking/rules/{rule_id}").status_code == 200
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 0}
    assert client.get("/api/tracking").status_code == 401
    assert "/api/tracking/rules" in client.get("/openapi.json").json()["paths"]

def test_standard_bearer_authentication_uses_the_real_owner(setup):
    from types import SimpleNamespace

    from backend.app.core.auth import create_access_token
    from backend.app.repositories.postgres_user_account_repository import PostgresUserAccountRepository

    database, repository, user_id = setup
    users = PostgresUserAccountRepository(database)
    record = users.get_user_by_id(user_id)
    app = FastAPI()
    app.state.application_repositories = SimpleNamespace(users=users, tracking=repository)
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/tracking").status_code == 401
    token = create_access_token({"user_id": user_id, "pwd_ver": record["pwd_ver"], "membership_tier": "member"})
    headers = {"Authorization": "Bearer " + token}
    response = client.get("/api/tracking", headers=headers)
    assert response.status_code == 200 and response.json()["limit"] == 1
    with database.transaction() as connection:
        connection.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (user_id,))
    assert client.get("/api/tracking", headers=headers).status_code == 401


@pytest.mark.parametrize("regular_failed", [False, True])
def test_scheduler_always_dispatches_personal_digests(regular_failed):
    from backend.app.core.scheduler import _run_subscription_dispatch_job

    repositories = MagicMock()
    personal = AsyncMock(return_value={"generated": 1, "sent": 0, "failed": 0})
    with (
        patch("backend.app.services.push.dispatch_service.SubscriptionDispatchService") as service_cls,
        patch("backend.app.services.tracking.dispatch.dispatch_tracking", personal),
    ):
        service_cls.return_value.dispatch_all = AsyncMock(
            side_effect=RuntimeError("test failure") if regular_failed else None, return_value={},
        )
        result = asyncio.run(_run_subscription_dispatch_job(repositories))
    personal.assert_awaited_once_with(repositories.tracking, service_cls.return_value)
    assert result is not regular_failed


def test_cst_schedule_and_pausing_keep_the_digest_quiet(setup):
    _, repository, user_id = setup
    repository.save_rule(user_id, rule(uuid.uuid4().hex))
    repository.save_settings(user_id, {"enabled": True, "delivery_hour": 8, "channel_id": None})
    before = now().astimezone(CST).replace(hour=7, minute=59)
    due = before.replace(hour=8, minute=0)
    assert user_id not in repository.due_users(before)
    assert user_id in repository.due_users(due)
    assert repository.generate_digest(user_id, due) is None
    assert user_id not in repository.due_users(due + timedelta(minutes=30))
    repository.save_settings(user_id, {"enabled": False, "delivery_hour": 8, "channel_id": None})
    assert user_id not in repository.due_users(due + timedelta(days=1))


def test_quarantined_projects_never_reach_a_keyword_digest(setup):
    # 疑似诱饵隔离名单里的仓库不进公开项目库，关键词追踪也不推送
    database, repository, user_id = setup
    term = uuid.uuid4().hex
    repository.save_rule(user_id, rule(term))
    moment = now()
    with database.transaction() as connection:
        for repo_id in (term, term + "-lure"):
            connection.execute(
                "INSERT INTO github_repo_candidates (repo_id, full_name, url, stars, first_seen_at) VALUES (%s, %s, %s, 900, %s)",
                (repo_id, "example/" + repo_id, "https://github.com/example/" + repo_id,
                 (moment - timedelta(days=10)).isoformat()),
            )
            connection.execute(
                "INSERT INTO github_repo_enrichments (repo_id, category_slug, category_name, description_zh, source_fingerprint, "
                "prompt_version, enriched_at) VALUES (%s, 'tools', 'Tools', %s, %s, 'test', %s)",
                (repo_id, term, "0" * 64, moment.isoformat()),
            )
        connection.execute(
            "INSERT INTO github_repo_quarantine (repo_id, reason) VALUES (%s, 'coordinated_surge')", (term + "-lure",)
        )
    saved = repository.overview(user_id)["rules"][0]
    keys = {item["key"] for item in repository.preview(user_id, saved["id"])["items"]}
    assert "project:" + term in keys
    assert "project:" + term + "-lure" not in keys


def test_newly_enriched_projects_are_not_lost_and_results_are_bounded(setup):
    database, repository, user_id = setup
    term = uuid.uuid4().hex
    repository.save_rule(user_id, rule(term))
    moment = now()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO github_repo_candidates (repo_id, full_name, url, stars, first_seen_at) VALUES (%s, %s, %s, 900, %s)",
            (term, "example/" + term, "https://github.com/example/" + term, (moment - timedelta(days=10)).isoformat()),
        )
        connection.execute(
            "INSERT INTO github_repo_enrichments (repo_id, category_slug, category_name, description_zh, source_fingerprint, "
            "prompt_version, enriched_at) VALUES (%s, 'tools', 'Tools', %s, %s, 'test', %s)",
            (term, term, "0" * 64, moment.isoformat()),
        )
    saved = repository.overview(user_id)["rules"][0]
    assert any(item["key"] == "project:" + term for item in repository.preview(user_id, saved["id"])["items"])
    for index in range(55):
        document(database, f"{term} {index}")
    preview = repository.preview(user_id, saved["id"])
    assert len(preview["items"]) == 50 and preview["truncated"]
