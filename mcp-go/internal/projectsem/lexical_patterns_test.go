package projectsem

import (
	"encoding/json"
	"os"
	"regexp"
	"slices"
	"testing"
)

func TestConceptPatternsPreserveLiteralBoundaries(t *testing.T) {
	data, err := os.ReadFile("testdata/concept_patterns.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Term, Text string
		Match      bool
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		pattern := regexp.MustCompile("(?i)" + ConceptSearchPattern(tc.Term))
		if got := pattern.MatchString(tc.Text); got != tc.Match {
			t.Errorf("%q in %q = %v, want %v", tc.Term, tc.Text, got, tc.Match)
		}
	}
}

func TestLongTermMemoryKeepsCodebaseIntentSeparate(t *testing.T) {
	for _, q := range []string{"智能体长期记忆", "长期记忆", "agent long-term memory", "agent long term memory"} {
		intent := BuildProjectSearchIntent(q)
		if !slices.Equal(intent.ConceptIDs, []string{"agent_memory"}) {
			t.Errorf("%q concept IDs = %v", q, intent.ConceptIDs)
		}
		if plan := BuildProjectLexicalRetrievalPlan(intent); len(plan.StrictTerms) != 0 {
			t.Errorf("%q has unmatched terms: %v", q, plan.StrictTerms)
		}
	}
	for _, q := range []string{"代码库长期记忆", "项目长期记忆", "codebase memory"} {
		if ids := BuildProjectSearchIntent(q).ConceptIDs; !slices.Equal(ids, []string{"codebase_memory"}) {
			t.Errorf("%q concept IDs = %v", q, ids)
		}
	}
}
