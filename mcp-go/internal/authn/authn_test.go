package authn

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
)

type fakeDB struct {
	tx     *fakeTx
	err    error
	begins *int
}

func (d fakeDB) Begin(context.Context) (Tx, error) {
	if d.begins != nil {
		*d.begins = *d.begins + 1
	}
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

// fakeRow 的 nil 表示 SQL NULL，照 pgx 的规则处理：扫进 *string 报错，扫进指针得 nil
// （见 TestFakeRowNullRulesMatchPgx）。
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
			if value == nil {
				return errors.New("can't scan NULL into *string")
			}
			*d = value.(string)
		case **string:
			if value == nil {
				*d = nil
			} else {
				v := value.(string)
				*d = &v
			}
		case **time.Time:
			if value == nil {
				*d = nil
			} else {
				v := value.(time.Time)
				*d = &v
			}
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
	identity, authenticated, response := (Authenticator{}).Authenticate(context.Background(), "")
	if response != nil || authenticated || identity.UserID != 0 {
		t.Fatalf("got identity=%+v authenticated=%v response=%v", identity, authenticated, response)
	}
}

func TestAuthenticateRejectsNonBearer(t *testing.T) {
	_, authenticated, response := (Authenticator{}).Authenticate(context.Background(), "Basic abc")
	if authenticated {
		t.Fatal("invalid scheme marked authenticated")
	}
	assertUnauthorized(t, response, invalidSchemeDetail, "")
}

func TestAuthenticateRejectsMalformedBearerBeforeDatabase(t *testing.T) {
	cases := map[string]string{
		"empty":           "Bearer ",
		"whitespace-only": "Bearer \t",
		"extra-space":     "Bearer  secret",
		"trailing-space":  "Bearer secret ",
		"tab":             "Bearer sec\tret",
		"newline":         "Bearer sec\nret",
		"carriage-return": "Bearer sec\rret",
	}
	for name, header := range cases {
		t.Run(name, func(t *testing.T) {
			begins := 0
			identity, authenticated, response := (Authenticator{DB: fakeDB{begins: &begins}}).Authenticate(context.Background(), header)
			if response == nil || response.Status != http.StatusUnauthorized || response.BearerError != BearerInvalidToken {
				t.Fatalf("header %q got response=%+v", header, response)
			}
			if authenticated || identity.UserID != 0 {
				t.Fatalf("header %q got identity=%+v authenticated=%v", header, identity, authenticated)
			}
			if begins != 0 {
				t.Fatalf("malformed header %q touched database %d times", header, begins)
			}
		})
	}
}

func TestAuthenticateAcceptsOpaqueEmbeddedSpaceToken(t *testing.T) {
	begins := 0
	tx := &fakeTx{row: fakeRow{err: pgx.ErrNoRows}}
	_, authenticated, response := (Authenticator{DB: fakeDB{tx: tx, begins: &begins}}).Authenticate(context.Background(), "Bearer opaque token")
	if authenticated {
		t.Fatal("unknown opaque token marked authenticated")
	}
	assertUnauthorized(t, response, invalidTokenDetail, BearerInvalidToken)
	if begins != 1 {
		t.Fatalf("embedded ordinary spaces should be treated as token data, begins=%d", begins)
	}
}

func TestAuthenticateLookupAndConditionalTouch(t *testing.T) {
	tx := &fakeTx{row: fakeRow{values: []any{7, 42, `["projects:favorites:read"]`, nil, nil, nil, "u@example.com", "user", "member", nil}}}
	identity, authenticated, response := authenticator(tx).Authenticate(context.Background(), "bEaReR secret")
	if response != nil || !authenticated {
		t.Fatalf("authenticated=%v response=%+v", authenticated, response)
	}
	if identity.UserID != 42 || identity.Email != "u@example.com" ||
		identity.Role != "user" || identity.MembershipTier != "member" ||
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

func TestFakeRowNullRulesMatchPgx(t *testing.T) {
	types := pgtype.NewMap()
	var plain string
	if err := types.Scan(pgtype.TextOID, pgtype.TextFormatCode, nil, &plain); err == nil {
		t.Fatal("pgx scanned NULL into *string; fakeRow's NULL rule is out of date")
	}
	if err := (fakeRow{values: []any{nil}}).Scan(&plain); err == nil {
		t.Fatal("fakeRow scanned NULL into *string")
	}
	pointer := new(string)
	if err := types.Scan(pgtype.TextOID, pgtype.TextFormatCode, nil, &pointer); err != nil || pointer != nil {
		t.Fatalf("pgx NULL into **string: pointer=%v err=%v", pointer, err)
	}
	pointer = new(string)
	if err := (fakeRow{values: []any{nil}}).Scan(&pointer); err != nil || pointer != nil {
		t.Fatalf("fakeRow NULL into **string: pointer=%v err=%v", pointer, err)
	}
}

// 手机号注册的用户 email 为 NULL，role 列也可空：令牌照常可用，按空串处理（不是 admin）。
func TestAuthenticateNullUserColumns(t *testing.T) {
	tx := &fakeTx{row: fakeRow{values: []any{7, 42, `["projects:favorites:read"]`, nil, nil, nil, nil, nil, "member", nil}}}
	identity, authenticated, response := authenticator(tx).Authenticate(context.Background(), "Bearer secret")
	if response != nil || !authenticated {
		t.Fatalf("authenticated=%v response=%+v", authenticated, response)
	}
	if identity.UserID != 42 || identity.Email != "" || identity.Role != "" || identity.MembershipTier != "member" {
		t.Fatalf("bad identity: %+v", identity)
	}
	if !tx.committed || tx.rolledBack || len(tx.updateArgs) != 1 || tx.updateArgs[0] != 7 {
		t.Fatalf("token use not recorded and committed: %+v", tx)
	}
}

func TestAuthenticateMissingToken(t *testing.T) {
	tx := &fakeTx{row: fakeRow{err: pgx.ErrNoRows}}
	_, authenticated, response := authenticator(tx).Authenticate(context.Background(), "Bearer nope")
	if authenticated {
		t.Fatal("missing token marked authenticated")
	}
	assertUnauthorized(t, response, invalidTokenDetail, BearerInvalidToken)
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
			tx := &fakeTx{row: fakeRow{values: []any{7, 42, raw, nil, nil, nil, "u@example.com", "user", "free", nil}}}
			_, authenticated, response := authenticator(tx).Authenticate(context.Background(), "Bearer secret")
			if authenticated {
				t.Fatal("malformed scopes marked authenticated")
			}
			assertUnauthorized(t, response, invalidScopesDetail, BearerInvalidToken)
			if tx.updateSQL != "" || tx.committed || !tx.rolledBack {
				t.Fatalf("malformed scopes must rollback without usage write or commit: %+v", tx)
			}
		})
	}
}

func TestAuthenticateDatabaseFailures(t *testing.T) {
	t.Run("nil-db", func(t *testing.T) {
		_, authenticated, response := (Authenticator{}).Authenticate(context.Background(), "Bearer x")
		if authenticated {
			t.Fatal("nil database marked authenticated")
		}
		assertInternalError(t, response)
	})
	t.Run("nil-pool", func(t *testing.T) {
		_, authenticated, response := (Authenticator{DB: PgxQuerier{}}).Authenticate(context.Background(), "Bearer x")
		if authenticated {
			t.Fatal("nil pool marked authenticated")
		}
		assertInternalError(t, response)
	})
	t.Run("begin", func(t *testing.T) {
		auth := Authenticator{DB: fakeDB{err: errors.New("pool exhausted")}}
		_, authenticated, response := auth.Authenticate(context.Background(), "Bearer x")
		if authenticated {
			t.Fatal("begin failure marked authenticated")
		}
		assertInternalError(t, response)
	})
	t.Run("query", func(t *testing.T) {
		tx := &fakeTx{row: fakeRow{err: errors.New("database down")}}
		_, authenticated, response := authenticator(tx).Authenticate(context.Background(), "Bearer x")
		if authenticated {
			t.Fatal("query failure marked authenticated")
		}
		assertInternalError(t, response)
		if !tx.rolledBack || tx.committed {
			t.Fatalf("query failure must rollback: %+v", tx)
		}
	})
	t.Run("update", func(t *testing.T) {
		tx := &fakeTx{
			row:     fakeRow{values: []any{7, 42, `[]`, nil, nil, nil, "u@example.com", "user", "free", nil}},
			execErr: errors.New("lock timeout"),
		}
		_, authenticated, response := authenticator(tx).Authenticate(context.Background(), "Bearer x")
		if authenticated {
			t.Fatal("update failure marked authenticated")
		}
		assertInternalError(t, response)
		if !tx.rolledBack || tx.committed {
			t.Fatalf("update failure must rollback: %+v", tx)
		}
	})
	t.Run("commit", func(t *testing.T) {
		tx := &fakeTx{
			row:         fakeRow{values: []any{7, 42, `[]`, nil, nil, nil, "u@example.com", "user", "free", nil}},
			commitError: errors.New("commit failed"),
		}
		_, authenticated, response := authenticator(tx).Authenticate(context.Background(), "Bearer x")
		if authenticated {
			t.Fatal("commit failure marked authenticated")
		}
		assertInternalError(t, response)
		if !tx.rolledBack || tx.committed {
			t.Fatalf("commit failure must rollback: %+v", tx)
		}
	})
}

func assertUnauthorized(t *testing.T, response *Response, detail, bearerError string) {
	t.Helper()
	if response == nil || response.Status != http.StatusUnauthorized {
		t.Fatalf("got %+v", response)
	}
	if response.BearerError != bearerError {
		t.Fatalf("bearer error=%q, want %q", response.BearerError, bearerError)
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
	// BearerError 不进 /api/mcp 的线上字节：质询头仍是裸 Bearer。
	unauthorized(invalidTokenDetail, BearerInvalidToken).Write(rec)
	if rec.Header().Get("WWW-Authenticate") != "Bearer" {
		t.Fatalf("www-authenticate=%q", rec.Header().Get("WWW-Authenticate"))
	}
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

// Active authenticated accounts keep full access regardless of historical billing tier.
func TestEffectiveTier(t *testing.T) {
	now := time.Date(2026, 8, 19, 12, 0, 0, 0, time.UTC)
	past := now.Add(-time.Second)
	future := now.Add(time.Hour)
	for name, tc := range map[string]struct {
		identity Identity
		want     string
	}{
		"anonymous":               {Identity{}, TierFree},
		"anonymous-claims-member": {Identity{MembershipTier: TierMember}, TierFree},
		"unknown-tier":            {Identity{UserID: 7, MembershipTier: "pro"}, TierMember},
		"empty-tier":              {Identity{UserID: 7, MembershipTier: ""}, TierMember},
		"free":                    {Identity{UserID: 7, MembershipTier: "free"}, TierMember},
		"member-no-expiry":        {Identity{UserID: 7, MembershipTier: "member"}, TierMember},
		"member-future":           {Identity{UserID: 7, MembershipTier: "member", MembershipExpiresAt: &future}, TierMember},
		"member-expired":          {Identity{UserID: 7, MembershipTier: "member", MembershipExpiresAt: &past}, TierMember},
		"member-at-boundary":      {Identity{UserID: 7, MembershipTier: "member", MembershipExpiresAt: &now}, TierMember},
	} {
		t.Run(name, func(t *testing.T) {
			if got := tc.identity.EffectiveTier(now); got != tc.want {
				t.Fatalf("EffectiveTier = %q, want %q", got, tc.want)
			}
		})
	}
}
