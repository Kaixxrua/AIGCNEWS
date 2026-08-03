from __future__ import annotations

from datetime import date, timedelta

from scripts import backfill_github_stars_500_1000 as backfill


def test_daterange_shards_returns_single_shard_when_under_cap() -> None:
    shards = backfill.daterange_shards(
        date(2020, 1, 1), date(2020, 12, 31), lambda s, e: 100
    )
    assert shards == [(date(2020, 1, 1), date(2020, 12, 31), 100)]


def test_daterange_shards_bisects_until_each_shard_under_cap() -> None:
    counts = {
        (date(2020, 1, 1), date(2020, 12, 31)): 1800,
        (date(2020, 1, 1), date(2020, 7, 1)): 800,
        (date(2020, 7, 2), date(2020, 12, 31)): 1000,
        (date(2020, 7, 2), date(2020, 10, 1)): 400,
        (date(2020, 10, 2), date(2020, 12, 31)): 600,
    }

    def count_for(start: date, end: date) -> int:
        return counts[(start, end)]

    shards = backfill.daterange_shards(
        date(2020, 1, 1), date(2020, 12, 31), count_for
    )
    assert shards == [
        (date(2020, 1, 1), date(2020, 7, 1), 800),
        (date(2020, 7, 2), date(2020, 10, 1), 400),
        (date(2020, 10, 2), date(2020, 12, 31), 600),
    ]
    for start, end, _ in shards:
        assert start <= end
    assert [s for s, _, _ in shards] == sorted(s for s, _, _ in shards)
    for (_, left_end, _), (right_start, _, _) in zip(shards, shards[1:]):
        assert right_start == left_end + timedelta(days=1)


def test_daterange_shards_stops_at_single_day_even_over_cap() -> None:
    one_day = date(2024, 5, 5)
    shards = backfill.daterange_shards(one_day, one_day, lambda s, e: 5000)
    assert shards == [(one_day, one_day, 5000)]


def test_parse_search_item_maps_fields_and_defaults() -> None:
    payload = backfill.parse_search_item(
        {
            "full_name": "octo/demo",
            "html_url": "https://github.com/octo/demo",
            "description": None,
            "language": "Python",
            "topics": ["llm", "agent"],
            "created_at": "2021-03-04T05:06:07Z",
            "pushed_at": "2026-01-02T03:04:05Z",
            "stargazers_count": 876,
            "forks_count": 54,
            "watchers_count": 876,
        }
    )
    assert payload is not None
    assert payload["repo_id"] == "octo/demo"
    assert payload["full_name"] == "octo/demo"
    assert payload["url"] == "https://github.com/octo/demo"
    assert payload["description"] == ""
    assert payload["language"] == "Python"
    assert payload["topics_json"] == '["llm", "agent"]'
    assert payload["stars"] == 876
    assert payload["forks"] == 54
    assert payload["created_at"] == "2021-03-04T05:06:07Z"


def test_parse_search_item_rejects_missing_full_name() -> None:
    assert backfill.parse_search_item({"stargazers_count": 900}) is None
    assert backfill.parse_search_item({"full_name": "  "}) is None


def test_eligible_enforces_hard_min_stars_gate() -> None:
    assert backfill.eligible({"stars": 500}, min_stars=500) is True
    assert backfill.eligible({"stars": 499}, min_stars=500) is False
    assert backfill.eligible({"stars": 0}, min_stars=500) is False
    assert backfill.eligible({}, min_stars=500) is False


def test_merge_channels_appends_new_channel_without_duplicates() -> None:
    assert backfill.merge_channels("", "backfill_stars_500_999") == "backfill_stars_500_999"
    assert (
        backfill.merge_channels("trending_daily,daily_metrics", "backfill_stars_500_999")
        == "trending_daily,daily_metrics,backfill_stars_500_999"
    )
    assert (
        backfill.merge_channels("backfill_stars_500_999", "backfill_stars_500_999")
        == "backfill_stars_500_999"
    )


def test_stars_query_format() -> None:
    assert backfill._stars_query(500, 999, date(2020, 1, 1), date(2020, 6, 30)) == (
        "stars:500..999 created:2020-01-01..2020-06-30"
    )
