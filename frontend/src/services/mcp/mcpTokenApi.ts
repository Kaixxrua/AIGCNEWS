import { api } from '../http/apiClient'

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
