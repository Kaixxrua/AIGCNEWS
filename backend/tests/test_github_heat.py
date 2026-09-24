import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.domain.github_heat import (
    SCORE_VERSION,
    HeatInputs,
    _blend,
    _trend_curve,
    score_heat,
    snapshot_velocity,
    suspicion_multiplier,
)
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


def magnitude(growth, base):
    scale = 100 * min(math.log1p(growth / math.sqrt(max(base, 500))) / math.log1p(100), 1)
    absolute = 100 * min(math.log1p(growth) / math.log1p(10000), 1)
    return 0.625 * scale + 0.375 * absolute


@pytest.mark.parametrize(('current', 'hours', 'expected'), [(240, 2, 240), (60, 2, 210), (60, 6, 150), (60, 12, 60)])
def test_short_window_velocity_examples(current, hours, expected):
    assert _blend(current, 240, hours) == pytest.approx(expected)


def test_first_interval_without_prior_uses_its_own_rate():
    assert _blend(60, None, 2) == 60


def test_day_boundary_preserves_constant_star_velocity():
    short = snapshot_velocity(history(2, 20), '2026-07-14')
    full = snapshot_velocity(history(24, 240), '2026-07-14')
    assert short.star_velocity == pytest.approx(240) == full.star_velocity
    for key in ('scale_corrected_growth_score', 'absolute_growth_score', 'growth_acceleration_score'):
        assert score_heat(short)[key] == score_heat(full)[key]
    assert score_heat(short)['growth_acceleration_score'] == pytest.approx(60)


def test_real_cooling_reduces_velocity_without_ema():
    early = snapshot_velocity(history(2, 0), '2026-07-14')
    late = snapshot_velocity(history(12, 0), '2026-07-14')
    assert early.star_velocity > late.star_velocity == 0
    assert score_heat(late)['hot_score'] == 0


def test_invalid_history_does_not_invent_velocity():
    rows = history()
    assert snapshot_velocity(rows[:-1], '2026-07-14') is None
    assert snapshot_velocity(rows[-1:], '2026-07-14') is None
    naive = [dict(row, captured_at=row['captured_at'][:19]) for row in rows]
    assert snapshot_velocity(naive, '2026-07-14') is None
    rows[-1]['captured_at'] = 'invalid'
    assert snapshot_velocity(rows, '2026-07-14') is None
    backfilled = history()
    backfilled[-1]['captured_at'] = '2026-07-20T00:00:00+00:00'
    assert snapshot_velocity(backfilled, '2026-07-14') is None


def test_gaps_up_to_a_week_are_rates_not_single_day_spikes():
    rows = history(24, 240)
    gap = rows[:1] + rows[-1:]
    velocity = snapshot_velocity(gap, '2026-07-14')
    assert velocity.star_velocity == pytest.approx(240)
    assert velocity.baseline_velocity is None
    stale = [dict(rows[0], snapshot_date='2026-07-06', captured_at='2026-07-06T15:00:00+00:00'), rows[-1]]
    assert snapshot_velocity(stale, '2026-07-14') is None


def test_missing_inputs_are_unknown_not_zero():
    rows = history(24, 240)[-2:]
    rows[-1]['community_metrics_complete'] = False
    velocity = snapshot_velocity(rows, '2026-07-14')
    assert velocity.fork_velocity is None and velocity.baseline_velocity is None
    result = score_heat(velocity)
    assert result['score_version'] == SCORE_VERSION
    assert result['community_engagement_score'] == 0
    # 无基线 → 中性趋势；缺失社区 → 退出质量均值
    assert result['growth_acceleration_score'] == pytest.approx(60)
    quality = (0.5 * 60 + 0.25 * result['maintenance_activity_score']) / 0.75
    expected = magnitude(velocity.star_velocity, velocity.base_stars) * (0.8 + 0.2 * quality / 100)
    assert result['hot_score'] == pytest.approx(expected, abs=1e-3)


def test_historical_score_is_independent_of_future_and_reruns():
    rows = history()
    expected = snapshot_velocity(rows, '2026-07-14')
    rows.append(dict(rows[-1], snapshot_date='2026-07-15', captured_at='2026-07-15T15:00:00+00:00', stars=999999))
    assert snapshot_velocity(rows, '2026-07-14') == expected
    assert snapshot_velocity(rows, '2026-07-14') == expected


@pytest.mark.parametrize(('ratio', 'expected'), [
    (0.125, 0), (0.25, 0), (0.5, 20), (1, 60), (2, 85), (4, 100), (8, 100),
])
def test_trend_curve_anchors(ratio, expected):
    baseline = 100.0
    assert _trend_curve(ratio * (baseline + 20) - 20, baseline) == pytest.approx(expected)


def test_top_growth_does_not_saturate():
    scores = [score_heat(HeatInputs(star_velocity=g, base_stars=5000))['absolute_growth_score'] for g in (900, 2000, 6500)]
    assert scores == sorted(scores) and scores[-1] < 100
    scale = [score_heat(HeatInputs(star_velocity=g, base_stars=500))['scale_corrected_growth_score'] for g in (240, 1100, 2000)]
    assert scale == sorted(scale) and scale[-1] < 100


def test_secondary_signals_only_modulate_magnitude():
    big = score_heat(HeatInputs(star_velocity=3000, base_stars=5000, baseline_velocity=20000, baseline_confidence=1))
    small = score_heat(HeatInputs(star_velocity=600, base_stars=5000, baseline_velocity=0, baseline_confidence=1,
                                  fork_velocity=500, watcher_velocity=50, days_since_push=0))
    assert big['growth_acceleration_score'] == 0 and small['growth_acceleration_score'] == 100
    assert big['hot_score'] > small['hot_score']
    for result, growth in ((big, 3000), (small, 600)):
        assert 0.8 * magnitude(growth, 5000) - 1e-3 <= result['hot_score'] <= magnitude(growth, 5000) + 1e-3


def test_newcomer_without_history_scores_like_steady_repo():
    newcomer = score_heat(HeatInputs(star_velocity=300, base_stars=800))
    steady = score_heat(HeatInputs(star_velocity=300, base_stars=800, baseline_velocity=300, baseline_confidence=1))
    assert newcomer['hot_score'] == steady['hot_score'] > 0


def test_zero_growth_has_zero_heat():
    result = score_heat(HeatInputs(star_velocity=0, base_stars=5000, fork_velocity=20, watcher_velocity=5, days_since_push=0))
    assert result['hot_score'] == 0
    assert result['maintenance_activity_score'] == 100


@pytest.mark.parametrize(('suspicion', 'expected'), [(0, 1), (0.4, 1), (0.5, 0.7), (0.9, 0.46), (1.5, 0.4)])
def test_suspicion_demotes_only_multi_signal_growth(suspicion, expected):
    assert suspicion_multiplier(suspicion) == pytest.approx(expected)
    inputs = HeatInputs(star_velocity=500, base_stars=1000)
    assert score_heat(inputs, suspicion=suspicion)['hot_score'] == pytest.approx(
        score_heat(inputs)['hot_score'] * expected, abs=1e-3)


def test_service_scores_snapshot_velocity_but_preserves_observed_daily_delta():
    rows = history()
    repo = MagicMock()
    repo.get_github_daily_metric_inputs.return_value = [dict(repo_id='one', stars=1740,
        previous_stars=1720, previous_snapshot_date='2026-07-13', heat_snapshot_history=rows)]
    result = compute_github_daily_metrics(metric_date='2026-07-14', db=repo)
    payload = repo.upsert_github_daily_metrics.call_args.args[0][0]
    assert payload['daily_star_growth'] == 20
    assert payload['daily_growth_source'] == 'snapshot_delta'
    assert payload['hot_score'] == score_heat(snapshot_velocity(rows, '2026-07-14'))['hot_score']
    assert payload['score_version'] == SCORE_VERSION == result['score_version']
    assert result['snapshot_velocity'] == 1 and result['observed_velocity'] == 0


def test_service_zero_observed_growth_ignores_previous_interval_velocity():
    rows = history(2, 0)
    assert snapshot_velocity(rows, '2026-07-14').star_velocity > 0
    repo = MagicMock()
    repo.get_github_daily_metric_inputs.return_value = [dict(repo_id='one', stars=1720,
        previous_stars=1720, previous_snapshot_date='2026-07-13', heat_snapshot_history=rows)]
    compute_github_daily_metrics(metric_date='2026-07-14', db=repo)
    payload = repo.upsert_github_daily_metrics.call_args.args[0][0]
    assert payload['daily_star_growth'] == 0
    assert payload['hot_score'] == 0
