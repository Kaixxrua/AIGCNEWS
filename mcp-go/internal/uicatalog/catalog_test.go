package uicatalog

import (
	"encoding/json"
	"os"
	"reflect"
	"slices"
	"testing"
)

func TestSharedBilingualSearchContract(t *testing.T) {
	// Search behavior is stable even when operators withdraw published material.
	fixture, err := os.ReadFile("testdata/search_catalog.json")
	if err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Items []Template `json:"items"`
	}
	if err := json.Unmarshal(fixture, &payload); err != nil {
		t.Fatal(err)
	}
	catalog := &Catalog{items: payload.Items}
	raw, err := os.ReadFile("testdata/search_cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Q, Category, Framework string
		IDs                    []string
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		t.Run(tc.Q+"/"+tc.Framework+"/"+tc.Category, func(t *testing.T) {
			items := catalog.Search(tc.Q, tc.Category, tc.Framework)
			ids := []string{}
			for _, item := range items {
				ids = append(ids, item.ID)
			}
			slices.Sort(ids)
			slices.Sort(tc.IDs)
			if !reflect.DeepEqual(ids, tc.IDs) {
				t.Fatalf("ids = %v, want %v", ids, tc.IDs)
			}
		})
	}
}

func TestPinnedSourcesAndLocalFileBoundary(t *testing.T) {
	catalog, err := New() // New verifies every source SHA-256 and license file.
	if err != nil {
		t.Fatal(err)
	}
	items := catalog.Search("", "", "")
	if len(items) == 0 {
		t.Fatalf("got %d curated templates", len(items))
	}
	for _, item := range items {
		if len(item.Revision) != 40 {
			t.Fatalf("unpinned source %s", item.ID)
		}
		for _, file := range item.Files {
			content, err := catalog.Source(item.ID, file.Name)
			if err != nil || content == "" {
				t.Fatalf("source missing: %s: %v", file.Name, err)
			}
		}
	}
	for _, path := range []string{"../../../../.env", "https://example.com", "/etc/passwd", "data/catalog.json"} {
		if _, err := catalog.Source(items[0].ID, path); err == nil {
			t.Fatalf("accepted non-manifest file %q", path)
		}
		if _, ok := catalog.Get(path); ok {
			t.Fatalf("accepted non-catalog id %q", path)
		}
	}
}
