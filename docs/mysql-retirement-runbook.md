# MySQL 最终退役运行手册

> 状态：最终操作基线（2026-07-29）
>
> 当前应用关系型运行时为 PostgreSQL 16；主 `docker/docker-compose.yml` 不包含 MySQL。本文只授权在既定变更窗口内停用并精确移除旧 MySQL 容器，不授权删除数据卷。当前架构见 [`architecture.md`](architecture.md)。

## 1. 适用边界与证据

- 操作者必须记录变更单、执行人、主 Compose 文件路径、镜像摘要、容器名、卷名、备份位置和回滚负责人；不得记录数据内容、密码、DSN、Token 或其他密钥。
- 2026-07-29 本地证据可引用其**类型**：两轮稳定核对报告、表计数/主键或业务键摘要、备份文件校验和、PostgreSQL 恢复演练记录、Compose 配置与服务清单、REST/MCP/SSE 冒烟结果、容器与卷清单。不得把真实数据或密钥复制到文档或日志。
- 本手册不改变 Milvus、Neo4j、Redis、MinIO 或本地 PDF 数据的归属。
- 视觉问答消息持久化尚未实现；不得把临时视觉消息当作已迁移、已恢复或已持久化的数据。

## 2. 绝对禁止项

在没有“最终卷删除”单独书面授权时，明确禁止：

```text
docker compose down --volumes
docker volume rm ...
docker volume prune
```

也禁止任何等效的 `-v`、批量清理或自动 prune 操作。旧 MySQL 数据卷必须在观察期和回滚窗口内保留，且不得挂载给普通应用运行时。

## 3. 退役前门禁

1. 冻结会写入旧 MySQL 的任务、迁移进程和人工操作，记录冻结起止时间。
2. 在同一冻结边界内完成第一次全量核对：覆盖表集合、行数、主键/业务键集合、关键字段与序列/自增边界；结果必须稳定且无未解释差异。
3. 间隔一个已批准的稳定观察窗口后，在没有 MySQL 写入的前提下重复同一核对。第二次结果必须与第一次一致，形成“两次稳定核对”。
4. 对旧 MySQL 执行一致性备份；备份文件写入受控位置并生成强校验和（如 SHA-256）。由第二位操作者验证文件可读、校验和一致、权限最小化。
5. 使用该迁移基线或批准的 PostgreSQL 备份，在隔离环境完成 PostgreSQL 恢复演练：恢复 schema 与数据，修复/验证 sequence，运行一致性核对及固定 REST/MCP/SSE 冒烟。记录版本、耗时、校验结论和失败处置，不记录业务数据或凭据。
6. 验证主 `docker/docker-compose.yml` 的解析结果只包含 PostgreSQL 16 关系数据库服务，不包含 MySQL；确认 backend 的 composition root 打开 PostgreSQL，并组装 repository Protocol 的 PostgreSQL 实现。
7. 记录旧 MySQL 的**精确容器名/ID**和**精确卷名**。若名称存在歧义、容器仍有写入、备份/恢复演练失败或两轮核对不稳定，立即停止。

## 4. PostgreSQL-only 部署与验证

1. 使用已审核的主 Compose 配置部署或重建应用；不得附加 MySQL migration/rehearsal Compose 文件，不得执行 `down --volumes`。
2. 等待 PostgreSQL、backend 及依赖健康；确认应用报告的关系数据库 backend 为 PostgreSQL。
3. 执行固定冒烟：
   - REST：健康/就绪、认证只读检查、Dashboard/论文/项目查询，以及一个经授权的可回滚写入路径；
   - MCP：`initialize`、`tools/list`、代表性只读 `tools/call`，核对 JSON-RPC envelope 与公开字段；
   - SSE：聊天或简报的事件顺序、分隔、`[DONE]` 和断开行为，避免在验证中写入敏感内容。
4. 核对日志、连接与网络流量，证明应用没有访问 MySQL；发现 MySQL 连接尝试即失败并回滚。

## 5. 精确移除旧容器并保留卷

只有第 3、4 节全部通过后，才可停止并移除第 3.7 步记录的那个旧 MySQL 容器：

```bash
docker stop <exact-old-mysql-container-name-or-id>
docker rm <exact-old-mysql-container-name-or-id>
```

- 命令中的值必须由变更记录人工复核；不得使用通配符、模糊 grep 结果、Compose 项目级 `down` 或批量删除。
- 移除后再次列出容器和网络，确认目标容器消失且 PostgreSQL-only 应用健康。
- 旧 MySQL 卷保持原样，不删除、不重命名、不复用；记录其精确名称、保留期限、所有者和访问控制。

## 6. 凭据撤销

容器移除且 PostgreSQL-only 冒烟通过后：

1. 撤销旧 MySQL 应用账号、迁移账号和不再需要的网络访问；轮换可能与其他环境复用的凭据。
2. 从运行环境/secret store 删除旧 MySQL endpoint 与凭据引用，但保留经批准、可审计的离线恢复材料。
3. 验证主应用仅持有 PostgreSQL 所需权限；不得在终端历史、命令参数或证据中暴露密钥。

若回滚窗口要求临时保留恢复凭据，应封存为 break-glass 凭据并设定到期时间，而不是继续注入应用。

## 7. 观察期

在批准的观察期持续检查：

- `/api/live`、`/api/ready`、PostgreSQL 连接池、事务错误、锁等待、延迟与容量；
- REST/MCP/SSE 错误率、字段/排序/分页、JSON-RPC 与 SSE wire format；
- 调度、采集、认证、会话、简报、项目目录和语义水合；
- 是否出现 MySQL DNS、端口、驱动、容器或凭据访问尝试。

每个观察点只记录时间、版本、指标/检查类型和结论，不记录数据或密钥。

## 8. 回滚

触发条件包括：未解释的数据差异、PostgreSQL 恢复或 sequence 问题、关键写入失败、REST/MCP/SSE 契约变化、持续错误/延迟超阈值，或发现隐藏的 MySQL 运行时依赖。

1. 停止产生新写入并保全 PostgreSQL 日志与故障证据。
2. 优先回滚到最近已验证的 PostgreSQL 版本/备份，并重新执行固定冒烟。
3. 只有在 PostgreSQL 回滚不可行且变更单明确授权 MySQL 灾难恢复时，才可从已校验备份或保留卷恢复隔离 MySQL；重新启用旧应用凭据和应用流量需要额外授权。
4. 若 PostgreSQL 已产生新写入，不得直接把流量切回旧 MySQL；必须先制定并批准数据对账/回放方案，避免覆盖或分叉。
5. 回滚期间仍不得删除任何数据库卷。

## 9. 最终卷删除（独立授权）

观察期结束不等于授权删除。只有在备份保留策略满足、恢复演练有效、业务/数据负责人签字且获得针对**精确卷名**的单独最终授权后，才可制定一次性删除命令。执行前再次核对卷未被任何容器挂载，并由双人复核。

没有该授权时，结论必须是“容器已退役，卷继续保留”。禁止 `docker compose down --volumes`、`docker volume prune`，也不得以维护、节省空间或自动清理为由执行 `docker volume rm`。
