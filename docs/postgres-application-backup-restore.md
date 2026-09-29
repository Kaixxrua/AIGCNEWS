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

脚本先验证（默认模式，与仓库 migration 版本解耦）：

- `app_schema_migrations` 账本从版本 1 开始且连续无缺口（**不与仓库最新 migration 比对**——仓库有尚未应用的新迁移时夜间备份照常进行，即"迁移前必能备份"）；
- 基本应用表 `github_repo_candidates`、`github_repo_enrichments`、`users`、`documents`、`conversations`、`chat_messages` 存在且可查询。

恢复后校验同样使用默认模式：以 dump 内的 `app_schema_migrations` 账本为准，恢复旧备份（账本落后于仓库最新迁移）不会被误判失败。

如需恢复旧的严格口径（账本必须恰好覆盖到仓库最新 migration 且文件名一致），显式传 `--strict` 或 `POSTGRES_VERIFY_STRICT=1` 调用 `scripts/verify_postgres_application_restore.sh`。

成功后生成 PostgreSQL custom-format dump 和同名 `.sha256` 证据。脚本拒绝覆盖已有 dump。

## 定时备份（systemd timer）

`scripts/backup_postgres_application_scheduled.sh` 为上面的备份脚本加上定时运行所需的四件事：时间戳命名（`aigcnews-YYYYMMDD-HHMMSS.dump`）、保留策略（默认保留最新 14 份，`AIGCNEWS_BACKUP_RETENTION` 可调）、凭据环境文件注入（`BACKUP_ENV_FILE`）、失败邮件告警（见下文"语义与限制"）。配套单元：`deploy/systemd/aigcnews-postgres-backup@.service` + `.timer`（每日 03:17，随机延迟 15 分钟，错过补跑）。

1. 准备凭据环境文件（`chmod 600`，不要提交到任何仓库）：

   ```bash
   # ~/.aigcnews-postgres-backup.env
   PGHOST=127.0.0.1
   PGPORT=5432
   PGUSER=backup_operator
   PGDATABASE=aigcnews
   PGPASSFILE=$HOME/.pgpass
   ```

   主 Compose（`docker/docker-compose.yml`）已为 `project-catalog-postgres` 内联 `127.0.0.1:5432:5432` 回环映射（带注释说明仅限备份用途），无需再加 override 文件；按上例 env 文件直接连接即可。不要为备份把数据库暴露到公网。

2. 安装并启用（以部署用户为例（记为 `<deploy-user>`））：

   ```bash
   sudo cp deploy/systemd/aigcnews-postgres-backup@.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now aigcnews-postgres-backup@<deploy-user>.timer
   systemctl list-timers aigcnews-postgres-backup@<deploy-user>.timer
   ```

3. 首次启用后手动触发一次并核对制品：`sudo systemctl start aigcnews-postgres-backup@<deploy-user>.service`，dump 与 `.sha256` 默认落在 `~/backups/aigcnews/`（service 的 `AIGCNEWS_BACKUP_DIR` 可改）。

语义与限制：

- 每日一次 = **RPO 不超过 24 小时**；需要更小 RPO 时必须上 WAL 归档/PITR，本流程不覆盖。
- 单机磁盘上的 dump 不抗主机/磁盘故障，应再有一层异地副本（rsync/rclone 到另一台机器或对象存储），异地层同样按敏感制品处理。
- timer 失败会体现在 `systemctl status aigcnews-postgres-backup@*.service`。失败告警已由包装脚本内置：备份任一步骤失败时尽力调用 `scripts/notify_ops_alert.py` 发送邮件（SMTP 配置读项目 `.env` 的 `SMTP_*`，收件人默认 `SMTP_FROM_EMAIL`，可用 `AIGCNEWS_OPS_ALERT_TO` 改投；`AIGCNEWS_OPS_ALERT_DISABLED=1` 关闭；告警自身失败不遮蔽备份退出码）。

## PostgreSQL 之外的数据

PG dump 之外，其余有状态数据按"是否可从 PG + 公开来源重建"分两类处置：

| 数据 | 位置 | 体量 | 处置 |
| --- | --- | --- | --- |
| MCP 工具调用计数 | `storage/metrics` | <1MB | **每周快照**（见下） |
| 聊天上传附件（用户 PDF） | `storage/papers/_chat_uploads` | 随用户增长 | **每周快照** |
| arXiv 论文 PDF | `storage/papers` | ~3.5G | 不快照；按 PG `documents` 表中的 arXiv id 重新下载 |
| Milvus 向量（项目/论文索引） | `docker/volumes/{milvus,minio,etcd}` | ~3.4G | 不快照；由 PG 文档经 `scripts/backfill_github_project_semantic_index.py` 等回填脚本重建 |
| Neo4j 论文图谱 | `data/neo4j` | ~0.5G | 不快照；由 PG 文档经 `graph_extractor` 图谱抽取重建 |
| Redis（限流/缓存/访客统计） | docker volume `redis_data` | 小 | 不快照；缓存性质，丢失影响可忽略 |
| X 媒体磁盘缓存 | `storage/x_media` | 小 | 不快照；本就按 LRU 驱逐的易失设计 |

每周快照由 `scripts/backup_stateful_data_scheduled.sh` 完成：tar.gz + `.sha256` 证据，默认源为 `storage/metrics`、`storage/papers/_chat_uploads`（`AIGCNEWS_STATEFUL_SOURCES` 可调），保留最新 8 份（`AIGCNEWS_STATEFUL_RETENTION`），失败告警与 PG 备份共用 `notify_ops_alert.py`。配套单元 `deploy/systemd/aigcnews-stateful-backup@.{service,timer}`（每周日 04:07，随机延迟 15 分钟，错过补跑）：

```bash
sudo cp deploy/systemd/aigcnews-stateful-backup@.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aigcnews-stateful-backup@<deploy-user>.timer
sudo systemctl start aigcnews-stateful-backup@<deploy-user>.service   # 首次手动触发并核对制品
```

恢复快照：停止相关容器后，在仓库根执行 `tar -xzf aigcnews-stateful-<stamp>.tar.gz -C <仓库根>` 解回原路径，再启动容器。

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
6. restore 后重新执行 migration ledger 连续性、必需表和基本查询 smoke（以 dump 内账本为准，不与仓库最新 migration 比对）。

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
