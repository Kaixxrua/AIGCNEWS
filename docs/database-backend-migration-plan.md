# 数据库后端并行迁移与一键切换实施方案

> 状态：设计文档，默认不改变生产行为
>
> 目标：在保留现有 MySQL 逻辑的前提下，新增可独立验证的新数据库后端，经过 shadow 对比、双写和一致性校验后，通过配置完成切换，并保留快速回滚能力。
>
> 适用对象：负责数据库抽象、PostgreSQL/pgvector 实现、数据同步、shadow 校验和发布切换的 Agent。

---

## 1. 背景与目标

当前项目的业务数据库是 MySQL，Milvus 独立负责项目语义向量召回。项目搜索和 MCP 依赖 MySQL 完成：

- GitHub 项目元数据查询；
- stars、language、category、subcategory 等过滤；
- `all/today/recommended` scope；
- `stars/hot/updated/recent/name` 排序；
- count、分页和 `has_next`；
- 语义召回后的 `repo_id` 水合；
- 语义失败后的 GitHub API fallback；
- 语义索引状态和 README snapshot 状态。

本方案不是直接替换 MySQL，也不是把 MySQL 和 Milvus 一起迁移。目标是先建立一套不影响现有生产链路的新数据库逻辑：

```text
现有 MySQL ───────────────┐
                          ├── active catalog backend ── REST / MCP
新数据库（默认关闭）──────┘

Milvus：继续独立保存项目 embedding，暂不迁移
SiliconFlow：继续作为 embedding provider
```

最终期望通过配置切换：

```dotenv
PROJECT_CATALOG_BACKEND=mysql
# 验证完成后切换为：
# PROJECT_CATALOG_BACKEND=postgres
```

整个迁移必须满足：

1. 默认配置仍使用 MySQL；
2. 新代码未验证前不能影响 REST、MCP、SSE、SQL 和 GitHub fallback；
3. 新库故障时可以回退到 MySQL；
4. 不因数据库切换而重建 Milvus embedding；
5. 不在同一个提交中混入语义索引、MCP wire format 或无关业务重构；
6. 每个阶段都是独立、可测试、可回滚的 PR-sized 工作单元。

---

## 2. 非目标与约束

### 2.1 本次不做

- 不直接删除或大幅重写 `backend/app/repositories/mysql_repo.py`；
- 不迁移通用文档 RAG 的 Milvus collection；
- 不将项目向量立即迁移到 pgvector；
- 不修改 MCP JSON-RPC envelope、tool schema、`content.text` 或 `structuredContent`；
- 不改变 GitHub fallback 的触发条件和 provenance；
- 不在没有 shadow/一致性证据时正式切换；
- 不在运行中的 embedding backfill 期间重置或删除 `aigc_github_projects_v1`；
- 不提交、记录或打印任何数据库密码、API key 或 token。

### 2.2 必须遵守

- 遵守仓库 `CLAUDE.md` 的 Contract → Extract → Adapt → Switch → Delete 流程；
- 只修改本工作单元涉及的文件，不覆盖其他 Agent 的未提交变更；
- 数据库 schema migration、权限、事务和 MCP wire format 属于 Red 变更，必须额外测试；
- 提交标题遵循 `<type>(<scope>)!: <subject>` 项目格式，并包含 Claude trailer；
- 切换前必须有可执行的 rollback 命令和一致性报告；
- 当前 semantic index 的 canonical `repo_id` 必须在新旧数据库中保持完全一致。

---

## 3. 推荐目标架构

### 3.1 Catalog interface

新增项目目录接口，让业务层依赖契约而不是具体 MySQL 类：

```python
class ProjectCatalogRepository(Protocol):
    def list_projects(self, **kwargs) -> dict[str, Any]: ...
    def get_project(self, repo_id: str) -> dict[str, Any] | None: ...
    def upsert_project(self, project: dict[str, Any]) -> None: ...
    def get_semantic_status(self, **kwargs) -> dict[str, Any]: ...
```

实际方法签名应以现有调用点和测试为准，不要为了抽象而改变现有业务参数。至少必须覆盖：

- `list_projects(..., candidate_repo_ids=...)`；
- 项目 catalog 查询涉及的 enrichment、metrics、taxonomy 和 alias 行为；
- semantic source/status 相关方法；
- 当前写入路径使用的方法。

推荐文件结构：

```text
backend/app/repositories/project_catalog.py
backend/app/repositories/mysql_project_catalog.py
backend/app/repositories/postgres_project_catalog.py
backend/app/repositories/project_catalog_factory.py
```

现有 MySQL 行为先做 adapter：

```python
class MySQLProjectCatalogRepository:
    def __init__(self, repository: MySQLRepository | None = None):
        self.repository = repository or MySQLRepository()

    def list_projects(self, **kwargs):
        return self.repository.list_projects(**kwargs)
```

不要一开始复制所有 SQL。先让 adapter 证明新抽象不会改变旧行为。

### 3.2 Active backend

业务层只通过 factory 获取 active repository：

```python
repository = get_project_catalog_repository()
```

factory 读取集中配置：

```dotenv
PROJECT_CATALOG_BACKEND=mysql
PROJECT_CATALOG_SHADOW_BACKEND=
PROJECT_CATALOG_SHADOW_ENABLED=false
PROJECT_CATALOG_OUTBOX_CAPTURE_ENABLED=false
PROJECT_CATALOG_SYNC_WORKER_ENABLED=true
```

允许值：

```text
mysql
postgres
```

非法值必须 fail fast 或安全回退到 mysql，不能静默选择未验证实现。

### 3.3 Semantic search boundary

保持现有边界：

```text
query
  → Milvus search_repo_ids()
  → active catalog repository.list_projects(candidate_repo_ids=...)
  → active catalog 过滤/排序/分页
```

数据库切换不需要重新生成 embedding。只要 `repo_id` canonicalization 不变，现有 Milvus collection `aigc_github_projects_v1` 可以继续使用。

---

## 4. 分阶段实施路线

## Phase 0：冻结 Contract

先为现有 MySQL 行为建立 golden contract 测试和可重复 fixture。

### 必须固定的结果

每个查询场景至少比较：

- `items` 中的 canonical `repo_id` 或公开 `id`；
- 返回顺序；
- `total`；
- `page`、`page_size`、`has_next`；
- `min_stars`、scope、sort、language、taxonomy；
- `result_origin`、`fallback_used`、fallback reason；
- SQL miss + semantic hit；
- semantic empty/error/timeout；
- page 2；
- today/recommended；
- category/subcategory；
- generic search 不使用 semantic；
- MCP structured content 和公开字段集合。

建议增加：

```text
backend/tests/test_project_catalog_contract.py
backend/tests/fixtures/project_catalog_cases.json
```

测试不得依赖线上数据库。可以使用固定 repository fake，或在隔离测试数据库中建立最小 fixture。

**完成标准：** active MySQL adapter 与直接调用 `MySQLRepository` 的结果逐项一致。

---

## Phase 1：Extract：抽取 MySQL adapter

新增 protocol、MySQL adapter 和 factory，但默认仍返回 MySQL adapter。

### 要求

- 原有调用方不感知 repository 类型；
- 现有测试可继续注入 `repository_factory`；
- 现有 `semantic_search_factory` seam 保持兼容；
- 不修改 SQL 行为；
- 不改变连接池生命周期；
- 不改变事务边界。

重点接入点：

- `backend/app/services/project_discovery.py`；
- GitHub 项目每日流水线和 enrichment；
- 项目语义 indexer 使用的 semantic source/status 存储；
- 需要项目 catalog 的 MCP/REST 服务。

这一阶段只使用：

```dotenv
PROJECT_CATALOG_BACKEND=mysql
```

**完成标准：** 全部既有项目搜索、MCP 和语义索引相关测试通过，结果与迁移前一致。

---

## Phase 2：Adapt：实现 PostgreSQL repository

推荐新库采用 PostgreSQL。若最终选择其他 SQL 数据库，也必须实现同一 protocol，不得让业务层出现数据库专用分支。

### 2.1 连接与配置

新增独立配置，不复用 MySQL 密码字段：

```dotenv
POSTGRES_HOST=
POSTGRES_PORT=5432
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DATABASE=
POSTGRES_SSLMODE=require
POSTGRES_POOL_MIN_SIZE=2
POSTGRES_POOL_MAX_SIZE=20
```

要求：

- 使用独立连接池；
- 使用应用 lifespan 管理连接池创建/关闭；
- 新库连接失败不能影响 MySQL 默认链路；
- 密码只从环境变量或 secret store 读取；
- 日志只记录 host/database/status，不记录密码和 DSN query secret。

### 2.2 Schema

新库至少需要支持 active catalog 查询涉及的表和字段：

- `github_repo_candidates`；
- `github_repo_enrichments`；
- taxonomy/category/subcategory 关联；
- daily metrics/snapshot 表；
- canonical repo alias 表（如果现有 schema 使用）；
- `github_project_semantic_sources`；
- 需要写入的 ingest/enrichment 辅助表。

迁移必须：

- 幂等；
- 有版本号；
- 为 canonical repo_id 建立唯一约束；
- 为常用过滤和排序字段建立索引；
- JSON 字段明确转换为 PostgreSQL `jsonb` 或保持可兼容文本格式；
- 时间字段统一时区策略；
- 不在应用启动时隐式执行破坏性 migration。

建议目录：

```text
backend/migrations/postgres/
scripts/migrate_mysql_to_postgres.py
scripts/verify_project_catalog_consistency.py
```

### 2.3 SQL 转换注意事项

不要机械替换 SQL。逐条验证：

- `%s` 参数占位符与 PostgreSQL 驱动参数格式；
- `INSERT ... ON DUPLICATE KEY UPDATE` → `INSERT ... ON CONFLICT (...) DO UPDATE`；
- MySQL `IFNULL`、`GROUP_CONCAT`、日期函数和布尔值；
- JSON 文本与 `jsonb` 操作；
- `LIKE`/大小写匹配和 collation 差异；
- `ORDER BY` null 排序；
- `LIMIT/OFFSET` 和 count 子查询；
- `IN` 参数化，禁止拼接用户输入；
- transaction isolation、commit/rollback 和 deadlock retry；
- 字符串、时区、Unicode 和中文排序。

### 2.4 业务语义必须与 MySQL 一致

特别验证：

- stars 的最小值；
- enrichment succeeded 条件；
- today 的本地日期和时区；
- recommended 的排序与资格；
- hot score、recent、updated、name 排序；
- taxonomy filter；
- candidate repo ID 过滤；
- alias/canonical repo_id 解析；
- page count 与 `has_next`。

**完成标准：** PostgreSQL adapter 在固定 fixture 上与 MySQL golden result 一致，且通过独立 integration suite。

---

## Phase 3：数据迁移与同步

### 3.1 初始全量迁移

迁移顺序建议：

```text
schema
  → taxonomy/reference
  → candidates
  → enrichments
  → metrics/snapshots
  → semantic sources/status
  → consistency verification
```

脚本必须具备：

- dry-run；
- 分批处理；
- 游标续跑；
- 幂等 upsert；
- 失败记录和重试；
- 不删除 MySQL 数据；
- 迁移前后数量、主键、canonical repo_id hash 校验。

### 3.2 增量同步 / 双写

默认策略是 MySQL 继续作为 primary：

```text
写入请求
  ├── 同步写 MySQL（主结果）
  └── 异步或受控同步写 PostgreSQL（shadow）
```

要求：

- MySQL 成功不能因为 PostgreSQL 失败而回滚；
- PostgreSQL 写失败进入 retry/outbox；
- 双写事件必须幂等；
- 记录 source、entity key、operation、attempt、last_error；
- 不允许新旧库使用不同 canonical ID；
- migration/backfill job 不得与生产写入产生不可控覆盖。

可选 outbox 表/队列应单独设计，不要用内存 list 作为可靠同步机制。

**完成标准：** 连续观察期间 PostgreSQL lag 为 0 或在明确 SLO 内，失败事件可重放，MySQL 主链路不受影响。

---

## Phase 4：Shadow read 与一致性报告

shadow 模式下，用户仍使用 MySQL：

```text
请求
  ├── MySQL 查询 → 返回用户
  └── PostgreSQL 查询 → 异步比较，不改变响应
```

比较内容：

- canonical repo_id 集合；
- 顺序；
- total/page/has_next；
- 过滤后的字段；
- semantic candidate hydrate 结果；
- fallback provenance；
- 查询耗时和异常率。

日志/指标必须脱敏：

- 记录 query hash，不默认记录完整用户 query；
- 不记录 README 全文、embedding body、密码或 API key；
- 记录 mismatch type、case id、latency、backend；
- 对 mismatch 采样，避免日志爆量。

建议配置：

```dotenv
PROJECT_CATALOG_BACKEND=mysql
PROJECT_CATALOG_SHADOW_BACKEND=postgres
PROJECT_CATALOG_SHADOW_ENABLED=true
PROJECT_CATALOG_OUTBOX_CAPTURE_ENABLED=true
PROJECT_CATALOG_SYNC_WORKER_ENABLED=true
```

这里的增量同步是 MySQL transaction 内 durable outbox capture 加异步 PostgreSQL reconciliation，不是同步双写。所有目录写入、personal/private reads 与 legacy `GET /github/projects` 仍由 MySQL 提供；PostgreSQL 仅作为公开目录读取副本。

**正式切换前最低门槛建议：**

- 关键 contract case mismatch = 0；
- 连续观察至少一个完整业务周期；
- PostgreSQL 查询错误率和 p95 在目标范围；
- 数据 lag 在目标范围；
- no unresolved schema/transaction/auth issue；
- rollback 演练成功。

---

## Phase 5：一键切换

切换前先停止或冻结会修改 schema 的 migration job，确认 transactional outbox 与异步 sync 状态已追平；当前 compose 只有单个 backend 实例，`--force-recreate` 是 controlled recreate，不应称为 rolling restart。

### 5.1 切换到 PostgreSQL 公开目录读取

```dotenv
PROJECT_CATALOG_BACKEND=postgres
PROJECT_CATALOG_SHADOW_ENABLED=false
PROJECT_CATALOG_OUTBOX_CAPTURE_ENABLED=true
PROJECT_CATALOG_SYNC_WORKER_ENABLED=true
```

这不是 PostgreSQL 写入权威切换：MySQL 继续承载所有目录写入并通过 outbox 同步 PostgreSQL。切换前必须证明固定 outbox barrier 已由 PostgreSQL applied-event ledger 完整覆盖。

发布步骤：

1. 检查新库健康、schema version、连接池和 lag；
2. 检查一致性报告为 green；
3. 修改 secret/env，不在代码中写 key；
4. 经独立授权后 controlled recreate 应用；
5. 检查 `/health`、monitor、REST 项目查询、MCP tool；
6. 执行固定 contract smoke queries；
7. 观察错误率、延迟、pool saturation 和 fallback provenance；
8. 保持 MySQL 可读、可回滚，不立即删除旧库。

### 5.2 快速回滚

发现以下任一情况应回滚：

- 数据不一致；
- MCP/REST 字段或排序变化；
- 事务写入错误；
- PostgreSQL p95/错误率超 SLO；
- 连接池耗尽；
- semantic candidate 水合异常；
- fallback 行为改变。

回滚配置：

```dotenv
PROJECT_CATALOG_BACKEND=mysql
PROJECT_CATALOG_SHADOW_ENABLED=false
PROJECT_CATALOG_OUTBOX_CAPTURE_ENABLED=true
PROJECT_CATALOG_SYNC_WORKER_ENABLED=true
```

然后重启应用并执行同一组 smoke queries。回滚期间继续保留 PostgreSQL 增量同步，避免下次切换重新全量迁移。

### 5.3 稳定后收尾

PostgreSQL 公开读取稳定后仍必须保持 MySQL outbox capture 与 sync，因为写入权威尚未迁移。停止 capture/sync、把 PostgreSQL 改为写入权威或删除 MySQL 都必须是单独、经过授权的迁移项目，不能作为本次切换的隐含步骤。

---

## 5.4 是否同时迁移 Milvus

不建议在数据库切换发布中同时迁移 Milvus。保持：

```text
PostgreSQL / MySQL：项目元数据、过滤、水合、分页
Milvus：项目向量召回
SiliconFlow：embedding
```

原因：

- 数据库切换可以独立回滚；
- 已有向量不需要重建；
- 更容易定位性能或结果变化来源；
- 避免数据库、向量 schema、MCP 行为同时变化。

---

## 6. 测试清单

### 6.1 单元测试

- protocol/adapter 方法签名；
- factory backend 选择与非法配置；
- connection pool 创建/关闭；
- schema migration 幂等；
- parameterized IN；
- upsert/retry/outbox；
- MySQL adapter 不改变旧调用参数；
- shadow mismatch 脱敏和采样。

### 6.2 Repository contract tests

同一组 fixture 同时运行：

```text
MySQLProjectCatalogRepository
PostgresProjectCatalogRepository
```

逐字段比较：

- repo_id、full_name；
- stars、forks、language；
- taxonomy；
- timestamps；
- total/page/has_next；
- sort order；
- semantic candidate hydrate；
- empty result。

### 6.3 API/MCP contract tests

必须覆盖：

- `search_github_projects`；
- `search_github_ai_projects`；
- legacy project library alias；
- REST `/api/projects`；
- MCP `tools/list`；
- JSON-RPC envelope；
- `content.text`；
- `structuredContent`；
- local semantic result provenance；
- GitHub fallback provenance；
- taxonomy/scope/sort/page。

### 6.4 Failure and rollback tests

- PostgreSQL unavailable：MySQL 模式仍正常；
- MySQL unavailable：只有已批准的 PostgreSQL active 模式才接管；
- PostgreSQL dual-write 失败：MySQL 主请求仍成功，outbox 可重放；
- Milvus unavailable：数据库查询和 fallback 仍符合原契约；
- embedding unavailable：语义降级不影响关键词查询；
- pool exhausted：请求有界超时，不拖垮整个 API；
- restart 后 backend flag 仍正确；
- rollback 后 repo_id、排序和分页恢复一致。

### 6.5 性能测试

记录并比较：

- p50/p95/p99；
- MySQL/PostgreSQL pool wait；
- count/page 查询耗时；
- semantic hydrate 耗时；
- shadow overhead；
- dual-write lag；
- error/timeout/fallback rate。

不要只用一次查询判断新库性能，至少使用固定查询集和并发压测。

---

## 7. Agent 执行任务拆分

建议交给其他 Agent 按以下顺序执行，每个任务独立审查和测试：

### Agent A：Contract

- 阅读 `mysql_repo.py`、`project_discovery.py`、MCP routes/tools；
- 建立 repository contract fixture 和测试；
- 不实现 PostgreSQL，不改变生产路径。

### Agent B：Catalog abstraction

- 新增 protocol、MySQL adapter、factory 和配置；
- 默认 backend 仍为 MySQL；
- 迁移调用方但保持注入 seam；
- 运行旧测试和 contract tests。

### Agent C：PostgreSQL schema/repository

- 新增独立连接池生命周期；
- 编写版本化、幂等 PostgreSQL schema；
- 实现 `PostgresProjectCatalogRepository`；
- 完成 repository contract tests；
- 不打开 production switch。

### Agent D：Migration/sync

- 编写全量迁移、游标、dry-run、校验和增量/outbox；
- 只写新库，不删除 MySQL；
- 失败可重试、可重放；
- 输出一致性报告。

### Agent E：Shadow/observability

- 实现异步 shadow 查询和结果比较；
- 记录脱敏 mismatch 指标；
- 不改变用户响应；
- 增加开关和运行时监控。

### Agent F：Switch/rollback

- 实现 active backend factory 切换；
- 编写发布 smoke test、rollback test 和操作手册；
- 先在 staging/小流量验证；
- 未得到明确发布授权，不修改生产 backend flag。

---

## 8. 完成定义（Definition of Done）

只有同时满足以下条件，才允许把 `PROJECT_CATALOG_BACKEND` 切换为 `postgres`：

- [ ] MySQL adapter 与旧行为一致；
- [ ] PostgreSQL schema 版本化、幂等且已备份；
- [ ] 初始迁移完成，数量和 canonical repo_id 校验通过；
- [ ] 增量同步/双写可重试，lag 在 SLO 内；
- [ ] repository contract tests 全部通过；
- [ ] MCP/REST/SSE contract tests 全部通过；
- [ ] semantic Milvus → repo_id → database hydrate 已验证；
- [ ] shadow mismatch 为 0 或所有差异已解释并批准；
- [ ] PostgreSQL p95、错误率和连接池在 SLO 内；
- [ ] MySQL → PostgreSQL 切换演练成功；
- [ ] PostgreSQL → MySQL 回滚演练成功；
- [ ] 备份恢复演练成功；
- [ ] 发布人拥有明确 rollback 命令和窗口；
- [ ] 生产切换经过独立授权。

在上述条件完成前，生产配置必须保持：

```dotenv
PROJECT_CATALOG_BACKEND=mysql
```

---

## 9. 当前项目的执行建议

当前正在进行项目 profile embedding backfill，且语义查询刚完成启动预热和连接复用优化。因此建议其他 Agent：

1. 先只完成 Contract 和 MySQL adapter；
2. 不触碰 `aigc_github_projects_v1`；
3. 不暂停或重置 embedding backfill；
4. 新 PostgreSQL 逻辑默认关闭；
5. 先在隔离 fixture 中验证，再连接 staging 数据库；
6. 任何 schema migration、双写和 production switch 都必须单独提交和审批；
7. 最终切换只改一个配置项，但“一键切换”之前必须完成上面的所有门槛。
