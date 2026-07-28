#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MIGRATIONS_DIR=${POSTGRES_MIGRATIONS_DIR:-"$PROJECT_ROOT/backend/migrations/postgres"}

fail() {
    printf '%s\n' "PostgreSQL restore verification failed: $*" >&2
    exit 1
}

command -v psql >/dev/null 2>&1 || fail "psql is required"
[ -d "$MIGRATIONS_DIR" ] || fail "migration directory is unavailable"

latest_file=$(
    find "$MIGRATIONS_DIR" -maxdepth 1 -type f -name '[0-9][0-9][0-9][0-9]_*.sql' -print |
        LC_ALL=C sort |
        tail -n 1
)
[ -n "$latest_file" ] || fail "no PostgreSQL migrations were found"
latest_name=$(basename -- "$latest_file")
latest_version=$(printf '%s' "$latest_name" | cut -c1-4 | sed 's/^0*//')
[ -n "$latest_version" ] || latest_version=0

psql_value() {
    psql -X --no-psqlrc --set=ON_ERROR_STOP=1 --tuples-only --no-align --command "$1"
}

ledger_exists=$(psql_value "SELECT CASE WHEN to_regclass('public.app_schema_migrations') IS NULL THEN 0 ELSE 1 END")
[ "$ledger_exists" = "1" ] || fail "app_schema_migrations is missing"

ledger_state=$(psql_value "
    SELECT COALESCE(MIN(version), 0) || '|' || COALESCE(MAX(version), 0) || '|' || COUNT(*)
    FROM public.app_schema_migrations
")
expected_state="1|$latest_version|$latest_version"
[ "$ledger_state" = "$expected_state" ] ||
    fail "migration ledger does not span exactly versions 1 through $latest_version"
ledger_contiguous=$(psql_value "
    SELECT CASE WHEN COUNT(*) = $latest_version THEN 1 ELSE 0 END
    FROM generate_series(1, $latest_version) AS expected(version)
    JOIN public.app_schema_migrations actual USING (version)
")
[ "$ledger_contiguous" = "1" ] || fail "migration ledger contains a version gap"

restored_latest_name=$(psql_value "
    SELECT filename FROM public.app_schema_migrations WHERE version = $latest_version
")
[ "$restored_latest_name" = "$latest_name" ] ||
    fail "latest migration does not match $latest_name"

required_tables="github_repo_candidates github_repo_enrichments users documents conversations chat_messages"
for table in $required_tables; do
    present=$(psql_value "SELECT CASE WHEN to_regclass('public.$table') IS NULL THEN 0 ELSE 1 END")
    [ "$present" = "1" ] || fail "required table public.$table is missing"
done

psql -X --no-psqlrc --set=ON_ERROR_STOP=1 --quiet <<'SQL'
SELECT 1 FROM public.github_repo_candidates LIMIT 1;
SELECT 1 FROM public.documents LIMIT 1;
SELECT 1 FROM public.users LIMIT 1;
SELECT 1 FROM public.conversations LIMIT 1;
SQL

printf 'PostgreSQL restore verification passed: migration=%04d required_tables=%s\n' \
    "$latest_version" "$(printf '%s' "$required_tables" | tr ' ' ',')"
