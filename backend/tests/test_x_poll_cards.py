"""Poll cards survive the real X parser, persistence, and REST projection."""
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twitter_cli import parser

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import get_document_repository, get_optional_x_watch_account_repository
from backend.app.repositories.postgres_document_repository import _deserialize_row_media
from backend.app.services.ingestion.persistence_adapter import project_document_write
from backend.app.services.ingestion.sources import x_policy, x_transport


def poll_result(choices=3, suffix="text_only"):
    values = {
        "choice1_label": "5h limits, 2X week usage", "choice1_count": "79775",
        "choice2_label": "no 5h limits, same usage", "choice2_count": "91040",
        "end_datetime_utc": "2026-10-11T17:22:47Z",
        "counts_are_final": True,
    }
    if choices >= 3:
        values.update(choice3_label="show result", choice3_count="69828")
    if choices == 4:
        values.update(choice4_label="Other &amp; more", choice4_count="0")
    return {
        "__typename": "Tweet", "rest_id": "2109152716954222849",
        "core": {"user_results": {"result": {
            "rest_id": "u1", "legacy": {"name": "Tibo", "screen_name": "thsottiaux"},
        }}},
        "legacy": {"full_text": "Pro users, would you rather have", "created_at": "Sun Oct 11 05:22:48 +0000 2026"},
        "card": {"legacy": {
            "name": f"poll{choices}choice_{suffix}",
            "binding_values": [
                {"key": key, "value": {"boolean_value" if isinstance(value, bool) else "string_value": value}}
                for key, value in values.items()
            ],
        }},
    }


@pytest.fixture
def parse_poll(monkeypatch):
    # Restore both the parser and patch sentinel after every test.
    monkeypatch.setattr(parser, "parse_tweet_result", parser.parse_tweet_result)
    monkeypatch.setattr(x_transport, "_ORIGINAL_PARSE_TWEET_RESULT", None)
    x_transport._install_link_card_patch()
    return parser.parse_tweet_result


def test_poll_survives_parser_storage_and_rest(parse_poll, monkeypatch):
    tweet = parse_poll(poll_result())
    item = x_policy.project_tweets([tweet], limit=1)[0]
    write = project_document_write(item, Mock(metadata={"id": "poll-doc"}), "x")
    document = _deserialize_row_media(write)
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 10, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(routes_dashboard, "datetime", clock)
    app = FastAPI()
    app.include_router(routes_dashboard.router)
    app.dependency_overrides[get_document_repository] = lambda: Mock(list_recent_by_source=Mock(return_value=[document]))
    app.dependency_overrides[get_optional_x_watch_account_repository] = lambda: None
    with TestClient(app) as client:
        response = client.get("/dashboard/x/recent")
    assert response.status_code == 200
    card = response.json()["items"][0]["link_card"]
    assert card["url"] == "https://x.com/i/status/2109152716954222849"
    assert card["poll"] == {
        "choices": [
            {"label": "5h limits, 2X week usage", "votes": 79775},
            {"label": "no 5h limits, same usage", "votes": 91040},
            {"label": "show result", "votes": 69828},
        ],
        "total_votes": 240643, "is_final": True, "ends_at": "2026-10-11T17:22:47Z",
    }
    assert json.loads(json.dumps(card)) == card


@pytest.mark.parametrize("choices,suffix", [(2, "image"), (3, "text_only"), (4, "video")])
def test_poll_variants_and_visibility_wrappers(parse_poll, choices, suffix):
    tweet = parse_poll({"__typename": "TweetWithVisibilityResults", "tweet": poll_result(choices, suffix)})
    assert len(tweet.link_card["poll"]["choices"]) == choices
    if choices == 4:
        assert tweet.link_card["poll"]["choices"][3] == {"label": "Other & more", "votes": 0}


def test_retweet_keeps_original_poll_and_destination(parse_poll):
    outer = poll_result()
    outer["rest_id"] = "999"
    outer.pop("card")
    outer["legacy"]["retweeted_status_result"] = {"result": poll_result()}
    assert parse_poll(outer).link_card["poll"]["total_votes"] == 240643
    assert parse_poll(outer).link_card["url"].endswith("/2109152716954222849")


@pytest.mark.parametrize("count", [None, "", "-1", "unknown", "1.5"])
def test_unavailable_counts_are_not_fabricated_as_zero(parse_poll, count):
    raw = poll_result()
    for entry in raw["card"]["legacy"]["binding_values"]:
        if entry["key"] == "choice2_count":
            entry["value"]["string_value"] = count
    poll = parse_poll(raw).link_card["poll"]
    assert len(poll["choices"]) == 3
    assert poll["choices"][1]["votes"] is None
    assert poll["total_votes"] is None


def test_open_zero_vote_poll_and_malformed_card(parse_poll):
    raw = poll_result(2)
    for entry in raw["card"]["legacy"]["binding_values"]:
        if entry["key"].endswith("_count"):
            entry["value"]["string_value"] = "0"
        if entry["key"] == "counts_are_final":
            entry["value"]["boolean_value"] = False
    poll = parse_poll(raw).link_card["poll"]
    assert poll["total_votes"] == 0
    assert poll["is_final"] is False
    raw["card"]["legacy"]["binding_values"] = [
        entry for entry in raw["card"]["legacy"]["binding_values"] if entry["key"] != "choice2_label"
    ]
    assert not hasattr(parse_poll(raw), "link_card")
    raw["card"]["legacy"] = None
    assert not hasattr(parse_poll(raw), "link_card")
