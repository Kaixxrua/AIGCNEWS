package uicatalog

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"sort"
	"strings"
)

// MaxIconFileBytes bounds a single distributable icon source. Icons are
// served verbatim, so oversized assets are rejected at load time.
const MaxIconFileBytes = 64 * 1024

// Icon is a single reviewed, pinned and hash-checked redistributable icon.
type Icon struct {
	ID       string            `json:"id"`
	Name     string            `json:"name"`
	Display  map[string]string `json:"display"`
	Style    string            `json:"style"`
	Category string            `json:"category"`
	Aliases  []string          `json:"aliases"`
	File     string            `json:"file"`
	SHA256   string            `json:"sha256"`
}

// IconSet carries the provenance and license scope of one pinned upstream
// icon source. Icons holds the full set while loading; a validated
// IconCatalog moves them into flat entries and keeps metadata only.
type IconSet struct {
	Provider          string            `json:"provider"`
	ProviderID        string            `json:"provider_id"`
	Author            string            `json:"author"`
	License           string            `json:"license"`
	LicenseURL        string            `json:"license_url"`
	LicenseNote       string            `json:"license_note"`
	ScopeNote         string            `json:"scope_note"`
	Repository        string            `json:"repository"`
	Revision          string            `json:"revision"`
	SourceURL         string            `json:"source_url"`
	Format            string            `json:"format"`
	Dependencies      map[string]string `json:"dependencies"`
	AddedAt           string            `json:"added_at"`
	RightsEvidenceURL string            `json:"rights_evidence_url"`
	Icons             []Icon            `json:"icons"`
}

type iconEntry struct {
	set   int
	icon  Icon
	title string
	core  string
}

// IconCatalog serves reviewed icon sets without network access. Every icon
// file passed the same pinned-revision, license-evidence and integrity gate
// as component sources.
type IconCatalog struct {
	sets    []IconSet
	entries []iconEntry
	byID    map[string]int
}

// LoadIcons validates the embedded icon catalog once at startup.
func LoadIcons() (*IconCatalog, error) {
	return loadIcons(assets)
}

func loadIcons(files fs.FS) (*IconCatalog, error) {
	raw, err := fs.ReadFile(files, "data/icons.json")
	if err != nil {
		return nil, err
	}
	var payload struct {
		Version int       `json:"version"`
		Sets    []IconSet `json:"sets"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, err
	}
	if payload.Version != 1 || len(payload.Sets) == 0 {
		return nil, fmt.Errorf("unsupported or empty UI icon catalog")
	}
	catalog := &IconCatalog{byID: map[string]int{}}
	for index, set := range payload.Sets {
		if set.ProviderID == "" || set.Provider == "" || set.Author == "" || set.License == "" || set.Revision == "" || set.AddedAt == "" || set.Format == "" {
			return nil, fmt.Errorf("invalid UI icon set: %s", set.ProviderID)
		}
		if len(set.Icons) == 0 {
			return nil, fmt.Errorf("empty UI icon set: %s", set.ProviderID)
		}
		proof, err := verifyRightsEvidence(files, set.ProviderID, set.Revision, set.License, set.RightsEvidenceURL, "icon set "+set.ProviderID)
		if err != nil {
			return nil, err
		}
		if _, err := fs.ReadFile(files, "data/licenses/"+set.ProviderID+"/LICENSE"); err != nil {
			return nil, err
		}
		for _, icon := range set.Icons {
			if icon.Name == "" || icon.ID != set.ProviderID+":"+icon.Name || icon.Display["zh"] == "" || icon.Display["en"] == "" || icon.Style == "" || icon.Category == "" {
				return nil, fmt.Errorf("invalid UI icon: %s", icon.ID)
			}
			if _, taken := catalog.byID[icon.ID]; taken {
				return nil, fmt.Errorf("duplicate UI icon: %s", icon.ID)
			}
			if proof.SourceFiles[icon.File] != icon.SHA256 {
				return nil, fmt.Errorf("icon source absent from rights evidence: %s", icon.File)
			}
			if !fs.ValidPath(icon.File) || !strings.HasPrefix(icon.File, "sources/"+set.ProviderID+"/") {
				return nil, fmt.Errorf("invalid UI icon path: %s", icon.File)
			}
			content, err := fs.ReadFile(files, "data/"+icon.File)
			if err != nil {
				return nil, err
			}
			hash := sha256.Sum256(content)
			if hex.EncodeToString(hash[:]) != icon.SHA256 {
				return nil, fmt.Errorf("UI icon integrity failed: %s", icon.File)
			}
			if len(content) > MaxIconFileBytes {
				return nil, fmt.Errorf("UI icon exceeds single-file budget: %s", icon.File)
			}
			title := normalize(icon.Display["zh"] + " " + icon.Display["en"] + " " + icon.ID)
			core := normalize(title + " " + set.Provider + " " + strings.Join(icon.Aliases, " ") + " " + icon.Style + " " + icon.Category)
			catalog.byID[icon.ID] = len(catalog.entries)
			catalog.entries = append(catalog.entries, iconEntry{set: index, icon: icon, title: title, core: core})
		}
		set.Icons = nil
		catalog.sets = append(catalog.sets, set)
	}
	return catalog, nil
}

// Sets returns the validated set metadata without the per-icon payloads.
func (c *IconCatalog) Sets() []IconSet {
	return c.sets
}

// IconCount returns the total number of validated icons across all sets.
func (c *IconCatalog) IconCount() int {
	return len(c.entries)
}

// Icons returns every validated icon in catalog order.
func (c *IconCatalog) Icons() []Icon {
	icons := make([]Icon, 0, len(c.entries))
	for _, entry := range c.entries {
		icons = append(icons, entry.icon)
	}
	return icons
}

// Get returns an icon and its owning set metadata.
func (c *IconCatalog) Get(id string) (Icon, *IconSet, bool) {
	position, ok := c.byID[id]
	if !ok {
		return Icon{}, nil, false
	}
	entry := c.entries[position]
	return entry.icon, &c.sets[entry.set], true
}

// Source returns the verbatim icon source for a validated icon id.
func (c *IconCatalog) Source(id string) (string, error) {
	icon, _, ok := c.Get(id)
	if !ok {
		return "", fmt.Errorf("unknown UI icon")
	}
	content, err := assets.ReadFile("data/" + icon.File)
	if err != nil {
		return "", err
	}
	return string(content), nil
}

// LicenseNotice returns the archived license text of the owning set.
func (c *IconCatalog) LicenseNotice(id string) (string, error) {
	_, set, ok := c.Get(id)
	if !ok {
		return "", fmt.Errorf("unknown UI icon")
	}
	content, err := assets.ReadFile("data/licenses/" + set.ProviderID + "/LICENSE")
	if err != nil {
		return "", err
	}
	return string(content), nil
}

// SearchIcons keeps the strict all-terms scoring contract of the component
// catalog. Icon aliases are English, so query terms are used as tokenized.
func (c *IconCatalog) SearchIcons(query, provider, style, category string) []Icon {
	type candidate struct {
		entry iconEntry
		score int
	}
	results := []candidate{}
	terms := []string{}
	for _, term := range tokens.FindAllString(normalize(query), -1) {
		if !strings.Contains(" "+strings.Join(iconStopWords, " ")+" ", " "+term+" ") {
			terms = append(terms, term)
		}
	}
	for _, entry := range c.entries {
		if !c.matchesFilters(entry, provider, style, category) {
			continue
		}
		score, matches := 0, true
		for _, term := range terms {
			if !strings.Contains(entry.core, term) {
				matches = false
				break
			}
			if strings.Contains(entry.title, term) {
				score += 20
			} else {
				score += 10
			}
		}
		if matches {
			results = append(results, candidate{entry: entry, score: score})
		}
	}
	sort.SliceStable(results, func(i, j int) bool { return results[i].score > results[j].score })
	icons := make([]Icon, 0, len(results))
	for _, result := range results {
		icons = append(icons, result.entry.icon)
	}
	return icons
}

// matchesFilters is the set/style/category gate shared by every icon search.
func (c *IconCatalog) matchesFilters(entry iconEntry, provider, style, category string) bool {
	set := c.sets[entry.set]
	return !(provider != "" && set.ProviderID != provider || style != "" && entry.icon.Style != style || category != "" && entry.icon.Category != category)
}

// Lookup returns the icons for ids in the given order, skipping unknown ids
// and icons outside the set/style/category filters.
func (c *IconCatalog) Lookup(ids []string, provider, style, category string) []Icon {
	icons := make([]Icon, 0, len(ids))
	for _, id := range ids {
		position, ok := c.byID[id]
		if ok && c.matchesFilters(c.entries[position], provider, style, category) {
			icons = append(icons, c.entries[position].icon)
		}
	}
	return icons
}

var iconStopWords = []string{"a", "an", "the", "icon", "icons", "for", "with", "and", "in", "of"}
