package postgres

// statistics.go 移植 PostgresDocumentRepository 的两个看板统计读方法
// （backend/app/repositories/postgres_document_repository.py::
// get_source_counts / get_today_document_count）。SQL 逐字搬运；
// "今日" 锚复刻 _local_today()：datetime.now(ZoneInfo(
// settings.scheduler_timezone 或 "Asia/Shanghai")).date()。

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	// alpine 基础镜像不带系统 tzdata；内嵌时区库保证 LoadLocation 在任何
	// 部署形态下与 Python zoneinfo 同口径（Python 镜像装了 tzdata）。
	_ "time/tzdata"
)

// DocumentStatistics 提供看板统计查询。timezone 对应
// settings.scheduler_timezone（SCHEDULER_TIMEZONE），空串按 Python 的
// `or "Asia/Shanghai"` 兜底。
type DocumentStatistics struct {
	pool     *pgxpool.Pool
	timezone string
}

func NewDocumentStatistics(pool *pgxpool.Pool, timezone string) DocumentStatistics {
	if timezone == "" {
		timezone = "Asia/Shanghai"
	}
	return DocumentStatistics{pool: pool, timezone: timezone}
}

// GetSourceCounts 逐字复刻 get_source_counts：按源统计去重文档数
// （url 空串回退 title）。map 键序由 PG GROUP BY 决定，消费方
// （summaryStats）自行排序，与 Python dict 的 PG 序同为不稳定序。
func (s DocumentStatistics) GetSourceCounts() (map[string]int, error) {
	rows, err := s.pool.Query(context.Background(),
		"SELECT source, COUNT(DISTINCT COALESCE(NULLIF(url, ''), title)) AS cnt FROM documents GROUP BY source")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := map[string]int{}
	for rows.Next() {
		var source string
		var count int64
		if err := rows.Scan(&source, &count); err != nil {
			return nil, err
		}
		out[source] = int(count)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

// GetTodayDocumentCount 逐字复刻 get_today_document_count：github 源计
// github_repo_candidates 当日 first_seen_at，其余源计 documents.created_at
// 当日入库，两侧同为 LEFT(...,10) 词法日期前缀。
// 时区名非法时 LoadLocation 报错返回——对齐 Python ZoneInfoNotFoundError
// 在查询期抛出的语义（最终投射 -32603）。
func (s DocumentStatistics) GetTodayDocumentCount() (int, error) {
	zone, err := time.LoadLocation(s.timezone)
	if err != nil {
		return 0, fmt.Errorf("postgres: 调度时区 %q 加载失败: %w", s.timezone, err)
	}
	today := time.Now().In(zone).Format("2006-01-02")
	var count int64
	err = s.pool.QueryRow(context.Background(), `
            SELECT (
                SELECT COUNT(*) FROM documents
                WHERE LEFT(created_at, 10) = $1 AND source <> 'github'
            ) + (
                SELECT COUNT(*) FROM github_repo_candidates
                WHERE LEFT(COALESCE(first_seen_at, ''), 10) = $2
            ) AS cnt
        `, today, today).Scan(&count)
	if err != nil {
		return 0, err
	}
	return int(count), nil
}
