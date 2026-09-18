import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/ci/runner_resource_budget.py"
spec = importlib.util.spec_from_file_location("runner_resource_budget", SCRIPT)
budget = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = budget
spec.loader.exec_module(budget)


def usage(cpu=0, memory=0, reserved_cpu=0, reserved_memory=0):
    return budget.Usage(cpu, memory, reserved_cpu, reserved_memory)


def test_no_queue_means_no_runner():
    assert budget.allocate(0, usage()).count == 0


@pytest.mark.parametrize("state", [usage(cpu=5.4), usage(memory=12 * budget.GIB * .9)])
def test_ninety_percent_is_not_admitted(state):
    assert budget.allocate(3, state).count == 0


def test_capacity_varies_with_queue_not_fixed_runner_count():
    assert budget.allocate(1, usage()).count == 1
    assert budget.allocate(2, usage()).count == 2
    assert budget.allocate(4, usage()).count == 3


def test_reserved_capacity_prevents_overcommit_even_when_idle():
    assert budget.allocate(9, usage(reserved_memory=12 * budget.GIB)).count == 0
    assert budget.allocate(9, usage(reserved_cpu=5.4)).count == 0


def test_allocations_never_exceed_aggregate_admission_budget():
    for queued in range(1, 21):
        for reserved in (0, 2, 4, 8, 10):
            state = usage(reserved_cpu=1, reserved_memory=reserved * budget.GIB)
            result = budget.allocate(queued, state)
            assert result.count * result.cpu + 1 <= 5.4
            assert result.count * result.memory + state.reserved_memory <= 12 * budget.GIB * .9


def test_frozen_ci_retains_reservation_and_stopped_does_not():
    item = {"name": "aigcnews-ci", "status": "Frozen", "expanded_config": {
        "limits.cpu": "6", "limits.memory": "12GiB"}}
    assert budget.reservations([item]) == (["aigcnews-ci"], 6, 12 * budget.GIB)
    assert budget.reservations([{**item, "status": "Stopped"}]) == ([], 0, 0)


def test_unknown_memory_limit_fails_closed():
    with pytest.raises(ValueError):
        budget.memory_bytes("90%")


def test_cpu_quota_is_counted_not_visible_cores():
    item = {"name": "aigcnews-ci-job-one", "status": "Running", "expanded_config": {
        "limits.cpu": "6", "limits.cpu.allowance": "180ms/100ms", "limits.memory": "3GiB"}}
    assert budget.reservations([item])[1] == 1.8


@pytest.mark.parametrize("state", [usage(cpu=float('nan')), usage(memory=-1)])
def test_bad_metrics_fail_closed(state):
    with pytest.raises(ValueError):
        budget.allocate(1, state)
