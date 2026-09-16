#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERIFY_SCRIPT="$SCRIPT_DIR/verify_postgres_application_restore.sh"

fail() {
    printf '%s\n' "PostgreSQL restore failed: $*" >&2
    exit 1
}

usage() {
    printf '%s\n' "Usage: $0 BACKUP.dump"
    printf '%s\n' "Requires CONFIRM_EMPTY_DATABASE to equal PGDATABASE exactly."
    printf '%s\n' "Connection: PGHOST, PGPORT, PGUSER, PGDATABASE and PGPASSWORD/PGPASSFILE."
}

[ "$#" -eq 1 ] || { usage >&2; exit 2; }
backup=$1
[ -f "$backup" ] || fail "backup file does not exist"
[ -f "${backup}.sha256" ] || fail "SHA-256 evidence file is missing: ${backup}.sha256"
[ -n "${PGDATABASE:-}" ] || fail "PGDATABASE must be set"
[ "${CONFIRM_EMPTY_DATABASE:-}" = "$PGDATABASE" ] ||
    fail "set CONFIRM_EMPTY_DATABASE to the exact target database name"
command -v psql >/dev/null 2>&1 || fail "psql is required"
command -v pg_restore >/dev/null 2>&1 || fail "pg_restore is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

(
    cd -- "$(dirname -- "$backup")"
    sha256sum -c -s -- "$(basename -- "${backup}.sha256")"
) || fail "backup SHA-256 verification failed"

current_database=$(psql -X --no-psqlrc --set=ON_ERROR_STOP=1 --tuples-only --no-align \
    --command="SELECT current_database()")
[ "$current_database" = "$PGDATABASE" ] || fail "connected target does not match PGDATABASE"

nonempty=$(psql -X --no-psqlrc --set=ON_ERROR_STOP=1 --tuples-only --no-align --command="
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname !~ '^pg_toast'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname !~ '^pg_toast'
    ) THEN 1 ELSE 0 END
")
[ "$nonempty" = "0" ] || fail "target database is not empty; nothing was restored"

pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname="$PGDATABASE" "$backup"
"$VERIFY_SCRIPT"

printf 'PostgreSQL restore completed and verified: database=%s backup=%s\n' \
    "$PGDATABASE" "$backup"
