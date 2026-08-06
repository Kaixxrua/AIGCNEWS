#!/bin/sh
# AIGCNEWS PostgreSQL 定时备份包装：时间戳命名 + 保留策略。
# 凭据不内嵌——经 BACKUP_ENV_FILE（默认 /etc/aigcnews/postgres-backup.env，
# 建议 chmod 600）注入 PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSWORD/PGPASSFILE，
# 实际备份与恢复验收由 backup_postgres_application.sh 完成。
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKUP_SCRIPT=${AIGCNEWS_BACKUP_SCRIPT:-"$SCRIPT_DIR/backup_postgres_application.sh"}
ENV_FILE=${BACKUP_ENV_FILE:-/etc/aigcnews/postgres-backup.env}
BACKUP_DIR=${AIGCNEWS_BACKUP_DIR:-/var/backups/aigcnews}
RETENTION=${AIGCNEWS_BACKUP_RETENTION:-14}

fail() {
    printf '%s\n' "scheduled backup failed: $*" >&2
    exit 1
}

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

[ -x "$BACKUP_SCRIPT" ] || fail "backup script not executable: $BACKUP_SCRIPT"
[ -d "$BACKUP_DIR" ] || fail "backup directory does not exist: $BACKUP_DIR"
case "$RETENTION" in
    ''|*[!0-9]*) fail "AIGCNEWS_BACKUP_RETENTION must be a positive integer" ;;
esac
[ "$RETENTION" -ge 1 ] || fail "AIGCNEWS_BACKUP_RETENTION must be >= 1"

stamp=$(date +%Y%m%d-%H%M%S)
output="$BACKUP_DIR/aigcnews-$stamp.dump"

"$BACKUP_SCRIPT" "$output"

# 保留策略：只处理本包装生成的命名模式（aigcnews-YYYYMMDD-HHMMSS.dump），
# 文件名有序即时间有序，逆序枚举并删除第 N 份之后的 dump 与其 sha256 证据。
count=0
for dump in $(ls -1r "$BACKUP_DIR"/aigcnews-????????-??????.dump 2>/dev/null); do
    count=$((count + 1))
    if [ "$count" -gt "$RETENTION" ]; then
        rm -f -- "$dump" "$dump.sha256"
        printf 'pruned old backup: %s\n' "$dump"
    fi
done

printf 'scheduled backup complete: %s (retention %s)\n' "$output" "$RETENTION"
