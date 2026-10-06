package postgres

import (
	"strings"
	"testing"
)

// 三段查询都只按 $1（token 属主）取行；简报按期号新到旧、只取 since 起。
func TestTrackingSQLIsScopedToTokenOwner(t *testing.T) {
	for name, sql := range map[string]string{
		"rules":    trackingRulesSQL,
		"settings": trackingSettingsSQL,
		"digests":  trackingDigestsSQL,
	} {
		if !strings.Contains(sql, "WHERE user_id = $1") {
			t.Fatalf("%s query is not scoped to the token owner: %s", name, sql)
		}
		if strings.Contains(strings.ToUpper(sql), "UPDATE") || strings.Contains(strings.ToUpper(sql), "INSERT") {
			t.Fatalf("%s query must stay read-only: %s", name, sql)
		}
	}
	if !strings.Contains(trackingRulesSQL, "ORDER BY id") {
		t.Fatalf("rules order drifted: %s", trackingRulesSQL)
	}
	if !strings.Contains(trackingDigestsSQL, "issue_date >= $2::date") ||
		!strings.HasSuffix(trackingDigestsSQL, "ORDER BY issue_date DESC") {
		t.Fatalf("digest window drifted: %s", trackingDigestsSQL)
	}
}

func TestDecodeTrackingExcludesKeepsStringsOnly(t *testing.T) {
	got := decodeTrackingExcludes(`["crypto", 3, null, "nft"]`)
	if strings.Join(got, ",") != "crypto,nft" {
		t.Fatalf("excludes=%v", got)
	}
	if got := decodeTrackingExcludes(`{"bad": true}`); len(got) != 0 {
		t.Fatalf("non-array excludes=%v", got)
	}
}

func TestDecodeTrackingItemsSkipsMalformedEntries(t *testing.T) {
	raw := `[
		{"observed_at": "2026-10-05T22:00:00+00:00", "key": "news:1", "title": "kept", "url": "https://example.com/a",
		 "summary": "s", "source": "news", "matched_rules": ["Agent", "MCP"]},
		{"title": "plain http", "url": "http://example.com/b", "matched_rules": []},
		{"title": "", "url": "https://example.com/c"},
		{"title": "bad rules", "url": "https://example.com/d", "matched_rules": [1]},
		"not an object",
		{"title": "no rules", "url": "https://example.com/e", "source": "x"}
	]`
	items := decodeTrackingItems(raw)
	if len(items) != 2 {
		t.Fatalf("items=%+v", items)
	}
	first := items[0]
	if first.Title != "kept" || first.URL != "https://example.com/a" || first.ObservedAt != "2026-10-05T22:00:00+00:00" ||
		first.Source != "news" || first.Summary != "s" || strings.Join(first.MatchedRules, ",") != "Agent,MCP" {
		t.Fatalf("first=%+v", first)
	}
	if items[1].Title != "no rules" || items[1].MatchedRules == nil || len(items[1].MatchedRules) != 0 {
		t.Fatalf("second=%+v", items[1])
	}
	if got := decodeTrackingItems(`{"not": "an array"}`); len(got) != 0 {
		t.Fatalf("non-array items=%v", got)
	}
}
