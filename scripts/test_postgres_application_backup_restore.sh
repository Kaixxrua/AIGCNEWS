#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.postgres-backup-test.yml"
COMPOSE_PROJECT_NAME="aigcnews-pg-backup-test-$$"
export COMPOSE_PROJECT_NAME
export AIGCNEWS_PROJECT_ROOT="$PROJECT_ROOT"

fail() {
    printf '%s\n' "PostgreSQL backup acceptance test failed: $*" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
docker compose version >/dev/null 2>&1 || fail "docker compose is required"

workdir=$(mktemp -d)
export AIGCNEWS_BACKUP_ARTIFACTS="$workdir"
cleanup() {
    docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf -- "$workdir"
}
trap cleanup EXIT HUP INT TERM

docker compose -f "$COMPOSE_FILE" up -d --wait postgres-backup-test

docker compose -f "$COMPOSE_FILE" exec -T postgres-backup-test \
    createdb --username=aigcnews_test restore_db

pg_exec() {
    docker compose -f "$COMPOSE_FILE" exec -T postgres-backup-test "$@"
}

for migration in "$PROJECT_ROOT"/backend/migrations/postgres/*.sql; do
    pg_exec psql -X --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username=aigcnews_test --dbname=source_db <"$migration"
    filename=$(basename -- "$migration")
    version=$(printf '%s' "$filename" | cut -c1-4 | sed 's/^0*//')
    checksum=$(sha256sum -- "$migration" | cut -d' ' -f1)
    pg_exec psql -X --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username=aigcnews_test --dbname=source_db \
        --set=version="$version" --set=filename="$filename" --set=checksum="$checksum" <<'SQL'
CREATE TABLE IF NOT EXISTS app_schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    filename TEXT NOT NULL UNIQUE,
    checksum_sha256 CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO app_schema_migrations (version, filename, checksum_sha256)
VALUES (:'version', :'filename', :'checksum');
SQL
done

pg_exec psql -X --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username=aigcnews_test --dbname=source_db <<'SQL'
INSERT INTO github_repo_candidates (repo_id, full_name, stars)
VALUES ('acceptance/repository', 'acceptance/repository', 501);
INSERT INTO documents (id, title) VALUES ('acceptance-document', 'Backup restore acceptance');
SQL

pg_exec env PGUSER=aigcnews_test PGDATABASE=source_db PGPASSWORD=aigcnews_test \
    /workspace/scripts/backup_postgres_application.sh /artifacts/application.dump

pg_exec env PGUSER=aigcnews_test PGDATABASE=restore_db PGPASSWORD=aigcnews_test \
    CONFIRM_EMPTY_DATABASE=restore_db \
    /workspace/scripts/restore_postgres_application.sh /artifacts/application.dump

restored=$(pg_exec psql -X --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username=aigcnews_test --dbname=restore_db --tuples-only --no-align --command="
        SELECT full_name || '|' || stars
        FROM github_repo_candidates
        WHERE repo_id = 'acceptance/repository'
    ")
[ "$restored" = "acceptance/repository|501" ] || fail "restored application row differs"

printf 'PostgreSQL 16 dump/restore acceptance passed with SHA-256 evidence.\n'
