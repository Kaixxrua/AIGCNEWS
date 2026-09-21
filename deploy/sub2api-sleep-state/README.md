# SUB2API sleep-state adapter

This deployment package is for the separate SUB2API installation on the CN
host. It does not change the AIGCNEWS backend or its Docker Compose services.

## Source and scope

- SUB2API base: `4d8c1f0b4` (the deployed v0.2.5 build with existing UI preserved).
- Adapter commits: `fc92f756e`, `1374ea476`, `f8147062c`; apply `sub2api.patch` with `git am`
  to that base, not arbitrary upstream main.
- sleep-state base: `gylive/ccodex-sleep-state` commit
  `dab37ce36c48818f81ec15fc152a6c7058991ace` (GPL-3.0), plus `sleep-state.patch`
  (`91bf7cb`), preserving the upstream usage object in legacy compaction output.
- Account opt-in: `accounts.extra.openai_sleep_state_enabled`, default false.
  Only OpenAI OAuth accounts are eligible. This rollout selects account 821.
- Supported models are the sidecar's `gpt-6-astra`, `gpt-5.6-sol`, and
  `gpt-5.6-terra`. Other models, including existing Luna traffic, retain native
  forwarding rather than being remapped or rejected by the sidecar.

The HTTP adapter preserves request bodies, authentication, account identity and
SSE streaming. It sends supported Codex endpoints to the fixed address
`127.0.0.1:17841`, without an environment proxy or redirects. It does not copy
OAuth credentials to disk or retry a failed sidecar generation. Existing
SUB2API error handling still applies. Other account types and unrelated
endpoints retain their original transport.

Opted-in accounts use HTTP/SSE for the upstream leg, including the existing
WebSocket HTTP bridge. Legacy compaction for supported models preserves the requested model instead
of applying an incompatible global/account compact-model override. Disabling
the flag restores the previous transport and compaction mapping behavior.

## Runtime

The sidecar shares the SUB2API network namespace and binds only to loopback.
It has no published ports, Docker socket, or database access. Both containers
run as UID 1000; the sidecar has a read-only root filesystem and a dedicated
state volume. The sidecar prints its management token at startup;
Docker log access remains restricted to host administrators.

Configuration is generated on the private host using the account's existing
proxy 4. Credentials stay in the protected runtime directory. Direct egress is
disabled; probes are limited to one candidate per round with a 180-second
cooldown. `state_fallback=passthrough` keeps requests working when no qualifying
state is available. It does not claim that injection occurred in that case.

The expected personal-account state shape is an upstream project's heuristic,
not a verified model-quality measurement. Initial Sol and Astra probes observed
11 blocks / 312 characters, not the expected 10 blocks / 292 characters.
Enabling this deployment therefore does not establish a quality improvement.

## Build and delivery

Build the patched SUB2API backend using its Go 1.27 toolchain and the existing
deployment's embedded `internal/web/dist`, with `CGO_ENABLED=0`, `-trimpath`,
`-tags embed`, and the deployment version passed through `main.Version`.
Build sleep-state with `CGO_ENABLED=0 go build -trimpath ./cmd/ccodex-sleep-state`.
Place both binaries, this Dockerfile, and `rollout.py` in the host's protected
`/opt/sub2api-cn/releases/sleep-state-20260921` directory.

The script must run as root on that host. It locks the existing deployment lock,
checks the previous image/account, preserves Compose and the original account
flag, and creates an isolated staging sidecar. The commands are:

```sh
python3 rollout.py prepare
python3 rollout.py stage-test
python3 rollout.py activate
```

Activation recreates the gateway and sidecar together, checks health, then
requires an integrated SSE reply plus compaction and continuation through the
existing key 81 / group 14, whose only account is 821. A failure restores the
old image, Compose file and account flag. Database schema is unchanged. Runtime
evidence is kept in `/opt/sub2api-cn/backups/sleep-state-20260921`.

To roll back manually, run `python3 rollout.py rollback`. The rollback stops
and removes only this sidecar and restores the original application image.
Recreating the gateway later must also recreate its namespace-sharing sidecar.
The first activation and rollback were exercised while validating compaction.

## Validation

- sleep-state: `go test ./...` passed.
- SUB2API: unit tests for service, handler and server middleware passed.
- Adapter, WebSocket resolver, turn-state, HTTP bridge and compact contracts
  passed with `-race -parallel=1`; the compact-model fix has an additional
  regression test for both enabled and disabled behavior.
- The wider parallel race invocation exposes pre-existing concurrent
  `gin.SetMode` calls in compact tests; this was reproduced on the unchanged
  deployment source. Serial race checking avoids that test-fixture conflict.
- Rollout script: Python compilation and repository Ruff rules passed.
- Remote r3 image `sha256:9d41474feca3938d4a98f8bd4f81cd801496ce825670f7f41449500ea4f996d7`
  is active and the gateway health check passed. Only account 821 has the flag.
- Sol and Astra integrated SSE replies passed. Sol legacy compaction and
  continuation passed; the database recorded 45 input / 35 output tokens for
  compaction and 58 input / 5 output tokens for the continuation.
- Existing Luna traffic continued successfully on the native route.
- Both tested sidecar models still reported `shape_mismatch`, 11 blocks / 312
  characters, `usable=false`. No successful qualifying-state injection or
  model-quality improvement has been demonstrated.

Build hashes (SHA-256):

```text
SUB2API r3: a4ec02f6150a14702a0201a65b2b978e9a817d03bceb94cae53f04f9760bc4f4
sleep-state: 261de75e133bf5159b21c659acb335975ae67d104e1ef04006ea57726d5954de
```
