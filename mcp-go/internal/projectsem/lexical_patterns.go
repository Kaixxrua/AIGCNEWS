package projectsem

import "regexp"

// ConceptSearchPattern mirrors project_search_patterns.concept_search_pattern.
// Parameters stay literal; ASCII concepts cannot match fragments of other words.
func ConceptSearchPattern(term string) string {
	escaped := regexp.QuoteMeta(term)
	for _, r := range term {
		if r > 127 {
			return escaped
		}
	}
	return "(^|[^a-z0-9])" + escaped + "($|[^a-z0-9])"
}
