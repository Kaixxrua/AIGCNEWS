package projectsem

import (
	"slices"
	"testing"
)

func TestHostLexicalHintsPreserveOriginalChineseNames(t *testing.T) {
	intent, err := BuildClientProjectSearchIntent("混元 RAG", ClientIntentFields{
		Language: "mixed", LexicalTerms: []string{"RAG", "offline", "Offline", "教程"},
		SemanticQueries: []string{"混元 RAG offline tutorials"},
	})
	if err != nil {
		t.Fatal(err)
	}
	plan := BuildProjectLexicalRetrievalPlan(intent)
	if !slices.Equal(plan.StrictTerms, []string{"混元", "offline"}) {
		t.Fatalf("lost query or hints: %#v", plan)
	}
	if len(plan.Concepts) != 2 || plan.Concepts[0].ConceptID != "rag" || plan.Concepts[1].ConceptID != "learning" {
		t.Fatalf("concepts: %#v", plan.Concepts)
	}
}
