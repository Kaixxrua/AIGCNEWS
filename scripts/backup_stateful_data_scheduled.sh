#!/bin/sh
# AIGCNEWS 非 PG 小体量有状态数据周期快照：tar.gz + 时间戳命名 + 保留策略 + 失败告警。
#
# 只快照"不可重建或重建代价高"的小体量目录（默认 storage/wechat、
# storage/metrics、storage/papers/_chat_uploads）；可从 PG/公网重建的大体量
# 数据（arXiv PDF、Milvus/Neo4j 索引、媒体缓存）不在本脚本范围，重建矩阵见
# docs/postgres-application-backup-restore.md。
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BASE_DIR=${AIGCNEWS_STATEFUL_BASE:-$REPO_ROOT}
BACKUP_DIR=${AIGCNEWS_STATEFUL_BACKUP_DIR:-/var/backups/aigcnews-stateful}
RETENTION=${AIGCNEWS_STATEFUL_RETENTION:-8}
SOURCES=${AIGCNEWS_STATEFUL_SOURCES:-"storage/wechat storage/metrics storage/papers/_chat_uploads"}
ALERT_SCRIPT=${AIGCNEWS_OPS_ALERT_SCRIPT:-"$SCRIPT_DIR/notify_ops_alert.py"}
ALERT_UNIT=${AIGCNEWS_OPS_ALERT_UNIT:-aigcnews-stateful-backup}

# 失败告警：尽力调用告警脚本，告警自身失败不得遮蔽快照的真实退出码。
# 置 AIGCNEWS_OPS_ALERT_DISABLED=1 可整体关闭。
alert_failure() {
    [ "${AIGCNEWS_OPS_ALERT_DISABLED:-0}" != "1" ] || return 0
    [ -f "$ALERT_SCRIPT" ] || return 0
    python3 "$ALERT_SCRIPT" --failed-unit "$ALERT_UNIT" --detail "$*" || true
}

fail() {
    printf '%s\n' "stateful snapshot failed: $*" >&2
    alert_failure "$*"
    exit 1
}

command -v tar >/dev/null 2>&1 || fail "tar is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"
[ -d "$BACKUP_DIR" ] || fail "backup directory does not exist: $BACKUP_DIR"
[ -d "$BASE_DIR" ] || fail "base directory does not exist: $BASE_DIR"
case "$RETENTION" in
    ''|*[!0-9]*) fail "AIGCNEWS_STATEFUL_RETENTION must be a positive integer" ;;
esac
[ "$RETENTION" -ge 1 ] || fail "AIGCNEWS_STATEFUL_RETENTION must be >= 1"

# 只收集真实存在的源目录；缺失的打印警告后跳过（如 _chat_uploads 尚无内容）。
existing=""
for source in $SOURCES; do
    if [ -d "$BASE_DIR/$source" ]; then
        existing="$existing $source"
    else
        printf 'warning: snapshot source missing, skipped: %s\n' "$BASE_DIR/$source" >&2
    fi
done
[ -n "$existing" ] || fail "no snapshot sources present under $BASE_DIR"

stamp=$(date +%Y%m%d-%H%M%S)
output="$BACKUP_DIR/aigcnews-stateful-$stamp.tar.gz"
[ ! -e "$output" ] || fail "refusing to overwrite existing output: $output"

umask 077
temporary="${output}.partial.$$"
trap 'rm -f -- "$temporary"' EXIT HUP INT TERM

# existing 中的路径均为仓库内相对路径、不含空格，按词拆分是有意为之
if ! tar -czf "$temporary" -C "$BASE_DIR" $existing; then
    alert_failure "tar failed for sources:$existing"
    exit 1
fi
mv -- "$temporary" "$output"
sha256sum -- "$output" >"${output}.sha256"
trap - EXIT HUP INT TERM

# 保留策略：只处理本脚本命名模式，逆序枚举并删除第 N 份之后的快照与 sha256 证据。
count=0
for dump in $(ls -1r "$BACKUP_DIR"/aigcnews-stateful-????????-??????.tar.gz 2>/dev/null); do
    count=$((count + 1))
    if [ "$count" -gt "$RETENTION" ]; then
        rm -f -- "$dump" "$dump.sha256"
        printf 'pruned old snapshot: %s\n' "$dump"
    fi
done

printf 'stateful snapshot complete: %s (sources:%s, retention %s)\n' "$output" "$existing" "$RETENTION"
