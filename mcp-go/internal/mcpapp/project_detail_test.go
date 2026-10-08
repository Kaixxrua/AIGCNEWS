package mcpapp

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/metrics"
	"aigcnews/mcp-go/internal/ratelimit"
	"aigcnews/mcp-go/internal/usage"
	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

type projectDetailStub struct {
	row   GitHubProjectDetail
	err   error
	calls int
	name  string
}

func (s *projectDetailStub) GetProjectDetail(name string) (GitHubProjectDetail, error) {
	s.calls++
	s.name = name
	return s.row, s.err
}

func projectDetailTestApp(markdown string) (*App, *projectDetailStub) {
	reader := &projectDetailStub{row: GitHubProjectDetail{
		Project: map[string]any{"full_name": "owner/repo", "url": "https://github.com/owner/repo", "stars": 900, "license_spdx_id": "MIT", "result_origin": "github_api"},
		Readme:  markdown, ReadmeSHA: "v1", ReadmeStatus: "available",
		ReadmeURL: "https://github.com/owner/repo/blob/main/README.md",
		FetchedAt: time.Date(2026, 10, 8, 1, 0, 0, 0, time.UTC),
	}}
	service := NewGitHubProjectDetailService(reader, "")
	return New("aigc-radar", "test", Handlers{"get_github_project_detail": service.Get}), reader
}

func TestProjectDetailCatalogIsOptionalPublicAndAdditive(t *testing.T) {
	app, _ := projectDetailTestApp("")
	for _, withUI := range []bool{false, true} {
		if withUI {
			handlers, err := NewUITemplateHandlers("")
			if err != nil {
				t.Fatal(err)
			}
			for name, handler := range handlers {
				app.tools.(Handlers)[name] = handler
			}
		}
		for _, authenticated := range []bool{false, true} {
			listed := app.toolsList(authenticated)[0].Value.([]any)
			want := len(publicTools) + 1
			if withUI {
				want += 4
			}
			if authenticated {
				want += len(privateTools)
			}
			if len(listed) != want {
				t.Fatalf("tools/list length %d, want %d", len(listed), want)
			}
			for i, legacy := range publicTools {
				if string(jsonx.MustMarshalCompact(listed[i])) != string(jsonx.MustMarshalCompact(legacy)) {
					t.Fatalf("existing tool %d changed", i)
				}
			}
			newIndex := len(publicTools)
			if withUI {
				newIndex += 4
			}
			tool := listed[newIndex].(jsonx.Object)
			if objectValue(tool, "name") != "get_github_project_detail" {
				t.Fatal("detail tool missing")
			}
			description := objectValue(tool, "description").(string)
			if !strings.Contains(description, "It is optional") || !strings.Contains(description, "no prior search is required") || utf16Len(description) > claudeCodeTextBudget {
				t.Fatal("detail guidance must remain optional and within client budget")
			}
			annotations := objectValue(tool, "annotations").(jsonx.Object)
			if objectValue(annotations, "readOnlyHint") != true || objectValue(annotations, "openWorldHint") != true || objectValue(annotations, "destructiveHint") != false {
				t.Fatal("incorrect annotations")
			}
		}
	}
	if strings.Contains(string(jsonx.MustMarshalCompact(New("aigc-radar", "test", nil).toolsList(false))), "get_github_project_detail") {
		t.Fatal("advertised an unregistered handler")
	}
}

func TestProjectDetailHTTPMarkdownAndProvenance(t *testing.T) {
	markdown := "# 安装 🐈\n```sh\npip install example\n```\n[Docs](https://example.com)"
	app, reader := projectDetailTestApp(markdown)
	result := uiCall(t, app, "get_github_project_detail", map[string]any{"full_name": " owner/repo "})
	if result["isError"] != false || reader.name != "owner/repo" {
		t.Fatalf("tool failed: %v", result)
	}
	data := result["structuredContent"].(map[string]any)
	readme := data["readme"].(map[string]any)
	if readme["content"] != markdown || readme["format"] != "markdown" || readme["truncated"] != false || readme["next_offset"] != nil || readme["sha"] != "v1" {
		t.Fatalf("README lost content: %v", readme)
	}
	if readme["source_url"] != reader.row.ReadmeURL || data["fetched_at"] != "2026-10-08T01:00:00Z" || data["result_origin"] != "github_api" {
		t.Fatalf("missing provenance: %v", data)
	}
	item := data["item"].(map[string]any)
	if item["stars"] != float64(900) || item["license"] != "MIT" || item["data_source"] != "aigcnews.cn" {
		t.Fatalf("missing project metadata: %v", item)
	}
	var textData any
	if err := json.Unmarshal([]byte(result["content"].([]any)[0].(map[string]any)["text"].(string)), &textData); err != nil || !reflect.DeepEqual(data, textData) {
		t.Fatal("text and structuredContent differ")
	}
}

func TestProjectDetailPaginationPreservesUnicodeAndEscapes(t *testing.T) {
	for _, markdown := range []string{strings.Repeat("中文🐈\n", 18000), strings.Repeat("\x00\"\\\n", 18000)} {
		app, _ := projectDetailTestApp(markdown)
		var reconstructed strings.Builder
		var offset any = 0
		for calls := 0; ; calls++ {
			if calls > 10 {
				t.Fatal("pagination did not terminate")
			}
			result := uiCall(t, app, "get_github_project_detail", map[string]any{"full_name": "owner/repo", "readme_offset": offset, "max_chars": 40000, "readme_sha": "v1"})
			if result["isError"] != false {
				t.Fatalf("page failed: %v", result)
			}
			data := result["structuredContent"].(map[string]any)
			if data["truncated"] == true {
				t.Fatal("global truncation discarded detail structure")
			}
			page := data["readme"].(map[string]any)
			reconstructed.WriteString(page["content"].(string))
			offset = page["next_offset"]
			if offset == nil {
				break
			}
			if page["truncated"] != true || offset.(float64) <= page["offset"].(float64) {
				t.Fatal("invalid pagination cursor")
			}
		}
		if reconstructed.String() != markdown {
			t.Fatal("pagination lost or reordered README content")
		}
	}
}

func TestProjectDetailValidationAndFailureContract(t *testing.T) {
	for _, args := range []map[string]any{
		{}, {"full_name": nil}, {"full_name": 7}, {"full_name": "a/../b"}, {"full_name": "https://github.com/a/b"},
		{"full_name": "owner/repo", "url": "https://evil.example"}, {"full_name": "owner/repo", "readme_offset": -1},
		{"full_name": "owner/repo", "readme_offset": 1.5}, {"full_name": "owner/repo", "readme_offset": true},
		{"full_name": "owner/repo", "readme_offset": "1"}, {"full_name": "owner/repo", "readme_offset": 1048577},
		{"full_name": "owner/repo", "max_chars": 0}, {"full_name": "owner/repo", "max_chars": 40001},
		{"full_name": "owner/repo", "readme_sha": strings.Repeat("x", 65)},
	} {
		app, reader := projectDetailTestApp("text")
		result := uiCall(t, app, "get_github_project_detail", args)
		if result["isError"] != true || result["structuredContent"] != nil || reader.calls != 0 {
			t.Fatalf("invalid input reached upstream: %v => %v", args, result)
		}
	}
	app, reader := projectDetailTestApp("text")
	for _, args := range []map[string]any{{"full_name": "owner/repo", "readme_offset": 5}, {"full_name": "owner/repo", "readme_sha": "changed"}} {
		if result := uiCall(t, app, "get_github_project_detail", args); result["isError"] != true {
			t.Fatalf("invalid page accepted: %v", result)
		}
	}
	reader.err = errors.New("internal secret-token and database URL")
	result := uiCall(t, app, "get_github_project_detail", map[string]any{"full_name": "owner/repo"})
	if result["isError"] != true || strings.Contains(string(jsonx.MustMarshalCompact(result)), "secret-token") || !strings.Contains(string(jsonx.MustMarshalCompact(result)), "Tool execution failed.") {
		t.Fatalf("internal error leaked: %v", result)
	}
	reader.err = nil
	reader.row.Readme, reader.row.ReadmeStatus, reader.row.ReadmeSHA = "", "not_found", ""
	result = uiCall(t, app, "get_github_project_detail", map[string]any{"full_name": "owner/repo"})
	if result["isError"] != false || result["structuredContent"].(map[string]any)["readme"].(map[string]any)["status"] != "not_found" {
		t.Fatalf("missing README lost metadata: %v", result)
	}
}

func TestProjectDetailUsesExistingQuotaAndUsageCounters(t *testing.T) {
	app, reader := projectDetailTestApp("cached text")
	reader.row.CacheHit = true
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	app.SetMetrics(metrics.NewRecorder(client), map[string]struct{}{"get_github_project_detail": {}})
	auth := &stubAuthenticator{identity: authn.Identity{UserID: 42, Role: "user", MembershipTier: authn.TierFree}, authenticated: true}
	limiter := ratelimit.NewLimiter(&countingRedis{}, "", func(l *ratelimit.Limits) { l.AuthenticatedToolCallPerMinute = 1 })
	handler := NewHandler(app, auth, limiter)
	handler.SetUsage(usage.NewRecorder(client))
	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_github_project_detail","arguments":{"full_name":"owner/repo"}}}`
	if response := postFrom(t, handler, body, "", ""); response.Code != 200 {
		t.Fatalf("first call failed: %s", response.Body)
	}
	if response := postFrom(t, handler, body, "", ""); response.Code != 429 {
		t.Fatal("detail bypassed existing quota")
	}
	if reader.calls != 1 || mr.HGet("mcpmetrics:tool_calls", "get_github_project_detail") != "1" || mr.HGet(usageKey(t, mr, "calls"), "free|get_github_project_detail") != "1" {
		t.Fatal("detail was not counted under its own name")
	}
}
