import { FileText, GitBranch, Newspaper, Rocket, Triangle } from 'lucide-vue-next'

export type {
  McpServerConfig,
  McpServerForm,
  ProviderConfig,
  ProviderForm,
  SchedulerStatus,
  SourceKey,
  Task,
} from './monitorModel'

import type { McpServerConfig, SourceKey } from './monitorModel'

export interface SourceItem {
  key: SourceKey
  label: string
  icon: typeof FileText
  color: string
  textColor: string
}

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
