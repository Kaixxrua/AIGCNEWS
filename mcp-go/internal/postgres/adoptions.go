package postgres

// adoptions.go 移植 backend/app/repositories/postgres_project_adoption_repository.py
// 全文（record_project_adoption 的 INSERT/RETURNING 与
// get_project_adoption_stats 的两条 GROUP BY 聚合），并实现
// mcpapp.AdoptionRecorder（对应 services/project_adoptions.py
// ProjectAdoptionService.record 的仓储段：写一行后默认 since_days=30 取
// 聚合）。
//
// 逐字对齐的源片段：
//   - _COLUMNS = "id, project_full_name, decision, reason, query, source,
//     created_at"（RETURNING 列序）
//   - INSERT INTO project_adoptions (project_full_name, decision, reason,
//     query, source) VALUES (%s, %s, %s, %s, %s) RETURNING {_COLUMNS}
//   - stats：窗口查询（now() - make_interval(days => %s)）与全量查询各一条，
//     同一事务内先窗口后全量
//
// 语义对齐要点：
//   - Python 侧 record 与 stats 各开一个 database.transaction()（默认
//     READ COMMITTED），Go 侧同样两段独立事务，不用 favorites 链路的
//     REPEATABLE READ READ ONLY。
//   - created_at：psycopg3 对 timestamptz 返回 tz-aware UTC datetime，
//     str() 得 "2026-08-20 12:34:56.789012+00:00"（微秒为 0 省略小数段）。
//     pgx 的 time.Time 统一转 UTC 后按此形状格式化——与 favorites.go 的
//     isoTimestamp（ISO8601 "Z" 形态）不同，勿混用。
//   - window/total 嵌套 dict 是 {row["decision"]: int(row["count"])} 推导，
//     键序跟随 SQL 行序（GROUP BY 无 ORDER BY，顺序由 PG 决定）；Go 侧用
//     jsonx.Object 按行序保序，不用 map（encoding/json 会按键名排序）。
//   - days 钳制 max(1, min(int(since_days), 365))：唯一调用点恒为 30
//     （service.record 不传参），钳制逻辑按原样保留以钉住仓储语义。

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/mcpapp"
)

// adoptionColumns 逐字搬运 _COLUMNS（RETURNING 列序）。
const adoptionColumns = "id, project_full_name, decision, reason, query, source, created_at"

// adoptionStatsWindowDays 对应 service.record 调用
// get_project_adoption_stats() 的缺省 since_days=30。
const adoptionStatsWindowDays = 30

// ProjectAdoptionsRepository 是 project_adoptions 表的生产仓储
// （append-only 回执写入 + 窗口聚合读取）。
type ProjectAdoptionsRepository struct {
	pool *pgxpool.Pool
}

func NewProjectAdoptionsRepository(pool *pgxpool.Pool) ProjectAdoptionsRepository {
	return ProjectAdoptionsRepository{pool: pool}
}

// RecordAdoption 对应 ProjectAdoptionService.record 的仓储段：
// record_project_adoption（一段事务）+ get_project_adoption_stats（另一段
// 事务，先窗口后全量两条查询）。
func (r ProjectAdoptionsRepository) RecordAdoption(receipt mcpapp.AdoptionReceipt) (mcpapp.RecordedAdoption, error) {
	recorded, err := r.insert(receipt)
	if err != nil {
		return mcpapp.RecordedAdoption{}, err
	}
	stats, err := r.stats(adoptionStatsWindowDays)
	if err != nil {
		return mcpapp.RecordedAdoption{}, err
	}
	recorded.Stats = stats
	return recorded, nil
}

// insert 复刻 record_project_adoption：INSERT … RETURNING _COLUMNS，
// 单行单事务。reason/query/source 的缺省填充（""/""/"mcp"）在 Python 由
// 工具处理器与仓储各做一次；MCP 路径入参校验已填满，此处与仓储一致地再
// 兜底一次空值（对齐 receipt.get("reason") or "" 语义）。
func (r ProjectAdoptionsRepository) insert(receipt mcpapp.AdoptionReceipt) (mcpapp.RecordedAdoption, error) {
	reason := receipt.Reason
	query := receipt.Query
	source := receipt.Source
	if source == "" {
		source = "mcp"
	}

	ctx := context.Background() // 对齐 asyncio.to_thread 语义：跑完不随客户端断连取消。
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return mcpapp.RecordedAdoption{}, fmt.Errorf("postgres: 采纳回执事务开启失败: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var recorded mcpapp.RecordedAdoption
	var createdAt time.Time
	err = tx.QueryRow(ctx,
		"INSERT INTO project_adoptions "+
			"(project_full_name, decision, reason, query, source) "+
			"VALUES ($1, $2, $3, $4, $5) "+
			"RETURNING "+adoptionColumns,
		receipt.ProjectFullName, receipt.Decision, reason, query, source,
	).Scan(
		&recorded.ID, &recorded.ProjectFullName, &recorded.Decision,
		&recorded.Reason, &recorded.Query, &recorded.Source, &createdAt,
	)
	if err != nil {
		return mcpapp.RecordedAdoption{}, fmt.Errorf("postgres: 采纳回执写入失败: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return mcpapp.RecordedAdoption{}, fmt.Errorf("postgres: 采纳回执事务提交失败: %w", err)
	}
	recorded.CreatedAt = pythonDatetimeString(createdAt)
	return recorded, nil
}

// stats 复刻 get_project_adoption_stats：同一事务内先窗口聚合后全量聚合，
// 返回键序 window_days, window, total（Python dict 插入序）。
func (r ProjectAdoptionsRepository) stats(sinceDays int) (mcpapp.AdoptionStats, error) {
	// days = max(1, min(int(since_days), 365))
	days := sinceDays
	if days < 1 {
		days = 1
	} else if days > 365 {
		days = 365
	}

	ctx := context.Background()
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return mcpapp.AdoptionStats{}, fmt.Errorf("postgres: 采纳统计事务开启失败: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	window, err := adoptionDecisionCounts(tx, ctx,
		"SELECT decision, COUNT(*) AS count FROM project_adoptions "+
			"WHERE created_at >= now() - make_interval(days => $1) GROUP BY decision",
		days)
	if err != nil {
		return mcpapp.AdoptionStats{}, fmt.Errorf("postgres: 采纳窗口统计失败: %w", err)
	}
	total, err := adoptionDecisionCounts(tx, ctx,
		"SELECT decision, COUNT(*) AS count FROM project_adoptions GROUP BY decision")
	if err != nil {
		return mcpapp.AdoptionStats{}, fmt.Errorf("postgres: 采纳全量统计失败: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return mcpapp.AdoptionStats{}, fmt.Errorf("postgres: 采纳统计事务提交失败: %w", err)
	}
	return mcpapp.AdoptionStats{WindowDays: days, Window: window, Total: total}, nil
}

// adoptionDecisionCounts 执行一条 GROUP BY decision 聚合并按行序组装
// jsonx.Object（对齐 Python dict 推导的插入序；int(row["count"]) 把
// COUNT(*) 的 int64 落成 Python int 语义值）。
func adoptionDecisionCounts(tx pgx.Tx, ctx context.Context, sql string, args ...any) (jsonx.Object, error) {
	rows, err := tx.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	counts := jsonx.Object{}
	for rows.Next() {
		var decision string
		var count int64
		if err := rows.Scan(&decision, &count); err != nil {
			return nil, err
		}
		counts = append(counts, jsonx.Pair{Key: decision, Value: int(count)})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return counts, nil
}

// pythonDatetimeString 复刻 str(tz-aware UTC datetime)：
// "2006-01-02 15:04:05[.ffffff]+00:00"，微秒为 0 时省略小数段。
// PG timestamptz 为微秒精度（纳秒截断到微秒）。
func pythonDatetimeString(t time.Time) string {
	u := t.UTC()
	base := u.Format("2006-01-02 15:04:05")
	if micro := u.Nanosecond() / 1000; micro != 0 {
		return fmt.Sprintf("%s.%06d+00:00", base, micro)
	}
	return base + "+00:00"
}
