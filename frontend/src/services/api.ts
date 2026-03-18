import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers = config.headers ?? {}
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

let _is401Handling = false

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error?.response?.status
    const requestUrl: string = error?.config?.url ?? ''
    const data = error?.response?.data
    const message = error?.message ?? 'Unknown API error'

    console.error('[API Error]', {
      status,
      message,
      data,
      url: requestUrl,
      method: error?.config?.method,
    })

    if (status === 401 && !_is401Handling) {
      const isAuthEndpoint = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/me')

      localStorage.removeItem('auth_token')
      try {
        const { useAuthStore } = await import('../stores/authStore')
        const { getActivePinia } = await import('pinia')
        const pinia = getActivePinia()
        if (pinia) {
          const authStore = useAuthStore(pinia)
          authStore.token = null
          authStore.user = null
        }
      } catch (_) {
        /* ignore */
      }

      if (!isAuthEndpoint) {
        _is401Handling = true
        try {
          const { default: router } = await import('../router/index')
          alert('登录已过期，请重新登录')
          await router.push('/login')
        } finally {
          _is401Handling = false
        }
      }
    }

    return Promise.reject(error)
  },
)

export interface PaperItem {
  id: string
  source: string
  source_channel?: string
  title: string
  url?: string
  summary?: string
  published_date?: string
  tags?: string
  score?: number
  raw_score?: number
  rank_in_period?: number
  local_pdf_path?: string | null
  pdf_media_url?: string | null
  created_at?: string
}

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

export async function fetchSnapshotDates(limit = 60): Promise<string[]> {
  const res = await api.get('/dashboard/snapshot-dates', { params: { limit } })
  return res.data?.dates ?? []
}

export async function searchPapers(q: string, limit = 20): Promise<PaperItem[]> {
  const res = await api.get('/papers/search', { params: { q, limit } })
  return res.data?.items ?? []
}

export async function fetchTop10Today(): Promise<PaperItem[]> {
  const res = await api.get('/papers/top10-today')
  return res.data?.items ?? []
}

export async function fetchPaperDetail(paperId: string): Promise<PaperItem | null> {
  try {
    const res = await api.get(`/papers/${paperId}`)
    return res.data ?? null
  } catch {
    return null
  }
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
