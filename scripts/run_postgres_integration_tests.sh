#!/usr/bin/env bash
set -Eeuo pipefail

# Disposable PostgreSQL integration runner.  The application POSTGRES_* settings
# are deliberately not exported: pytest receives only the scoped test DSN.
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${TEST_POSTGRES_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
RUN_ID="$(printf '%s' "$RUN_ID" | tr -c 'A-Za-z0-9_-' '_')"
PROJECT="aigcnews-pg-test-${RUN_ID,,}"
PROJECT="${PROJECT:0:50}"
# Compose project names may contain only a conservative portable subset.
PROJECT="$(printf '%s' "$PROJECT" | tr -c 'a-z0-9_-' '_' | sed 's/_*$//')"
PORT="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
DB=""
USER=""
PASSWORD=""
COMPOSE=()
ADMIN_DATABASE=""
METADATA_FILE=""
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
cleanup() {
    if [[ -n "$ADMIN_DATABASE" ]]; then
        "$PYTHON_BIN" "$ROOT_DIR/scripts/provision_postgres_test_database.py" drop \
            --admin-dsn "$TEST_POSTGRES_ADMIN_DSN" --database "$ADMIN_DATABASE" --run-id "$RUN_ID" >/dev/null 2>&1 || \
            printf 'orphaned PostgreSQL test database: %s\n' "$ADMIN_DATABASE" >&2
    elif ((${#COMPOSE[@]})); then
        "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    fi
    if [[ -n "$METADATA_FILE" ]]; then
        rm -f -- "$METADATA_FILE"
    fi
}
trap cleanup EXIT
cd "$ROOT_DIR"
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    printf 'Backend test environment is missing: %s\n' "$PYTHON_BIN" >&2
    exit 1
fi
if [[ -n "${TEST_POSTGRES_ADMIN_DSN:-}" ]]; then
    METADATA_FILE="$(mktemp)"
    "$PYTHON_BIN" "$ROOT_DIR/scripts/provision_postgres_test_database.py" provision \
        --admin-dsn "$TEST_POSTGRES_ADMIN_DSN" --run-id "$RUN_ID" --output "$METADATA_FILE"
    ADMIN_DATABASE="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["database"])' "$METADATA_FILE")"
    export TEST_POSTGRES_DSN="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["dsn"])' "$METADATA_FILE")"
else
    DB="aigcnews_test"
    USER="aigcnews_test"
    PASSWORD="aigcnews_test"
    export COMPOSE_PROJECT_NAME="$PROJECT"
    export POSTGRES_TEST_PORT="$PORT"
    COMPOSE=(docker compose -f "$ROOT_DIR/docker/docker-compose.postgres-test.yml")
    "${COMPOSE[@]}" up -d --wait
    ready=0
    for _ in $(seq 1 30); do
        if PGPASSWORD="$PASSWORD" psql "host=127.0.0.1 port=$PORT user=$USER dbname=$DB sslmode=disable" -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 1
    done
    if [[ "$ready" != 1 ]]; then
        printf 'PostgreSQL test service did not become ready on port %s\n' "$PORT" >&2
        exit 1
    fi
    PGPASSWORD="$PASSWORD" psql "host=127.0.0.1 port=$PORT user=$USER dbname=$DB sslmode=disable" -v ON_ERROR_STOP=1 \
        -v run_id="$RUN_ID" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public;
CREATE TABLE IF NOT EXISTS public.aigcnews_test_run_guard (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO public.aigcnews_test_run_guard (run_id) VALUES (:'run_id');
SQL
    export TEST_POSTGRES_DSN="host=127.0.0.1 port=$PORT user=$USER password=$PASSWORD dbname=$DB sslmode=disable"
fi
export TEST_POSTGRES_RUN_ID="$RUN_ID"
unset POSTGRES_INTEGRATION POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DATABASE POSTGRES_DB POSTGRES_SSLMODE
# Test-only MCP secret key: fixed, public, and valid only inside pytest.
export MCP_SERVER_ENCRYPTION_KEY="${MCP_SERVER_ENCRYPTION_KEY:-rRMcQkNlCLdB-aJue6WnZTeQ6n-HIhmbb2Qy04cW7KU=}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    printf 'Backend test environment is missing: %s\n' "$PYTHON_BIN" >&2
    exit 1
fi
"$PYTHON_BIN" -m pytest -q "$@"
