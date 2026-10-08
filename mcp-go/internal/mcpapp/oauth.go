package mcpapp

// OAuth 入口（/api/mcp/oauth）：与 /api/mcp 同一套认证、解析、限流与分派，区别只在认证
// 这一步——不收匿名请求，401 的 WWW-Authenticate 按 MCP 授权规范带上 RFC 9728 §5.1 的
// resource_metadata，客户端据此找到授权服务器、走浏览器授权换令牌。授权服务器在 Python
// 主后端（backend/app/services/auth/mcp_oauth.py），签发的仍是 user_mcp_tokens 里的普通
// 令牌，鉴权查询与 /api/mcp 完全相同。

import (
	"net/http"
	"strings"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
)

// OAuthResourceMetadataURL 是 /api/mcp/oauth 的受保护资源元数据地址（RFC 9728 §3.1：把
// /.well-known/oauth-protected-resource 插在资源路径前面）。元数据文件随前端发布包放在两个
// 边缘上；与 Python 的 MCP_OAUTH_RESOURCE、前端的元数据文件三方对钉。
const OAuthResourceMetadataURL = "https://aigcnews.cn/.well-known/oauth-protected-resource/api/mcp/oauth"

const missingTokenDetail = "此入口需要 MCP Token，请先完成 OAuth 授权"

// OAuthEntry 返回 OAuth 入口：共享同一个 App、认证器、限流器与用量记录，所以要在
// SetUsage 之后调用。
func (h *Handler) OAuthEntry(resourceMetadataURL string) *Handler {
	entry := *h
	entry.resourceMetadata = resourceMetadataURL
	return &entry
}

// challenge 把 OAuth 入口的 401 质询改写成 Bearer [error="…", ]resource_metadata="…"；
// 请求里没有 Bearer 凭证时按 RFC 6750 §3.1 不带 error。/api/mcp 与非 401 响应原样返回。
func (h *Handler) challenge(response *authn.Response) *authn.Response {
	if h.resourceMetadata == "" || response.Status != http.StatusUnauthorized {
		return response
	}
	params := make([]string, 0, 2)
	if response.BearerError != "" {
		params = append(params, `error="`+response.BearerError+`"`)
	}
	params = append(params, `resource_metadata="`+h.resourceMetadata+`"`)
	// 401 的头表有的是字面量键（"WWW-Authenticate"，非规范形式），Set 不会覆盖它，
	// 写出时会多出一行裸 Bearer；按大小写不敏感去掉旧质询再设新值。
	headers := http.Header{}
	for key, values := range response.Headers {
		if !strings.EqualFold(key, "WWW-Authenticate") {
			headers[key] = append([]string(nil), values...)
		}
	}
	headers.Set("WWW-Authenticate", "Bearer "+strings.Join(params, ", "))
	challenged := *response
	challenged.Headers = headers
	return &challenged
}

func missingTokenResponse() *authn.Response {
	return &authn.Response{
		Status:  http.StatusUnauthorized,
		Body:    jsonx.MustMarshalCompact(jsonx.Object{{Key: "detail", Value: missingTokenDetail}}),
		Headers: http.Header{"WWW-Authenticate": []string{"Bearer"}},
	}
}
