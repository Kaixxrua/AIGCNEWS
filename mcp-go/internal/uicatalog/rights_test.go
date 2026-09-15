package uicatalog

import (
	"encoding/json"
	"io/fs"
	"strings"
	"testing"
	"testing/fstest"
)

func TestRightsEvidenceFailsClosed(t *testing.T) {
	catalog, err := New()
	if err != nil {
		t.Fatal(err)
	}
	item := catalog.items[0]
	filename := "data/" + strings.TrimPrefix(item.RightsEvidenceURL, "/ui-library/")
	raw, err := assets.ReadFile(filename)
	if err != nil {
		t.Fatal(err)
	}
	fixtures := fstest.MapFS{}
	directory := strings.TrimSuffix(filename, "manifest.json")
	err = fs.WalkDir(assets, strings.TrimSuffix(directory, "/"), func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		content, err := assets.ReadFile(name)
		if err != nil {
			return err
		}
		fixtures[name] = &fstest.MapFile{Data: content}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := loadRightsEvidence(fixtures, item); err != nil {
		t.Fatal(err)
	}
	fixtures[filename] = &fstest.MapFile{Data: []byte(strings.Replace(string(raw), "commercial-use", "personal-use", 1))}
	if _, err := loadRightsEvidence(fixtures, item); err == nil {
		t.Fatal("accepted insufficient license grant")
	}
	fixtures[filename] = &fstest.MapFile{Data: raw}
	var proof rightsEvidence
	if err := json.Unmarshal(raw, &proof); err != nil {
		t.Fatal(err)
	}
	fixtures[directory+proof.Resources[0].Name] = &fstest.MapFile{Data: []byte("changed license")}
	if _, err := loadRightsEvidence(fixtures, item); err == nil {
		t.Fatal("accepted modified evidence")
	}
	item.RightsEvidenceURL = ""
	if _, err := loadRightsEvidence(assets, item); err == nil {
		t.Fatal("accepted absent evidence")
	}
}
