package mcpapp

import (
	"errors"
	"testing"

	"aigcnews/mcp-go/internal/uisemantic"
)

func TestDeprecatedMaterialsStayOutOfMCPDiscoveryAndDirectAccess(t *testing.T) {
	catalog, icons, err := LoadUICatalogs()
	if err != nil {
		t.Fatal(err)
	}
	deprecated := map[string]bool{}
	for _, item := range catalog.Items() {
		deprecated[item.ID] = true
	}
	for _, icon := range icons.Icons() {
		deprecated[icon.ID] = true
	}
	templateID, iconID := catalog.Items()[0].ID, icons.Icons()[0].ID
	semantic := &fakeUISemantic{ids: map[string][]string{
		uisemantic.KindTemplate: {templateID}, uisemantic.KindIcon: {iconID},
	}}
	handlers := NewUICatalogHandlers(catalog, icons, "https://catalog.test", semantic,
		func() (map[string]bool, error) { return deprecated, nil })
	app := New("aigc-radar", "test", handlers)
	for _, kind := range []string{"templates", "icons"} {
		for _, query := range []string{"", "semantic-only-moderation-query"} {
			data := structured(t, app, "search_ui_"+kind, map[string]any{"q": query})
			if len(itemIDs(data)) != 0 || data["total"] != float64(0) {
				t.Fatalf("deprecated %s escaped filtering: %v", kind, data)
			}
		}
	}
	for name, id := range map[string]string{"get_ui_template": templateID, "get_ui_icon": iconID} {
		if _, err := handlers[name](map[string]any{"id": id}); err == nil {
			t.Fatalf("%s returned deprecated material", name)
		}
		delete(deprecated, id)
		if _, err := handlers[name](map[string]any{"id": id}); err != nil {
			t.Fatalf("%s did not see restoration without a restart: %v", name, err)
		}
	}
	for _, kind := range []string{"templates", "icons"} {
		data := structured(t, app, "search_ui_"+kind, map[string]any{})
		if len(itemIDs(data)) != 1 || data["total"] != float64(1) {
			t.Fatalf("restored %s not returned with accurate total: %v", kind, data)
		}
	}
}

func TestUIVisibilityDatabaseFailureDoesNotExposeTheStaticCatalog(t *testing.T) {
	catalog, icons, err := LoadUICatalogs()
	if err != nil {
		t.Fatal(err)
	}
	unavailable := errors.New("visibility unavailable")
	handlers := NewUICatalogHandlers(catalog, icons, "https://catalog.test", nil,
		func() (map[string]bool, error) { return nil, unavailable })
	for name, args := range map[string]map[string]any{
		"search_ui_templates": {}, "search_ui_icons": {},
		"get_ui_template": {"id": catalog.Items()[0].ID}, "get_ui_icon": {"id": icons.Icons()[0].ID},
	} {
		if _, err := handlers[name](args); !errors.Is(err, unavailable) {
			t.Fatalf("%s did not fail closed: %v", name, err)
		}
	}
}
