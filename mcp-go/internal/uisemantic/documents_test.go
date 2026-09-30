package uisemantic

import (
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/uicatalog"
)

func TestTemplateDocumentsBuildBilingualTextAndStableFingerprint(t *testing.T) {
	items := []uicatalog.Template{{
		ID:          "eui-fluid-studio",
		Name:        map[string]string{"zh": "流动工作室", "en": "Fluid studio"},
		Description: map[string]string{"zh": "大字轮廓排版", "en": "Fluid studio layout."},
		Category:    "component",
		Subcategory: "agency",
		Kind:        "template",
		Styles:      []string{"dark", "Dark"},
		Aliases:     []string{"fluid-studio", "流动工作室", "Fluid studio", "fluid studio", " "},
	}}
	documents := TemplateDocuments(items)
	if len(documents) != 1 {
		t.Fatalf("documents %#v", documents)
	}
	got := documents[0]
	want := "Fluid studio / 流动工作室\nFluid studio layout.\n大字轮廓排版\ncomponent, agency, template, dark\nfluid-studio, 流动工作室, Fluid studio"
	if got.ID != "eui-fluid-studio" || got.Kind != KindTemplate || got.Text != want {
		t.Fatalf("document %#v", got)
	}
	if got.Fingerprint != Fingerprint(KindTemplate+"\n"+want) || len(got.Fingerprint) != 64 {
		t.Fatalf("fingerprint %q", got.Fingerprint)
	}
	if again := TemplateDocuments(items)[0]; again.Fingerprint != got.Fingerprint || again.VectorID() != got.VectorID() {
		t.Fatal("fingerprint must be deterministic")
	}
	items[0].Description["en"] = "Changed."
	if changed := TemplateDocuments(items)[0]; changed.Fingerprint == got.Fingerprint || changed.VectorID() == got.VectorID() {
		t.Fatal("text change must produce a new fingerprint and vector id")
	}
}

func TestIconDocumentsUseReadableNameAliasesAndCategory(t *testing.T) {
	documents := IconDocuments([]uicatalog.Icon{{
		ID:       "heroicons:academic-cap",
		Display:  map[string]string{"zh": "academic-cap", "en": "academic-cap"},
		Category: "interface",
		Aliases:  []string{"academic-cap", "academic cap", "Academic Cap", "cap"},
	}})
	if len(documents) != 1 {
		t.Fatalf("documents %#v", documents)
	}
	if got := documents[0]; got.Kind != KindIcon || got.Text != "academic cap icon\nacademic-cap, academic cap, cap\ninterface" {
		t.Fatalf("document %#v", got)
	}
}

func TestVectorIDSeparatesItemsAndVersions(t *testing.T) {
	a := VectorID("a", Fingerprint("x"))
	if a == VectorID("b", Fingerprint("x")) || a == VectorID("a", Fingerprint("y")) {
		t.Fatal("vector ids must differ across items and fingerprints")
	}
	if len(a) != 64 || strings.Trim(a, "0123456789abcdef") != "" {
		t.Fatalf("vector id must be lowercase hex sha256, got %q", a)
	}
	// 同一文本在模板与图标下的指纹不同，避免跨 kind 串行。
	if TemplateDocuments([]uicatalog.Template{{ID: "same", Name: map[string]string{"en": "x"}}})[0].Fingerprint ==
		IconDocuments([]uicatalog.Icon{{ID: "same", Display: map[string]string{"en": "x"}}})[0].Fingerprint {
		t.Fatal("kind must participate in the fingerprint")
	}
}

func TestDocumentsFromEmbeddedCatalogAreUniqueAndNonEmpty(t *testing.T) {
	catalog, err := uicatalog.New()
	if err != nil {
		t.Skipf("embedded catalog unavailable: %v", err)
	}
	icons, err := uicatalog.LoadIcons()
	if err != nil {
		t.Skipf("embedded icons unavailable: %v", err)
	}
	documents := append(TemplateDocuments(catalog.Items()), IconDocuments(icons.Icons())...)
	if len(documents) != len(catalog.Items())+icons.IconCount() {
		t.Fatalf("documents=%d templates=%d icons=%d", len(documents), len(catalog.Items()), icons.IconCount())
	}
	seen := map[string]bool{}
	for _, document := range documents {
		if strings.TrimSpace(document.Text) == "" || seen[document.VectorID()] || len(document.ID) > 255 {
			t.Fatalf("invalid or duplicate document %#v", document)
		}
		seen[document.VectorID()] = true
	}
}
