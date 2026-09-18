# Shared CI pool operator setup and acceptance

The frozen PR66 draft was imported into the newly bound standalone-12 worktree
on merged main `65c3a8ccd506750ba73b5393097952945e534136`. All 19 source hashes
matched before review fixes. The original worktree remains untouched. After coordinator release, the branch fast-forwarded to PR68 merge
`549d9bf4817c840cdab906683dd9325d28935a97`, preserving all production
notification changes exactly. Runtime installation remains coordinator-owned. No runtime
activation commands below have been applied to the live CI pool.

## Executed isolated acceptance

The disposable parent ran the actual `runner_pool_owner.py` via a transient user
service, with Type=notify readiness, user delegation, CPU6, MemoryHigh90%,
MemoryMax12GiB and no swap. UID ownership, invocation and MainPID checks passed.
The supervisor and monitors had 64 MiB hard memory ceilings each. Existing CI
reservations were checked before each canary; the canary payload had 0.25 CPU /
512 MiB limits, and supervisor/monitor CPU limits were each 0.05 CPU. Thus the
proof added at most 0.35 CPU / 640 MiB against existing reservations (at most
5.39 CPU / 10.8 GiB during this session), below 6 CPU / 12 GiB total. It did not
attempt a full 90%-load experiment while production CI was running.

A stopped sanitized template was cloned to a disposable name. Network devices
were disabled/removed on the clone only. Docker was started only inside the
canary; nested containers carried `ao.session`, used `--network none` and
`--pull=never` with a cached image ID. No proxy or existing runner was changed.

- Nested Docker reported cgroup v2/systemd. The payload and LXC monitor were in
  the expected user-parent subgroups; the nested workload was below the payload.
- A bounded 64 MiB allocation/CPU workload exited 0. Swap remained zero. The
  final outer memory peak was 536875008 bytes (kernel page accounting).
- A stop request left the owner `deactivating` while the container remained
  Running and completed its work. After container deletion the owner exited and
  systemd collected the transient unit. The final redundant stop returned
  “unit not loaded”; subsequent read-only checks confirmed no unit/container/
  parent remained. This is successful drain cleanup, not a surviving service.
- An intentional nested 96 MiB limit with a 256 MiB allocation exited 137 with
  `OOMKilled=true`. The outer cgroup recorded `oom=1`, `oom_kill=1`, no swap.
  Only the disposable workload was killed. This proves real OOM evidence is
  observable; exact GitHub job attribution/recovery was validated with mocked
  API identity tests, not a deliberately failed live GitHub job.

Evidence: `docs/evidence/ci-pool-load-drain.json` and
`docs/evidence/ci-pool-oom.json`. Parent memory.high is rounded down by the kernel
by less than one page; the verifier accepts only that downward rounding.

## Coordinator activation sequence

1. Keep the existing live pool unchanged until current jobs drain. Preserve the
   persistent admission-pause marker. Stop the old autoscaler before staging
   new modules; the staging installer refuses an active autoscaler.
2. From the approved worktree run `bash scripts/ci/install_shared_runner_pool.sh`.
   It stages user units/modules only: no reload, enable, start, permissions or
   linger changes. It uses the canonical user install path.
3. Review the staged unit and `shared-pool.conf` dependency. The scheduler has
   Requires/After/BindsTo on the parent; Type=notify waits for bounded subgroups.
   Ensure every CI/control container has `boot.autostart=false`; otherwise
   `check_shared_runner_pool.py` refuses boot-order acceptance. Never migrate a
   running payload. The coordinator recreates drained control/CI containers
   under the parent and records their actual runner IDs.
4. Coordinator runs `systemctl --user daemon-reload` and starts
   `aigcnews-ci-pool.service`. No sudo is required. Read its ControlGroup using
   `systemctl --user show aigcnews-ci-pool.service -p ControlGroup --value`.
5. In the existing private autoscaler environment, configure
   `AIGCNEWS_RUNNER_SHARED_UNIT=aigcnews-ci-pool.service` and
   `AIGCNEWS_RUNNER_SHARED_CGROUP=/sys/fs/cgroup/<reported ControlGroup>`.
   Keep the compatibility label while old queued workflows exist. Preserve the
   coordinator-approved Mihomo endpoint and optional expected-proxy assertion.
   Do not print credentials or change them.
6. Run the read-only `check_shared_runner_pool.py` under that environment, then
   a controller dry run. All online/busy CI/control registrations must map to
   inventoried payloads; unknown ownership, parent placement or limits block.
7. Coordinator may enable parent/controller user units only under the existing
   approved user-manager persistence policy. This does not enable linger.
   The read-only preflight requires existing `Linger=yes`; the policy verification
   below establishes the configured boot/logout behavior. A physical reboot/logout
   experiment remains separate from this policy acceptance. Remove the
   pause marker and start the scheduler only after full accounting passes.

## Drain and recovery

Normal drain: create the persistent pause marker, stop the autoscaler service,
then run the installed `autoscaler.py --apply --drain --loop` under its existing
private environment. This mode shares the singleton lock, records final peaks
and reaps completed containers, but never registers or launches new jobs.
Stop the drain process once no ephemeral instances remain. The coordinator must
also drain and stop the control runner before stopping the parent. A normal
parent stop waits for payload/monitor subgroups to disappear; force-stop,
logout or machine failure remain external loss risks.

For OOM, preserve logs and the fsynced `job-receipts/<runner-id>.json`, which
contains exact job/run/head, final peak, conclusion and OOM classification.
Non-OOM failures are `needs_failure_logs`, never automatically called code bugs.
A failed final capture prevents deletion. Review workload sizing and reduce
admission risk before retry. The history latch persists across controller
restarts; no automatic rerun occurs.

After draining all CI/control and recreating a clean parent, the coordinator can
run `review_pool_recovery.py --runner-id ID --job-id ID --pr NUMBER
--current-head SHA --evidence 'review reference and profile correction'` under
the existing environment. It requires the singleton lock, verified empty parent,
zero parent OOM evidence and live PR/main ancestry checks. It consumes one durable
recovery authorization before clearing that exact job's latch. It does not rerun
a workflow. Duplicate attempts fail closed; interrupted receipt/history updates
require reconciliation, not replay. A coordinator-triggered fresh validation
must still pass all current-head/base gates.

## Remaining rollout boundaries

Isolated nested load, OOM observation and drain passed. Full production-job peak
calibration, 90% sustained saturation, multi-job CPU fairness measurements and
host reboot/logout acceptance were not forced on the shared host. Bootstrap
floors remain estimates. Actual-memory overcommit can OOM; parent memory.high
and prediction margins reduce risk, not eliminate it. New children keep a fixed
12GiB maximum beneath the hard shared parent; active memory limits are never
shrunk. Fallback reservation mode remains available only after draining
weight-only shared children and restoring explicit quotas.

## Fresh-worktree review and persistence policy

On 2026-09-18, read-only checks found `loginctl show-user kaixxrua` reporting
`Linger=yes`, `State=active`, and `RuntimePath=/run/user/1000`. The existing
root-owned `/var/lib/systemd/linger/kaixxrua` marker dates to 2026-09-16.
`user@1000.service` and the user `default.target` are active. The existing
controller is enabled; the new parent unit is not installed yet. Effective
logind configuration has no local override of the default `KillUserProcesses=no`.
Thus the existing user manager is configured to start at boot and survive the
last logout. The coordinator still must stage and enable the reviewed dependency
chain; this is policy evidence, not an executed reboot/logout test. No linger,
permission, user-manager, CI, or production settings were changed.

Review fixes persist runner/instance ownership before payload launch, explicitly
set clone `boot.autostart=false`, install the recovery tool's controller import,
cache terminal workflow jobs by run attempt, bound LXD command waits, reject
nonfinite prediction evidence, and finalize completed young runners without the
old five-minute delay. Waiting for an active JIT service or GitHub completion
propagation does not restart admission warmup. An isolated controller regression
admits an eighth light runner with legacy maximum two and 84GiB summed child
ceilings, while actual load and predicted growth remain below the shared target.

Missing task identity or final counters remains a preservation/reconciliation
hold, never permission to delete a container or replay a task. Two unassigned
bootstrap runners temporarily block further starts; this bounds uncertain
startup demand and is not a cap on running assigned jobs. A listener that never
receives a task is preserved for coordinator review rather than silently killed.
