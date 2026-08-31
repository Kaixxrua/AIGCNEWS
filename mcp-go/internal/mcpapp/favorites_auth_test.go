package mcpapp

import (
	"testing"

	"aigcnews/mcp-go/internal/authn"
)

type favoritesAuthReaderStub struct {
	calls  int
	userID int
}

func (r *favoritesAuthReaderStub) ListUserProjectCollection(filters ProjectCollectionFilters) (ProjectCollectionPage, error) {
	r.calls++
	r.userID = filters.UserID
	return ProjectCollectionPage{Items: []map[string]any{}, Total: 0}, nil
}

func TestFavoritesServiceAuthorization(t *testing.T) {
	reader := &favoritesAuthReaderStub{}
	service := NewFavoritesService(reader, "https://aigcnews.cn")
	cases := []struct {
		name     string
		identity authn.Identity
		args     map[string]any
		want     string
	}{
		{
			name:     "anonymous-before-validation",
			identity: authn.Identity{},
			args:     map[string]any{"limit": "bad"},
			want:     "Authentication is required for this tool.",
		},
		{
			name:     "missing-scope",
			identity: authn.Identity{UserID: 7},
			args:     map[string]any{},
			want:     "This token requires the projects:favorites:read scope.",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			reader.calls = 0
			_, err := service.Get(tc.identity, tc.args)
			if err == nil || err.Error() != tc.want {
				t.Fatalf("error=%v, want %q", err, tc.want)
			}
			if reader.calls != 0 {
				t.Fatalf("authorization failure called reader %d times", reader.calls)
			}
		})
	}
	_, err := service.Get(
		authn.Identity{UserID: 7, Scopes: []string{"projects:favorites:read"}},
		map[string]any{},
	)
	if err != nil {
		t.Fatalf("valid scoped identity failed: %v", err)
	}
	if reader.calls != 1 || reader.userID != 7 {
		t.Fatalf("valid request reader state=%+v", reader)
	}
}
