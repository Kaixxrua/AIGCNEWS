package postgres

// tracking.go 是 get_my_tracking 的读路径：一个用户的追踪规则、追踪设置与
// since 当天起的追踪简报（backend postgres_tracking_repository.py 的
// overview 读同一组表；MCP 只读，不改 last_read_digest_id 等游标）。
//
//   - 三段查询在同一 REPEATABLE READ READ ONLY 事务里，规则与简报同一快照；
//   - tracking_settings 缺行时取后端默认（开启、8 点），与 overview 一致；
//   - JSONB 列以 ::text 取回再解码：excludes 只收字符串元素；简报条目逐个
//     解码，形状不对的条目跳过，不让一条脏数据拖垮整次调用。

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"aigcnews/mcp-go/internal/mcpapp"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type TrackingRepository struct{ pool *pgxpool.Pool }

func NewTrackingRepository(pool *pgxpool.Pool) TrackingRepository {
	return TrackingRepository{pool: pool}
}

const (
	trackingRulesSQL = "SELECT id, kind, query, source, excludes::text, star_threshold, enabled" +
		" FROM tracking_rules WHERE user_id = $1 ORDER BY id"
	trackingSettingsSQL = "SELECT enabled, delivery_hour FROM tracking_settings WHERE user_id = $1"
	trackingDigestsSQL  = "SELECT to_char(issue_date, 'YYYY-MM-DD'), truncated, items::text" +
		" FROM tracking_digests WHERE user_id = $1 AND issue_date >= $2::date" +
		" ORDER BY issue_date DESC"
)

// ReadTracking 读取 userID 的追踪规则、设置与 since（UTC+8 的 YYYY-MM-DD）
// 当天起的追踪简报，简报按期号新到旧。
func (r TrackingRepository) ReadTracking(userID int, since string) (mcpapp.TrackingSnapshot, error) {
	ctx := context.Background()
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪读取事务开启失败: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	snapshot := mcpapp.TrackingSnapshot{
		Rules:        []mcpapp.TrackingRule{},
		Enabled:      true,
		DeliveryHour: 8,
		Issues:       []mcpapp.TrackingIssue{},
	}

	rows, err := tx.Query(ctx, trackingRulesSQL, userID)
	if err != nil {
		return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪规则查询失败: %w", err)
	}
	for rows.Next() {
		var rule mcpapp.TrackingRule
		var excludes string
		if err := rows.Scan(&rule.ID, &rule.Kind, &rule.Query, &rule.Source, &excludes,
			&rule.StarThreshold, &rule.Enabled); err != nil {
			rows.Close()
			return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪规则解码失败: %w", err)
		}
		rule.Excludes = decodeTrackingExcludes(excludes)
		snapshot.Rules = append(snapshot.Rules, rule)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪规则读取失败: %w", err)
	}

	err = tx.QueryRow(ctx, trackingSettingsSQL, userID).Scan(&snapshot.Enabled, &snapshot.DeliveryHour)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪设置查询失败: %w", err)
	}

	rows, err = tx.Query(ctx, trackingDigestsSQL, userID, since)
	if err != nil {
		return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪简报查询失败: %w", err)
	}
	for rows.Next() {
		var issue mcpapp.TrackingIssue
		var items string
		if err := rows.Scan(&issue.IssueDate, &issue.Truncated, &items); err != nil {
			rows.Close()
			return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪简报解码失败: %w", err)
		}
		issue.Items = decodeTrackingItems(items)
		snapshot.Issues = append(snapshot.Issues, issue)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪简报读取失败: %w", err)
	}

	if err := tx.Commit(ctx); err != nil {
		return mcpapp.TrackingSnapshot{}, fmt.Errorf("postgres: 追踪读取事务提交失败: %w", err)
	}
	return snapshot, nil
}

// decodeTrackingExcludes 解码 excludes（JSONB 数组，CHECK 保证是数组），
// 只保留字符串元素；无法解码时按无排除词处理。
func decodeTrackingExcludes(raw string) []string {
	var values []any
	if err := json.Unmarshal([]byte(raw), &values); err != nil {
		return []string{}
	}
	terms := make([]string, 0, len(values))
	for _, value := range values {
		if term, ok := value.(string); ok {
			terms = append(terms, term)
		}
	}
	return terms
}

// trackingItemJSON 是后端 domain/tracking.clean_item 写入的条目形状
// （key 是去重键，不对外）。
type trackingItemJSON struct {
	ObservedAt   string   `json:"observed_at"`
	Title        string   `json:"title"`
	URL          string   `json:"url"`
	Summary      string   `json:"summary"`
	Source       string   `json:"source"`
	MatchedRules []string `json:"matched_rules"`
}

// decodeTrackingItems 逐个解码简报条目，保持存储顺序；形状不对、缺标题或
// 链接不是 https 的条目跳过（生成时 public_link 已只收 https 公网链接，这里
// 再守一道）。
func decodeTrackingItems(raw string) []mcpapp.TrackingItem {
	var elements []json.RawMessage
	if err := json.Unmarshal([]byte(raw), &elements); err != nil {
		return []mcpapp.TrackingItem{}
	}
	items := make([]mcpapp.TrackingItem, 0, len(elements))
	for _, element := range elements {
		var item trackingItemJSON
		if err := json.Unmarshal(element, &item); err != nil || item.Title == "" ||
			!strings.HasPrefix(item.URL, "https://") {
			continue
		}
		matched := item.MatchedRules
		if matched == nil {
			matched = []string{}
		}
		items = append(items, mcpapp.TrackingItem{
			ObservedAt:   item.ObservedAt,
			Title:        item.Title,
			URL:          item.URL,
			Summary:      item.Summary,
			Source:       item.Source,
			MatchedRules: matched,
		})
	}
	return items
}
