// Package uicatalog serves reviewed, pinned upstream UI sources without network access.
package uicatalog

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"regexp"
	"slices"
	"sort"
	"strings"

	"golang.org/x/text/unicode/norm"
)

//go:embed data/catalog.json data/icons.json data/upstreams.json data/sources data/licenses data/assets
var assets embed.FS

// Explicit file requests can retrieve complete upstream configuration files.
// Default multi-file responses retain their smaller response budget.
const MaxSourceFileBytes = 256 * 1024

type File struct {
	Name   string `json:"name"`
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}

type Asset struct {
	Name       string `json:"name"`
	Path       string `json:"path"`
	SHA256     string `json:"sha256"`
	License    string `json:"license"`
	LicenseURL string `json:"license_url"`
}

type Template struct {
	RightsEvidenceURL string            `json:"rights_evidence_url"`
	ID                string            `json:"id"`
	AddedAt           string            `json:"added_at"`
	Name              map[string]string `json:"name"`
	Description       map[string]string `json:"description"`
	Notes             map[string]string `json:"notes"`
	Provider          string            `json:"provider"`
	ProviderID        string            `json:"provider_id"`
	Author            string            `json:"author"`
	License           string            `json:"license"`
	LicenseURL        string            `json:"license_url"`
	Revision          string            `json:"revision"`
	SourceURL         string            `json:"source_url"`
	DemoURL           string            `json:"demo_url"`
	Category          string            `json:"category"`
	Kind              string            `json:"kind,omitempty"`
	Subcategory       string            `json:"subcategory,omitempty"`
	Styles            []string          `json:"styles,omitempty"`
	Frameworks        []string          `json:"frameworks"`
	Aliases           []string          `json:"aliases"`
	Files             []File            `json:"files"`
	Notices           []File            `json:"notices"`
	Assets            []Asset           `json:"assets"`
	Props             map[string]any    `json:"props"`
	Dependencies      map[string]string `json:"dependencies"`
	ExportName        string            `json:"export_name"`
	PreviewURL        string            `json:"preview_url"`
	PosterURL         string            `json:"poster_url"`
}

// LicenseNotices carries the original upstream license and attribution texts.
func (c *Catalog) LicenseNotices(id string) (map[string]string, error) {
	item, ok := c.Get(id)
	if !ok {
		return nil, fmt.Errorf("unknown template")
	}
	notices := map[string]string{}
	for _, file := range item.Notices {
		content, err := assets.ReadFile("data/" + file.Path)
		if err != nil {
			return nil, err
		}
		notices[file.Name] = string(content)
	}
	return notices, nil
}

type Catalog struct {
	items []Template
}

func New() (*Catalog, error) {
	raw, err := assets.ReadFile("data/catalog.json")
	if err != nil {
		return nil, err
	}
	var payload struct {
		Version int        `json:"version"`
		Items   []Template `json:"items"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, err
	}
	if payload.Version != 1 || len(payload.Items) == 0 {
		return nil, fmt.Errorf("unsupported or empty UI catalog")
	}
	seen := map[string]bool{}
	proofs := map[string]*rightsEvidence{}
	for _, item := range payload.Items {
		if item.ID == "" || seen[item.ID] || len(item.Files) == 0 || item.Name["zh"] == "" || item.Name["en"] == "" {
			return nil, fmt.Errorf("invalid UI template: %s", item.ID)
		}
		seen[item.ID] = true
		proof := proofs[item.RightsEvidenceURL]
		if proof == nil {
			proof, err = loadRightsEvidence(assets, item)
			if err != nil {
				return nil, err
			}
			proofs[item.RightsEvidenceURL] = proof
		}
		if proof.Revision != item.Revision || proof.License != item.License {
			return nil, fmt.Errorf("rights evidence mismatch: %s", item.ID)
		}
		if _, err := assets.ReadFile("data/licenses/" + item.ProviderID + "/LICENSE"); err != nil {
			return nil, err
		}
		for _, file := range item.Files {
			if proof.SourceFiles[file.Path] != file.SHA256 {
				return nil, fmt.Errorf("source absent from rights evidence: %s", file.Path)
			}
			if !fs.ValidPath(file.Path) || !strings.HasPrefix(file.Path, "sources/"+item.ProviderID+"/") {
				return nil, fmt.Errorf("invalid UI source path: %s", file.Path)
			}
			content, err := assets.ReadFile("data/" + file.Path)
			if err != nil {
				return nil, err
			}
			hash := sha256.Sum256(content)
			if hex.EncodeToString(hash[:]) != file.SHA256 {
				return nil, fmt.Errorf("UI source integrity failed: %s", file.Path)
			}
			if len(content) > MaxSourceFileBytes {
				return nil, fmt.Errorf("UI source exceeds single-file budget: %s", file.Path)
			}
		}
	}
	return &Catalog{items: payload.Items}, nil
}

// Items returns the validated templates in catalog order (a copy).
func (c *Catalog) Items() []Template {
	return slices.Clone(c.items)
}

func (c *Catalog) Get(id string) (Template, bool) {
	for _, item := range c.items {
		if item.ID == id {
			return item, true
		}
	}
	return Template{}, false
}

// Source accepts only a file belonging to this catalog, never a caller-supplied path.
func (c *Catalog) Source(id, name string) (string, error) {
	item, ok := c.Get(id)
	if !ok {
		return "", fmt.Errorf("unknown template")
	}
	for _, file := range item.Files {
		if file.Name == name {
			content, err := assets.ReadFile("data/" + file.Path)
			return string(content), err
		}
	}
	return "", fmt.Errorf("unknown source file")
}

var tokens = regexp.MustCompile(`[a-z0-9]+|\p{Han}+`)
var han = regexp.MustCompile(`\p{Han}`)
var stopWords = strings.Fields("a an the for with and in make build please show me")
var adaptiveStopWords = strings.Fields("ui component components template templates effect effects frontend page pages website web design make build create dark futuristic modern clean professional ai 组件 素材 模板 效果 前端 页面 网站 设计 做 实现 创建 深色 科技感 高级")

func normalize(value string) string {
	return strings.ToLower(strings.TrimSpace(norm.NFKC.String(value)))
}

// Terms uses the same bilingual vocabulary and scoring contract as the website.
func (c *Catalog) Terms(query string) []string {
	vocabulary := []string{}
	for _, item := range c.items {
		for _, alias := range item.Aliases {
			if !slices.Contains(vocabulary, alias) {
				vocabulary = append(vocabulary, alias)
			}
		}
	}
	terms := []string{}
	for _, term := range tokens.FindAllString(normalize(query), -1) {
		if slices.Contains(stopWords, term) {
			continue
		}
		known := []string{}
		if han.MatchString(term) {
			for _, alias := range vocabulary {
				if han.MatchString(alias) && strings.Contains(term, alias) {
					known = append(known, alias)
				}
			}
		}
		if len(known) > 0 {
			terms = append(terms, known...)
		} else {
			terms = append(terms, term)
		}
	}
	return terms
}

// matchesFilters is the category/framework gate shared by every search pass.
func matchesFilters(item Template, category, framework string) bool {
	return !(category != "" && item.Category != category && item.Subcategory != category || framework != "" && !slices.Contains(item.Frameworks, framework))
}

// Lookup returns the templates for ids in the given order, skipping unknown
// ids and templates outside the category/framework filters.
func (c *Catalog) Lookup(ids []string, category, framework string) []Template {
	index := make(map[string]int, len(c.items))
	for position, item := range c.items {
		index[item.ID] = position
	}
	items := make([]Template, 0, len(ids))
	for _, id := range ids {
		position, ok := index[id]
		if ok && matchesFilters(c.items[position], category, framework) {
			items = append(items, c.items[position])
		}
	}
	return items
}

func (c *Catalog) Search(query, category, framework string) []Template {
	type candidate struct {
		item  Template
		score int
	}
	results := []candidate{}
	terms := c.Terms(query)
	for _, item := range c.items {
		if !matchesFilters(item, category, framework) {
			continue
		}
		title := normalize(item.Name["zh"] + " " + item.Name["en"] + " " + item.ID)
		core := normalize(title + " " + item.Provider + " " + strings.Join(item.Aliases, " ") + " " + strings.Join(item.Frameworks, " ") + " " + item.Category)
		all := core + " " + normalize(item.Description["zh"]+" "+item.Description["en"])
		score, matches := 0, true
		for _, term := range terms {
			if !strings.Contains(all, term) {
				matches = false
				break
			}
			switch {
			case strings.Contains(title, term):
				score += 20
			case strings.Contains(core, term):
				score += 10
			default:
				score++
			}
		}
		if matches {
			results = append(results, candidate{item: item, score: score})
		}
	}
	sort.SliceStable(results, func(i, j int) bool { return results[i].score > results[j].score })
	items := make([]Template, 0, len(results))
	for _, result := range results {
		items = append(items, result.item)
	}
	return items
}

// SearchAdaptive keeps the strict all-terms contract as its first pass, then
// relaxes only an empty multi-term result. This lets agents send a natural
// language design brief without having to guess the catalog's exact aliases.
// A category fallback is intentionally available only when the caller supplied
// a category; an unrelated free-text query must still return no results.
func (c *Catalog) SearchAdaptive(query, category, framework string) ([]Template, string) {
	if items := c.Search(query, category, framework); len(items) > 0 || normalize(query) == "" {
		return items, "exact"
	}

	terms := []string{}
	for _, term := range c.Terms(query) {
		if (!han.MatchString(term) && len(term) < 3) || slices.Contains(adaptiveStopWords, term) || slices.Contains(terms, term) {
			continue
		}
		terms = append(terms, term)
	}
	if len(terms) > 1 {
		type candidate struct {
			item    Template
			matches int
			score   int
		}
		results := []candidate{}
		for _, item := range c.items {
			if !matchesFilters(item, category, framework) {
				continue
			}
			title := normalize(item.Name["zh"] + " " + item.Name["en"] + " " + item.ID)
			core := normalize(title + " " + item.Provider + " " + strings.Join(item.Aliases, " ") + " " + strings.Join(item.Frameworks, " ") + " " + item.Category)
			all := core + " " + normalize(item.Description["zh"]+" "+item.Description["en"])
			matches, score := 0, 0
			for _, term := range terms {
				if !strings.Contains(all, term) {
					continue
				}
				matches++
				switch {
				case strings.Contains(title, term):
					score += 20
				case strings.Contains(core, term):
					score += 10
				default:
					score++
				}
			}
			if matches > 0 {
				results = append(results, candidate{item: item, matches: matches, score: score})
			}
		}
		sort.SliceStable(results, func(i, j int) bool {
			if results[i].matches != results[j].matches {
				return results[i].matches > results[j].matches
			}
			return results[i].score > results[j].score
		})
		if len(results) > 0 {
			bestMatches := results[0].matches
			items := []Template{}
			for _, result := range results {
				if result.matches != bestMatches {
					break
				}
				items = append(items, result.item)
			}
			return items, "relaxed_terms"
		}
	}

	if category != "" {
		if items := c.Search("", category, framework); len(items) > 0 {
			return items, "category_fallback"
		}
	}
	return []Template{}, "exact"
}
