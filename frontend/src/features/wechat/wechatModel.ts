export type WeChatLoginStatus =
  | 'waiting_scan'
  | 'scanned_waiting_confirmation'
  | 'confirmed'
  | 'completed'
  | 'qr_expired'
  | 'failed'
  | 'cancelled'

export interface WeChatLoginAttempt {
  attempt_id: string
  status: WeChatLoginStatus
  expires_at: string
  error_code: string | null
}

export type WeChatSessionStatus = 'disconnected' | 'active' | 'invalid'

export interface WeChatSessionSummary {
  connected: boolean
  status: WeChatSessionStatus
  account_name: string
  account_avatar_url: string
  last_validated_at: string | null
  last_used_at: string | null
  expires_at: string | null
  invalid_reason_code: string | null
}

export interface WeChatOfficialAccount {
  id: number | null
  fakeid: string
  nickname: string
  alias: string
  avatar_url: string
  signature: string
  enabled: boolean
  sort_order: number
  last_sync_status: string
  last_sync_message: string
  last_sync_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface WeChatAccountForm {
  fakeid: string
  nickname: string
  alias: string
  avatar_url: string
  signature: string
  enabled: boolean
  sort_order: number
}

export interface WeChatOfficialAccountSearchResult {
  items: WeChatOfficialAccount[]
  total: number
  begin: number
  size: number
}

export interface WeChatArticle {
  id: number | null
  account_id: number
  stable_article_key: string
  message_id: string
  itemidx: number
  title: string
  digest: string
  author: string
  article_url: string
  cover_url: string
  source_url: string
  has_content?: boolean
  published_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface WeChatArticleDetail extends WeChatArticle {
  /** Sanitized server-side at ingest; re-sanitized client-side before render. */
  content_html: string
  content_fetched_at?: string | null
}

export interface WeChatArticleListResult {
  items: WeChatArticle[]
  total: number
  offset: number
  limit: number
}

export interface WeChatSyncSubmitResult {
  status: 'submitted'
  account_id: number
  message: string
}

export interface WeChatCatalogAccount {
  id: number
  nickname: string
  alias: string
  avatar_url: string
  signature: string
  sort_order: number
  followed: boolean
}

export interface WeChatFeedEntry {
  account: WeChatCatalogAccount
  articles: WeChatArticle[]
}

export interface WeChatFeedResult {
  items: WeChatFeedEntry[]
  per_account: number
}

export const buildWeChatAccountPayload = (form: WeChatAccountForm) => ({
  fakeid: form.fakeid.trim(),
  nickname: form.nickname.trim(),
  alias: form.alias.trim(),
  avatar_url: form.avatar_url.trim(),
  signature: form.signature.trim(),
  enabled: form.enabled,
  sort_order: form.sort_order,
})

export const isWeChatLoginTerminal = (status: WeChatLoginStatus): boolean =>
  status === 'completed' || status === 'failed' || status === 'cancelled'

export const isWeChatLoginExpired = (status: WeChatLoginStatus): boolean =>
  status === 'qr_expired'
