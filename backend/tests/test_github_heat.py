from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.domain.github_heat import _blend, display_score, score_snapshots
from backend.app.services.ingestion.github_project_metrics_service import compute_github_daily_metrics


def history(hours=2, growth=20):
    start = datetime(2026, 7, 10, 15, tzinfo=timezone.utc)
    rows = [dict(snapshot_date=(start + timedelta(days=i)).date().isoformat(),
                 captured_at=(start + timedelta(days=i)).isoformat(), stars=1000 + 240*i,
                 forks=100 + 24*i, watchers=10 + i, community_metrics_complete=True,
                 repo_pushed_at="2026-07-14T00:00:00+00:00") for i in range(4)]
    rows.append(dict(rows[-1], snapshot_date="2026-07-14",
                     captured_at=(start + timedelta(days=3, hours=hours)).isoformat(),
                     stars=1720+growth, forks=172, watchers=13))
    return rows


@pytest.mark.parametrize(('current', 'hours', 'expected'), [(240, 2, 240), (60, 2, 210), (60, 6, 150), (60, 12, 60)])
def test_short_window_velocity_examples(current, hours, expected):
    assert _blend(current, 240, hours) == pytest.approx(expected)


def test_day_boundary_preserves_constant_star_velocity():
    short = score_snapshots(history(2, 20), '2026-07-14')
    full = score_snapshots(history(24, 240), '2026-07-14')
    assert short['absolute_growth_score'] == full['absolute_growth_score']
    assert short['scale_corrected_growth_score'] == full['scale_corrected_growth_score']
    assert short['growth_acceleration_score'] == full['growth_acceleration_score'] == 60


def test_real_cooling_can_reduce_score_without_ema():
    early = score_snapshots(history(2, 0), '2026-07-14')
    late = score_snapshots(history(12, 0), '2026-07-14')
    assert early['hot_score'] > late['hot_score']
    assert late['absolute_growth_score'] == late['growth_acceleration_score'] == 0


def test_invalid_or_missing_history_does_not_invent_velocity():
    rows = history()
    assert score_snapshots(rows[-2:], '2026-07-14') is None
    assert score_snapshots(rows[:-2] + rows[-1:], '2026-07-14') is None
    rows[-1]['captured_at'] = rows[-2]['captured_at']
    assert score_snapshots(rows, '2026-07-14') is None
    rows[-1]['captured_at'] = 'invalid'
    assert score_snapshots(rows, '2026-07-14') is None
    assert score_snapshots(history(49, 490), '2026-07-14') is None


def test_full_interval_needs_no_prior_and_missing_community_is_not_zero_growth_evidence():
    rows = history(24, 240)[-2:]
    rows[-1]['community_metrics_complete'] = False
    result = score_snapshots(rows, '2026-07-14')
    assert result['score_version'] == 'daily_hot_v6'
    assert result['absolute_growth_score'] > 0
    assert result['community_engagement_score'] == result['growth_acceleration_score'] == 0


def test_historical_score_is_independent_of_future_and_reruns():
    rows = history()
    expected = score_snapshots(rows, '2026-07-14')
    rows.append(dict(rows[-1], snapshot_date='2026-07-15', captured_at='2026-07-15T15:00:00+00:00', stars=999999))
    assert score_snapshots(rows, '2026-07-14') == expected
    assert score_snapshots(rows, '2026-07-14') == expected


def test_high_score_mapping_is_monotone_and_spread():
    assert [display_score(x) for x in (70, 80, 85, 90, 95, 100)] == [77, 85, 90, 93, 96, 100]
    scores = [display_score(i / 10) for i in range(1001)]
    assert scores == sorted(scores)
    assert display_score(-1) == 0 and display_score(101) == 100


def test_service_changes_heat_but_preserves_observed_daily_delta():
    rows = history()
    repo = MagicMock()
    repo.get_github_daily_metric_inputs.return_value = [dict(repo_id='one', stars=1740,
        previous_stars=1720, previous_snapshot_date='2026-07-13', heat_snapshot_history=rows)]
    result = compute_github_daily_metrics(metric_date='2026-07-14', db=repo)
    payload = repo.upsert_github_daily_metrics.call_args.args[0][0]
    assert payload['daily_star_growth'] == 20
    assert payload['daily_growth_source'] == 'snapshot_delta'
    assert payload['hot_score'] == score_snapshots(rows, '2026-07-14')['hot_score']
    assert payload['score_version'] == 'daily_hot_v6'
    assert result['speed_scored'] == 1 and result['legacy_fallback'] == 0
