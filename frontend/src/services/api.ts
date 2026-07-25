import { api } from './http/apiClient'

export { api } from './http/apiClient'
export {
  createMcpToken,
  deleteMcpToken,
  fetchMcpTokens,
  type CreateMcpTokenPayload,
  type CreateMcpTokenResponse,
  type McpClientType,
  type McpTokenMetadata,
} from './mcp/mcpTokenApi'
export {
  fetchGitHubHotRepos,
  fetchSnapshotDates,
  type GitHubHotPeriod,
  type GitHubHotRepo,
  type GitHubHotResponse,
} from './dashboard/dashboardApi'
export {
  fetchPaperDetail,
  fetchTop10Today,
  searchPapers,
  type PaperItem,
} from './papers/paperApi'
export {
  addMyToolWebsite,
  addMyToolWebsiteManual,
  favoriteProject,
  fetchGitHubProjectCategories,
  fetchGitHubProjects,
  fetchMyProjectCategories,
  fetchMyProjectCollection,
  fetchMyProjectTags,
  fetchProjectCategories,
  fetchProjects,
  fetchProjectTaxonomy,
  recommendGitHubProject,
  removeMyToolWebsite,
  unfavoriteProject,
  unrecommendGitHubProject,
  updateMyToolWebsite,
  type GitHubProjectCategoriesResponse,
  type GitHubProjectCategory,
  type GitHubProjectItem,
  type GitHubProjectRecommendPayload,
  type GitHubProjectRecommendResponse,
  type GitHubProjectsResponse,
  type GitHubProjectSort,
  type GitHubProjectSubcategory,
  type GitHubProjectTag,
  type GitHubProjectTagsResponse,
  type ManualToolWebsitePayload,
  type ProjectFavoritePayload,
  type ProjectFavoriteResponse,
  type ProjectListParams,
  type ProjectScope,
  type ProjectSource,
  type ProjectTaxonomyItem,
  type ProjectTaxonomyResponse,
  type ProjectViewSource,
  type ToolWebsiteAddResponse,
  type ToolWebsiteDeleteResponse,
  type ToolWebsiteUpdatePayload,
  type ToolWebsiteUpdateResponse,
} from './projects/projectApi'

export interface AttachmentMeta {
  id: string
  type: 'image' | 'pdf'
  status: 'uploading' | 'processing' | 'ready' | 'error' | 'expired'
  filename: string
  mime_type: string
  size_bytes: number
  page_count: number
  text_preview: string
  error_msg: string
}

export interface ChatAttachmentRef {
  id: string
  name: string
  mimeType: string
  modality: 'image' | 'pdf'
  parseStatus: 'uploaded' | 'processing' | 'ready' | 'failed'
  progress?: number
}

export interface ChatMessageDTO {
  id: number | string
  conversation_id: number | string
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  thinking_preview?: string
  has_thinking?: boolean
  is_thinking?: boolean
  is_streaming?: boolean
  sources?: unknown[]
  attachments?: Array<{
    id: number | string
    name?: string
    mime_type?: string
    modality?: 'image' | 'pdf'
    parse_status?: 'uploaded' | 'processing' | 'ready' | 'failed'
  }>
  created_at?: string
  updated_at?: string
}

export interface ConversationSummaryDTO {
  id: number | string
  title: string
  scope: 'global' | 'paper'
  scope_key?: string | null
  last_message_preview?: string
  message_count: number
  updated_at?: string
  last_accessed_at?: string
  created_at?: string
}

export interface ConversationListResponse {
  items: ConversationSummaryDTO[]
  total: number
  page: number
  page_size: number
}

export interface ConversationDetailResponse {
  conversation: ConversationSummaryDTO
  messages: ChatMessageDTO[]
}

export async function uploadImageAttachment(
  imageBase64: string,
  mimeType = 'image/jpeg',
  filename = '',
): Promise<AttachmentMeta> {
  const res = await api.post('/chat/attachments/image', {
    image_base64: imageBase64,
    mime_type: mimeType,
    filename,
  })
  return res.data
}

export async function uploadPdfAttachment(file: File): Promise<AttachmentMeta> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await api.post('/chat/attachments/pdf', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
  })
  return res.data
}

export async function getAttachmentStatus(attachmentId: string): Promise<AttachmentMeta> {
  const res = await api.get(`/chat/attachments/${attachmentId}`)
  return res.data
}

export async function ensureConversation(payload: {
  scope?: 'global' | 'paper'
  scope_key?: string | null
  title?: string
}): Promise<ConversationSummaryDTO> {
  const res = await api.post('/chat/conversations/ensure', payload)
  return res.data
}

export async function fetchConversations(params?: {
  scope?: 'global' | 'paper'
  page?: number
  page_size?: number
}): Promise<ConversationListResponse> {
  const res = await api.get('/chat/conversations', { params })
  return res.data
}

export async function fetchConversationDetail(
  conversationId: string | number,
): Promise<ConversationDetailResponse> {
  const res = await api.get(`/chat/conversations/${conversationId}`)
  return res.data
}

export async function createConversation(payload: {
  scope?: 'global' | 'paper'
  scope_key?: string | null
  title?: string
}): Promise<ConversationSummaryDTO> {
  const res = await api.post('/chat/conversations/create', payload)
  return res.data
}

export async function deleteConversation(
  conversationId: string | number,
): Promise<{ detail: string; conversation_id: number | string }> {
  const res = await api.delete(`/chat/conversations/${conversationId}`)
  return res.data
}

export async function deleteConversationMessage(
  messageId: string | number,
): Promise<{ detail: string; deleted_ids: number[]; conversation_id: number | string }> {
  const res = await api.delete(`/chat/messages/${messageId}`)
  return res.data
}
