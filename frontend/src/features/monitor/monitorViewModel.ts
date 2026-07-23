import { FileText, GitBranch, Newspaper, Rocket, Triangle } from 'lucide-vue-next'

export interface Task {
  id: number
  task_name: string
  status: string
  item_count: number
  error_msg: string | null
  started_at: string | null
  finished_at: string | null
}

export interface SchedulerStatus {
  running: boolean
  job_count: number
  jobs: Array<{ id: string; name: string; next_run_time: string | null }>
}

export interface PagedResult {
  items: Task[]
  total: number
  page: number
  page_size: number
}

export interface ProviderConfig {
  provider: 'openai' | 'anthropic'
  base_url: string
  model_name: string
  api_key_configured: boolean
  api_key_masked: string | null
  updated_at: string | null
}

export interface ProviderForm {
  provider: 'openai' | 'anthropic'
  base_url: string
  model_name: string
  api_key: string
  clear_api_key: boolean
}

export interface McpToolSummary {
  name: string
  description: string
}

export interface McpServerConfig {
  id: number
  server_key: string
  display_name: string
  description: string
  url: string
  transport: 'streamable_http' | string
  auth_type: 'none' | 'bearer' | string
  auth_token_configured: boolean
  auth_token_masked: string | null
  enabled: boolean
  last_test_status: string
  last_test_message: string
  last_test_at: string | null
  tools: McpToolSummary[]
  created_at: string | null
  updated_at: string | null
}

export interface McpServerForm {
  id: number | null
  server_key: string
  display_name: string
  description: string
  url: string
  auth_type: 'none' | 'bearer'
  auth_token: string
  clear_auth_token: boolean
  enabled: boolean
}

export type SourceKey = 'arxiv' | 'github' | 'hackernews' | 'producthunt' | 'news'

export interface SourceItem {
  key: SourceKey
  label: string
  icon: typeof FileText
  color: string
  textColor: string
}

export const createEmptyMcpForm = (): McpServerForm => ({
  id: null,
  server_key: '',
  display_name: '',
  description: '',
  url: '',
  auth_type: 'none',
  auth_token: '',
  clear_auth_token: false,
  enabled: true,
})

export const MCP_TEST_SCOPE = [
  { title: 'initialize', description: '协商协议版本与客户端信息' },
  { title: 'initialized', description: '发送初始化完成通知' },
  { title: 'tools/list', description: '只读取工具清单，不执行工具' },
]

export const SOURCE_LIST: SourceItem[] = [
  { key: 'arxiv', label: 'Arxiv 论文', icon: FileText, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'github', label: 'GitHub Trending', icon: GitBranch, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'hackernews', label: 'Hacker News', icon: Triangle, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'producthunt', label: 'Product Hunt', icon: Rocket, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'news', label: 'Tech News', icon: Newspaper, color: 'bg-white', textColor: 'text-stone-600' },
]

export const formatDate = (value: string | null | undefined): string => {
  if (!value) return '—'
  const date = new Date(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export const formatTime = (value: string | null | undefined): string => {
  if (!value) return '—'
  const date = new Date(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

const STATUS_CONFIG: Record<string, { label: string; dot: string; bg: string; text: string }> = {
  success: { label: '成功', dot: 'bg-brand-green', bg: 'bg-green-50', text: 'text-green-700' },
  succeeded: { label: '成功', dot: 'bg-brand-green', bg: 'bg-green-50', text: 'text-green-700' },
  failed: { label: '失败', dot: 'bg-brand-rose', bg: 'bg-rose-50', text: 'text-rose-600' },
  running: { label: '运行中', dot: 'bg-brand-blue', bg: 'bg-blue-50', text: 'text-blue-600' },
  unknown: { label: '未测试', dot: 'bg-stone-300', bg: 'bg-stone-50', text: 'text-stone-500' },
}

export const getStatusConfig = (status: string) => (
  STATUS_CONFIG[(status || 'unknown').toLowerCase()]
  ?? { label: status, dot: 'bg-stone-400', bg: 'bg-stone-50', text: 'text-stone-500' }
)

export const getMcpTransportLabel = (transport: string) => {
  if ((transport || '').toLowerCase() === 'streamable_http') return 'Streamable HTTP'
  return transport || '未知传输'
}

export const getMcpAuthLabel = (authType: string) => {
  if ((authType || '').toLowerCase() === 'bearer') return 'Bearer Token'
  return '无需鉴权'
}

export const getMcpServerInitial = (server: McpServerConfig) => {
  const value = (server.display_name || server.server_key || 'M').trim()
  return value.slice(0, 1).toUpperCase()
}
