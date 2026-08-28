import axios from 'axios'
import { api } from '@/services/http/apiClient'

export type McpClientType = 'claude' | 'cursor' | 'vscode' | 'other'

export interface McpTokenMetadata {
  id: number
  user_id?: number
  token_hint: string
  scopes: string[]
  client_type: McpClientType
  client_label: string
  expires_at: string | null
  revoked_at: string | null
  deleted_at?: string | null
  created_at?: string | null
  last_used_at?: string | null
}

export interface CreateMcpTokenPayload {
  client_type: McpClientType
  client_label?: string
  scopes?: string[]
  expires_at?: string | null
}

export interface CreateMcpTokenResponse {
  token: string
  token_metadata: McpTokenMetadata
  replaced_count: number
}

export async function fetchMcpTokens(): Promise<McpTokenMetadata[]> {
  const res = await api.get<McpTokenMetadata[]>('/auth/me/mcp-tokens')
  return Array.isArray(res.data) ? res.data : []
}

export async function createMcpToken(payload: CreateMcpTokenPayload): Promise<CreateMcpTokenResponse> {
  const res = await api.post<CreateMcpTokenResponse>('/auth/me/mcp-tokens', payload)
  return res.data
}

export async function deleteMcpToken(tokenId: number): Promise<{ deleted: boolean; id: number }> {
  const res = await api.delete<{ deleted: boolean; id: number }>(`/auth/me/mcp-tokens/${tokenId}`)
  return res.data
}

// ---------------------------------------------------------------- DSH 专用 token

export interface DshMcpTokenResponse {
  token: string
  token_metadata: McpTokenMetadata
  reused: boolean
  revoked_count?: number
}

/** 与后端 routes_auth.DSH_TOKEN_RECOVERY_REQUIRED_CODE 冻结一致 */
export const DSH_TOKEN_RECOVERY_REQUIRED_CODE = 'dsh_token_recovery_required'

/**
 * 确保当前用户的 DSH 专用 MCP Token：首次签发，之后每次调用回显同一枚
 * （跨刷新复用）。purpose/scope/客户端标识由服务端固定，客户端不得提交
 * membership_tier/group 等字段——调用配额按 token 属主实时会员档位计算。
 */
export async function ensureDshMcpToken(): Promise<DshMcpTokenResponse> {
  const res = await api.post<DshMcpTokenResponse>('/auth/me/mcp-tokens/dsh/ensure')
  return res.data
}

/** 重新生成 DSH Token：旧 DSH token 立即吊销，返回新明文（仅本次响应）。 */
export async function rotateDshMcpToken(): Promise<DshMcpTokenResponse> {
  const res = await api.post<DshMcpTokenResponse>('/auth/me/mcp-tokens/dsh/rotate')
  return res.data
}

/** 409 + detail.code=dsh_token_recovery_required：历史 hash-only token 需显式轮换。 */
export const isDshTokenRecoveryRequired = (error: unknown): boolean => {
  if (!axios.isAxiosError(error) || error.response?.status !== 409) return false
  const detail: unknown = error.response.data?.detail
  return (
    typeof detail === 'object'
    && detail !== null
    && (detail as { code?: unknown }).code === DSH_TOKEN_RECOVERY_REQUIRED_CODE
  )
}
