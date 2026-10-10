package mcpapp

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
)

type trackingReaderStub struct {
	snapshot TrackingSnapshot
	err      error
	calls    int
	userID   int
	since    string
}

func (r *trackingReaderStub) ReadTracking(userID int, since string) (TrackingSnapshot, error) {
	r.calls++
	r.userID = userID
	r.since = since
	return r.snapshot, r.err
}

// trackingNow 是 2026-10-05 23:30 UTC = 2026-10-06 07:30 UTC+8：UTC 日期与
// 期号日期不同，钉住 since 按 UTC+8 计算。
var trackingNow = time.Date(2026, 10, 5, 23, 30, 0, 0, time.UTC)

func trackingMember() authn.Identity {
	return authn.Identity{UserID: 7, MembershipTier: authn.TierMember, Scopes: []string{TrackingReadScope}}
}

func newTrackingTestService(reader TrackingReader) *TrackingService {
	service := NewTrackingService(reader, "https://aigcnews.cn")
	service.now = func() time.Time { return trackingNow }
	return service
}

func trackingFixture() TrackingSnapshot {
	return TrackingSnapshot{
		Rules: []TrackingRule{
			{ID: 3, Kind: "keyword", Query: "Agent", Source: "all", Excludes: []string{"crypto"}, StarThreshold: 50, Enabled: true},
			{ID: 5, Kind: "project", Query: "vllm-project/vllm", Source: "github", Excludes: []string{}, StarThreshold: 200, Enabled: true},
		},
		Enabled:      true,
		DeliveryHour: 8,
		Issues: []TrackingIssue{
			{IssueDate: "2026-10-06", Items: []TrackingItem{
				{ObservedAt: "2026-10-05T22:00:00+00:00", Title: "Agent SDK 1.0", URL: "https://example.com/a", Summary: "s1", Source: "news", MatchedRules: []string{"Agent"}},
				{ObservedAt: "2026-10-05T21:00:00+00:00", Title: "vllm 0.9", URL: "https://github.com/vllm-project/vllm", Summary: "s2", Source: "github", MatchedRules: []string{"vllm-project/vllm", "Agent"}},
			}},
			{IssueDate: "2026-10-04", Truncated: true, Items: []TrackingItem{
				{ObservedAt: "2026-10-04T01:00:00+00:00", Title: "Older agent post", URL: "https://example.com/b", Summary: "s3", Source: "x", MatchedRules: []string{"Agent"}},
			}},
		},
	}
}

func trackingResult(t *testing.T, value any) map[string]any {
	t.Helper()
	var decoded map[string]any
	if err := json.Unmarshal(jsonx.MustMarshalCompact(value), &decoded); err != nil {
		t.Fatal(err)
	}
	return decoded
}

func TestTrackingGatesRunBeforeAnyRead(t *testing.T) {
	expired := trackingNow.Add(-time.Minute)
	cases := []struct {
		name     string
		identity authn.Identity
		args     map[string]any
		want     string
	}{
		{
			name:     "anonymous-before-validation",
			identity: authn.Identity{},
			args:     map[string]any{"days": "bad"},
			want:     "Authentication is required for this tool.",
		},
		{
			name:     "validation-before-scope",
			identity: authn.Identity{UserID: 7, MembershipTier: authn.TierMember},
			args:     map[string]any{"days": float64(0)},
			want:     "days: Input should be greater than or equal to 1",
		},
		{
			name:     "missing-scope",
			identity: authn.Identity{UserID: 7, MembershipTier: authn.TierMember, Scopes: []string{"projects:favorites:read"}},
			args:     map[string]any{},
			want:     "This token requires the tracking:read scope. Create a new token at https://aigcnews.cn/mcp.",
		},
		{
			name:     "free-account",
			identity: authn.Identity{UserID: 7, MembershipTier: authn.TierFree, Scopes: []string{TrackingReadScope}},
			args:     map[string]any{},
			want: "get_my_tracking is a vip membership benefit. Tracking results stay available on the website at " +
				"https://aigcnews.cn/subscriptions; upgrade at https://aigcnews.cn/membership.",
		},
		{
			name:     "lapsed-member",
			identity: authn.Identity{UserID: 7, MembershipTier: authn.TierMember, MembershipExpiresAt: &expired, Scopes: []string{TrackingReadScope}},
			args:     map[string]any{},
			want: "get_my_tracking is a vip membership benefit. Tracking results stay available on the website at " +
				"https://aigcnews.cn/subscriptions; upgrade at https://aigcnews.cn/membership.",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			reader := &trackingReaderStub{snapshot: trackingFixture()}
			_, err := newTrackingTestService(reader).Get(tc.identity, tc.args)
			var inputErr ToolInputError
			if !errors.As(err, &inputErr) || inputErr.Message != tc.want {
				t.Fatalf("error=%v, want %q", err, tc.want)
			}
			if reader.calls != 0 {
				t.Fatalf("gate failure read tracking %d times", reader.calls)
			}
		})
	}
}

func TestTrackingMemberWithFutureExpiryReadsOwnRows(t *testing.T) {
	expires := trackingNow.Add(time.Hour)
	identity := trackingMember()
	identity.MembershipExpiresAt = &expires
	reader := &trackingReaderStub{snapshot: trackingFixture()}
	value, err := newTrackingTestService(reader).Get(identity, map[string]any{})
	if err != nil {
		t.Fatal(err)
	}
	if reader.calls != 1 || reader.userID != 7 {
		t.Fatalf("reader state=%+v", reader)
	}
	// 默认 7 期：UTC+8 的 10-06 往回 6 天。
	if reader.since != "2026-09-30" {
		t.Fatalf("since=%q", reader.since)
	}
	result := trackingResult(t, value)
	if result["since"] != "2026-09-30" || result["total"] != float64(3) {
		t.Fatalf("result=%v", result)
	}
}

func TestTrackingSinceCountsDaysInUTC8(t *testing.T) {
	for days, want := range map[int]string{1: "2026-10-06", 2: "2026-10-05", 30: "2026-09-07"} {
		reader := &trackingReaderStub{snapshot: trackingFixture()}
		if _, err := newTrackingTestService(reader).Get(trackingMember(), map[string]any{"days": float64(days)}); err != nil {
			t.Fatal(err)
		}
		if reader.since != want {
			t.Fatalf("days=%d since=%q want %q", days, reader.since, want)
		}
	}
}

func TestTrackingProjectionShapeAndOrder(t *testing.T) {
	reader := &trackingReaderStub{snapshot: trackingFixture()}
	value, err := newTrackingTestService(reader).Get(trackingMember(), map[string]any{})
	if err != nil {
		t.Fatal(err)
	}
	body := string(jsonx.MustMarshalCompact(value))
	for _, key := range []string{`{"rules":`, `,"schedule":`, `,"since":`, `,"items":`, `,"total":`, `,"hint":`, `,"manage_url":`, `,"attribution":`} {
		if !strings.Contains(body, key) {
			t.Fatalf("missing %s in %s", key, body)
		}
	}
	wantRules := `[{"id":3,"kind":"keyword","query":"Agent","source":"all","excludes":["crypto"],"enabled":true},` +
		`{"id":5,"kind":"project","query":"vllm-project/vllm","source":"github","excludes":[],"star_threshold":200,"enabled":true}]`
	if !strings.Contains(body, `"rules":`+wantRules) {
		t.Fatalf("rules projection drifted: %s", body)
	}
	result := trackingResult(t, value)
	items := result["items"].([]any)
	var titles []string
	for _, raw := range items {
		item := raw.(map[string]any)
		titles = append(titles, item["issue_date"].(string)+" "+item["title"].(string))
	}
	want := []string{"2026-10-06 Agent SDK 1.0", "2026-10-06 vllm 0.9", "2026-10-04 Older agent post"}
	if strings.Join(titles, "|") != strings.Join(want, "|") {
		t.Fatalf("items order=%v", titles)
	}
	first := items[0].(map[string]any)
	if first["url"] != "https://example.com/a" || first["source"] != "news" || first["observed_at"] != "2026-10-05T22:00:00+00:00" {
		t.Fatalf("item fields=%v", first)
	}
	if result["schedule"] != "daily at 08:00 UTC+8" || result["manage_url"] != "https://aigcnews.cn/subscriptions" ||
		result["attribution"] != "Data provided by AIGC Radar · https://aigcnews.cn" {
		t.Fatalf("result=%v", result)
	}
	// 2026-10-04 期被截断且有条目列出 → 提示截断。
	if hint, _ := result["hint"].(string); !strings.Contains(hint, "50-item limit") {
		t.Fatalf("hint=%v", result["hint"])
	}
}

func TestTrackingRuleFilterIsCaseInsensitive(t *testing.T) {
	reader := &trackingReaderStub{snapshot: trackingFixture()}
	value, err := newTrackingTestService(reader).Get(trackingMember(), map[string]any{"rule": "  VLLM-project/VLLM "})
	if err != nil {
		t.Fatal(err)
	}
	result := trackingResult(t, value)
	items := result["items"].([]any)
	if len(items) != 1 || items[0].(map[string]any)["title"] != "vllm 0.9" || result["total"] != float64(1) {
		t.Fatalf("filtered=%v", result)
	}
	// 截断的 10-04 期没有该规则的条目，不提示截断。
	if result["hint"] != nil {
		t.Fatalf("hint=%v", result["hint"])
	}
}

func TestTrackingUnknownRuleListsQueries(t *testing.T) {
	reader := &trackingReaderStub{snapshot: trackingFixture()}
	_, err := newTrackingTestService(reader).Get(trackingMember(), map[string]any{"rule": "diffusion"})
	want := `rule: Use the query of one of your tracking rules: "Agent", "vllm-project/vllm".`
	if err == nil || err.Error() != want {
		t.Fatalf("error=%v", err)
	}
	reader = &trackingReaderStub{snapshot: TrackingSnapshot{Enabled: true, DeliveryHour: 8}}
	_, err = newTrackingTestService(reader).Get(trackingMember(), map[string]any{"rule": "diffusion"})
	if err == nil || err.Error() != "rule: You have no tracking rules yet; omit rule." {
		t.Fatalf("error=%v", err)
	}
}

func TestTrackingLimitCapsItemsButNotTotal(t *testing.T) {
	reader := &trackingReaderStub{snapshot: trackingFixture()}
	value, err := newTrackingTestService(reader).Get(trackingMember(), map[string]any{"limit": float64(1)})
	if err != nil {
		t.Fatal(err)
	}
	result := trackingResult(t, value)
	if len(result["items"].([]any)) != 1 || result["total"] != float64(3) {
		t.Fatalf("result=%v", result)
	}
}

func TestTrackingHints(t *testing.T) {
	base := trackingFixture()
	cases := []struct {
		name   string
		mutate func(*TrackingSnapshot)
		args   map[string]any
		want   string
	}{
		{"no-rules", func(s *TrackingSnapshot) { s.Rules = nil; s.Issues = nil }, nil, "No tracking rules yet."},
		{"paused", func(s *TrackingSnapshot) { s.Enabled = false }, nil, "Tracking is paused"},
		{"all-rules-disabled", func(s *TrackingSnapshot) {
			rules := append([]TrackingRule(nil), s.Rules...)
			for i := range rules {
				rules[i].Enabled = false
			}
			s.Rules = rules
		}, nil, "All tracking rules are disabled"},
		{"no-matches", func(s *TrackingSnapshot) { s.Issues = nil; s.DeliveryHour = 21 }, map[string]any{"days": float64(1)},
			"No matches in issues since today. A new issue is compiled daily at 21:00 UTC+8"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			snapshot := base
			tc.mutate(&snapshot)
			args := tc.args
			if args == nil {
				args = map[string]any{}
			}
			value, err := newTrackingTestService(&trackingReaderStub{snapshot: snapshot}).Get(trackingMember(), args)
			if err != nil {
				t.Fatal(err)
			}
			hint, _ := trackingResult(t, value)["hint"].(string)
			if !strings.HasPrefix(hint, tc.want) {
				t.Fatalf("hint=%q want prefix %q", hint, tc.want)
			}
		})
	}
	value, err := newTrackingTestService(&trackingReaderStub{snapshot: TrackingSnapshot{Enabled: false, DeliveryHour: 8,
		Rules: base.Rules}}).Get(trackingMember(), map[string]any{})
	if err != nil {
		t.Fatal(err)
	}
	if trackingResult(t, value)["schedule"] != "paused" {
		t.Fatal("paused schedule label drifted")
	}
}

func TestTrackingArgumentValidation(t *testing.T) {
	cases := []struct {
		args map[string]any
		want string
	}{
		{map[string]any{"days": 1.5}, "days: Input should be a valid integer"},
		{map[string]any{"days": "7"}, "days: Input should be a valid integer"},
		{map[string]any{"days": float64(31)}, "days: Input should be less than or equal to 30"},
		{map[string]any{"limit": float64(0)}, "limit: Input should be greater than or equal to 1"},
		{map[string]any{"limit": float64(51)}, "limit: Input should be less than or equal to 50"},
		{map[string]any{"rule": 3.0}, "rule: Input should be a valid string"},
		{map[string]any{"rule": strings.Repeat("长", 121)}, "rule: String should have at most 120 characters"},
		{
			map[string]any{"zeta": true, "days": float64(0), "alpha": 1.0, "limit": true},
			"days: Input should be greater than or equal to 1; limit: Input should be a valid integer; " +
				"alpha: Extra inputs are not permitted; zeta: Extra inputs are not permitted",
		},
	}
	for _, tc := range cases {
		reader := &trackingReaderStub{snapshot: trackingFixture()}
		_, err := newTrackingTestService(reader).Get(trackingMember(), tc.args)
		if err == nil || err.Error() != tc.want {
			t.Fatalf("args=%v error=%v want %q", tc.args, err, tc.want)
		}
		if reader.calls != 0 {
			t.Fatalf("invalid args read tracking")
		}
	}
}

func TestTrackingReaderErrorIsNotAnInputError(t *testing.T) {
	reader := &trackingReaderStub{err: errors.New("db down")}
	_, err := newTrackingTestService(reader).Get(trackingMember(), map[string]any{})
	var inputErr ToolInputError
	if err == nil || errors.As(err, &inputErr) {
		t.Fatalf("storage failure must surface as a generic tool failure, got %v", err)
	}
}

func TestTrackingToolIsListedOnlyForAuthenticatedSessions(t *testing.T) {
	for _, authenticated := range []bool{false, true} {
		body := string(jsonx.MustMarshalCompact(ToolsList(authenticated)))
		if strings.Contains(body, `"name":"get_my_tracking"`) != authenticated {
			t.Fatalf("authenticated=%v listing=%v", authenticated, !authenticated)
		}
	}
	var listed struct {
		Tools []struct {
			Name        string         `json:"name"`
			Annotations map[string]any `json:"annotations"`
		} `json:"tools"`
	}
	if err := json.Unmarshal(jsonx.MustMarshalCompact(ToolsList(true)), &listed); err != nil {
		t.Fatal(err)
	}
	// get_my_tracking 之后紧跟 get_my_quota（见 quota.go）。
	tracking := listed.Tools[len(listed.Tools)-2]
	if tracking.Name != "get_my_tracking" || tracking.Annotations["readOnlyHint"] != true || tracking.Annotations["destructiveHint"] != false {
		t.Fatalf("tracking tool listing=%+v", tracking)
	}
}

// 线上形状（Red：MCP wire）：门禁错误是 isError 的 {"error": ...} 文本，
// 成功结果带 structuredContent；免费账号不被当作调用失败。
func TestTrackingToolCallWireShape(t *testing.T) {
	app := newApp()
	reader := &trackingReaderStub{snapshot: trackingFixture()}
	app.RegisterIdentityTool("get_my_tracking", newTrackingTestService(reader).Get)

	r := app.DispatchWithIdentity(rpc(1, "tools/call", `{"name":"get_my_tracking","arguments":{}}`), authn.Identity{}, false)
	want := `{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"error\": \"Authentication is required for this tool.\"}"}],"isError":true}}`
	if string(r.Body) != want {
		t.Fatalf("anonymous:\n got %s\nwant %s", r.Body, want)
	}

	free := authn.Identity{UserID: 7, MembershipTier: authn.TierFree, Scopes: []string{TrackingReadScope}}
	r = app.DispatchWithIdentity(rpc(2, "tools/call", `{"name":"get_my_tracking","arguments":{}}`), free, true)
	if !strings.Contains(string(r.Body), `get_my_tracking is a vip membership benefit.`) || !strings.Contains(string(r.Body), `"isError":true`) {
		t.Fatalf("free account: %s", r.Body)
	}

	r = app.DispatchWithIdentity(rpc(3, "tools/call", `{"name":"get_my_tracking","arguments":{"limit":2}}`), trackingMember(), true)
	body := string(r.Body)
	if !strings.Contains(body, `"isError":false`) || !strings.Contains(body, `"structuredContent":{"rules":[`) ||
		!strings.Contains(body, `"total":3`) {
		t.Fatalf("member call: %s", body)
	}
	if reader.calls != 1 || reader.userID != 7 {
		t.Fatalf("reader state=%+v", reader)
	}
}
