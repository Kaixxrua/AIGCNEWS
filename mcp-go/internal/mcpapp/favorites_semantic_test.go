package mcpapp

import (
	"errors"
	"reflect"
	"testing"

	"aigcnews/mcp-go/internal/authn"
)

type favoritesFilterRecorder struct {
	filters []ProjectCollectionFilters
}

func (r *favoritesFilterRecorder) ListUserProjectCollection(filters ProjectCollectionFilters) (ProjectCollectionPage, error) {
	r.filters = append(r.filters, filters)
	return ProjectCollectionPage{Items: []map[string]any{}, Total: 0}, nil
}

type fakeFavoritesSemantic struct {
	ids     []string
	err     error
	userIDs []int
	queries []string
}

func (f *fakeFavoritesSemantic) SearchFavoriteRepoIDs(userID int, query string) ([]string, error) {
	f.userIDs = append(f.userIDs, userID)
	f.queries = append(f.queries, query)
	return f.ids, f.err
}

var favoritesReader = authn.Identity{UserID: 7, Scopes: []string{"projects:favorites:read"}}

func runFavorites(t *testing.T, semantic FavoritesSemanticSearcher, args map[string]any) ProjectCollectionFilters {
	t.Helper()
	reader := &favoritesFilterRecorder{}
	service := NewFavoritesService(reader, "https://aigcnews.cn")
	if semantic != nil {
		service = service.WithSemantic(semantic)
	}
	if _, err := service.Get(favoritesReader, args); err != nil {
		t.Fatalf("Get: %v", err)
	}
	if len(reader.filters) != 1 {
		t.Fatalf("reader calls = %d, want 1", len(reader.filters))
	}
	return reader.filters[0]
}

func TestFavoritesSemanticPassesHitsToReader(t *testing.T) {
	semantic := &fakeFavoritesSemantic{ids: []string{"acme/agent-memory", "R_kgDOSL4dpw"}}
	filters := runFavorites(t, semantic, map[string]any{"q": "长期记忆的智能体"})
	if !reflect.DeepEqual(filters.SemanticRepoIDs, semantic.ids) {
		t.Fatalf("SemanticRepoIDs = %v, want %v", filters.SemanticRepoIDs, semantic.ids)
	}
	if filters.Q != "长期记忆的智能体" {
		t.Fatalf("Q = %q, lexical filter must stay in place", filters.Q)
	}
	if !reflect.DeepEqual(semantic.userIDs, []int{7}) || !reflect.DeepEqual(semantic.queries, []string{"长期记忆的智能体"}) {
		t.Fatalf("semantic calls userIDs=%v queries=%v", semantic.userIDs, semantic.queries)
	}
}

func TestFavoritesSemanticFallsBackToLexicalFilters(t *testing.T) {
	args := map[string]any{"q": "agent memory", "sort": "stars"}
	want := runFavorites(t, nil, args)
	if want.SemanticRepoIDs != nil {
		t.Fatalf("no semantic lane produced SemanticRepoIDs=%v", want.SemanticRepoIDs)
	}
	for name, semantic := range map[string]*fakeFavoritesSemantic{
		"failing":  {err: errors.New("embedding 429")},
		"no-hits":  {ids: nil},
		"disabled": nil,
	} {
		t.Run(name, func(t *testing.T) {
			var lane FavoritesSemanticSearcher
			if semantic != nil {
				lane = semantic
			}
			got := runFavorites(t, lane, args)
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("filters = %+v, want lexical-only %+v", got, want)
			}
		})
	}
}

func TestFavoritesSemanticSkipsBlankQuery(t *testing.T) {
	semantic := &fakeFavoritesSemantic{ids: []string{"acme/x"}}
	for _, args := range []map[string]any{{}, {"q": "   "}} {
		filters := runFavorites(t, semantic, args)
		if filters.SemanticRepoIDs != nil {
			t.Fatalf("args=%v SemanticRepoIDs=%v, want nil", args, filters.SemanticRepoIDs)
		}
	}
	if len(semantic.queries) != 0 {
		t.Fatalf("blank query reached the semantic lane: %v", semantic.queries)
	}
}
