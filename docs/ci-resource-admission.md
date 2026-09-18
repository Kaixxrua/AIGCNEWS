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
capacity are not implemented by this change. Workflow routing uses ephemeral runners for PR admission, tests and contract
evaluations, with separate trusted control and production runners. Before
activating these labels, drain legacy CI and establish the control runner;
privileged control jobs must not run on general-purpose PR runners.

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
reads the live PR twice. Only same-repository, open, non-draft PRs targeting
main with conflicts or a head behind/diverged from current main are dispatched.
Base-update notifications deduplicate by task/PR/head rather than every main SHA;
the receiving task fetches latest main once before resolving and validating.
GitHub access is GET-only. Test-failure classification is
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
New tasks without a valid `CODEX_THREAD_ID` are rejected before worktree creation;
start from the owning Codex task rather than silently creating an unowned branch.

The earlier one-shot acceptance hardcoded the observing task and demonstrated
transport only, not correct ownership. It must not be reused. Turn receipt/read
inconsistency also remains unverified; directed end-to-end acceptance is pending.
Subsequent inspection found the original `dev_session.py start` call and receipt
for PR #66 in the observing task's history (call
`call_bbzGzhsUOB4mpK4XPP8nxR18`). This means #66 was an unsuitable cross-task
acceptance target, not proof that the transport routed to a different task.
No legacy receipt has been minted or automatic wake enabled on that basis.

### Temporary queue-label compatibility

During migration, the coordinator may set
`AIGCNEWS_RUNNER_COMPAT_LABELS=aigcnews-ci` in the autoscaler environment.
The optional comma-separated labels augment `AIGCNEWS_RUNNER_LABEL` (default:
`aigcnews-ci-ephemeral`). Queued jobs matching either the primary label or an
alias are counted once by job ID, case-insensitively. Each temporary JIT runner
registers all supported labels so it can serve either workflow generation.
The default has no aliases. Resource admission, quotas, singleton locking and
LXD isolation are unchanged; aliases never create a separate resource pool.

Keep the small trusted control runner control-only; do not give it the classic
CI label. Remove `AIGCNEWS_RUNNER_COMPAT_LABELS` after all workflows have migrated
and remaining classic-label runs, including queued older runs, have drained.
Removing the setting affects newly created runners; existing one-job runners
retain their registration until completion. Runtime changes belong to the
coordinator and are separate from installing this code.

### Prepared shared-parent adaptive mode (not runtime-accepted)

Read-only inspection on 2026-09-18 found LXD 5.21.7, LXC 6.0.6 and unified
cgroup v2 with CPU and memory controllers. The control container was under
`/lxc.payload.aigcnews-ci/init.scope`, not a shared CI parent. Upstream
[LXD validation](https://github.com/canonical/lxd/blob/lxd-5.21.7/lxd/instance/instance_utils.go)
allows the raw keys documented by
[LXC](https://github.com/lxc/lxc/blob/stable-6.0/doc/lxc.container.conf.sgml.in):
`lxc.cgroup.dir.container`, `lxc.cgroup.dir.monitor`, and
`lxc.cgroup.dir.container.inner`. A subsequent disposable user-service/container proof confirmed placement on this
host; see `docs/ci-user-cgroup-feasibility.md`. Existing containers and production
services were not changed. The new persistent owner design is not runtime-accepted.

The coordinator must separately install/review `aigcnews-ci-pool.service` and its
unprivileged `runner_pool_owner.py`. The autoscaler installer copies the Python
owner but never installs or starts the pool unit. The dedicated parent must have
`cpu.max = 600000 100000`, `memory.max = 12884901888`, and
`memory.swap.max = 0`, delegate CPU/memory controllers to its children and
arrange durable recreation before LXD instances start after reboot. Use an
empty parent (no direct processes). Place all CI payloads, nested Docker and
the control runner beneath it. Never lower live memory limits or move running
jobs to accomplish migration: drain and recreate instead. A control container
must carry its correct `user.aigcnews.runner_id`; nonstandard CI container
names must also carry `user.aigcnews.ci=true`. Other LXD projects or host CI
runners are not supported unless their payloads are brought into this inventory.
All CI provisioners must serialize with the existing controller lock; kernel
ceilings remain effective during races, but external unsynchronized resource
changes cannot provide the same memory growth guarantee.

Only after coordinator acceptance may
`AIGCNEWS_RUNNER_SHARED_CGROUP=/sys/fs/cgroup/<dedicated-parent>` select adaptive
mode, together with `AIGCNEWS_RUNNER_SHARED_UNIT=aigcnews-ci-pool.service`.
The installer includes `shared_runner_pool.py`. The controller never
creates or edits the parent. The unprivileged owner initializes only its new
supervisor/monitors subgroups, each with a 64 MiB hard ceiling and no swap,
refusing existing payloads or existing memory bounds. These 128 MiB of growth
headroom count in admission. It uses no sudo or privilege helper. New instances receive separate payload and monitor
paths under it; conflicting template placement is rejected. Before admitting,
it verifies kernel ceilings, swap, every active/frozen container's init PID and
kernel child memory bound, online/busy CI/control registrations, and unexpected
parent subtrees. Membership and inventory are rechecked during measurement and
immediately before launch; new container membership is checked before providing
JIT configuration. Any unavailable or inconsistent proof denies admission.

The controller uses actual parent CPU/memory samples, an EWMA (alpha 0.5), the
maximum of current and smoothed load for burst protection, 90% stop / 80% resume
hysteresis, memory PSI/events, and a 60-second settling interval after startup,
inventory changes and launches. Each poll launches at most one runner; CPU
startup headroom is 1 CPU and memory headroom is task-predicted. CPU scheduling uses LXD
priority 5 and a 100% allowance (relative weight, not a permanent time quota).
There is no runner-count admission cap in this mode. Idle demand launches none;
completion removes predicted remaining growth, followed by settling before reuse.
Restart reconstructs membership and measured predictions and repeats warmup, so it does
not forget running jobs or burst-launch on empty controller state.

Shared mode deliberately permits memory overcommit under the hard parent. It
uses queued/running job metadata: admission/control floor 256 MiB, MCP 768 MiB,
database/backend/frontend/smoke 2 GiB, unknown 3 GiB. These are provisional
bootstrap predictions, not demonstrated workload bounds. Measured per-container
`memory.peak` updates category high-water history with a 25% margin. Admission
adds predicted remaining growth of active work and startup demand to the greater
of actual/smoothed memory. Hard-limit sums are reported, not used to cap shared
concurrency. No active memory limit is shrunk; new children use the 12 GiB ceiling,
with the 12 GiB parent providing the aggregate bound and `memory.high` at
11596411699 bytes (90%) providing reclaim/throttling feedback.

There may be at most two unassigned bootstraps and one launch per settling
interval. The controller identifies the control runner separately so an idle
control service is not a permanent bootstrap. Generic JIT labels cannot bind a
runner to a selected job: mixed queues use the largest eligible category
prediction. Category-specific routing is a future optimization, not something
this implementation pretends to provide. Unknown work uses the conservative
unknown floor. Shared-mode clones override the template poweroff hook so completed one-job
containers remain until the host captures their final `memory.peak` and OOM
counters into an fsynced exact-job/run/SHA receipt. Reaping requires a completed
live job response and a finished JIT service before deregistration/deletion.
Abruptly stopped containers or missing identity remain for reconciliation rather
than silently losing their final peak. History is a conservative bounded high-water estimate,
not a calibrated percentile or guaranteed upper bound.

Memory PSI, high/max events and OOM evidence stop admission. OOM observations
persist in workload-history.json and require coordinator reconciliation; a
restart does not erase the hold. Parent OOM counts also latch a hold for the
parent's lifetime. Record affected job IDs, preserve logs, classify the failed
job, update its profile from evidence, and rerun only after head/base validation
and coordinator clearance. This draft does not blindly retry OOM failures or
clear evidence. Existing work continues under the parent; no active limits are
shrunk and no job is killed to make room.

CPU, measured memory, predicted growth/startup, bootstrap count, pressure,
OOM hold, memory.high and hard-limit overcommit are exposed in plan metrics.
Memory overcommit can OOM on an unexpected simultaneous spike. There is no
mathematical no-OOM guarantee and no promise that CPU, memory and network all
reach 90%. Floors, history quality, final peak collection and spike recovery
require runtime validation before rollout.

With the shared-parent setting absent, the reservation allocator remains the
safe fallback, now also requiring registered CI/control coverage. If shared mode
was selected but its parent is missing or invalid, it fails closed rather than
silently treating weight-only children as quota-limited. To revert, drain shared
instances and return to explicit per-container quotas before clearing the setting.

Before rollout, the coordinator must validate parent placement for a bounded
canary, child CPU weights, inherited no-swap and nested Docker membership,
control accounting, concurrent CPU/memory bursts, cgroup recreation after a
restart and safe drain. Unit tests use mocked inventories and temporary files;
they do not establish live LXD placement or workload sizing acceptance.


### Coordinator Mihomo egress acceptance

Both the original proxy (`172.17.0.1:7897`) and replacement
(`127.0.0.1:17897`) are Mihomo. The coordinator's local record
`~/.local/state/aigcnews-ao/ci-egress-acceptance.json`, timestamp
`2026-09-18T12:39:30.757202+00:00`, records two successful actual `git ls-remote`
probes from the control container through an isolated LXD proxy. Coordinator
also reported a successful GitHub curl probe and checkout TLS failure for
job 105597333416 on attempt 2. The probes are coordinator evidence, not a claim
that the failed workflow has since passed.

Only the stopped `aigcnews-ci-template-v2` device was changed:
`egress-proxy.connect=tcp:127.0.0.1:17897`; the container-facing listener remains
7895. Existing payloads and production were not changed. Cloning retains that
device. To make this expectation explicit, the coordinator can set
`AIGCNEWS_RUNNER_EXPECTED_PROXY_CONNECT=tcp:127.0.0.1:17897`. The controller then
reads the template and clone's expanded device configuration and rejects a
mismatch before startup; it never changes the endpoint. This verifies
configuration inheritance, not network availability. Runtime proxy ownership
and switching remain with the coordinator.
