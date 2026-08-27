package postgres

// rank_snapshots.go 移植 PostgresRankSnapshotRepository 的两个读方法
// （backend/app/repositories/postgres_rank_snapshot_repository.py）：
// get_snapshot_documents 与 get_snapshot_doc_ids。SQL 逐字搬运（%s → $n），
// 排序/JOIN/COALESCE 口径不变；MCP 侧只消费 30 列中的 14 列，但 SELECT 全列
// 保留以使结果序与 Python 完全一致（ORDER BY 引用 d/s 两表的列）。

import (
	"context"
	"strconv"
	"strings"

	"aigcnews/mcp-go/internal/mcpapp"
	"github.com/jackc/pgx/v5/pgxpool"
)

type RankSnapshotRepository struct{ pool *pgxpool.Pool }

func NewRankSnapshotRepository(pool *pgxpool.Pool) RankSnapshotRepository {
	return RankSnapshotRepository{pool: pool}
}

// GetSnapshotDocuments 逐字复刻 get_snapshot_documents：动态条件按
// snapshot_date [+ source_channel] [+ source_type(!= "all")] 组装，
// LIMIT 恒为末位参数。空 source_channel / 空或 "all" 的 source_type
// 不生成条件（Python None/"all" 同语义）。
func (r RankSnapshotRepository) GetSnapshotDocuments(snapshotDate, sourceChannel, sourceType string, limit int) ([]mcpapp.DocumentRow, error) {
	conditions := []string{"s.snapshot_date = $1"}
	params := []any{snapshotDate}
	if sourceChannel != "" {
		params = append(params, sourceChannel)
		conditions = append(conditions, "s.source_channel = $"+strconv.Itoa(len(params)))
	}
	if sourceType != "" && sourceType != "all" {
		params = append(params, sourceType)
		conditions = append(conditions, "d.source = $"+strconv.Itoa(len(params)))
	}
	params = append(params, limit)
	// 与 Python get_snapshot_documents 同一规则：具体非 github sourceType
	// 已把 d.source 钉死，github 补全连接永不命中，直接读 d 自身列——
	// 避免 github_repo_snapshots(65 万行) 全表 DISTINCT ON 排序落盘；
	// 需要补全时用 LATERAL + (repo_id, snapshot_date) 索引倒序 LIMIT 1。
	githubVisible := sourceType == "" || sourceType == "all" || sourceType == "github"
	metricColumns := `COALESCE(NULLIF(d.stars, 0), 0) AS stars,
                   COALESCE(NULLIF(d.forks, 0), 0) AS forks,
                   COALESCE(NULLIF(d.language, ''), '') AS language,`
	githubJoins := ""
	if githubVisible {
		metricColumns = `COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars,
                   COALESCE(NULLIF(d.forks, 0), NULLIF(gs.forks, 0), c.forks, 0) AS forks,
                   COALESCE(NULLIF(d.language, ''), c.language, '') AS language,`
		githubJoins = `LEFT JOIN github_repo_candidates c
              ON d.source = 'github' AND (c.full_name = d.title
                  OR (NULLIF(c.url, '') IS NOT NULL AND c.url = d.url))
            LEFT JOIN LATERAL (
                SELECT g.stars, g.forks
                FROM github_repo_snapshots g
                WHERE g.repo_id = c.repo_id
                ORDER BY g.snapshot_date DESC
                LIMIT 1
            ) gs ON TRUE`
	}
	query := `
            SELECT d.id, d.source, d.title, d.url, d.summary, d.published_date,
                   d.published_at, d.tags, d.indexed, d.created_at,
                   d.media, d.quote, d.link_card, d.author_avatar_url, d.author_name, d.retweeted_by, d.translation_zh,
                   d.authors, d.arxiv_id,
                   ` + metricColumns + `
                   d.in_daily, d.in_weekly, d.in_monthly, s.source_channel,
                   s.rank_in_period, s.raw_score, s.score, s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            ` + githubJoins + `
            WHERE ` + strings.Join(conditions, " AND ") + `
            ORDER BY
                CASE WHEN d.source = 'github' THEN s.rank_in_period ELSE 9999 END ASC,
                CASE WHEN d.source != 'github' THEN -s.raw_score ELSE 0 END ASC,
                s.rank_in_period ASC
            LIMIT $` + strconv.Itoa(len(params))

	rows, err := r.pool.Query(context.Background(), query, params...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []mcpapp.DocumentRow{}
	for rows.Next() {
		values := make([]any, 30)
		pointers := make([]any, len(values))
		for i := range values {
			pointers[i] = &values[i]
		}
		if err := rows.Scan(pointers...); err != nil {
			return nil, err
		}
		out = append(out, mcpapp.DocumentRow{
			ID:            asString(values[0]),  // d.id
			Source:        asString(values[1]),  // d.source
			Title:         asString(values[2]),  // d.title
			URL:           asString(values[3]),  // d.url
			Summary:       asString(values[4]),  // d.summary
			PublishedDate: asString(values[5]),  // d.published_date
			Tags:          asString(values[7]),  // d.tags
			CreatedAt:     asString(values[9]),  // d.created_at
			Authors:       asString(values[17]), // d.authors
			ArxivID:       asString(values[18]), // d.arxiv_id
			SourceChannel: asString(values[25]), // s.source_channel
			RankInPeriod:  asInt32(values[26]),  // s.rank_in_period
			RawScore:      asFloat(values[27]),  // s.raw_score（DOUBLE PRECISION）
			Score:         asFloat(values[28]),  // s.score
			// local_pdf_path 不在本 SELECT 中（Python 同），保持 nil →
			// dashboard 投影的 pdf_media_url 恒 null。
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

// GetSnapshotDocIDs 逐字复刻 get_snapshot_doc_ids：DISTINCT doc_id，
// 空 source_channel 不生成条件。Python 返回 set[str]，Go 以
// map[string]bool 承载同一集合语义（空集=空 map）。
func (r RankSnapshotRepository) GetSnapshotDocIDs(snapshotDate, sourceChannel string) (map[string]bool, error) {
	query := "SELECT DISTINCT doc_id FROM document_rank_snapshots WHERE snapshot_date = $1"
	params := []any{snapshotDate}
	if sourceChannel != "" {
		params = append(params, sourceChannel)
		query += " AND source_channel = $2"
	}
	rows, err := r.pool.Query(context.Background(), query, params...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out[id] = true
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}
