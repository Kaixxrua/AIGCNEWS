package mcpapp

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/uicatalog"
	"aigcnews/mcp-go/internal/uisemantic"
)

type fakeUISemantic struct {
	ids     map[string][]string // kind -> ids
	err     error
	queries []string
}

func (f *fakeUISemantic) SearchIDs(query, kind string) ([]string, error) {
	f.queries = append(f.queries, kind+":"+query)
	return f.ids[kind], f.err
}

func semanticUIApp(t *testing.T, semantic UISemanticSearcher) (*App, *uicatalog.Catalog, *uicatalog.IconCatalog) {
	t.Helper()
	catalog, icons, err := LoadUICatalogs()
	if err != nil {
		t.Fatal(err)
	}
	return New("aigc-radar", "test", NewUICatalogHandlers(catalog, icons, "https://catalog.test/", semantic)), catalog, icons
}

func structured(t *testing.T, app *App, name string, args map[string]any) map[string]any {
	t.Helper()
	result := uiCall(t, app, name, args)
	data, ok := result["structuredContent"].(map[string]any)
	if result["isError"] != false || !ok {
		t.Fatalf("tool failure: %v", result)
	}
	return data
}

func itemIDs(data map[string]any) []string {
	ids := []string{}
	for _, raw := range data["items"].([]any) {
		ids = append(ids, raw.(map[string]any)["id"].(string))
	}
	return ids
}

// A lexical query with at least two hits, derived from the embedded data so
// the test runs against both the production catalog and small fixtures.
func multiHitTemplateQuery(t *testing.T, catalog *uicatalog.Catalog) (string, []uicatalog.Template) {
	t.Helper()
	for _, item := range catalog.Items() {
		for _, q := range []string{item.Category, item.Subcategory} {
			if q == "" {
				continue
			}
			if matches, mode := catalog.SearchAdaptive(q, "", ""); mode == "exact" && len(matches) >= 2 {
				return q, matches
			}
		}
	}
	t.Skip("embedded catalog has no multi-hit category query")
	return "", nil
}

// 词法两轮（严格 + 放宽）都不会命中的描述：语义通道才可能召回。
const unmatchedUIQuery = "qzxv plorbnik wuggle"

func TestUITemplateSemanticLaneIsNoOpWhenDisabledOrFailing(t *testing.T) {
	baseline := uiApp(t)
	catalog, _, err := LoadUICatalogs()
	if err != nil {
		t.Fatal(err)
	}
	q, _ := multiHitTemplateQuery(t, catalog)
	failing := &fakeUISemantic{err: errors.New("embedding timed out"), ids: map[string][]string{uisemantic.KindTemplate: {catalog.Items()[0].ID}}}
	for _, semantic := range []UISemanticSearcher{nil, failing} {
		app, _, _ := semanticUIApp(t, semantic)
		for _, args := range []map[string]any{
			{"q": q, "limit": 5},
			{"q": unmatchedUIQuery},
			{"q": "", "limit": 3},
		} {
			want, _ := json.Marshal(structured(t, baseline, "search_ui_templates", args))
			got, _ := json.Marshal(structured(t, app, "search_ui_templates", args))
			if string(got) != string(want) {
				t.Fatalf("semantic=%T args=%v changed output\nwant %s\ngot  %s", semantic, args, want, got)
			}
		}
	}
	if len(failing.queries) != 2 {
		t.Fatalf("blank query must skip the semantic lane: %v", failing.queries)
	}
}

func TestUITemplateSemanticLaneFusesWithLexicalRanking(t *testing.T) {
	catalog, _, err := LoadUICatalogs()
	if err != nil {
		t.Fatal(err)
	}
	q, lexical := multiHitTemplateQuery(t, catalog)
	var extra string
	for _, item := range catalog.Items() {
		if !slicesContainTemplate(lexical, item.ID) {
			extra = item.ID
			break
		}
	}
	if extra == "" {
		t.Skip("every template matches the lexical query")
	}
	// lexical[1] 两路都中，应升到第一；lexical[0] 次之；仅语义命中的 extra 第三。
	semantic := &fakeUISemantic{ids: map[string][]string{uisemantic.KindTemplate: {lexical[1].ID, extra, "missing-template"}}}
	app, _, _ := semanticUIApp(t, semantic)
	data := structured(t, app, "search_ui_templates", map[string]any{"q": q, "limit": 30})
	ids := itemIDs(data)
	if len(ids) < 3 || ids[0] != lexical[1].ID || ids[1] != lexical[0].ID || ids[2] != extra {
		t.Fatalf("fusion order %v (lexical %s,%s extra %s)", ids[:min(len(ids), 4)], lexical[0].ID, lexical[1].ID, extra)
	}
	if data["search_mode"] != "exact" || data["total"] != float64(len(lexical)+1) {
		t.Fatalf("mode/total: %v %v", data["search_mode"], data["total"])
	}
	if !reflect.DeepEqual(semantic.queries, []string{uisemantic.KindTemplate + ":" + q}) {
		t.Fatalf("semantic queries %v", semantic.queries)
	}
}

func TestUITemplateSemanticOnlyResultsReportSemanticModeAndKeepFilters(t *testing.T) {
	catalog, _, err := LoadUICatalogs()
	if err != nil {
		t.Fatal(err)
	}
	if matches, _ := catalog.SearchAdaptive(unmatchedUIQuery, "", ""); len(matches) != 0 {
		t.Skipf("probe query unexpectedly matches lexically: %d", len(matches))
	}
	items := catalog.Items()
	first := items[0]
	var other uicatalog.Template
	for _, item := range items[1:] {
		if item.Category != first.Category && item.Subcategory != first.Category {
			other = item
			break
		}
	}
	semantic := &fakeUISemantic{ids: map[string][]string{uisemantic.KindTemplate: {first.ID, "missing-template"}}}
	if other.ID != "" {
		semantic.ids[uisemantic.KindTemplate] = append(semantic.ids[uisemantic.KindTemplate], other.ID)
	}
	app, _, _ := semanticUIApp(t, semantic)

	data := structured(t, app, "search_ui_templates", map[string]any{"q": unmatchedUIQuery})
	want := []string{first.ID}
	if other.ID != "" {
		want = append(want, other.ID)
	}
	if ids := itemIDs(data); data["search_mode"] != "semantic" || !reflect.DeepEqual(ids, want) || data["total"] != float64(len(want)) {
		t.Fatalf("semantic-only: mode=%v ids=%v total=%v want %v", data["search_mode"], ids, data["total"], want)
	}

	// 语义命中同样受 category 约束：first 的分类下 other 不得出现。
	filtered := structured(t, app, "search_ui_templates", map[string]any{"q": unmatchedUIQuery, "category": first.Category})
	for _, id := range itemIDs(filtered) {
		if id == other.ID && other.ID != "" {
			t.Fatalf("category filter leaked %s", id)
		}
	}
	if ids := itemIDs(filtered); len(ids) == 0 || ids[0] != first.ID {
		t.Fatalf("category-filtered semantic hits %v", ids)
	}

	// 语义命中全部被过滤掉时保持词法结果与 search_mode。
	none := &fakeUISemantic{ids: map[string][]string{uisemantic.KindTemplate: {"missing-template"}}}
	noneApp, _, _ := semanticUIApp(t, none)
	if data := structured(t, noneApp, "search_ui_templates", map[string]any{"q": unmatchedUIQuery}); data["search_mode"] != "exact" || data["total"] != float64(0) {
		t.Fatalf("unknown semantic ids must keep the lexical result: %v", data)
	}
}

func TestUIIconSemanticLaneReachesEnglishIconsFromChineseQuery(t *testing.T) {
	_, _, icons := semanticUIApp(t, nil)
	probe := firstIconID(t)
	provider := strings.SplitN(probe, ":", 2)[0]
	const q = "购物车"
	if lexical := icons.SearchIcons(q, "", "", ""); len(lexical) != 0 {
		t.Skipf("icon metadata unexpectedly matches %q", q)
	}
	var otherSet string
	for _, set := range icons.Sets() {
		if set.ProviderID != provider {
			if found := icons.SearchIcons("", set.ProviderID, "", ""); len(found) > 0 {
				otherSet = found[0].ID
				break
			}
		}
	}
	ids := []string{probe, "missing:icon"}
	if otherSet != "" {
		ids = append(ids, otherSet)
	}
	semantic := &fakeUISemantic{ids: map[string][]string{uisemantic.KindIcon: ids}}
	app, _, _ := semanticUIApp(t, semantic)

	data := iconResult(t, app, "search_ui_icons", map[string]any{"q": q})
	want := []string{probe}
	if otherSet != "" {
		want = append(want, otherSet)
	}
	if got := itemIDs(data); !reflect.DeepEqual(got, want) || data["total"] != float64(len(want)) {
		t.Fatalf("icons %v total %v want %v", got, data["total"], want)
	}
	if got := itemIDs(iconResult(t, app, "search_ui_icons", map[string]any{"q": q, "set": provider})); !reflect.DeepEqual(got, []string{probe}) {
		t.Fatalf("set filter must apply to semantic hits: %v", got)
	}

	failing := &fakeUISemantic{err: errors.New("milvus down"), ids: semantic.ids}
	failingApp, _, _ := semanticUIApp(t, failing)
	baseline := uiApp(t)
	name := strings.SplitN(probe, ":", 2)[1]
	for _, args := range []map[string]any{{"q": q}, {"q": name, "limit": float64(5)}} {
		want, _ := json.Marshal(iconResult(t, baseline, "search_ui_icons", args))
		got, _ := json.Marshal(iconResult(t, failingApp, "search_ui_icons", args))
		if string(got) != string(want) {
			t.Fatalf("failing semantic lane changed %v\nwant %s\ngot  %s", args, want, got)
		}
	}
}

func slicesContainTemplate(items []uicatalog.Template, id string) bool {
	for _, item := range items {
		if item.ID == id {
			return true
		}
	}
	return false
}
