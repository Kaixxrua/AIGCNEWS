# AI operations delivery recovery (2026-09-20)

Delivery 71 for `ae5fecf011694de1b99e10d11a0826be98d7b340`
failed on integration candidate `9dd920d31498db441cd4288f2c5d30a33f3a7379`.
The receipt is stored under the local delivery state directory at
`integrations/1789896432615314197/ci.json`.

Backend tests, PostgreSQL integration, MCP Go, and Compose smoke passed.
The frontend runner reported `ValueError: unexpected monitor subgroups`
before readiness (`ready: false`, no executed steps); cleanup succeeded.
This receipt does not establish a frontend build failure or success.

A subsequent read-only `shared_runner_pool.sample` against the active
`aigcnews-ci-pool.service` passed owner, process membership, monitor subgroup,
CPU, memory, and swap checks. No active CI payloads remained; the configured
ceiling was 6 CPUs / 12 GiB, with no pressure or OOM evidence. The subgroup
mismatch was no longer present. The original receipt does not identify the
specific lifecycle transition that caused it.

Recovery merges current local `origin/main` into the existing owned session
and submits a new commit through normal delivery. Pool checks and trusted
executor configuration remain unchanged. The new candidate still requires
all five CI checks; the failed frontend check is not treated as passed.

Post-merge local validation: 54 backend tests passed across AI operations,
scheduler boundaries, migration contracts, and the incoming contact-quality
release tests; one database-dependent test skipped without `TEST_POSTGRES_DSN`.
Frontend type checking and 133 tests across the AI operations panel, monitor
navigation, controller, view model, and API passed. Frontend tests used the
existing catalog through `UI_LIBRARY_DATA_ROOT`.
