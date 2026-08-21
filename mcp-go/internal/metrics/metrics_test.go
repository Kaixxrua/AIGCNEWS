package metrics

import (
	"context"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

func TestIsBenchmarkUserAgent(t *testing.T) {
	cases := []struct {
		ua   string
		want bool
	}{
		{"mcp-latency-bench/1.0", true},
		{"  mcp-latency-bench/x  ", true}, // strip 后命中前缀
		{"mcp-latency-bench/", true},
		{"dsh-aigc-radar/1.2", false},
		{"curl/8.0", false},
		{"", false},
		{"prefix-mcp-latency-bench/1.0", false}, // 前缀必须从头命中
	}
	for _, c := range cases {
		if got := IsBenchmarkUserAgent(c.ua); got != c.want {
			t.Errorf("IsBenchmarkUserAgent(%q) = %v, want %v", c.ua, got, c.want)
		}
	}
}

func TestBucketClientName(t *testing.T) {
	if got := BucketClientName("dsh-aigc-radar/2.1"); got != "dsh-aigc-radar" {
		t.Errorf("known client = %q", got)
	}
	if got := BucketClientName("  dsh-aigc-radar/2.1 "); got != "dsh-aigc-radar" {
		t.Errorf("stripped known client = %q", got)
	}
	for _, ua := range []string{"", "curl/8.0", "mcp-latency-bench/1.0", "dsh-other/1"} {
		if got := BucketClientName(ua); got != "" {
			t.Errorf("BucketClientName(%q) = %q, want empty", ua, got)
		}
	}
}

func TestBucketToolName(t *testing.T) {
	known := map[string]struct{}{"search_papers": {}, "get_top_items": {}}
	if got := BucketToolName("search_papers", known); got != "search_papers" {
		t.Errorf("known = %q", got)
	}
	if got := BucketToolName(" search_papers ", known); got != "search_papers" {
		t.Errorf("stripped known = %q", got)
	}
	for _, name := range []string{"", "not-a-tool", "search_papers_extra"} {
		if got := BucketToolName(name, known); got != UnknownToolName {
			t.Errorf("BucketToolName(%q) = %q, want __unknown__", name, got)
		}
	}
	// 超长未知名截断到 64 后仍不在注册表 → __unknown__。
	long := string(make([]rune, 100))
	if got := BucketToolName(long, known); got != UnknownToolName {
		t.Errorf("long unknown = %q", got)
	}
}

func newMiniredis(t *testing.T) (*miniredis.Miniredis, *redis.Client) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	return mr, client
}

func TestRecorderRecordWritesAllKeys(t *testing.T) {
	mr, client := newMiniredis(t)
	rec := NewRecorder(client)
	ctx := context.Background()

	rec.Record(ctx, "search_papers", "dsh-aigc-radar")
	rec.Record(ctx, "search_papers", "dsh-aigc-radar")
	rec.Record(ctx, "get_top_items", "") // 空 client：跳过客户端桶

	if got, err := mr.Get("mcpmetrics:total"); err != nil || got != "3" {
		t.Errorf("total = %q err=%v, want 3", got, err)
	}
	if !mr.Exists("mcpmetrics:since") {
		t.Error("since key missing")
	}
	if got := mr.HGet("mcpmetrics:tool_calls", "search_papers"); got != "2" {
		t.Errorf("tool_calls[search_papers] = %q, want 2", got)
	}
	if got := mr.HGet("mcpmetrics:tool_calls", "get_top_items"); got != "1" {
		t.Errorf("tool_calls[get_top_items] = %q, want 1", got)
	}
	if got := mr.HGet("mcpmetrics:client_calls", "dsh-aigc-radar"); got != "2" {
		t.Errorf("client_calls[dsh-aigc-radar] = %q, want 2", got)
	}
	// 空 client 不写客户端桶。
	if mr.Exists("mcpmetrics:client_calls") {
		fields, err := mr.HKeys("mcpmetrics:client_calls")
		if err != nil || len(fields) != 1 || fields[0] != "dsh-aigc-radar" {
			t.Errorf("client_calls fields = %v err=%v, want only dsh-aigc-radar", fields, err)
		}
	}
}

func TestRecorderNilIsNoOp(t *testing.T) {
	var rec *Recorder
	rec.Record(context.Background(), "x", "y") // 不应 panic
	if NewRecorder(nil) != nil {
		t.Error("NewRecorder(nil) should be nil")
	}
}

func TestRecorderFailOpenOnRedisDown(t *testing.T) {
	mr, client := newMiniredis(t)
	rec := NewRecorder(client)
	mr.Close() // Redis 宕机
	// 不应 panic、不应向上返回错误（fail-open，只记日志）。
	rec.Record(context.Background(), "search_papers", "")
}
