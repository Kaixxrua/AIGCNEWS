package postgres

// 共享向量由 Python 权威实现 _document_search_plan 生成
// （backend/tests/fixtures/document_search_intent_vectors.json），
// backend/tests/test_document_search_intent.py 读同一文件，双向钉住。

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
	"time"
)

const documentIntentVectorsPath = "../../../backend/tests/fixtures/document_search_intent_vectors.json"

func TestDocumentSearchPlanMatchesSharedVectors(t *testing.T) {
	raw, err := os.ReadFile(documentIntentVectorsPath)
	if err != nil {
		t.Fatalf("读取共享向量失败: %v", err)
	}
	var vectors struct {
		Cases []struct {
			Today      string    `json:"today"`
			Query      string    `json:"query"`
			Candidates []string  `json:"candidates"`
			Window     *[]string `json:"window"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &vectors); err != nil {
		t.Fatalf("解析共享向量失败: %v", err)
	}
	if len(vectors.Cases) <= 20 {
		t.Fatalf("共享向量过少: %d", len(vectors.Cases))
	}
	for _, c := range vectors.Cases {
		today, err := time.Parse("2006-01-02", c.Today)
		if err != nil {
			t.Fatalf("today %q: %v", c.Today, err)
		}
		plan := buildDocumentSearchPlan(c.Query, 5, today)
		candidates := plan.candidates
		if candidates == nil {
			candidates = []string{}
		}
		if !reflect.DeepEqual(candidates, c.Candidates) {
			t.Errorf("%s %q candidates = %q, want %q", c.Today, c.Query, candidates, c.Candidates)
		}
		var window []string
		if plan.window != nil {
			window = []string{plan.window.since, plan.window.until}
		}
		var want []string
		if c.Window != nil {
			want = *c.Window
		}
		if !reflect.DeepEqual(window, want) {
			t.Errorf("%s %q window = %q, want %q", c.Today, c.Query, window, want)
		}
	}
}

// 调度时区锚：UTC 16:30 已是上海次日。
func TestDocumentRepositoryLocalTodayUsesSchedulerTimezone(t *testing.T) {
	repo := NewDocumentRepository(nil, "")
	repo.now = func() time.Time { return time.Date(2026, 9, 29, 16, 30, 0, 0, time.UTC) }
	if got := repo.localToday().Format("2006-01-02"); got != "2026-09-30" {
		t.Fatalf("localToday = %s, want 2026-09-30", got)
	}
}
