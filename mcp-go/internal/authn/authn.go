// Package authn 实现 /api/mcp 的可选 Bearer token 认证，逐项对齐
// backend/app/core/auth.py OptionalMcpUser 与
// postgres_mcp_access_token_repository.get_user_by_mcp_token_hash：
//
//   - 无 Authorization 头 → 匿名（不报错）；
//   - 提供了非 Bearer 头 → 401 {"detail":"Authorization 必须使用 Bearer Token"}；
//   - Bearer token 取 SHA-256 hex 反查，不存在/过期/撤销/禁用 →
//     401 {"detail":"MCP Token 无效、已过期或已撤销"}；
//   - scopes 不是字符串列表 → 401 {"detail":"MCP Token 权限无效"}；
//   - 401 一律带 WWW-Authenticate: Bearer，且不带 MCP 协议头。
package authn

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"aigcnews/mcp-go/internal/jsonx"
)

const (
	invalidSchemeDetail = "Authorization 必须使用 Bearer Token"
	invalidTokenDetail  = "MCP Token 无效、已过期或已撤销"
	invalidScopesDetail = "MCP Token 权限无效"
)

// Identity 是认证通过后的用户视图；字段对齐 Python 侧 user dict 的消费面
// （user_id/email/role/membership_tier + scopes 集合）。
type Identity struct {
	UserID         int
	Email          string
	Role           string
	MembershipTier string
	Scopes         []string
}

// HasScope 对齐 McpAuthorizationContext.has_scope。
func (i Identity) HasScope(scope string) bool {
	for _, s := range i.Scopes {
		if s == scope {
			return true
		}
	}
	return false
}

// Response 是认证失败的 HTTP 投射（独立于 wire 层，避免环依赖）。
type Response struct {
	Status  int
	Body    []byte
	Headers http.Header
}

// Write 按 FastAPI JSONResponse/ServerErrorMiddleware 口径写出：
// 显式 Content-Type 与 Content-Length。
func (r *Response) Write(w http.ResponseWriter) {
	for key, values := range r.Headers {
		for _, value := range values {
			w.Header().Add(key, value)
		}
	}
	contentType := r.Headers.Get("Content-Type")
	if contentType == "" {
		contentType = "application/json"
	}
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Content-Length", strconv.Itoa(len(r.Body)))
	w.WriteHeader(r.Status)
	_, _ = w.Write(r.Body)
}

// Tx 是 token 认证需要的最小事务面；pgx.Tx 直接满足，测试用 fake。
type Tx interface {
	QueryRow(context.Context, string, ...any) pgx.Row
	Exec(context.Context, string, ...any) (pgconn.CommandTag, error)
	Commit(context.Context) error
	Rollback(context.Context) error
}

// Querier 开启事务；PgxQuerier 适配 pgxpool.Pool。
type Querier interface {
	Begin(context.Context) (Tx, error)
}

// PgxQuerier 把 pgxpool.Pool 适配到 Querier（pgx.Tx 是接口超集，
// 需要一次显式收窄）。
type PgxQuerier struct {
	Pool *pgxpool.Pool
}

func (q PgxQuerier) Begin(ctx context.Context) (Tx, error) {
	return q.Pool.Begin(ctx)
}

// Authenticator 按请求执行可选认证；DB 在启动期绑定。
type Authenticator struct {
	DB Querier
}

// Authenticate 认证一个 Authorization 头值。匿名返回零 Identity 与 nil
// 失败响应；任何"提供了但无效"的头都是 401。
func (a Authenticator) Authenticate(ctx context.Context, authorization string) (Identity, *Response) {
	if authorization == "" {
		return Identity{}, nil
	}
	if !strings.HasPrefix(strings.ToLower(authorization), "bearer ") {
		return Identity{}, unauthorized(invalidSchemeDetail)
	}

	token := authorization[len("Bearer "):]
	digest := sha256.Sum256([]byte(token))
	tx, err := a.DB.Begin(ctx)
	if err != nil {
		return Identity{}, internalError()
	}
	committed := false
	defer func() {
		if !committed {
			_ = tx.Rollback(ctx)
		}
	}()

	var row tokenRow
	err = tx.QueryRow(ctx, lookupSQL, hex.EncodeToString(digest[:])).Scan(
		&row.TokenID, &row.UserID, &row.ScopesJSON, &row.ExpiresAt,
		&row.RevokedAt, &row.DeletedAt, &row.Email, &row.Role,
		&row.MembershipTier,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return Identity{}, unauthorized(invalidTokenDetail)
	}
	if err != nil {
		return Identity{}, internalError()
	}
	if _, err = tx.Exec(ctx, lastUsedSQL, row.TokenID); err != nil {
		return Identity{}, internalError()
	}
	if err = tx.Commit(ctx); err != nil {
		return Identity{}, internalError()
	}
	committed = true

	scopes, ok := decodeScopes(row.ScopesJSON)
	if !ok {
		return Identity{}, unauthorized(invalidScopesDetail)
	}
	return Identity{
		UserID:         row.UserID,
		Email:          row.Email,
		Role:           row.Role,
		MembershipTier: row.MembershipTier,
		Scopes:         scopes,
	}, nil
}

type tokenRow struct {
	TokenID        int
	UserID         int
	ScopesJSON     string
	ExpiresAt      any
	RevokedAt      any
	DeletedAt      any
	Email          string
	Role           string
	MembershipTier string
}

// lookupSQL / lastUsedSQL 与 Python 仓储逐字同义（占位符 %s → $1 是
// psycopg → pgx 的机械转写）；列清单不得增删，SQL 行为属兼容面。
const lookupSQL = `
                    SELECT t.id AS token_id, t.user_id, t.scopes_json, t.expires_at,
                           t.revoked_at, t.deleted_at, u.email, u.role, u.membership_tier
                    FROM user_mcp_tokens t JOIN users u ON u.id = t.user_id
                    WHERE t.token_hash = $1 AND t.revoked_at IS NULL AND t.deleted_at IS NULL
                      AND (t.expires_at IS NULL OR t.expires_at > CURRENT_TIMESTAMP)
                      AND u.disabled = FALSE
                    LIMIT 1`

const lastUsedSQL = `
                        UPDATE user_mcp_tokens SET last_used_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                          AND (last_used_at IS NULL OR last_used_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes')`

// decodeScopes 对齐 OptionalMcpUser 的 isinstance(list) + 全 str 校验：
// scopes_json 非数组、元素非字符串、或 JSON 非法/为 null 均属权限无效。
func decodeScopes(raw string) ([]string, bool) {
	var scopes []string
	if err := json.Unmarshal([]byte(raw), &scopes); err != nil || scopes == nil {
		return nil, false
	}
	return scopes, true
}

func unauthorized(detail string) *Response {
	headers := http.Header{}
	headers.Set("WWW-Authenticate", "Bearer")
	return &Response{
		Status:  http.StatusUnauthorized,
		Body:    jsonx.MustMarshalCompact(jsonx.Object{{Key: "detail", Value: detail}}),
		Headers: headers,
	}
}

// internalError 对齐依赖阶段未捕获异常的 ServerErrorMiddleware 投射：
// 500 纯文本定长，不回泄内部错误细节。
func internalError() *Response {
	return &Response{
		Status:  http.StatusInternalServerError,
		Body:    []byte("Internal Server Error"),
		Headers: http.Header{"Content-Type": []string{"text/plain; charset=utf-8"}},
	}
}
