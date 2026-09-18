# CI resource admission and delivery feedback

The new controller replaces the fixed two-runner admission decision with a
shared budget: 6 logical CPU equivalents and 12 GiB for CI containers. Only
90 percent (5.4 CPU and 10.8 GiB) may be reserved when admitting new work.
There must be queued runnable jobs, measured CPU and memory must both be below
90 percent, and existing reservations plus new allocations must fit.

All non-stopped `aigcnews-ci` and `aigcnews-ci-*` LXD containers count, including
frozen containers. Production is not in this pool. New runners have explicit
CPU time quotas, byte memory limits and swap disabled. The controller has a
singleton file lock. Inventory changes, missing limits, swapping or unavailable
metrics reject admission. Limits must not be increased outside the controller;
the aggregate bound currently relies on summed per-container hard limits, not
an independently provisioned parent cgroup.

Admission dynamically chooses a count from queued demand and available reserved
capacity, with a conservative 1 CPU / 3 GiB minimum per general-purpose job.
One, two or three new jobs can be admitted into an empty pool. This minimum is
not a measured guarantee for every test suite. Existing reservations are not
shrunk under running processes. Job-class profiling and reserved control-plane
capacity are not implemented by this change. Legacy workflow labels also still
need migration; this change does not silently route privileged control jobs to
general-purpose runners.

`~/.config/aigcnews/ci-paused` is a persistent admission pause. It is checked
before runner cleanup or creation. Stopping the service alone is not a durable
pause across reboots. Frozen legacy CI still holds its complete reservation;
it must be safely drained before the new pool has capacity.

`delivery_feedback.py` implements a durable per-thread/PR/SHA/fault outbox and a
Codex app-server proxy adapter. Only a confirmed idle thread may be dispatched;
pause and obsolete SHA checks suppress delivery. A receipt is required before
marking a wakeup sent. Ambiguous failures stay unconfirmed, never blindly
replayed. It inherits thread configuration and does not change model or approval
policy. Failure prompts send the PR back to development and require fresh CI.

The installed Codex CLI exposes `app-server proxy`, but the current local server
did not acknowledge initialize during a bounded read-only probe. Therefore the
adapter is NOT enabled as a watcher, no live task has been awakened, and automatic
fault collection/dispatch is not yet connected. Verify the desktop bridge and
its concurrent-turn semantics before enabling it; do not use a second CLI agent
or modify Codex's SQLite state to simulate a successful wakeup.
