package usage

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
)

// 2026-10-05 10:00 北京时间。
var fixedNow = time.Date(2026, 10, 5, 2, 0, 0, 0, time.UTC)

const fixedDay = "2026-10-05"

func newTestRecorder(t *testing.T) (*Recorder, *miniredis.Miniredis, *redis.Client) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	recorder := NewRecorder(client)
	recorder.now = func() time.Time { return fixedNow }
	return recorder, mr, client
}

func pfcount(t *testing.T, client *redis.Client, keys ...string) int64 {
	t.Helper()
	n, err := client.PFCount(context.Background(), keys...).Result()
	if err != nil {
		t.Fatalf("PFCOUNT %v: %v", keys, err)
	}
	return n
}

var (
	anonymous = authn.Identity{}
	freeUser  = authn.Identity{UserID: 7, Role: "user", MembershipTier: authn.TierFree}
	member    = authn.Identity{UserID: 9, Role: "user", MembershipTier: authn.TierMember}
	admin     = authn.Identity{UserID: 1, Role: "admin", MembershipTier: authn.TierMember}
)

func TestDayUsesBeijingCalendar(t *testing.T) {
	cases := map[time.Time]string{
		time.Date(2026, 10, 4, 15, 59, 59, 0, time.UTC): "2026-10-04",
		time.Date(2026, 10, 4, 16, 0, 0, 0, time.UTC):   "2026-10-05",
		time.Date(2026, 10, 5, 2, 0, 0, 0, time.UTC):    "2026-10-05",
	}
	for now, want := range cases {
		if got := Day(now); got != want {
			t.Errorf("Day(%s) = %s, want %s", now, got, want)
		}
	}
}

func TestAudienceFollowsEffectiveTier(t *testing.T) {
	past := fixedNow.Add(-time.Hour)
	future := fixedNow.Add(time.Hour)
	cases := []struct {
		name     string
		identity authn.Identity
		want     string
	}{
		{"anonymous", anonymous, AudienceAnonymous},
		{"free", freeUser, AudienceMember},
		{"member without expiry", member, AudienceMember},
		{"member active", authn.Identity{UserID: 3, MembershipTier: authn.TierMember, MembershipExpiresAt: &future}, AudienceMember},
		{"member expired", authn.Identity{UserID: 3, MembershipTier: authn.TierMember, MembershipExpiresAt: &past}, AudienceMember},
		{"unknown tier", authn.Identity{UserID: 3, MembershipTier: "gold"}, AudienceMember},
	}
	for _, tc := range cases {
		if got := Audience(tc.identity, fixedNow); got != tc.want {
			t.Errorf("%s: Audience = %s, want %s", tc.name, got, tc.want)
		}
	}
}

func TestLimitKind(t *testing.T) {
	if got := LimitKind(false, ""); got != LimitBurst {
		t.Errorf("burst = %s", got)
	}
	if got := LimitKind(true, "daily"); got != LimitDaily {
		t.Errorf("daily = %s", got)
	}
	if got := LimitKind(true, "monthly"); got != LimitMonthly {
		t.Errorf("monthly = %s", got)
	}
}

func TestNormalizeClientName(t *testing.T) {
	cases := map[string]string{
		"Claude Code":               "claude code",
		"  Cursor  ":                "cursor",
		"":                          UnknownClientName,
		"   ":                       UnknownClientName,
		"通义灵码":                      "通义灵码",
		"vscode/1.104 (insiders)":   "vscode/1.104 (insiders)",
		"dsh-aigc-radar@0.2.3":      "dsh-aigc-radar@0.2.3",
		"evil|field":                OtherClientName,
		"line\nbreak":               OtherClientName,
		"emoji 🤖":                   OtherClientName,
		strings.Repeat("a", 48):     strings.Repeat("a", 48),
		strings.Repeat("a", 49):     OtherClientName,
		"x�y":                       OtherClientName,
		"<script>alert(1)</script>": OtherClientName,
	}
	for raw, want := range cases {
		if got := NormalizeClientName(raw); got != want {
			t.Errorf("NormalizeClientName(%q) = %q, want %q", raw, got, want)
		}
	}
}

func TestRecordSplitsToolCallsByAudience(t *testing.T) {
	recorder, mr, client := newTestRecorder(t)
	ctx := context.Background()
	recorder.Record(ctx, Event{Identity: anonymous, ClientIP: "198.51.100.1", Method: "tools/call", Tool: "search_papers"})
	recorder.Record(ctx, Event{Identity: anonymous, ClientIP: "198.51.100.1", Method: "tools/call", Tool: "search_papers"})
	recorder.Record(ctx, Event{Identity: anonymous, ClientIP: "198.51.100.2", Method: "tools/call", Tool: "get_top_items"})
	recorder.Record(ctx, Event{Identity: freeUser, ClientIP: "198.51.100.3", Method: "tools/call", Tool: "search_papers"})
	recorder.Record(ctx, Event{Identity: member, ClientIP: "198.51.100.4", Method: "tools/call", Tool: "search_papers"})
	recorder.Record(ctx, Event{Identity: member, ClientIP: "198.51.100.5", Method: "tools/call", Tool: ""})

	calls := "mcpusage:" + fixedDay + ":calls"
	want := map[string]string{
		"anonymous|search_papers": "2",
		"anonymous|get_top_items": "1",
		"member|search_papers":    "2",
		"member|__unknown__":      "1",
	}
	fields, _ := mr.HKeys(calls)
	if len(fields) != len(want) {
		t.Fatalf("calls fields = %v, want %v", fields, want)
	}
	for field, count := range want {
		if got := mr.HGet(calls, field); got != count {
			t.Errorf("calls[%s] = %q, want %s", field, got, count)
		}
	}
	// 匿名按 IP 去重（两个 IP），登录按用户去重（同一会员换 IP 仍是 1）。
	for audience, want := range map[string]int64{AudienceAnonymous: 2, AudienceFree: 0, AudienceMember: 2} {
		if got := pfcount(t, client, "mcpusage:"+fixedDay+":clients:"+audience); got != want {
			t.Errorf("clients:%s = %d, want %d", audience, got, want)
		}
	}
	if got, _ := mr.Get("mcpusage:since"); got != fixedDay {
		t.Errorf("since = %q", got)
	}
}

func TestRecordOtherMethodsOnlyCountDistinctClients(t *testing.T) {
	recorder, mr, client := newTestRecorder(t)
	recorder.Record(context.Background(), Event{Identity: freeUser, Method: "tools/list"})
	recorder.Record(context.Background(), Event{Identity: freeUser, Method: "notifications/initialized"})
	if got := pfcount(t, client, "mcpusage:"+fixedDay+":clients:member"); got != 1 {
		t.Errorf("clients:member = %d", got)
	}
	for _, suffix := range []string{"calls", "limited", "client_names"} {
		if mr.Exists("mcpusage:" + fixedDay + ":" + suffix) {
			t.Errorf("%s must not be written by non-counted methods", suffix)
		}
	}
}

func TestRecordSkipsAdminAndBenchmark(t *testing.T) {
	recorder, mr, _ := newTestRecorder(t)
	ctx := context.Background()
	recorder.Record(ctx, Event{Identity: admin, Method: "tools/call", Tool: "search_papers"})
	recorder.Record(ctx, Event{Identity: admin, Method: "initialize", ClientName: "Claude Code"})
	recorder.Record(ctx, Event{Identity: admin, Method: "tools/call", Limited: LimitBurst})
	recorder.Record(ctx, Event{Identity: freeUser, UserAgent: "mcp-latency-bench/1.0", Method: "tools/call", Tool: "search_papers"})
	recorder.Record(ctx, Event{Identity: anonymous, UserAgent: "  mcp-latency-bench/2", Method: "tools/call", Limited: LimitDaily})
	if keys := mr.Keys(); len(keys) != 0 {
		t.Fatalf("admin/bench traffic wrote keys: %v", keys)
	}
}

func TestRecordLimitedByKindAndNotAsCall(t *testing.T) {
	recorder, mr, client := newTestRecorder(t)
	ctx := context.Background()
	recorder.Record(ctx, Event{Identity: anonymous, ClientIP: "198.51.100.1", Method: "tools/call", Tool: "search_papers", Limited: LimitDaily})
	recorder.Record(ctx, Event{Identity: anonymous, ClientIP: "198.51.100.1", Method: "ping", Limited: LimitBurst})
	recorder.Record(ctx, Event{Identity: freeUser, Method: "tools/call", Tool: "search_papers", Limited: LimitMonthly})
	recorder.Record(ctx, Event{Identity: member, Method: "tools/call", Tool: "search_papers", Limited: LimitDaily})

	limited := "mcpusage:" + fixedDay + ":limited"
	for field, count := range map[string]string{
		"anonymous|daily": "1",
		"anonymous|burst": "1",
		"member|monthly":  "1",
		"member|daily":    "1",
	} {
		if got := mr.HGet(limited, field); got != count {
			t.Errorf("limited[%s] = %q, want %s", field, got, count)
		}
	}
	if mr.Exists("mcpusage:" + fixedDay + ":calls") {
		t.Error("limited tools/call must not count as a call")
	}
	// 被限流的客户端仍算当天来过。
	if got := pfcount(t, client, "mcpusage:"+fixedDay+":clients:anonymous"); got != 1 {
		t.Errorf("clients:anonymous = %d", got)
	}
}

func TestRecordClientNamesWithDistinctClients(t *testing.T) {
	recorder, mr, client := newTestRecorder(t)
	ctx := context.Background()
	recorder.Record(ctx, Event{Identity: freeUser, Method: "initialize", ClientName: "Claude Code"})
	recorder.Record(ctx, Event{Identity: freeUser, Method: "initialize", ClientName: "claude code"})
	recorder.Record(ctx, Event{Identity: member, Method: "initialize", ClientName: "Claude Code"})
	recorder.Record(ctx, Event{Identity: anonymous, ClientIP: "198.51.100.1", Method: "initialize"})

	names := "mcpusage:" + fixedDay + ":client_names"
	for field, count := range map[string]string{
		"member|claude code":    "3",
		"anonymous|__unknown__": "1",
	} {
		if got := mr.HGet(names, field); got != count {
			t.Errorf("client_names[%s] = %q, want %s", field, got, count)
		}
	}
	// 三次连接来自两个账号，统一账号档位下仍按用户去重。
	if got := pfcount(t, client, "mcpusage:"+fixedDay+":name_clients:member|claude code"); got != 2 {
		t.Errorf("name_clients member|claude code = %d", got)
	}
}

func TestClientNameCapFoldsNewNamesIntoOther(t *testing.T) {
	recorder, mr, client := newTestRecorder(t)
	ctx := context.Background()
	for i := 0; i < MaxClientNames; i++ {
		recorder.Record(ctx, Event{Identity: freeUser, Method: "initialize", ClientName: fmt.Sprintf("client-%02d", i)})
	}
	recorder.Record(ctx, Event{Identity: member, Method: "initialize", ClientName: "late-comer"})
	recorder.Record(ctx, Event{Identity: freeUser, Method: "initialize", ClientName: "another-late"})
	recorder.Record(ctx, Event{Identity: freeUser, Method: "initialize", ClientName: "client-00"})

	names := "mcpusage:" + fixedDay + ":client_names"
	if got := mr.HGet(names, "member|late-comer"); got != "" {
		t.Errorf("name past the cap must not get its own field, got %q", got)
	}
	if got := mr.HGet(names, "member|__other__"); got != "2" {
		t.Errorf("member|__other__ = %q", got)
	}

	// 上限前已有的名字照常累加。
	if got := mr.HGet(names, "member|client-00"); got != "2" {
		t.Errorf("member|client-00 = %q", got)
	}
	if fields, _ := mr.HKeys(names); len(fields) != MaxClientNames+1 {
		t.Errorf("client_names has %d fields", len(fields))
	}
	if got := pfcount(t, client, "mcpusage:"+fixedDay+":name_clients:member|__other__"); got != 2 {
		t.Errorf("name_clients member|__other__ = %d", got)
	}
	if mr.Exists("mcpusage:" + fixedDay + ":name_clients:member|late-comer") {
		t.Error("overflowed name must not get its own HLL key")
	}
}

func TestAnonymousClientsNeverSendRawIP(t *testing.T) {
	recorder, mr, _ := newTestRecorder(t)
	ip := "203.0.113.77"
	recorder.Record(context.Background(), Event{Identity: anonymous, ClientIP: ip, Method: "initialize", ClientName: "cursor"})
	recorder.Record(context.Background(), Event{Identity: anonymous, ClientIP: ip, Method: "tools/call", Tool: "search_papers", Limited: LimitDaily})
	for _, key := range mr.Keys() {
		if strings.Contains(key, ip) {
			t.Errorf("key carries raw IP: %s", key)
		}
		if fields, err := mr.HKeys(key); err == nil {
			for _, field := range fields {
				if strings.Contains(field, ip) {
					t.Errorf("hash field carries raw IP: %s %s", key, field)
				}
			}
		}
	}

	memberToday := clientMember(fixedDay, anonymous, ip)
	if !regexp.MustCompile(`^a:[0-9a-f]{16}$`).MatchString(memberToday) || strings.Contains(memberToday, ip) {
		t.Fatalf("anonymous member = %q", memberToday)
	}
	if memberToday != clientMember(fixedDay, anonymous, ip) {
		t.Error("anonymous member must be stable within a day")
	}
	if memberToday == clientMember("2026-10-06", anonymous, ip) {
		t.Error("anonymous member must change across days")
	}
	if got := clientMember(fixedDay, freeUser, ip); got != "u:7" {
		t.Errorf("authenticated member = %q", got)
	}
}

func TestDayKeysExpireAfter400Days(t *testing.T) {
	recorder, mr, _ := newTestRecorder(t)
	ctx := context.Background()
	recorder.Record(ctx, Event{Identity: freeUser, Method: "initialize", ClientName: "cursor"})
	recorder.Record(ctx, Event{Identity: freeUser, Method: "tools/call", Tool: "search_papers"})
	recorder.Record(ctx, Event{Identity: freeUser, Method: "tools/call", Limited: LimitBurst})
	for _, key := range mr.Keys() {
		ttl := mr.TTL(key)
		if key == "mcpusage:since" {
			if ttl != 0 {
				t.Errorf("since must not expire, ttl=%s", ttl)
			}
			continue
		}
		if ttl != 400*24*time.Hour {
			t.Errorf("%s ttl = %s", key, ttl)
		}
	}
}

func TestSinceKeepsFirstDay(t *testing.T) {
	recorder, mr, _ := newTestRecorder(t)
	recorder.Record(context.Background(), Event{Identity: freeUser, Method: "ping"})
	recorder.now = func() time.Time { return fixedNow.Add(48 * time.Hour) }
	recorder.Record(context.Background(), Event{Identity: freeUser, Method: "ping"})
	if got, _ := mr.Get("mcpusage:since"); got != fixedDay {
		t.Errorf("since = %q, want %s", got, fixedDay)
	}
	if !mr.Exists("mcpusage:2026-10-07:clients:member") {
		t.Error("second day key missing")
	}
}

func TestRecordFailOpen(t *testing.T) {
	var unwired *Recorder
	unwired.Record(context.Background(), Event{Method: "tools/call"})
	if NewRecorder(nil) != nil {
		t.Fatal("NewRecorder(nil) must be nil")
	}

	recorder, mr, _ := newTestRecorder(t)
	mr.Close()
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // 请求已断开也照常尝试写，失败只记日志。
	start := time.Now()
	recorder.Record(ctx, Event{Identity: freeUser, Method: "tools/call", Tool: "search_papers"})
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Fatalf("Record blocked for %s", elapsed)
	}
}
