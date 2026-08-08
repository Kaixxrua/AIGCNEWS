#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MIGRATIONS_DIR=${POSTGRES_MIGRATIONS_DIR:-"$PROJECT_ROOT/backend/migrations/postgres"}

fail() {
    printf '%s\n' "PostgreSQL restore verification failed: $*" >&2
    exit 1
}

usage() {
    printf '%s\n' "Usage: $0 [--strict]" >&2
    printf '%s\n' "Default mode: ledger contiguity + required tables (pre-backup / post-restore)." >&2
    printf '%s\n' "--strict (or POSTGRES_VERIFY_STRICT=1): additionally require the ledger to match the newest repo migration." >&2
}

STRICT=${POSTGRES_VERIFY_STRICT:-0}
case "${1:-}" in
    "") ;;
    --strict) STRICT=1 ;;
    *) usage; exit 2 ;;
esac

command -v psql >/dev/null 2>&1 || fail "psql is required"

latest_version=""
latest_name=""
if [ "$STRICT" = "1" ]; then
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
fi

psql_value() {
    psql -X --no-psqlrc --set=ON_ERROR_STOP=1 --tuples-only --no-align --command "$1"
}

ledger_exists=$(psql_value "SELECT CASE WHEN to_regclass('public.app_schema_migrations') IS NULL THEN 0 ELSE 1 END")
[ "$ledger_exists" = "1" ] || fail "app_schema_migrations is missing"

# 两种模式共享的基线：账本从版本 1 开始且连续（MIN=1 且 COUNT=MAX）。
# 备份前模式不与仓库最新 migration 比对——有新迁移未应用也必须能备份；
# 恢复后校验以 dump 内账本为准，同样不与仓库版本比对。
ledger_state=$(psql_value "
    SELECT COALESCE(MIN(version), 0) || '|' || COALESCE(MAX(version), 0) || '|' || COUNT(*)
    FROM public.app_schema_migrations
")
ledger_min=$(printf '%s' "$ledger_state" | cut -d'|' -f1)
ledger_max=$(printf '%s' "$ledger_state" | cut -d'|' -f2)
ledger_count=$(printf '%s' "$ledger_state" | cut -d'|' -f3)
[ "$ledger_min" = "1" ] ||
    fail "migration ledger does not start at version 1 (state: $ledger_state)"
[ "$ledger_count" = "$ledger_max" ] ||
    fail "migration ledger is not contiguous (state: $ledger_state)"
ledger_contiguous=$(psql_value "
    SELECT CASE WHEN COUNT(*) = $ledger_max THEN 1 ELSE 0 END
    FROM generate_series(1, $ledger_max) AS expected(version)
    JOIN public.app_schema_migrations actual USING (version)
")
[ "$ledger_contiguous" = "1" ] || fail "migration ledger contains a version gap"

if [ "$STRICT" = "1" ]; then
    expected_state="1|$latest_version|$latest_version"
    [ "$ledger_state" = "$expected_state" ] ||
        fail "migration ledger does not span exactly versions 1 through $latest_version"
    restored_latest_name=$(psql_value "
        SELECT filename FROM public.app_schema_migrations WHERE version = $latest_version
    ")
    [ "$restored_latest_name" = "$latest_name" ] ||
        fail "latest migration does not match $latest_name"
fi

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

if [ "$STRICT" = "1" ]; then
    printf 'PostgreSQL restore verification passed (strict): migration=%04d required_tables=%s\n' \
        "$latest_version" "$(printf '%s' "$required_tables" | tr ' ' ',')"
else
    printf 'PostgreSQL restore verification passed: ledger_max=%04d required_tables=%s\n' \
        "$ledger_max" "$(printf '%s' "$required_tables" | tr ' ' ',')"
fi
