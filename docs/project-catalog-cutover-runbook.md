# Project catalog PostgreSQL public-read cutover

This runbook switches only the frozen public project-catalog read protocol. MySQL remains authoritative for every catalog write, personal/private reads, legacy `GET /github/projects`, authentication, and other application data. PostgreSQL remains an asynchronous public-read replica. Milvus is not part of this procedure.

Implementing or merging Phase 5 does not authorize a production database operation, environment edit, restart, cutover, rollback, commit, or push.

## Required configuration

Preparation and PostgreSQL-active operation require:

```dotenv
PROJECT_CATALOG_OUTBOX_CAPTURE_ENABLED=true
PROJECT_CATALOG_SYNC_WORKER_ENABLED=true
```

PostgreSQL public-read mode additionally requires:

```dotenv
PROJECT_CATALOG_BACKEND=postgres
PROJECT_CATALOG_SHADOW_ENABLED=false
```

There is no `DUAL_WRITE` setting and no runtime fail-open to MySQL. If PostgreSQL-active reads fail, readiness fails and the operator decides whether to roll back.

## Source timestamp contract

Project-catalog MySQL `DATETIME` values are UTC wall-clock values. Every application MySQL session sets `time_zone = '+00:00'`; transfer and incremental sync interpret PyMySQL's naive datetimes as UTC, PostgreSQL stores the resulting instant as `TIMESTAMPTZ`, consistency evidence hashes UTC instants, and public APIs emit UTC ISO-8601 strings with `Z`.

Before migrating an existing source, verify how its historical `DATETIME` values were written. If they are already UTC, use `--source-timezone UTC` throughout. If historical values were written as another local wall time, treat `--source-timezone` only as a legacy-import interpretation during a controlled freeze, normalize the authoritative MySQL values to UTC under a separately reviewed migration, and then use UTC for runtime sync and all later verification. Never mix source-timezone interpretations between full transfer, incremental replay, and consistency checks.

## Isolated deployment rehearsal

Use the rehearsal topology before requesting production deployment authorization. It creates a self-contained internal network with dedicated MySQL, PostgreSQL, Redis, etcd, MinIO, Milvus, and an immutable backend release. It publishes no ports, declares no external network, and cannot address containers in the running application project by service name. MySQL and PostgreSQL use rehearsal-only persistent volumes; Redis and the Milvus dependency data use tmpfs.

Required operator-supplied values (prefer a mode `0600` file outside the repository):

```bash
export REHEARSAL_BACKEND_IMAGE='registry.example/aigcnews-backend@sha256:<64-hex-digest>'
export REHEARSAL_ENV_FILE='/absolute/path/to/rehearsal.env'
export REHEARSAL_MYSQL_ROOT_PASSWORD='<secret>'
export REHEARSAL_MYSQL_DATABASE='aigcnews_rehearsal'
export REHEARSAL_MYSQL_USER='aigcnews_rehearsal'
export REHEARSAL_MYSQL_PASSWORD='<secret>'
export REHEARSAL_POSTGRES_DATABASE='aigcnews_rehearsal'
export REHEARSAL_POSTGRES_USER='aigcnews_rehearsal'
export REHEARSAL_POSTGRES_PASSWORD='<secret>'
export REHEARSAL_MINIO_ROOT_USER='aigcnews-rehearsal'
export REHEARSAL_MINIO_ROOT_PASSWORD='<secret>'
```

The env file supplies non-database application secrets only; do not commit it and do not place production database endpoints or credentials in it. Compose explicitly overrides database and dependency hosts with isolated service names. The backend image must include an `@sha256:` digest and all pinned images must already exist locally: the orchestrator uses `--no-build --pull never` to prevent source, tag, or registry drift.

The safe initial mode is MySQL reads with capture enabled, sync disabled, catalog shadow disabled, and the legacy search strategy. This prevents an empty PostgreSQL target from receiving incremental events before its full load:

```bash
export REHEARSAL_CATALOG_BACKEND=mysql
export REHEARSAL_CATALOG_CAPTURE=true
export REHEARSAL_CATALOG_SYNC=false
export REHEARSAL_CATALOG_SHADOW=false
export REHEARSAL_SEARCH_STRATEGY=legacy
```

After the full load and sequence repair, set sync to `true` and use `recreate` to restart only the backend. Catalog shadow additionally requires MySQL reads and sync enabled. PostgreSQL-active mode requires capture and sync enabled and catalog shadow disabled. The orchestrator rejects unsafe matrices. `REHEARSAL_SEARCH_STRATEGY` accepts `legacy`, `shadow`, or `v2` independently of the catalog storage shadow flag.

Static validation is non-mutating and does not print the rendered configuration or secrets:

```bash
scripts/rehearse_project_catalog_cutover.sh config
```

Starting or stopping requires a deliberate confirmation. `up` starts only this fixed Compose project and waits for every dependency healthcheck plus backend `/api/ready`:

```bash
export REHEARSAL_CONFIRM=REHEARSE_PROJECT_CATALOG_CUTOVER
scripts/rehearse_project_catalog_cutover.sh up
scripts/rehearse_project_catalog_cutover.sh status
# Change only the validated REHEARSAL_CATALOG_* mode values, then:
scripts/rehearse_project_catalog_cutover.sh recreate
scripts/rehearse_project_catalog_cutover.sh logs
scripts/rehearse_project_catalog_cutover.sh down
```

Seed the dedicated rehearsal MySQL from an approved sanitized snapshot, then run migrations, transfer, barrier proof, consistency checks, and the fixed REST/MCP/SSE smoke suite from the immutable rehearsal backend or a separately authorized operator process. Record the exact image digest and target databases in evidence. `down` preserves the named MySQL and PostgreSQL volumes; Redis, etcd, MinIO, and Milvus data are intentionally ephemeral. Deleting persistent volumes with `docker compose down --volumes` is not automated and requires separate authorization. Never point any rehearsal value at production, and never use the rehearsal backend as a public endpoint.

## Before requesting deployment authorization

1. Stop or freeze catalog schema-changing jobs. Establish a documented quiet proof window; `MAX(outbox.id)` cannot account for an earlier auto-increment ID that has not committed yet.
2. Capture a barrier with `scripts/sync_project_catalog.py capture-barrier`.
3. Drain only through that fixed barrier with the production authorization controls:

   ```text
   sync_project_catalog.py drain-to-barrier --barrier-id B --timeout-seconds N --apply --authorize-production
   ```

4. Run `prove-barrier`. Readiness requires every actual source event through `B` to be processed and metadata-identical in the PostgreSQL applied-event ledger; a high-water value alone is not proof.
5. Run the full consistency and sequence checks. Produce a fresh, release-bound evidence artifact with `project_catalog_preflight.py`. Evidence expires after 30 minutes by default.
6. Run the fixed REST/MCP/SSE contract suite against a disposable or staging MySQL-active process and a fresh PostgreSQL-active process. Record normalized output and fallback provenance.
7. Verify rollback by starting a fresh MySQL-active process with the same release. Keep capture and sync enabled.
8. Review failed gates, target identity, revision, expiry, and barrier. Then obtain separate production deployment authorization.

## Authorized production cutover

The deployment operator—not the application or preflight CLI—changes the external environment. Never store database credentials in command arguments or evidence.

1. Set backend to PostgreSQL while leaving capture and sync enabled and shadow disabled.
2. Recreate the backend service. The current compose topology has one fixed backend container, so this is a controlled recreate, not a rolling restart.
3. Require `/api/live`, `/api/ready`, and admin `/api/ops/project-catalog/readiness` to be healthy. The current compose file has no backend healthcheck; deployment wiring is external and must use `/api/ready` explicitly.
4. Run the same fixed REST/MCP/SSE smoke cases. Preserve fields, ordering, pagination, semantic `repo_id` hydration, JSON-RPC envelopes, SSE event shape, and fallback provenance.
5. Capture and prove a new post-restart barrier. Observe PostgreSQL errors, latency, pool pressure, outbox lag, and dead events.

## Rollback triggers

Rollback on any unexplained data mismatch, dead event, lag beyond the approved SLO, schema/sequence failure, REST/MCP/SSE contract change, semantic hydration problem, fallback provenance change, PostgreSQL error/latency threshold breach, or pool exhaustion.

## Authorized rollback

1. Restore only `PROJECT_CATALOG_BACKEND=mysql` externally.
2. Keep outbox capture and sync enabled. Do not clear the outbox or PostgreSQL.
3. Recreate the backend service and require readiness.
4. Run the identical smoke cases and record rollback evidence.
5. Diagnose PostgreSQL off the public response path. Do not automatically attempt another cutover.

Stopping capture/sync, making PostgreSQL the write authority, or deleting MySQL requires a separate migration project and explicit authorization.
