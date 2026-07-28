# PostgreSQL 应用库备份与恢复验收

本文只适用于 PostgreSQL 应用数据库。流程不会读取 `.env`，也不操作 MySQL 服务、数据或 volume。凭据必须由调用者通过 `PGPASSWORD`、`PGPASSFILE` 或 PostgreSQL 客户端支持的 secret 注入方式提供；命令和脚本输出不会打印连接串或密码。

## 前提

- 使用与服务器主版本兼容的 `pg_dump`、`pg_restore` 和 `psql`（当前验收基线为 PostgreSQL 16）。
- 备份账号能读取应用库全部对象；恢复账号能在一个预先创建的空数据库中创建对象。
- 在维护窗口内避免 schema migration。需要事务一致性时，确认应用写入策略和业务恢复点要求后再执行。
- 备份文件及 `.sha256` 是敏感运维制品，应保存在受控、加密且有保留策略的存储中。

## 创建备份

显式导出连接环境变量，不要把密码放入命令参数或 runbook：

```bash
export PGHOST=db.internal PGPORT=5432 PGUSER=backup_operator PGDATABASE=aigcnews
export PGPASSFILE=/run/secrets/postgres-pgpass
./scripts/backup_postgres_application.sh /secure/backups/aigcnews-20260728.dump
```

脚本先验证：

- `app_schema_migrations` 从版本 1 连续到仓库中的最新 migration；
- ledger 最新文件名与仓库 migration 一致；
- 基本应用表 `github_repo_candidates`、`github_repo_enrichments`、`users`、`documents`、`conversations`、`chat_messages` 存在且可查询。

成功后生成 PostgreSQL custom-format dump 和同名 `.sha256` 证据。脚本拒绝覆盖已有 dump。

## 恢复到明确确认的空目标

先由管理员创建全新数据库并授予恢复账号权限。不要复用生产数据库，不要对现有数据库执行 restore。脚本不会 drop、clean 或删除任何对象；目标非空时会在 `pg_restore` 前失败。

```bash
export PGHOST=db.internal PGPORT=5432 PGUSER=restore_operator PGDATABASE=aigcnews_restore_20260728
export PGPASSFILE=/run/secrets/postgres-pgpass
export CONFIRM_EMPTY_DATABASE=aigcnews_restore_20260728
./scripts/restore_postgres_application.sh /secure/backups/aigcnews-20260728.dump
```

安全门槛：

1. `CONFIRM_EMPTY_DATABASE` 必须逐字等于 `PGDATABASE`；
2. 实际连接的 `current_database()` 必须等于 `PGDATABASE`；
3. SHA-256 evidence 必须存在并校验通过；
4. 非系统 schema 中不能已有 table、view、sequence、foreign table 或 function；
5. `pg_restore` 使用单事务、`--exit-on-error`、`--no-owner`、`--no-acl`；
6. restore 后重新执行 migration ledger、必需表和基本查询 smoke。

验收日志应保存脚本成功输出、dump 文件名、`.sha256` 文件内容、执行时间、源/目标数据库名和操作人。不要保存密码或完整 DSN。

## PostgreSQL 16 一次性验收

以下测试使用独立 Compose project、固定的本地测试凭据、tmpfs 数据目录和新的 `source_db`/`restore_db`。结束时只删除该测试 project 的临时 volume，不接触 MySQL：

```bash
./scripts/test_postgres_application_backup_restore.sh
```

测试会应用仓库所有 PostgreSQL migrations，写入 smoke 数据，执行 `pg_dump`，校验 SHA-256，恢复到新空库，再验证最新 schema 和数据行。主机端 `127.0.0.1:55433` 必须可用。

## 失败处理与限制

- 任一检查失败都视为恢复未验收；保留日志和制品，修复后从新的空数据库重试。
- 脚本不创建或删除数据库，也不负责停止应用写入、对象存储文件、Milvus、MySQL 或其他外部系统。
- custom-format dump 是逻辑备份，不替代 PostgreSQL PITR/WAL、基础备份和跨区域灾备。
- 恢复到不同 PostgreSQL 主版本、扩展集或角色模型前必须另行演练。
