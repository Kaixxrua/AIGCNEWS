import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
import local_ci as ci


def test_lock_timeout_retries_before_single_launch(monkeypatch, tmp_path):
    attempts = []
    @contextmanager
    def lock(*args):
        attempts.append(args)
        if len(attempts) < 3:
            raise TimeoutError('shared admission lock timed out')
        yield
    monkeypatch.setattr(ci, 'admission_lock', lock)
    monkeypatch.setattr(ci.time, 'sleep', lambda _: None)
    runner, progress = Mock(), Mock()
    ci.launch_with_retry(runner, {'state_dir': str(tmp_path), 'queue_timeout': 90}, {}, progress)
    assert len(attempts) == 3
    runner.launch.assert_called_once()
    assert any(call.kwargs.get('retry_at') for call in progress.update.call_args_list)


def test_partial_launch_timeout_never_replayed(monkeypatch, tmp_path):
    @contextmanager
    def lock(*args):
        yield
    monkeypatch.setattr(ci, 'admission_lock', lock)
    runner = Mock()
    runner.launch.side_effect = TimeoutError('start failed')
    with pytest.raises(TimeoutError, match='start failed'):
        ci.launch_with_retry(runner, {'state_dir': str(tmp_path)}, {}, Mock())
    runner.launch.assert_called_once()


def test_retry_limit_and_total_budget(monkeypatch, tmp_path):
    clock = [0.0]
    waits = []
    @contextmanager
    def lock(root, timeout):
        waits.append(timeout)
        clock[0] += timeout
        raise TimeoutError('busy')
        yield
    monkeypatch.setattr(ci, 'admission_lock', lock)
    monkeypatch.setattr(ci.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(ci.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))
    runner = Mock()
    with pytest.raises(TimeoutError):
        ci.launch_with_retry(runner, {'state_dir': str(tmp_path), 'queue_timeout': 90}, {}, Mock())
    assert len(waits) == 3
    assert clock[0] <= 90
    runner.launch.assert_not_called()
