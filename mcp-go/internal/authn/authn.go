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
	"time"

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

// RFC 6750 §3.1 的错误码，写进 Response.BearerError。
const (
	BearerInvalidRequest = "invalid_request"
	BearerInvalidToken   = "invalid_token"
)

// 会员档位常量，对齐 backend/app/services/membership/tiers.py。
const (
	TierFree   = "free"
	TierMember = "member"
)

// Identity 是认证通过后的用户视图；字段对齐 Python 侧 user dict 的消费面
// （user_id/email/role/membership_tier/membership_expires_at + scopes 集合）。
type Identity struct {
	UserID              int
	Email               string
	Role                string
	MembershipTier      string
	MembershipExpiresAt *time.Time
	Scopes              []string
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

// EffectiveTier 对齐 tiers.resolve_effective_tier：未知/空档位一律 free；
// member 已过期（expiry <= now）回落 free。
func (i Identity) EffectiveTier(now time.Time) string {
	tier := i.MembershipTier
	if tier != TierFree && tier != TierMember {
		tier = TierFree
	}
	if tier != TierMember || i.MembershipExpiresAt == nil {
		return tier
	}
	if !i.MembershipExpiresAt.After(now) {
		return TierFree
	}
	return tier
}

// Response 是认证失败的 HTTP 投射（独立于 wire 层，避免环依赖）。
type Response struct {
	Status  int
	Body    []byte
	Headers http.Header
	// BearerError 是 RFC 6750 §3.1 的错误码（凭证无效时为 invalid_token）；没带 Bearer
	// 凭证的失败按 §3.1 不给错误码，留空。只供 OAuth 入口拼质询头，Write 不读它，
	// /api/mcp 的 401 仍是裸 "Bearer"。
	BearerError string
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
	if q.Pool == nil {
		return nil, errors.New("pgx pool is not configured")
	}
	return q.Pool.Begin(ctx)
}

// Authenticator 按请求执行可选认证；DB 在启动期绑定。
type Authenticator struct {
	DB Querier
}

// Authenticate 认证一个 Authorization 头值。匿名返回零 Identity 与 nil
// 失败响应；任何"提供了但无效"的头都是 401。authenticated 独立于
// Identity.UserID，避免测试缝或未来账号 ID 语义变化造成权限降级。
func (a Authenticator) Authenticate(ctx context.Context, authorization string) (Identity, bool, *Response) {
	if authorization == "" {
		return Identity{}, false, nil
	}
	if !strings.HasPrefix(strings.ToLower(authorization), "bearer ") {
		return Identity{}, false, unauthorized(invalidSchemeDetail, "")
	}

	token := authorization[len("Bearer "):]
	// 空白 token（以及 scheme 后多余/尾随空白）不是可查找的凭证；
	// 在开启事务前拒绝，保证 malformed credential 不触碰数据库。
	if token == "" || token != strings.TrimSpace(token) ||
		strings.IndexFunc(token, func(r rune) bool { return r == '\t' || r == '\n' || r == '\r' }) >= 0 {
		return Identity{}, false, unauthorized(invalidTokenDetail, BearerInvalidToken)
	}
	digest := sha256.Sum256([]byte(token))
	if a.DB == nil {
		return Identity{}, false, internalError()
	}
	tx, err := a.DB.Begin(ctx)
	if err != nil {
		return Identity{}, false, internalError()
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
		&row.MembershipTier, &row.MembershipExpiresAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return Identity{}, false, unauthorized(invalidTokenDetail, BearerInvalidToken)
	}
	if err != nil {
		return Identity{}, false, internalError()
	}

	// scopes 属于凭证有效性的一部分，必须先于 usage 写入和提交校验。
	// malformed scope 由 deferred rollback 收尾，不能留下 last_used_at 写入。
	scopes, ok := decodeScopes(row.ScopesJSON)
	if !ok {
		return Identity{}, false, unauthorized(invalidScopesDetail, BearerInvalidToken)
	}
	if _, err = tx.Exec(ctx, lastUsedSQL, row.TokenID); err != nil {
		return Identity{}, false, internalError()
	}
	if err = tx.Commit(ctx); err != nil {
		return Identity{}, false, internalError()
	}
	committed = true

	return Identity{
		UserID:              row.UserID,
		Email:               row.Email,
		Role:                row.Role,
		MembershipTier:      row.MembershipTier,
		MembershipExpiresAt: row.MembershipExpiresAt,
		Scopes:              scopes,
	}, true, nil
}

type tokenRow struct {
	TokenID             int
	UserID              int
	ScopesJSON          string
	ExpiresAt           any
	RevokedAt           any
	DeletedAt           any
	Email               string
	Role                string
	MembershipTier      string
	MembershipExpiresAt *time.Time
}

// lookupSQL / lastUsedSQL 与 Python 仓储逐字同义（占位符 %s → $1 是
// psycopg → pgx 的机械转写）；列清单不得增删，SQL 行为属兼容面——
// 10 列含 u.membership_expires_at（0048 会员到期透出，供生效档位判定）。
const lookupSQL = `
                    SELECT t.id AS token_id, t.user_id, t.scopes_json, t.expires_at,
                           t.revoked_at, t.deleted_at, u.email, u.role, u.membership_tier,
                           u.membership_expires_at
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

func unauthorized(detail, bearerError string) *Response {
	headers := http.Header{}
	headers.Set("WWW-Authenticate", "Bearer")
	return &Response{
		Status:      http.StatusUnauthorized,
		Body:        jsonx.MustMarshalCompact(jsonx.Object{{Key: "detail", Value: detail}}),
		Headers:     headers,
		BearerError: bearerError,
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
