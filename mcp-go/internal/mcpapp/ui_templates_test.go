package mcpapp

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/uicatalog"
	"aigcnews/mcp-go/internal/wire"
)

func uiApp(t *testing.T) *App {
	t.Helper()
	handlers, err := NewUITemplateHandlers("https://catalog.test/")
	if err != nil {
		t.Fatal(err)
	}
	return New("aigc-radar", "test", handlers)
}

func uiRPC(t *testing.T, app *App, method string, params map[string]any) map[string]any {
	t.Helper()
	body, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 7, "method": method, "params": params})
	req := httptest.NewRequest(http.MethodPost, "/api/mcp", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	NewHandler(app, nil, nil).ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || rec.Header().Get("MCP-Protocol-Version") != wire.ProtocolVersion {
		t.Fatalf("wire response: %d %v", rec.Code, rec.Header())
	}
	var envelope map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope["id"] != float64(7) || envelope["error"] != nil {
		t.Fatalf("unexpected envelope: %v", envelope)
	}
	return envelope["result"].(map[string]any)
}

func uiCall(t *testing.T, app *App, name string, args map[string]any) map[string]any {
	t.Helper()
	return uiRPC(t, app, "tools/call", map[string]any{"name": name, "arguments": args})
}

func TestUIToolsArePublicAdditiveAndReadOnly(t *testing.T) {
	app := uiApp(t)
	result := uiRPC(t, app, "tools/list", map[string]any{})
	tools := result["tools"].([]any)
	if len(tools) != 12 {
		t.Fatalf("got %d tools", len(tools))
	}
	// Every existing public definition remains byte-identical in order.
	for i, legacy := range publicTools {
		var expected any
		_ = json.Unmarshal(jsonx.MustMarshalCompact(legacy), &expected)
		got, _ := json.Marshal(tools[i])
		want, _ := json.Marshal(expected)
		if !bytes.Equal(got, want) {
			t.Fatalf("legacy tool %d changed", i)
		}
	}
	for i, name := range []string{"search_ui_templates", "get_ui_template", "search_ui_icons", "get_ui_icon"} {
		tool := tools[len(publicTools)+i].(map[string]any)
		if tool["name"] != name {
			t.Fatalf("missing %s", name)
		}
		hints := tool["annotations"].(map[string]any)
		if hints["readOnlyHint"] != true || hints["openWorldHint"] != false || hints["destructiveHint"] != false {
			t.Fatalf("unsafe annotations: %v", hints)
		}
	}
	r := app.DispatchWithIdentity(rpc(7, "tools/list", "{}"), authn.Identity{UserID: 1}, true)
	var authenticated map[string]any
	_ = json.Unmarshal(r.Body, &authenticated)
	if len(authenticated["result"].(map[string]any)["tools"].([]any)) != 13 {
		t.Fatal("private tool authentication fork changed")
	}
	init := uiRPC(t, app, "initialize", map[string]any{})
	instructions := init["instructions"].(string)
	for _, required := range []string{
		"always call search_ui_templates, even if unasked",
		"redesigned, or restyled UI (colors, spacing, typography",
		"it overrides project discovery for visual work",
		"open the best match with get_ui_template before coding",
		"for small tweaks, only if directly reusable",
		"Skip copy-only and behavior-only fixes",
		"Icons: search_ui_icons, then get_ui_icon",
	} {
		if !strings.Contains(instructions, required) {
			t.Fatalf("missing proactive UI discovery instruction %q", required)
		}
	}
	searchTool := tools[len(publicTools)].(map[string]any)
	if !strings.Contains(searchTool["description"].(string), "existing-component changes") {
		t.Fatal("search tool description does not cover component style changes")
	}
	getTool := tools[len(publicTools)+1].(map[string]any)
	if !strings.Contains(getTool["description"].(string), "rather than stopping at the search summary") {
		t.Fatal("source tool description does not enforce the second step")
	}
}

func TestUISourceDeliveryDoesNotTruncateOrLoseFiles(t *testing.T) {
	app := uiApp(t)
	catalog, _ := uicatalog.New()
	for _, item := range catalog.Search("", "", "") {
		t.Run(item.ID, func(t *testing.T) {
			delivered := map[string]string{}
			collect := func(result map[string]any) map[string]any {
				if result["isError"] != false {
					t.Fatalf("unexpected tool failure: %v", result)
				}
				data := result["structuredContent"].(map[string]any)
				if data["truncated"] == true {
					t.Fatal("source result reached global truncation limit")
				}
				var textData any
				if err := json.Unmarshal([]byte(result["content"].([]any)[0].(map[string]any)["text"].(string)), &textData); err != nil {
					t.Fatal(err)
				}
				textJSON, _ := json.Marshal(textData)
				structuredJSON, _ := json.Marshal(data)
				if !bytes.Equal(textJSON, structuredJSON) {
					t.Fatal("text/structured content mismatch")
				}
				for _, raw := range data["files"].([]any) {
					file := raw.(map[string]any)
					if content, ok := file["content"].(string); ok {
						if next, paged := file["next_offset"]; paged {
							for next != nil {
								part := uiCall(t, app, "get_ui_template", map[string]any{"id": item.ID, "file": file["name"], "file_offset": next})["structuredContent"].(map[string]any)
								if part["truncated"] == true {
									t.Fatal("paged result truncated")
								}
								next = nil
								for _, entry := range part["files"].([]any) {
									segment := entry.(map[string]any)
									if segment["name"] == file["name"] {
										content += segment["content"].(string)
										next = segment["next_offset"]
									}
								}
							}
						}
						hash := sha256.Sum256([]byte(content))
						if hex.EncodeToString(hash[:]) != file["sha256"] {
							t.Fatal("source changed in wire encoding")
						}
						delivered[file["name"].(string)] = content
					}
				}
				return data
			}
			data := collect(uiCall(t, app, "get_ui_template", map[string]any{"id": item.ID, "language": "zh"}))
			if !strings.HasPrefix(data["preview_url"].(string), "https://catalog.test/ui-library/") || !strings.Contains(data["integration_prompt"].(string), "保留") {
				t.Fatal("missing provenance or Chinese prompt")
			}
			for _, file := range data["omitted_files"].([]any) {
				collect(uiCall(t, app, "get_ui_template", map[string]any{"id": item.ID, "file": file}))
			}
			if len(delivered) != len(item.Files) {
				t.Fatalf("delivered %d of %d files", len(delivered), len(item.Files))
			}
		})
	}
}

func TestUISearchAndErrorsThroughHTTP(t *testing.T) {
	app := uiApp(t)
	catalog, err := uicatalog.New()
	if err != nil {
		t.Fatal(err)
	}
	sample := catalog.Search("", "", "")[0]
	for _, q := range []string{sample.Name["zh"], sample.Name["en"]} {
		result := uiCall(t, app, "search_ui_templates", map[string]any{"q": q, "limit": 1})
		data := result["structuredContent"].(map[string]any)
		if data["total"] != float64(len(catalog.Search(q, "", ""))) || len(data["items"].([]any)) != 1 {
			t.Fatalf("query %q: %v", q, data)
		}
	}
	cases := []struct {
		name string
		args map[string]any
	}{
		{"search_ui_templates", map[string]any{"limit": 0}},
		{"search_ui_templates", map[string]any{"limit": 1.5}},
		{"search_ui_templates", map[string]any{"limit": "10"}},
		{"search_ui_templates", map[string]any{"q": strings.Repeat("中", 257)}},
		{"search_ui_templates", map[string]any{"q": nil}},
		{"search_ui_templates", map[string]any{"framework": "svelte"}},
		{"search_ui_templates", map[string]any{"language": "fr"}},
		{"search_ui_templates", map[string]any{"remote_url": "http://localhost"}},
		{"get_ui_template", map[string]any{"id": "../../.env"}},
		{"get_ui_template", map[string]any{"id": sample.ID, "file": "../../.env"}},
		{"get_ui_template", map[string]any{"id": sample.ID, "include_source": "true"}},
	}
	for _, tc := range cases {
		result := uiCall(t, app, tc.name, tc.args)
		if result["isError"] != true || result["structuredContent"] != nil {
			t.Fatalf("invalid input accepted: %v", tc.args)
		}
	}
	result := uiCall(t, app, "get_ui_template", map[string]any{"id": sample.ID, "include_source": false})
	data := result["structuredContent"].(map[string]any)
	for _, raw := range data["files"].([]any) {
		if _, found := raw.(map[string]any)["content"]; found {
			t.Fatal("metadata-only request returned source")
		}
	}
}

func TestUISearchAutomaticallyRelaxesLongFrontendBrief(t *testing.T) {
	app := uiApp(t)
	result := uiCall(t, app, "search_ui_templates", map[string]any{
		"q":        "深色 科技感 AI dashboard 趋势图 指标卡",
		"category": "dashboard",
		"language": "zh",
		"limit":    8,
	})
	data := result["structuredContent"].(map[string]any)
	if data["search_mode"] != "relaxed_terms" || data["total"].(float64) < 1 {
		t.Fatalf("natural-language fallback did not run: %v", data)
	}
	if !strings.Contains(data["next_step"].(string), "do not stop at this search summary") ||
		!strings.Contains(data["next_step"].(string), "narrow style adjustment") {
		t.Fatalf("search result does not explain source-fetch policy: %v", data["next_step"])
	}
}
