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

func TestArtifactAndNarrowConceptContracts(t *testing.T) {
	for _, query := range []string{"RAG 评估框架", "RAG evaluation framework", "RAG evaluation tools"} {
		plan := BuildProjectLexicalRetrievalPlan(BuildProjectSearchIntent(query))
		if len(plan.StrictTerms) != 0 || len(plan.Concepts) != 2 {
			t.Fatalf("%s: %#v", query, plan)
		}
		for _, concept := range plan.Concepts {
			if concept.ConceptID == "rag" && slices.Contains(concept.Aliases, "knowledge base") {
				t.Fatal("explicit RAG query expanded to broad knowledge-base matches")
			}
		}
	}
	plan := BuildProjectLexicalRetrievalPlan(BuildProjectSearchIntent("codebase memory"))
	if slices.Contains(plan.Concepts[0].Aliases, "编程智能体") || slices.Contains(plan.Concepts[0].Aliases, "knowledge graph") {
		t.Fatal("codebase memory expanded to all coding assistants or knowledge graphs")
	}
	for _, query := range []string{"Agent 任务跟踪", "agent task tracking"} {
		plan := BuildProjectLexicalRetrievalPlan(BuildProjectSearchIntent(query))
		if len(plan.StrictTerms) != 0 || len(plan.Concepts) != 1 || plan.Concepts[0].ConceptID != "agent_task_tracking" {
			t.Fatalf("%s: %#v", query, plan)
		}
	}
}
