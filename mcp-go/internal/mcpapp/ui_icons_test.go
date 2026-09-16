package mcpapp

import (
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/uicatalog"
)

func iconResult(t *testing.T, app *App, name string, args map[string]any) map[string]any {
	t.Helper()
	result := uiCall(t, app, name, args)
	if result["isError"] != false {
		t.Fatalf("unexpected tool failure: %v", result)
	}
	payload, ok := result["structuredContent"].(map[string]any)
	if !ok {
		t.Fatalf("missing structured content: %v", result)
	}
	return payload
}

// These tests run against both the production catalog and the tiny CI
// fixture, so expectations derive from the embedded icon data itself.
func firstIconID(t *testing.T) string {
	t.Helper()
	catalog, err := uicatalog.LoadIcons()
	if err != nil {
		t.Fatal(err)
	}
	set := catalog.Sets()[0]
	icon, _, ok := catalog.Get(catalog.SearchIcons("", set.ProviderID, "", "")[0].ID)
	if !ok {
		t.Fatal("no embedded icons")
	}
	return icon.ID
}

func TestUIIconSearchReturnsLicensedSets(t *testing.T) {
	app := uiApp(t)
	probe := firstIconID(t)
	name := strings.SplitN(probe, ":", 2)[1]
	payload := iconResult(t, app, "search_ui_icons", map[string]any{"q": name, "limit": float64(3)})
	items := payload["items"].([]any)
	if len(items) == 0 || len(items) > 3 {
		t.Fatalf("unexpected items: %v", items)
	}
	found := false
	for _, raw := range items {
		item := raw.(map[string]any)
		if item["id"] == probe {
			found = true
			if !strings.Contains(item["svg_url"].(string), "/ui-library/sources/") || item["sha256"] == "" {
				t.Fatalf("incomplete summary: %v", item)
			}
		}
	}
	if !found {
		t.Fatalf("search missed %s", probe)
	}
	catalog, _ := uicatalog.LoadIcons()
	sets := payload["sets"].([]any)
	if len(sets) != len(catalog.Sets()) {
		t.Fatalf("sets: %v", sets)
	}
	for _, raw := range sets {
		set := raw.(map[string]any)
		if set["license"] == "" || set["revision"] == "" || set["repository"] == "" {
			t.Fatalf("incomplete set summary: %v", set)
		}
	}
	if payload["total"].(float64) < 1 {
		t.Fatalf("total: %v", payload["total"])
	}
}

func TestUIIconSearchFiltersAndErrors(t *testing.T) {
	app := uiApp(t)
	probe := firstIconID(t)
	provider := strings.SplitN(probe, ":", 2)[0]
	payload := iconResult(t, app, "search_ui_icons", map[string]any{"q": "", "set": provider})
	if len(payload["items"].([]any)) == 0 {
		t.Fatal("provider browse empty")
	}
	for _, raw := range payload["items"].([]any) {
		item := raw.(map[string]any)
		if !strings.HasPrefix(item["id"].(string), provider+":") {
			t.Fatalf("provider filter leaked: %v", item["id"])
		}
	}
	for _, args := range []map[string]any{
		{"set": "not-a-set"},
		{"style": float64(3)},
		{"limit": float64(0)},
		{"limit": float64(61)},
		{"bogus": "x"},
	} {
		result := uiCall(t, app, "search_ui_icons", args)
		if result["isError"] != true {
			t.Fatalf("expected input error for %v", args)
		}
	}
}

func TestUIIconGetReturnsVerbatimSVGAndLicense(t *testing.T) {
	app := uiApp(t)
	probe := firstIconID(t)
	payload := iconResult(t, app, "get_ui_icon", map[string]any{"id": probe})
	if payload["svg"] == nil || !strings.Contains(payload["svg"].(string), "<svg") {
		t.Fatalf("missing svg source: %v", payload)
	}
	notices := payload["license_notices"].(map[string]any)
	if notices["LICENSE"] == "" {
		t.Fatalf("missing license notice: %v", notices)
	}
	for _, key := range []string{"revision", "rights_evidence_url", "integration_prompt", "sha256"} {
		if payload[key] == nil || payload[key] == "" {
			t.Fatalf("missing %s", key)
		}
	}
	meta := iconResult(t, app, "get_ui_icon", map[string]any{"id": probe, "include_source": false})
	if meta["svg"] != nil || meta["source_included"] != false {
		t.Fatal("include_source=false still delivered source")
	}
	zh := iconResult(t, app, "get_ui_icon", map[string]any{"id": probe, "language": "zh"})
	if !strings.Contains(zh["integration_prompt"].(string), "SVG") {
		t.Fatalf("missing zh prompt: %v", zh["integration_prompt"])
	}
	missing := strings.SplitN(probe, ":", 2)[0] + ":missing"
	for _, args := range []map[string]any{{"id": missing}, {"id": ""}, {}} {
		result := uiCall(t, app, "get_ui_icon", args)
		if result["isError"] != true {
			t.Fatalf("expected input error for %v", args)
		}
	}
}
