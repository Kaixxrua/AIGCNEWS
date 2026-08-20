package projectsem

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

type referenceIntent struct {
	SchemaVersion    string   `json:"schema_version"`
	NormalizedQuery  string   `json:"normalized_query"`
	Language         string   `json:"language"`
	LexicalTerms     []string `json:"lexical_terms"`
	SemanticQueries  []string `json:"semantic_queries"`
	IntentClass      string   `json:"intent_class"`
	Topics           []string `json:"topics"`
	Languages        []string `json:"languages"`
	ArtifactTypes    []string `json:"artifact_types"`
	MustHave         []string `json:"must_have"`
	ShouldHave       []string `json:"should_have"`
	ConceptIDs       []string `json:"concept_ids"`
	BilingualAliases []string `json:"bilingual_aliases"`
}

type referenceConcept struct {
	ConceptID    string   `json:"concept_id"`
	PrimaryTerms []string `json:"primary_terms"`
	Aliases      []string `json:"aliases"`
}

type referencePlan struct {
	NormalizedQuery string             `json:"normalized_query"`
	StrictTerms     []string           `json:"strict_terms"`
	Concepts        []referenceConcept `json:"concepts"`
}

type referenceQuery struct {
	Q          string          `json:"q"`
	Normalized string          `json:"normalized"`
	Terms      []string        `json:"terms"`
	Intent     referenceIntent `json:"intent"`
	Plan       referencePlan   `json:"plan"`
}

type referenceClient struct {
	Q       string                 `json:"q"`
	Payload referenceClientPayload `json:"payload"`
	OK      bool                   `json:"ok"`
	Intent  referenceIntent        `json:"intent"`
	Error   string                 `json:"error"`
}

type referenceClientPayload struct {
	Language        string   `json:"language"`
	IntentClass     string   `json:"intent_class"`
	LexicalTerms    []string `json:"lexical_terms"`
	SemanticQueries []string `json:"semantic_queries"`
	Topics          []string `json:"topics"`
	Languages       []string `json:"languages"`
	ArtifactTypes   []string `json:"artifact_types"`
	MustHave        []string `json:"must_have"`
	ShouldHave      []string `json:"should_have"`
}

func (p referenceClientPayload) clientIntentFields() ClientIntentFields {
	return ClientIntentFields{
		Language: p.Language, IntentClass: p.IntentClass,
		LexicalTerms: p.LexicalTerms, SemanticQueries: p.SemanticQueries,
		Topics: p.Topics, Languages: p.Languages, ArtifactTypes: p.ArtifactTypes,
		MustHave: p.MustHave, ShouldHave: p.ShouldHave,
	}
}

type referenceNorm struct {
	Values   []string `json:"values"`
	MaxItems int      `json:"max_items"`
	MaxChars int      `json:"max_chars"`
	OK       bool     `json:"ok"`
	Result   []string `json:"result"`
	Error    string   `json:"error"`
}

type conformanceFixture struct {
	Queries []referenceQuery  `json:"queries"`
	Clients []referenceClient `json:"clients"`
	Norms   []referenceNorm   `json:"norms"`
	Escapes [][2]string       `json:"escapes"`
}

func loadConformanceFixture(t *testing.T) conformanceFixture {
	t.Helper()
	data, err := os.ReadFile("testdata/conformance.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture conformanceFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	return fixture
}

func intentReference(i Intent) referenceIntent {
	return referenceIntent{
		SchemaVersion: i.SchemaVersion, NormalizedQuery: i.NormalizedQuery,
		Language: i.Language, LexicalTerms: i.LexicalTerms,
		SemanticQueries: i.SemanticQueries, IntentClass: i.IntentClass,
		Topics: i.Topics, Languages: i.Languages, ArtifactTypes: i.ArtifactTypes,
		MustHave: i.MustHave, ShouldHave: i.ShouldHave,
		ConceptIDs: i.ConceptIDs, BilingualAliases: i.BilingualAliases,
	}
}

func planReference(p LexicalRetrievalPlan) referencePlan {
	concepts := make([]referenceConcept, 0, len(p.Concepts))
	for _, c := range p.Concepts {
		concepts = append(concepts, referenceConcept{
			ConceptID: c.ConceptID, PrimaryTerms: c.PrimaryTerms, Aliases: c.Aliases,
		})
	}
	return referencePlan{NormalizedQuery: p.NormalizedQuery, StrictTerms: p.StrictTerms, Concepts: concepts}
}

func TestPythonConformance(t *testing.T) {
	fixture := loadConformanceFixture(t)
	for _, tc := range fixture.Queries {
		t.Run(tc.Q, func(t *testing.T) {
			if got := NormalizeSearchQuery(tc.Q); got != tc.Normalized {
				t.Errorf("NormalizeSearchQuery = %q, want %q", got, tc.Normalized)
			}
			if got := ProjectSearchTerms(tc.Q, 8); !reflect.DeepEqual(got, tc.Terms) {
				t.Errorf("ProjectSearchTerms = %#v, want %#v", got, tc.Terms)
			}
			gotIntent := intentReference(BuildProjectSearchIntent(tc.Q))
			if !reflect.DeepEqual(gotIntent, tc.Intent) {
				t.Errorf("BuildProjectSearchIntent = %#v, want %#v", gotIntent, tc.Intent)
			}
			gotPlan := planReference(BuildProjectLexicalRetrievalPlan(BuildProjectSearchIntent(tc.Q)))
			if !reflect.DeepEqual(gotPlan, tc.Plan) {
				t.Errorf("BuildProjectLexicalRetrievalPlan = %#v, want %#v", gotPlan, tc.Plan)
			}
		})
	}
	for _, tc := range fixture.Clients {
		t.Run("client/"+tc.Q, func(t *testing.T) {
			got, err := BuildClientProjectSearchIntent(tc.Q, tc.Payload.clientIntentFields())
			if tc.OK {
				if err != nil {
					t.Fatalf("BuildClientProjectSearchIntent error = %v", err)
				}
				if want := tc.Intent; !reflect.DeepEqual(intentReference(got), want) {
					t.Errorf("BuildClientProjectSearchIntent = %#v, want %#v", intentReference(got), want)
				}
				return
			}
			if err == nil || err.Error() != tc.Error {
				t.Errorf("BuildClientProjectSearchIntent error = %v, want %q", err, tc.Error)
			}
		})
	}
	for _, tc := range fixture.Norms {
		t.Run("normalize/"+tc.Error, func(t *testing.T) {
			got, err := NormalizeClientIntentValues(tc.Values, tc.MaxItems, tc.MaxChars)
			if tc.OK {
				if err != nil {
					t.Fatalf("NormalizeClientIntentValues error = %v", err)
				}
				if !reflect.DeepEqual(got, tc.Result) {
					t.Errorf("NormalizeClientIntentValues = %#v, want %#v", got, tc.Result)
				}
				return
			}
			if err == nil || err.Error() != tc.Error {
				t.Errorf("NormalizeClientIntentValues error = %v, want %q", err, tc.Error)
			}
		})
	}
	for _, tc := range fixture.Escapes {
		if got := EscapeLikeLiteral(tc[0]); got != tc[1] {
			t.Errorf("EscapeLikeLiteral(%q) = %q, want %q", tc[0], got, tc[1])
		}
	}
}

type lexiconReference struct {
	ConceptID string   `json:"concept_id"`
	Phrases   []string `json:"phrases"`
	Aliases   []string `json:"aliases"`
}

func TestLexiconMatchesPython(t *testing.T) {
	data, err := os.ReadFile("testdata/lexicon.json")
	if err != nil {
		t.Fatal(err)
	}
	var want []lexiconReference
	if err := json.Unmarshal(data, &want); err != nil {
		t.Fatal(err)
	}
	if len(projectConceptLexicon) != 115 {
		t.Fatalf("Go lexicon has %d specs, want 115", len(projectConceptLexicon))
	}
	if len(want) != len(projectConceptLexicon) {
		t.Fatalf("Python lexicon has %d specs, Go has %d", len(want), len(projectConceptLexicon))
	}
	for i, got := range projectConceptLexicon {
		if !reflect.DeepEqual(got.conceptID, want[i].ConceptID) ||
			!reflect.DeepEqual(got.phrases, want[i].Phrases) ||
			!reflect.DeepEqual(got.aliases, want[i].Aliases) {
			t.Errorf("lexicon[%d] = %#v, want %#v", i, got, want[i])
		}
	}
}
