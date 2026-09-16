#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERIFY_SCRIPT="$SCRIPT_DIR/verify_postgres_application_restore.sh"

fail() {
    printf '%s\n' "PostgreSQL backup failed: $*" >&2
    exit 1
}

usage() {
    printf '%s\n' "Usage: $0 OUTPUT.dump"
    printf '%s\n' "Connection: PGHOST, PGPORT, PGUSER, PGDATABASE and PGPASSWORD/PGPASSFILE."
}

[ "$#" -eq 1 ] || { usage >&2; exit 2; }
[ -n "${PGDATABASE:-}" ] || fail "PGDATABASE must be set"
command -v pg_dump >/dev/null 2>&1 || fail "pg_dump is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

output=$1
case "$output" in
    *.dump) ;;
    *) fail "output must use the .dump suffix" ;;
esac
[ ! -e "$output" ] || fail "refusing to overwrite existing output: $output"
[ ! -e "${output}.sha256" ] || fail "refusing to overwrite existing evidence: ${output}.sha256"
[ -d "$(dirname -- "$output")" ] || fail "output directory does not exist"

"$VERIFY_SCRIPT"

umask 077
temporary="${output}.partial.$$"
trap 'rm -f -- "$temporary"' EXIT HUP INT TERM

pg_dump --format=custom --compress=9 --no-owner --no-acl --file="$temporary"
mv -- "$temporary" "$output"
sha256sum -- "$output" >"${output}.sha256"
trap - EXIT HUP INT TERM

printf 'PostgreSQL custom-format backup created: %s\n' "$output"
printf 'SHA-256 evidence: %s\n' "${output}.sha256"
