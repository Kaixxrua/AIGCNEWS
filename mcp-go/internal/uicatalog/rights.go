package uicatalog

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"path"
	"slices"
	"strings"
)

type rightsEvidence struct {
	Revision         string                          `json:"revision"`
	License          string                          `json:"license"`
	CapturedAt       string                          `json:"captured_at"`
	Grants           []string                        `json:"license_grants"`
	SourceFiles      map[string]string               `json:"source_files"`
	Resources        []struct{ Name, SHA256 string } `json:"resources"`
	Screenshot       string                          `json:"screenshot"`
	ScreenshotSHA256 string                          `json:"screenshot_sha256"`
}

func loadRightsEvidence(files fs.FS, item Template) (*rightsEvidence, error) {
	expected := "/ui-library/assets/" + item.ProviderID + "/evidence/" + item.Revision + "/manifest.json"
	if item.RightsEvidenceURL != expected || !fs.ValidPath(strings.TrimPrefix(expected, "/ui-library/")) {
		return nil, fmt.Errorf("missing or invalid rights evidence: %s", item.ID)
	}
	filename := "data/" + strings.TrimPrefix(expected, "/ui-library/")
	raw, err := fs.ReadFile(files, filename)
	if err != nil {
		return nil, err
	}
	var proof rightsEvidence
	if err = json.Unmarshal(raw, &proof); err != nil {
		return nil, err
	}
	if proof.Revision != item.Revision || proof.License != item.License || proof.CapturedAt == "" ||
		!slices.Contains(proof.Grants, "commercial-use") || !slices.Contains(proof.Grants, "redistribution") ||
		len(proof.Resources) < 2 || proof.ScreenshotSHA256 == "" {
		return nil, fmt.Errorf("incomplete rights evidence: %s", item.ID)
	}
	verify := func(name, expectedHash string) error {
		if !fs.ValidPath(name) || strings.Contains(name, "/") {
			return fmt.Errorf("invalid evidence resource")
		}
		content, err := fs.ReadFile(files, path.Join(path.Dir(filename), name))
		if err != nil {
			return err
		}
		digest := sha256.Sum256(content)
		if hex.EncodeToString(digest[:]) != expectedHash {
			return fmt.Errorf("rights evidence integrity failed: %s", name)
		}
		return nil
	}
	for _, resource := range proof.Resources {
		if err := verify(resource.Name, resource.SHA256); err != nil {
			return nil, err
		}
	}
	if err := verify(proof.Screenshot, proof.ScreenshotSHA256); err != nil {
		return nil, err
	}
	return &proof, nil
}
