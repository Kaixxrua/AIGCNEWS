import axios from 'axios'
import { api } from '@/services/http/apiClient'

/**
 * MCP OAuth 同意页的后端接口（backend/app/api/routes_mcp_oauth.py）。
 * 授权端点 /oauth/authorize 是前端页面：页面把查询串里的授权请求参数原样转给后端校验，用户点同意或拒绝后，
 * 后端给出带授权码（或错误）的回跳地址，页面再跳回 MCP 客户端。
 */

/** 要转给后端的授权请求参数，与 AuthorizationRequestBody 的字段一致；其余参数按 RFC 6749 §3.1 忽略。 */
export const MCP_OAUTH_REQUEST_FIELDS = [
  'response_type',
  'client_id',
  'redirect_uri',
  'state',
  'code_challenge',
  'code_challenge_method',
  'scope',
  'resource',
] as const

export type McpOAuthRequestField = (typeof MCP_OAUTH_REQUEST_FIELDS)[number]
export type McpOAuthRequest = Partial<Record<McpOAuthRequestField, string>>

export interface McpOAuthRedirect {
  kind: 'loopback' | 'web' | 'app'
  host: string
}

export interface McpOAuthPreviewReady {
  status: 'ready'
  client: { client_id: string; client_name: string; registered_at: string | null }
  redirect_uri: string
  redirect: McpOAuthRedirect
  scopes: string[]
  resource: string
}

/** 客户端与回调地址都已核实之后的错误：由用户点击把错误带回客户端（RFC 6749 §4.1.2.1）。 */
export interface McpOAuthRedirectableError {
  status: 'error'
  error: string
  error_description: string
  redirect_to: string
  redirect: McpOAuthRedirect
}

export type McpOAuthPreview = McpOAuthPreviewReady | McpOAuthRedirectableError

export type McpOAuthDecision = 'approve' | 'deny'

export type McpOAuthDecisionResult =
  | { status: 'approved' | 'denied'; redirect_to: string }
  | McpOAuthRedirectableError

export async function previewMcpOAuthAuthorization(request: McpOAuthRequest): Promise<McpOAuthPreview> {
  const res = await api.post<McpOAuthPreview>('/oauth/authorize/preview', request)
  return res.data
}

export async function decideMcpOAuthAuthorization(
  request: McpOAuthRequest,
  decision: McpOAuthDecision,
): Promise<McpOAuthDecisionResult> {
  const res = await api.post<McpOAuthDecisionResult>('/oauth/authorize', { ...request, decision })
  return res.data
}

/** 不能回跳客户端的错误（4xx/5xx 的 {error, error_description}）取 OAuth 错误码；别的失败返回 null。 */
export function mcpOAuthErrorCode(error: unknown): string | null {
  if (!axios.isAxiosError(error)) return null
  const code: unknown = error.response?.data?.error
  return typeof code === 'string' && code ? code : null
}

/** 跳回 MCP 客户端。抽成函数便于测试 vi.mock 替换（jsdom 无法 spy location.assign）。 */
export function navigateToMcpClient(url: string): void {
  window.location.assign(url)
}
