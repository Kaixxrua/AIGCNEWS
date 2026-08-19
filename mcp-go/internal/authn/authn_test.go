package authn

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

type fakeDB struct {
	tx  *fakeTx
	err error
}

func (d fakeDB) Begin(context.Context) (Tx, error) {
	if d.err != nil {
		return nil, d.err
	}
	return d.tx, nil
}

type fakeTx struct {
	row         pgx.Row
	lookupSQL   string
	lookupArgs  []any
	updateSQL   string
	updateArgs  []any
	committed   bool
	rolledBack  bool
	execErr     error
	commitError error
}

func (t *fakeTx) QueryRow(_ context.Context, sql string, args ...any) pgx.Row {
	t.lookupSQL, t.lookupArgs = sql, args
	return t.row
}

func (t *fakeTx) Exec(_ context.Context, sql string, args ...any) (pgconn.CommandTag, error) {
	t.updateSQL, t.updateArgs = sql, args
	if t.execErr != nil {
		return pgconn.CommandTag{}, t.execErr
	}
	return pgconn.NewCommandTag("UPDATE 1"), nil
}

func (t *fakeTx) Commit(context.Context) error {
	if t.commitError != nil {
		return t.commitError
	}
	t.committed = true
	return nil
}

func (t *fakeTx) Rollback(context.Context) error { t.rolledBack = true; return nil }

type fakeRow struct {
	values []any
	err    error
}

func (r fakeRow) Scan(dest ...any) error {
	if r.err != nil {
		return r.err
	}
	for i, value := range r.values {
		switch d := dest[i].(type) {
		case *int:
			*d = value.(int)
		case *string:
			*d = value.(string)
		case *any:
			*d = value
		}
	}
	return nil
}

func authenticator(tx *fakeTx) Authenticator {
	return Authenticator{DB: fakeDB{tx: tx}}
}

func TestAuthenticateAnonymous(t *testing.T) {
	identity, response := (Authenticator{}).Authenticate(context.Background(), "")
	if response != nil || identity.UserID != 0 {
		t.Fatalf("got identity=%+v response=%v", identity, response)
	}
}

func TestAuthenticateRejectsNonBearer(t *testing.T) {
	_, response := (Authenticator{}).Authenticate(context.Background(), "Basic abc")
	assertUnauthorized(t, response, invalidSchemeDetail)
}

func TestAuthenticateLookupAndConditionalTouch(t *testing.T) {
	tx := &fakeTx{row: fakeRow{values: []any{7, 42, `["projects:favorites:read"]`, nil, nil, nil, "u@example.com", "user", "pro"}}}
	identity, response := authenticator(tx).Authenticate(context.Background(), "bEaReR secret")
	if response != nil {
		t.Fatalf("unexpected response: %+v", response)
	}
	if identity.UserID != 42 || identity.Email != "u@example.com" ||
		identity.Role != "user" || identity.MembershipTier != "pro" ||
		len(identity.Scopes) != 1 || !identity.HasScope("projects:favorites:read") ||
		identity.HasScope("projects:favorites:write") {
		t.Fatalf("bad identity: %+v", identity)
	}
	if !tx.committed || tx.rolledBack {
		t.Fatalf("transaction not committed exactly once: %+v", tx)
	}
	if len(tx.lookupArgs) != 1 {
		t.Fatalf("lookup args = %v, want single sha256 hex", tx.lookupArgs)
	}
	if digest, ok := tx.lookupArgs[0].(string); !ok || len(digest) != 64 {
		t.Fatalf("lookup arg = %v, want 64-char sha256 hex", tx.lookupArgs[0])
	}
	if len(tx.updateArgs) != 1 || tx.updateArgs[0] != 7 {
		t.Fatalf("last_used update args = %v, want token id 7", tx.updateArgs)
	}
}

func TestAuthenticateMissingToken(t *testing.T) {
	tx := &fakeTx{row: fakeRow{err: pgx.ErrNoRows}}
	_, response := authenticator(tx).Authenticate(context.Background(), "Bearer nope")
	assertUnauthorized(t, response, invalidTokenDetail)
	if !tx.rolledBack || tx.committed {
		t.Fatalf("missing token must rollback without commit: %+v", tx)
	}
}

func TestAuthenticateMalformedScopes(t *testing.T) {
	for name, raw := range map[string]string{
		"non-string-element": `["read",3]`,
		"bare-string":        `"oops"`,
		"null":               `null`,
		"not-json":           `oops`,
		"object":             `{"read":true}`,
	} {
		t.Run(name, func(t *testing.T) {
			tx := &fakeTx{row: fakeRow{values: []any{7, 42, raw, nil, nil, nil, "u@example.com", "user", "free"}}}
			_, response := authenticator(tx).Authenticate(context.Background(), "Bearer secret")
			assertUnauthorized(t, response, invalidScopesDetail)
		})
	}
}

func TestAuthenticateDatabaseFailures(t *testing.T) {
	t.Run("begin", func(t *testing.T) {
		auth := Authenticator{DB: fakeDB{err: errors.New("pool exhausted")}}
		_, response := auth.Authenticate(context.Background(), "Bearer x")
		assertInternalError(t, response)
	})
	t.Run("query", func(t *testing.T) {
		tx := &fakeTx{row: fakeRow{err: errors.New("database down")}}
		_, response := authenticator(tx).Authenticate(context.Background(), "Bearer x")
		assertInternalError(t, response)
	})
	t.Run("update", func(t *testing.T) {
		tx := &fakeTx{
			row:     fakeRow{values: []any{7, 42, `[]`, nil, nil, nil, "u@example.com", "user", "free"}},
			execErr: errors.New("lock timeout"),
		}
		_, response := authenticator(tx).Authenticate(context.Background(), "Bearer x")
		assertInternalError(t, response)
	})
	t.Run("commit", func(t *testing.T) {
		tx := &fakeTx{
			row:         fakeRow{values: []any{7, 42, `[]`, nil, nil, nil, "u@example.com", "user", "free"}},
			commitError: errors.New("commit failed"),
		}
		_, response := authenticator(tx).Authenticate(context.Background(), "Bearer x")
		assertInternalError(t, response)
	})
}

func assertUnauthorized(t *testing.T, response *Response, detail string) {
	t.Helper()
	if response == nil || response.Status != http.StatusUnauthorized {
		t.Fatalf("got %+v", response)
	}
	if string(response.Body) != `{"detail":"`+detail+`"}` {
		t.Fatalf("body=%s", response.Body)
	}
	if response.Headers.Get("WWW-Authenticate") != "Bearer" {
		t.Fatalf("headers=%v", response.Headers)
	}
	if response.Headers.Get("MCP-Protocol-Version") != "" {
		t.Fatalf("protocol header leaked: %v", response.Headers)
	}
}

func assertInternalError(t *testing.T, response *Response) {
	t.Helper()
	if response == nil || response.Status != http.StatusInternalServerError {
		t.Fatalf("got %+v", response)
	}
	if string(response.Body) != "Internal Server Error" {
		t.Fatalf("body=%q, must not leak internals", response.Body)
	}
	if response.Headers.Get("Content-Type") != "text/plain; charset=utf-8" {
		t.Fatalf("content-type=%v", response.Headers)
	}
}

// 401 写出形状钉死：application/json + 显式长度 + WWW-Authenticate。
func TestResponseWrite(t *testing.T) {
	rec := httptest.NewRecorder()
	unauthorized(invalidTokenDetail).Write(rec)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d", rec.Code)
	}
	if rec.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("content-type=%q", rec.Header().Get("Content-Type"))
	}
	if rec.Header().Get("Content-Length") != "53" {
		t.Fatalf("content-length=%q", rec.Header().Get("Content-Length"))
	}
	if rec.Body.String() != `{"detail":"MCP Token 无效、已过期或已撤销"}` {
		t.Fatalf("body=%q", rec.Body.String())
	}
}
