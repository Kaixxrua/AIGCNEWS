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
Codex app-server Unix WebSocket adapter. Only a confirmed idle thread may be dispatched;
pause and obsolete SHA checks suppress delivery. A receipt is required before
marking a wakeup sent. Ambiguous failures stay unconfirmed, never blindly
replayed. It inherits thread configuration and does not change model or approval
policy. Failure prompts send the PR back to development and require fresh CI.

`watch_delivery_feedback.py` reads the independent observatory snapshot (maximum
age 180 seconds), requires creation-time ownership and exact branch/SHA, then
reads the live PR twice. Only same-repository, open, non-draft conflicts targeting
main are dispatched. GitHub access is GET-only. Test-failure classification is
not enabled: infrastructure/network failures must not be reported as code faults.
The CI pause marker also pauses wakeups, and is rechecked after GitHub requests.

Install the watcher, `delivery_feedback.py`, `delivery_ownership.py` and `delivery_sweeper.py` under
`~/.local/lib/aigcnews-delivery-feedback/`, then install the supplied user service.
It uses the existing backend venv with `websockets==15.0.1`, the existing private
`~/.config/aigcnews/delivery-read-token`, and a singleton lock and SQLite outbox
under `~/.local/state/aigcnews-delivery-feedback/`. Do not log credentials.
Inspect `journalctl --user -u aigcnews-delivery-feedback.service` for receipts or
pause/unavailable status. Unconfirmed/dispatching records need manual receipt
reconciliation; never reset them to pending without verifying no turn was created.

The local server has acknowledged initialize and thread/read in a real read-only
probe. Automated tests cover turn/start transport, deduplication and rejection
cases, but no live task has been awakened for acceptance testing. Busy and
notLoaded tasks wait; the adapter does not resume unloaded or archived tasks.
The second idle check reduces races but is not an atomic idle-and-start operation;
concurrent desktop input behavior remains an integration-test limitation.
Do not use a second CLI agent or modify Codex's SQLite state to simulate success.
The service may be installed while CI remains paused; installation does not imply
end-to-end wakeup, CI or production-delivery acceptance.

### Directed ownership

Dashboard `association=verified` and `session-links.json` are NOT wakeup authority.
At worktree creation, `dev_session.py start` records the caller's UUID from
`CODEX_THREAD_ID` in a private, exclusively created receipt under the Git common
directory's `delivery-owners/`. Receipts bind thread, branch and worktree. The
watcher verifies the current worktree branch and repository and rechecks ownership
before dispatch. It never falls back to the current task, branch mentions or a
dashboard-supplied thread ID. Missing receipts report `ownership_unverified`.
Legacy branches (including PR #66) require independently verified ownership
before any migration; no old receipt is fabricated from the current environment.
Tasks started without `CODEX_THREAD_ID` remain ineligible for automatic wakeup.

The earlier one-shot acceptance hardcoded the observing task and demonstrated
transport only, not correct ownership. It must not be reused. Turn receipt/read
inconsistency also remains unverified; directed end-to-end acceptance is pending.
Subsequent inspection found the original `dev_session.py start` call and receipt
for PR #66 in the observing task's history (call
`call_bbzGzhsUOB4mpK4XPP8nxR18`). This means #66 was an unsuitable cross-task
acceptance target, not proof that the transport routed to a different task.
No legacy receipt has been minted or automatic wake enabled on that basis.
