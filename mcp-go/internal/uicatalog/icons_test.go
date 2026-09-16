package uicatalog

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"
	"testing/fstest"
)

// These tests run both against the production catalog and the tiny CI
// fixture, so every expectation is derived from the embedded data itself.
func TestEmbeddedIconCatalogPassesIntegrityGate(t *testing.T) {
	catalog, err := LoadIcons()
	if err != nil {
		t.Fatal(err)
	}
	if len(catalog.Sets()) == 0 || catalog.IconCount() == 0 {
		t.Fatal("empty embedded icon catalog")
	}
	providers := map[string]bool{}
	count := 0
	for _, set := range catalog.Sets() {
		if providers[set.ProviderID] {
			t.Fatalf("duplicate provider %s", set.ProviderID)
		}
		providers[set.ProviderID] = true
		if set.Icons != nil {
			t.Fatalf("validated set still carries icon payloads: %s", set.ProviderID)
		}
	}
	// Every set's first icon round-trips through Get, Source and LicenseNotice.
	for _, set := range catalog.Sets() {
		matches := catalog.SearchIcons("", set.ProviderID, "", "")
		if len(matches) == 0 {
			t.Fatalf("set %s has no icons", set.ProviderID)
		}
		count += len(matches)
		icon, owner, ok := catalog.Get(matches[0].ID)
		if !ok || owner.ProviderID != set.ProviderID || icon.ID != matches[0].ID {
			t.Fatalf("pinned icon lookup failed: %s", matches[0].ID)
		}
		source, err := catalog.Source(icon.ID)
		if err != nil || len(source) == 0 {
			t.Fatalf("icon source unavailable: %v", err)
		}
		hash := sha256.Sum256([]byte(source))
		if hex.EncodeToString(hash[:]) != icon.SHA256 {
			t.Fatalf("served icon diverged from pinned hash: %s", icon.ID)
		}
		notice, err := catalog.LicenseNotice(icon.ID)
		if err != nil || len(notice) == 0 {
			t.Fatalf("license notice unavailable: %v", err)
		}
	}
	if count != catalog.IconCount() {
		t.Fatalf("provider walk found %d of %d icons", count, catalog.IconCount())
	}
	if _, _, ok := catalog.Get("missing:icon"); ok {
		t.Fatal("unknown icon resolved")
	}
}

func TestIconSearchUsesStrictAllTermsContract(t *testing.T) {
	catalog, err := LoadIcons()
	if err != nil {
		t.Fatal(err)
	}
	set := catalog.Sets()[0]
	probe := catalog.SearchIcons("", set.ProviderID, "", "")[0]
	matches := catalog.SearchIcons(probe.Name, "", "", "")
	if len(matches) == 0 {
		t.Fatalf("name search empty for %q", probe.Name)
	}
	found := false
	for _, icon := range matches {
		if icon.ID == probe.ID {
			found = true
		}
	}
	if !found {
		t.Fatalf("strict search missed %s", probe.ID)
	}
	outline := catalog.SearchIcons(probe.Name, "", probe.Style, "")
	for _, icon := range outline {
		if icon.Style != probe.Style {
			t.Fatalf("style filter leaked: %s", icon.ID)
		}
	}
	provider := catalog.SearchIcons(probe.Name, set.ProviderID, "", "")
	for _, icon := range provider {
		if !strings.HasPrefix(icon.ID, set.ProviderID+":") {
			t.Fatalf("provider filter leaked: %s", icon.ID)
		}
	}
	if got := catalog.SearchIcons("definitely-not-an-icon-xyz", "", "", ""); len(got) != 0 {
		t.Fatalf("unknown term matched %d icons", len(got))
	}
}

type iconFixture struct {
	files  fstest.MapFS
	set    IconSet
	svgSHA string
}

func newIconFixture(t *testing.T) *iconFixture {
	t.Helper()
	svg := []byte("<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path d=\"M0 0h24v24H0z\"/></svg>\n")
	svgHash := sha256.Sum256(svg)
	f := &iconFixture{files: fstest.MapFS{}, svgSHA: hex.EncodeToString(svgHash[:])}
	path := "sources/fixture/check.svg"
	f.files["data/"+path] = &fstest.MapFile{Data: svg}
	license := []byte("MIT License\n")
	f.files["data/licenses/fixture/LICENSE"] = &fstest.MapFile{Data: license}
	resourceA := []byte("resource-a\n")
	resourceB := []byte("resource-b\n")
	screenshot := []byte("png\n")
	hash := func(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
	revision := strings.Repeat("a", 40)
	manifest := map[string]any{
		"revision": revision, "license": "MIT", "captured_at": "2026-09-16T00:00:00Z",
		"license_grants": []string{"commercial-use", "redistribution"},
		"source_files":   map[string]string{path: f.svgSHA},
		"resources": []map[string]string{
			{"name": "LICENSE", "sha256": hash(resourceA)},
			{"name": "README.md", "sha256": hash(resourceB)},
		},
		"screenshot": "license-page.png", "screenshot_sha256": hash(screenshot),
	}
	manifestJSON, _ := json.Marshal(manifest)
	dir := "data/assets/fixture/evidence/" + revision + "/"
	f.files[dir+"manifest.json"] = &fstest.MapFile{Data: manifestJSON}
	f.files[dir+"LICENSE"] = &fstest.MapFile{Data: resourceA}
	f.files[dir+"README.md"] = &fstest.MapFile{Data: resourceB}
	f.files[dir+"license-page.png"] = &fstest.MapFile{Data: screenshot}
	f.set = IconSet{
		Provider: "Fixture", ProviderID: "fixture", Author: "AIGCNEWS", License: "MIT",
		LicenseURL: "/ui-library/licenses/fixture/LICENSE", Repository: "fixture/icons",
		Revision: revision, SourceURL: "https://example.invalid/fixture", Format: "svg",
		Dependencies: map[string]string{}, AddedAt: "2026-09-16T00:00:00Z",
		RightsEvidenceURL: "/ui-library/assets/fixture/evidence/" + revision + "/manifest.json",
		Icons: []Icon{{
			ID: "fixture:check", Name: "check", Display: map[string]string{"zh": "check", "en": "check"},
			Style: "outline", Category: "interface", Aliases: []string{"check"},
			File: path, SHA256: f.svgSHA,
		}},
	}
	return f
}

func (f *iconFixture) writeIcons(t *testing.T, sets []IconSet) {
	t.Helper()
	payload, _ := json.Marshal(map[string]any{"version": 1, "sets": sets})
	f.files["data/icons.json"] = &fstest.MapFile{Data: payload}
}

func TestLoadIconsRejectsIntegrityFailures(t *testing.T) {
	base := newIconFixture(t)
	base.writeIcons(t, []IconSet{base.set})
	if _, err := loadIcons(base.files); err != nil {
		t.Fatalf("valid fixture rejected: %v", err)
	}
	cases := map[string]func(f *iconFixture) (func(), string){
		"wrong file hash": func(f *iconFixture) (func(), string) {
			return func() { f.files["data/"+f.set.Icons[0].File].Data = []byte("<svg/>") }, "integrity failed"
		},
		"missing evidence coverage": func(f *iconFixture) (func(), string) {
			return func() {
				set := f.set
				set.Icons[0].File = "sources/fixture/other.svg"
				f.files["data/sources/fixture/other.svg"] = &fstest.MapFile{Data: []byte("<svg/>")}
				f.writeIcons(t, []IconSet{set})
			}, "absent from rights evidence"
		},
		"escaping path": func(f *iconFixture) (func(), string) {
			return func() {
				set := f.set
				set.Icons[0].File = "sources/other/check.svg"
				f.writeIcons(t, []IconSet{set})
			}, "absent from rights evidence"
		},
		"duplicate id": func(f *iconFixture) (func(), string) {
			return func() {
				set := f.set
				set.Icons = append(set.Icons, f.set.Icons[0])
				f.writeIcons(t, []IconSet{set})
			}, "duplicate UI icon"
		},
		"mismatched id prefix": func(f *iconFixture) (func(), string) {
			return func() {
				set := f.set
				set.Icons[0].ID = "other:check"
				f.writeIcons(t, []IconSet{set})
			}, "invalid UI icon"
		},
	}
	for name, build := range cases {
		t.Run(name, func(t *testing.T) {
			f := newIconFixture(t)
			mutate, want := build(f)
			f.writeIcons(t, []IconSet{f.set})
			mutate()
			_, err := loadIcons(f.files)
			if err == nil || !strings.Contains(err.Error(), want) {
				t.Fatalf("expected %q failure, got %v", want, err)
			}
		})
	}
}
