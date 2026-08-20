package postgres

// briefings.go 移植 PostgresBriefingRepository.get_briefing_by_date
// （backend/app/repositories/postgres_briefing_repository.py）。
// Python 是 SELECT *；MCP 只消费 content_zh/content_en/content 三列
// （select_briefing_content 的候选集），显式列名等效且不受表结构演进影响。
// 无行 → (nil, nil)，对齐 Python 的 None（资源侧投射 "not found" 文案）。

import (
	"context"
	"errors"

	"aigcnews/mcp-go/internal/mcpapp"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type BriefingRepository struct{ pool *pgxpool.Pool }

func NewBriefingRepository(pool *pgxpool.Pool) BriefingRepository {
	return BriefingRepository{pool: pool}
}

func (r BriefingRepository) GetBriefing(key string) (*mcpapp.BriefingRecord, error) {
	// 三列 DDL 均 NOT NULL（0008 起 zh/en DEFAULT ''），但 any-slice 扫描
	// 对 NULL 同样安全（落空串，select_briefing_content 视作空候选）。
	values := make([]any, 3)
	pointers := make([]any, len(values))
	for i := range values {
		pointers[i] = &values[i]
	}
	err := r.pool.QueryRow(context.Background(),
		"SELECT content_zh, content_en, content FROM briefings WHERE date = $1", key,
	).Scan(pointers...)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &mcpapp.BriefingRecord{
		ContentZH: textOrEmpty(values[0]),
		ContentEN: textOrEmpty(values[1]),
		Content:   textOrEmpty(values[2]),
	}, nil
}

// textOrEmpty 把 any 形态的 TEXT 列收窄为 string；NULL/异常形态落空串
// （Python 侧 None 在 select_briefing_content 里同样被 strip 判空跳过）。
func textOrEmpty(value any) string {
	text, ok := value.(string)
	if !ok {
		return ""
	}
	return text
}
