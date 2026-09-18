# User-delegated shared CI parent: isolated feasibility evidence

Observed 2026-09-18; cleanup verified at 12:34:03 UTC. This is a feasibility
result, not approval to migrate CI or enable the adaptive scheduler.

## Host and authority

- LXD 5.21.7 LTS, LXC 6.0.6, systemd 255, cgroup v2.
- `user@1000.service` delegates `cpu memory pids`.
- Its cgroup directory, `cgroup.procs` and `cgroup.subtree_control` belong to
  UID/GID 1000. CPU and memory controllers are available and enabled there.
- No sudo, host-privilege helper or permission expansion was used. LXD operations
  used the existing API authorization. No existing container was restarted,
  migrated, stopped or reconfigured.

## Isolated executed proof

A transient USER service `aigcnews-cgroup-proof-pr66.service` was created with:

```ini
Delegate=cpu memory pids
DelegateSubgroup=supervisor
CPUQuota=600%
MemoryMax=12G
MemorySwapMax=0
RuntimeMaxSec=180
ExecStart=/usr/bin/sleep 170
```

The service's parent was:

```
/user.slice/user-1000.slice/user@1000.service/app.slice/aigcnews-cgroup-proof-pr66.service
```

Observed kernel files:

| File | Value |
| --- | --- |
| `cpu.max` | `600000 100000` |
| `memory.max` | `12884901888` |
| `memory.swap.max` | `0` |
| `cgroup.procs` | empty |

A disposable container was initialized from cached Ubuntu image
`cc6b6e557372769f5b0d0945d61f200360818a408f9d0dddadbbab584d2fb414`, with no
profiles, no network device, no runner credentials, no autostart, 0.1 CPU quota,
256 MiB hard memory and swap disabled. No existing template was modified.

Through the normal `lxc config set ... raw.lxc` API, LXD accepted:

```ini
lxc.cgroup.dir.container = user.slice/user-1000.slice/user@1000.service/app.slice/aigcnews-cgroup-proof-pr66.service/aigcnews-cgroup-proof-pr66
lxc.cgroup.dir.monitor = user.slice/user-1000.slice/user@1000.service/app.slice/aigcnews-cgroup-proof-pr66.service/aigcnews-cgroup-proof-pr66-monitor
lxc.cgroup.dir.container.inner = payload
```

The container started successfully. Host `/proc/3315441/cgroup` placed init at:

```
0::/user.slice/user-1000.slice/user@1000.service/app.slice/aigcnews-cgroup-proof-pr66.service/aigcnews-cgroup-proof-pr66/payload
```

Its outer child limits were `cpu.max=10000 100000`,
`memory.max=268435456`, `memory.swap.max=0`. Inside the container,
`/proc/1/cgroup` reported `0::/init.scope`: the host parent and outer limit
controls are outside the container cgroup namespace. The parent belonged to
UID/GID 1000 and remained free of direct processes.

This establishes that this LXD build accepts and executes the documented raw
placement under a user-delegated service. It is stronger evidence than the LXC
manual alone. It does not prove adversarial escape resistance, sustained load,
monitor PID placement, reboot behavior or production nested-Docker behavior.

Cleanup: deleted only the disposable container, then stopped only the temporary
user service. Verified the container absent, service `LoadState=not-found` /
`ActiveState=inactive`, and its parent cgroup removed. Existing CI containers
remained running. No persistent unit or live pool was installed.

## Ownership and lifecycle requirements before rollout

Use a dedicated stable user service with a supervised lifetime, not the AO task
service or an interactive login scope. A slice can own limits, but delegation is
provided by a service beneath it; the executed proof used a service directly.
The controller must resolve `ControlGroup` from the intended unit and verify its
UID, active state, invocation identity and cgroup inode, rather than trusting a
path string. Parent replacement must invalidate all cached evidence and repeat
inventory reconciliation and settling. Never let LXC recreate a missing parent
with unlimited defaults: verify the active owning unit and kernel limits before
starting a canary or payload.

The service's `supervisor` subgroup needs explicit accounting and verification.
The updated draft verifies the systemd MainPID and exclusive supervisor
membership, counts parent-wide actual load and reserves a 64 MiB supervisor
bound plus a 64 MiB shared monitor bound. Monitor PIDs must identify the named
LXC container and occupy the expected subgroup. Unknown processes or subgroups
fail closed. These new checks have mocked tests; the revised supervisor and
shared monitor hierarchy still need coordinator runtime acceptance. All CI/control containers must have verified runner identities
and remain beneath this parent; host or other-project runners must fail closed.

A parent service stopping or reaching a runtime limit while containers remain
can terminate payloads or remove their lifecycle anchor. The temporary proof's
runtime limit and sleep are NOT a production unit design. Production needs an
explicit drain-before-stop protocol, boot ordering, disabled payload autostart
until the parent is verified, and no controller restart that restarts the parent.
User-manager logout/reboot persistence must be established under existing host
policy; do not enable linger or add privileges implicitly. Reboot acceptance,
monitor placement, concurrent pressure and nested Docker still require bounded
coordinator-owned tests.

Keep the existing reservation fallback until these integration requirements are
implemented and reviewed. A shared parent can enforce total ceilings, but it does
not make actual-memory-only overcommit OOM-safe. Retain growth protection and do
not reduce running containers' memory limits.

## References

- https://linuxcontainers.org/lxc/manpages/man5/lxc.container.conf.5.html
- https://github.com/canonical/lxd/blob/lxd-5.21.7/lxd/instance/instance_utils.go
- Installed LXD instance-options documentation: percentage CPU allowance uses
  shares; time allowance uses CFS quotas.


## Prepared persistent owner (not installed)

`aigcnews-ci-pool.service` uses the proven user delegation and parent ceilings,
with `DelegateSubgroup=supervisor`, `Restart=no`, `KillMode=mixed` and infinite
stop timeout. Its unprivileged Python owner handles SIGTERM by waiting for
payload and monitor subgroups to disappear. Admission rejects a deactivating
unit, so ordinary stop requests prevent fresh launches while old work drains.
Forced termination, OOM, user-manager shutdown or host failure can still kill
payloads; this is not a guarantee against infrastructure loss. The coordinator
must validate logout/boot policy and drain ordering. Nothing enables linger,
installs a privileged helper or changes permissions.

The controller checks service active/delegated state, ControlGroup, UID,
InvocationID, MainPID and cgroup inode. Owner replacement resets scheduler
warmup. It rechecks ownership before launch and membership before releasing JIT
configuration. The owner initializes bounded subgroups only on an empty parent;
it refuses to shrink existing limits or adopt leftover payloads after a crash.
