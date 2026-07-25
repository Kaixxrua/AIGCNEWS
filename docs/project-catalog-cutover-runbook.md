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
