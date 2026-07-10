<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useClipboard } from '../composables/useClipboard'

type ShellId = 'powershell' | 'cmd' | 'bash'
type ClientId =
  | 'claude-code'
  | 'cursor'
  | 'codex'
  | 'opencode'
  | 'cline-roo'
  | 'continue'
  | 'windsurf'
  | 'generic-json'

type OutputKind = 'command' | 'json' | 'toml'
type TestPhaseId = 'initialize' | 'initialized' | 'tools' | 'resources' | 'prompts'
type TestPhaseStatus = 'idle' | 'running' | 'success' | 'error'

interface ShellOption {
  id: ShellId
  label: string
  hint: string
}

interface ClientOption {
  id: ClientId
  label: string
  badge: string
  description: string
  outputKind: OutputKind
  configPath: string
  caveat?: string
}

interface PublicTool {
  name: string
  description: string
}

interface TestPhase {
  id: TestPhaseId
  label: string
  description: string
  status: TestPhaseStatus
  detail: string
}

interface JsonRpcData {
  jsonrpc?: string
  id?: string | number | null
  result?: any
  error?: { code?: string | number; message?: string } | string
}

const { copy } = useClipboard()

const MCP_PROTOCOL_VERSION = '2025-06-18'
const MCP_TEST_TIMEOUT_MS = 15_000
const MCP_SERVER_KEY = 'aigc-news'

const defaultEndpoint =
  typeof window !== 'undefined'
    ? new URL('/api/mcp', window.location.origin).href
    : 'https://your-domain.com/api/mcp'

const endpointUrl = ref(defaultEndpoint)
const selectedShell = ref<ShellId>('powershell')
const selectedClient = ref<ClientId>('claude-code')
const copiedKey = ref('')
const testing = ref(false)
const testMessage = ref('')
const testStatus = ref<'idle' | 'success' | 'error'>('idle')
const detectedTools = ref<PublicTool[]>([])
const detectedResourceCount = ref<number | null>(null)
const detectedPromptCount = ref<number | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | undefined

const shellOptions: ShellOption[] = [
  { id: 'powershell', label: 'PowerShell', hint: 'Windows / VS Code 终端默认推荐' },
  { id: 'cmd', label: 'Command Prompt', hint: '传统 Windows cmd.exe' },
  { id: 'bash', label: 'Bash / zsh', hint: 'macOS / Linux / Git Bash / WSL' },
]

const clientOptions: ClientOption[] = [
  {
    id: 'claude-code',
    label: 'Claude Code',
    badge: 'CLI',
    description: '生成先移除旧配置、再添加 HTTP MCP 的一键终端命令。',
    outputKind: 'command',
    configPath: 'Terminal',
  },
  {
    id: 'cursor',
    label: 'Cursor',
    badge: 'CMD',
    description: '生成创建/重置项目级 .cursor/mcp.json 的一键命令。',
    outputKind: 'command',
    configPath: '.cursor/mcp.json（在项目根目录运行）',
    caveat: '该命令会重写当前目录下的 .cursor/mcp.json；如果已有其他 MCP Server，请先备份或手动合并。',
  },
  {
    id: 'codex',
    label: 'Codex',
    badge: 'CLI',
    description: '生成先 remove、再无鉴权 add 的 codex mcp 一键命令。',
    outputKind: 'command',
    configPath: 'Terminal',
    caveat: '按 Codex CLI 的 --url 远程 MCP 形式生成，不设置 token / bearer-token-env-var。',
  },
  {
    id: 'opencode',
    label: 'OpenCode',
    badge: 'CMD',
    description: '生成创建/重置 opencode.json remote MCP 配置的一键命令。',
    outputKind: 'command',
    configPath: 'opencode.json（在项目根目录运行）',
    caveat: '该命令会重写当前目录下的 opencode.json；已有 OpenCode 配置请先备份或手动合并。',
  },
  {
    id: 'cline-roo',
    label: 'Cline / Roo Code',
    badge: 'CMD',
    description: '生成一个可直接导入 MCP Settings 的配置文件创建命令。',
    outputKind: 'command',
    configPath: 'aigc-news.cline-roo.mcp.json（生成后导入扩展设置）',
    caveat: 'Cline / Roo Code 不同扩展版本的配置文件位置差异较大；这里生成可导入文件，避免误写全局扩展配置。',
  },
  {
    id: 'continue',
    label: 'Continue',
    badge: 'CMD',
    description: '生成创建/重置 .continue/config.json 的一键命令。',
    outputKind: 'command',
    configPath: '.continue/config.json（在项目根目录运行）',
    caveat: '如果 Continue 当前版本不读取项目级 JSON MCP 配置，请将生成文件内容导入客户端支持的 MCP 配置入口。',
  },
  {
    id: 'windsurf',
    label: 'Windsurf',
    badge: 'CMD',
    description: '生成一个可导入 Windsurf MCP 设置的配置文件创建命令。',
    outputKind: 'command',
    configPath: 'aigc-news.windsurf.mcp.json（生成后导入 MCP Settings）',
    caveat: 'Windsurf 不同版本配置路径可能不同；这里生成可导入文件，优先避免覆盖未知全局配置。',
  },
  {
    id: 'generic-json',
    label: '通用文件',
    badge: 'Fallback',
    description: '生成通用 mcpServers JSON 文件的一键命令，其他客户端可从这里导入。',
    outputKind: 'command',
    configPath: 'aigc-news.mcp.json',
  },
]

const capabilityPills = [
  'Streamable HTTP',
  'No Auth',
  'Public Read-only',
  'Tools',
  'Resources',
  'Prompts',
]

const publicTools: PublicTool[] = [
  { name: 'search_papers', description: '检索公开论文、学术文章、AI 新闻与其他索引文档，不用于 GitHub 软件推荐。' },
  { name: 'get_paper_detail', description: '读取单条公开索引文档详情。' },
  { name: 'get_top_items', description: '读取 daily / weekly / monthly 排行与趋势条目。' },
  { name: 'search_github_projects', description: '通用首选入口：搜索任意领域 GitHub 开源软件，包括非 AI 桌面与截图工具。' },
  { name: 'search_github_ai_projects', description: 'AI 首选入口：本地优先搜索 GitHub AI 项目库，0 条时才进行 AI 定向只读 fallback。' },
  { name: 'get_project_library', description: '兼容旧客户端的 GitHub AI 项目库入口。' },
  { name: 'get_project_categories', description: '分类不确定时先读取 AI 项目分类与子分类计数。' },
]

const resources = [
  'aigc-news://dashboard/summary',
  'aigc-news://projects/categories',
  'aigc-news://report/latest',
]

const exampleQuestions = [
  '帮我找 GitHub 开源的 Windows 截图软件，效果像 macOS iShot，导出图片能自定义圆角。',
  '有没有适合本地部署、支持 RAG、有 Web UI 的 Python GitHub 仓库？',
  '帮我找 Agent / MCP / workflow automation 相关开源项目。',
  '总结今天 AIGC_NEWS 榜单趋势和最值得关注的项目。',
]

const localFirstNotes = [
  '任意领域 GitHub / 开源软件推荐（包括非 AI 桌面、截图工具）：先调用 search_github_projects。',
  'GitHub AI 项目 / RAG / Web UI / 本地部署 / Agent / MCP / workflow：先调用 search_github_ai_projects；get_project_library 仅保留兼容。',
  '广泛推荐/对比时优先使用 MCP 返回的摘要字段，不要逐个再查 GitHub；只有元数据不足以核验具体功能时才访问对应 README/docs。',
  '通用 fallback 不会自动追加 AI / LLM / RAG 关键词；AI 工具仍使用 AI 定向查询。',
  'MCP-first 是通过工具名称、描述和真实 Agent 回归测试提高命中率的策略，不是客户端强制优先级。',
  'fallback 是只读、限量、无写库行为，不暴露 GitHub Token 或后台 MCP 配置。',
]

const handshakeCopy = [
  { label: '握手', value: 'initialize → notifications/initialized' },
  { label: '工具', value: 'tools/list → tools/call' },
  { label: '上下文', value: 'resources/list · prompts/list' },
]

const defaultShellOption = shellOptions[0]!
const defaultClientOption = clientOptions[0]!

const normalizedEndpoint = computed(() => endpointUrl.value.trim() || defaultEndpoint)
const selectedClientOption = computed<ClientOption>(() => clientOptions.find((item) => item.id === selectedClient.value) ?? defaultClientOption)
const selectedShellOption = computed<ShellOption>(() => shellOptions.find((item) => item.id === selectedShell.value) ?? defaultShellOption)
const displayTools = computed(() => (detectedTools.value.length > 0 ? detectedTools.value : publicTools))

const endpointWarning = computed(() => {
  try {
    const parsed = new URL(normalizedEndpoint.value)
    if (!['http:', 'https:'].includes(parsed.protocol)) return 'MCP URL 只支持 http 或 https。'
    return ''
  } catch {
    return '请输入有效的 MCP Server URL。'
  }
})

const generatedTitle = computed(() => `${selectedClientOption.value.label} · ${selectedShellOption.value.label} 一键命令`)

const generatedSnippet = computed(() => generateSnippet(selectedClient.value, normalizedEndpoint.value, selectedShell.value))
const genericCommand = computed(() => generateSnippet('generic-json', normalizedEndpoint.value, selectedShell.value))

const outputLanguage = computed(() => {
  if (selectedClientOption.value.outputKind === 'toml') return 'toml'
  if (selectedClientOption.value.outputKind === 'json') return 'json'
  return selectedShell.value === 'powershell' ? 'powershell' : selectedShell.value
})

const testSummary = computed(() => {
  if (testStatus.value !== 'success') return ''
  const pieces = [`${detectedTools.value.length || publicTools.length} tools`]
  if (detectedResourceCount.value !== null) pieces.push(`${detectedResourceCount.value} resources`)
  if (detectedPromptCount.value !== null) pieces.push(`${detectedPromptCount.value} prompts`)
  return pieces.join(' · ')
})

function createTestPhases(): TestPhase[] {
  return [
    { id: 'initialize', label: 'initialize', description: '协商协议版本和会话', status: 'idle', detail: '' },
    { id: 'initialized', label: 'initialized', description: '确认客户端初始化完成', status: 'idle', detail: '' },
    { id: 'tools', label: 'tools/list', description: '读取公开只读工具清单', status: 'idle', detail: '' },
    { id: 'resources', label: 'resources/list', description: '读取资源入口（可选）', status: 'idle', detail: '' },
    { id: 'prompts', label: 'prompts/list', description: '读取 Prompt 模板（可选）', status: 'idle', detail: '' },
  ]
}

const testPhases = ref<TestPhase[]>(createTestPhases())

function quoteForShell(value: string, shell: ShellId): string {
  if (shell === 'bash') return `'${value.replace(/'/g, `'\\''`)}'`
  if (shell === 'powershell') return `"${value.replace(/`/g, '``').replace(/"/g, '`"')}"`
  return `"${value.replace(/"/g, '""')}"`
}

function quotePowerShellLiteral(value: string): string {
  return `'${value.replace(/'/g, "''")}'`
}

function encodePowerShellCommand(command: string): string {
  const bytes = new Uint8Array(command.length * 2)
  for (let index = 0; index < command.length; index += 1) {
    const code = command.charCodeAt(index)
    bytes[index * 2] = code & 0xff
    bytes[index * 2 + 1] = code >> 8
  }
  let binary = ''
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return btoa(binary)
}

function mcpServersConfig(url: string) {
  return {
    mcpServers: {
      [MCP_SERVER_KEY]: {
        type: 'http',
        url,
      },
    },
  }
}

function opencodeConfig(url: string) {
  return {
    $schema: 'https://opencode.ai/config.json',
    mcp: {
      [MCP_SERVER_KEY]: {
        type: 'remote',
        url,
        enabled: true,
      },
    },
  }
}

function commandJoin(shell: ShellId) {
  if (shell === 'cmd') return ' & '
  return '; '
}

function ignoreStderr(shell: ShellId) {
  if (shell === 'powershell') return '2>$null'
  if (shell === 'cmd') return '2>nul'
  return '2>/dev/null'
}

function powerShellWriteJsonScript(path: string, data: unknown): string {
  const directory = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
  const json = JSON.stringify(data)
  const mkdir = directory ? `New-Item -ItemType Directory -Force ${quotePowerShellLiteral(directory)} | Out-Null` : ''
  const write = `Set-Content -Encoding UTF8 -Path ${quotePowerShellLiteral(path)} -Value ${quotePowerShellLiteral(json)}`
  return [mkdir, write].filter(Boolean).join('; ')
}

function writeJsonCommand(path: string, data: unknown, shell: ShellId): string {
  if (shell === 'powershell') {
    return powerShellWriteJsonScript(path, data)
  }

  if (shell === 'cmd') {
    return `powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encodePowerShellCommand(powerShellWriteJsonScript(path, data))}`
  }

  const directory = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
  const json = JSON.stringify(data)
  const mkdir = directory ? `mkdir -p ${quoteForShell(directory, shell)}` : ''
  const write = `printf '%s\\n' ${quoteForShell(json, shell)} > ${quoteForShell(path, shell)}`
  return [mkdir, write].filter(Boolean).join(commandJoin(shell))
}

function generateSnippet(client: ClientId, url: string, shell: ShellId): string {
  const quotedUrl = quoteForShell(url, shell)
  const join = commandJoin(shell)
  const ignored = ignoreStderr(shell)

  if (client === 'claude-code') {
    return [`claude mcp remove ${MCP_SERVER_KEY} ${ignored}`, `claude mcp add --transport http ${MCP_SERVER_KEY} ${quotedUrl}`].join(join)
  }

  if (client === 'codex') {
    return [`codex mcp remove ${MCP_SERVER_KEY} ${ignored}`, `codex mcp add ${MCP_SERVER_KEY} --url ${quotedUrl}`].join(join)
  }

  if (client === 'cursor') {
    return writeJsonCommand('.cursor/mcp.json', mcpServersConfig(url), shell)
  }

  if (client === 'opencode') {
    return writeJsonCommand('opencode.json', opencodeConfig(url), shell)
  }

  if (client === 'continue') {
    return writeJsonCommand('.continue/config.json', mcpServersConfig(url), shell)
  }

  if (client === 'cline-roo') {
    return writeJsonCommand('aigc-news.cline-roo.mcp.json', mcpServersConfig(url), shell)
  }

  if (client === 'windsurf') {
    return writeJsonCommand('aigc-news.windsurf.mcp.json', mcpServersConfig(url), shell)
  }

  return writeJsonCommand('aigc-news.mcp.json', mcpServersConfig(url), shell)
}

async function copyText(key: string, text: string) {
  await copy(text)
  copiedKey.value = key
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copiedKey.value = ''
  }, 1600)
}

function setPhase(id: TestPhaseId, status: TestPhaseStatus, detail = '') {
  const phase = testPhases.value.find((item) => item.id === id)
  if (!phase) return
  phase.status = status
  phase.detail = detail
}

function markRunningPhaseAsError(message: string) {
  const running = testPhases.value.find((item) => item.status === 'running')
  if (running) {
    running.status = 'error'
    running.detail = message
  }
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function idMatches(actual: unknown, expectedId: string | number | undefined) {
  if (expectedId === undefined) return true
  return actual === expectedId || String(actual) === String(expectedId)
}

function shortenText(value: unknown, maxLength = 240) {
  const text = String(value ?? '').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength - 1)}…`
}

function parseRpcError(data: JsonRpcData) {
  const error = data.error
  if (!error) return ''
  if (typeof error === 'string') return error
  return String(error.message || error.code || JSON.stringify(error))
}

function assertJsonRpc(data: JsonRpcData, expectedId: string | number | undefined) {
  const error = parseRpcError(data)
  if (error) throw new Error(`MCP JSON-RPC 错误：${error}`)
  if (!idMatches(data.id, expectedId)) throw new Error('MCP JSON-RPC 响应 id 与请求不匹配。')
  return data
}

function parseSseResponse(text: string, expectedId: string | number | undefined) {
  const candidates: JsonRpcData[] = []
  let eventData: string[] = []

  const flushEvent = () => {
    const raw = eventData.join('\n').trim()
    eventData = []
    if (!raw || raw === '[DONE]') return
    try {
      const parsed = JSON.parse(raw) as unknown
      if (Array.isArray(parsed)) {
        parsed.forEach((item) => {
          if (isRecord(item)) candidates.push(item as JsonRpcData)
        })
      } else if (isRecord(parsed)) {
        candidates.push(parsed as JsonRpcData)
      }
    } catch {
      // Ignore SSE comments / non-JSON events and continue looking for JSON-RPC data.
    }
  }

  text.split(/\r?\n/).forEach((line) => {
    if (!line.trim()) {
      flushEvent()
      return
    }
    if (line.startsWith(':')) return
    if (line.startsWith('data:')) eventData.push(line.slice(5).trimStart())
  })
  flushEvent()

  const matched = expectedId === undefined
    ? candidates[candidates.length - 1]
    : candidates.find((item) => idMatches(item.id, expectedId))
  if (!matched) throw new Error('MCP Server 返回了 SSE，但未包含匹配的 JSON-RPC 数据。')
  return assertJsonRpc(matched, expectedId)
}

function parseJsonRpcResponse(text: string, contentType: string, expectedId: string | number | undefined) {
  if (contentType.includes('text/event-stream') || /^data:/m.test(text)) {
    return parseSseResponse(text, expectedId)
  }

  const parsed = JSON.parse(text) as unknown
  if (Array.isArray(parsed)) {
    const matched = expectedId === undefined
      ? parsed.find(isRecord)
      : parsed.find((item) => isRecord(item) && idMatches(item.id, expectedId))
    if (isRecord(matched)) return assertJsonRpc(matched as JsonRpcData, expectedId)
  }
  if (isRecord(parsed)) return assertJsonRpc(parsed as JsonRpcData, expectedId)
  throw new Error('MCP Server 响应格式不是 JSON-RPC 对象。')
}

function protocolHeaders(protocolVersion = MCP_PROTOCOL_VERSION, sessionId = ''): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json, text/event-stream',
    'MCP-Protocol-Version': protocolVersion,
  }
  if (sessionId) headers['Mcp-Session-Id'] = sessionId
  return headers
}

async function postMcp(
  method: string,
  params: Record<string, unknown> | undefined,
  id: number | undefined,
  headers: Record<string, string>,
) {
  const payload: Record<string, unknown> = { jsonrpc: '2.0', method }
  if (id !== undefined) payload.id = id
  if (params !== undefined) payload.params = params

  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), MCP_TEST_TIMEOUT_MS)

  try {
    const response = await fetch(normalizedEndpoint.value, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    const text = await response.text()
    if (!response.ok) {
      const reason = shortenText(text || response.statusText)
      throw new Error(`HTTP ${response.status}${reason ? `: ${reason}` : ''}`)
    }

    const contentType = response.headers.get('content-type')?.toLowerCase() || ''
    const data = text.trim() ? parseJsonRpcResponse(text, contentType, id) : null
    return { data, headers: response.headers }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`MCP 请求超过 ${Math.round(MCP_TEST_TIMEOUT_MS / 1000)} 秒未返回。`)
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

function extractTools(data: JsonRpcData | null): PublicTool[] {
  const rawTools = data?.result?.tools
  if (!Array.isArray(rawTools)) return []
  return rawTools
    .filter(isRecord)
    .map((tool) => ({
      name: String(tool.name || '').trim(),
      description: String(tool.description || '').trim(),
    }))
    .filter((tool) => tool.name)
}

function extractListCount(data: JsonRpcData | null, key: string) {
  const items = data?.result?.[key]
  return Array.isArray(items) ? items.length : 0
}

function testErrorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '连接测试失败。')
  if (/Failed to fetch|NetworkError|Load failed/i.test(message)) {
    return '浏览器无法连接该 MCP URL。请确认服务可访问，并已允许 CORS（Content-Type、MCP-Protocol-Version、Mcp-Session-Id）。'
  }
  if (/JSON/.test(message)) return `MCP Server 未返回有效 JSON-RPC 响应：${message}`
  return message
}

async function testToolsList() {
  if (testing.value) return
  if (endpointWarning.value) {
    testStatus.value = 'error'
    testMessage.value = endpointWarning.value
    return
  }

  testing.value = true
  testStatus.value = 'idle'
  testMessage.value = '正在进行 MCP Streamable HTTP 握手…'
  detectedTools.value = []
  detectedResourceCount.value = null
  detectedPromptCount.value = null
  testPhases.value = createTestPhases()

  try {
    setPhase('initialize', 'running')
    const initialize = await postMcp(
      'initialize',
      {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: { name: 'aigc-news-connect-page', version: '1.0.0' },
      },
      1,
      protocolHeaders(),
    )
    const negotiatedVersion = String(initialize.data?.result?.protocolVersion || MCP_PROTOCOL_VERSION)
    const sessionId = initialize.headers.get('mcp-session-id') || initialize.headers.get('Mcp-Session-Id') || ''
    setPhase('initialize', 'success', `协议 ${negotiatedVersion}${sessionId ? ' · session ready' : ''}`)

    const sessionHeaders = protocolHeaders(negotiatedVersion, sessionId)

    setPhase('initialized', 'running')
    await postMcp('notifications/initialized', undefined, undefined, sessionHeaders)
    setPhase('initialized', 'success', '初始化完成通知已发送')

    setPhase('tools', 'running')
    const toolsResult = await postMcp('tools/list', {}, 2, sessionHeaders)
    const tools = extractTools(toolsResult.data)
    detectedTools.value = tools
    setPhase('tools', 'success', `发现 ${tools.length} 个工具`)

    setPhase('resources', 'running')
    try {
      const resourceResult = await postMcp('resources/list', {}, 3, sessionHeaders)
      detectedResourceCount.value = extractListCount(resourceResult.data, 'resources')
      setPhase('resources', 'success', `发现 ${detectedResourceCount.value} 个资源`)
    } catch (error) {
      detectedResourceCount.value = 0
      setPhase('resources', 'error', shortenText(testErrorMessage(error), 120))
    }

    setPhase('prompts', 'running')
    try {
      const promptResult = await postMcp('prompts/list', {}, 4, sessionHeaders)
      detectedPromptCount.value = extractListCount(promptResult.data, 'prompts')
      setPhase('prompts', 'success', `发现 ${detectedPromptCount.value} 个 Prompt`)
    } catch (error) {
      detectedPromptCount.value = 0
      setPhase('prompts', 'error', shortenText(testErrorMessage(error), 120))
    }

    testStatus.value = 'success'
    testMessage.value = `连接成功：${testSummary.value || `${tools.length} tools`}。`
  } catch (error) {
    const message = testErrorMessage(error)
    markRunningPhaseAsError(shortenText(message, 140))
    testStatus.value = 'error'
    testMessage.value = message
  } finally {
    testing.value = false
  }
}

function phaseTone(status: TestPhaseStatus) {
  if (status === 'success') return 'border-emerald-200 bg-emerald-50/80 text-emerald-800'
  if (status === 'error') return 'border-rose-200 bg-rose-50/80 text-rose-800'
  if (status === 'running') return 'border-cyan-200 bg-cyan-50/80 text-cyan-800'
  return 'border-stone-200 bg-white/65 text-stone-500'
}

function phaseDot(status: TestPhaseStatus) {
  if (status === 'success') return 'bg-emerald-400'
  if (status === 'error') return 'bg-rose-400'
  if (status === 'running') return 'animate-pulse bg-cyan-400'
  return 'bg-stone-300'
}

onBeforeUnmount(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <div class="mcp-connect-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-8">
      <div class="mx-auto flex max-w-7xl flex-col gap-5 pb-24">
        <section class="mcp-hero glass-card relative overflow-hidden p-6 md:p-8">
          <div class="mcp-grid-overlay" />
          <div class="pointer-events-none absolute -right-10 -top-16 h-56 w-56 rounded-full bg-cyan-200/25 blur-3xl" />
          <div class="pointer-events-none absolute bottom-0 left-1/4 h-44 w-44 rounded-full bg-stone-300/15 blur-3xl" />

          <div class="relative z-10 grid gap-6 xl:grid-cols-[1.18fr_0.82fr] xl:items-end">
            <div>
              <div class="mb-5 flex flex-wrap gap-2">
                <span
                  v-for="pill in capabilityPills"
                  :key="pill"
                  class="rounded-full border border-cyan-200/60 bg-cyan-50/75 px-3 py-1 text-2xs font-semibold uppercase tracking-[0.14em] text-cyan-700"
                >
                  {{ pill }}
                </span>
              </div>
              <p class="text-xs font-semibold uppercase tracking-[0.32em] text-stone-400">AIGC_NEWS MCP Server</p>
              <h1 class="mt-3 max-w-4xl font-serif text-3xl font-semibold leading-tight text-stone-900 md:text-5xl">
                把公开 AI 情报库接进你的 MCP 客户端
              </h1>
              <p class="mt-4 max-w-3xl text-sm leading-7 text-stone-500 md:text-base">
                选择终端与 AI 客户端，生成无鉴权的 Streamable HTTP MCP 一键命令；能走 CLI 的客户端会先移除旧配置再重新接入，其他客户端生成可导入或项目级配置文件。客户端可直接查询公开论文、榜单、GitHub AI 项目库、简报资源与 Prompt 模板。
              </p>

              <div class="mt-6 grid gap-3 sm:grid-cols-3">
                <div v-for="item in handshakeCopy" :key="item.label" class="rounded-[22px] border border-white/80 bg-white/65 p-4 shadow-sm">
                  <p class="text-2xs font-semibold uppercase tracking-[0.18em] text-stone-400">{{ item.label }}</p>
                  <p class="mt-2 font-mono text-xs leading-5 text-stone-700">{{ item.value }}</p>
                </div>
              </div>
            </div>

            <div class="endpoint-card rounded-[28px] border border-white/90 bg-white/75 p-5 shadow-sm">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">Endpoint</p>
                  <p class="mt-1 text-sm font-semibold text-stone-800">当前公开入口</p>
                </div>
                <span class="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-2xs font-semibold uppercase tracking-[0.12em] text-emerald-700">Live</span>
              </div>
              <div class="mt-4 flex items-center gap-2 rounded-2xl border border-stone-200/70 bg-stone-50/80 px-3 py-3 font-mono text-xs text-stone-700">
                <span class="h-2 w-2 shrink-0 rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(52,211,153,0.14)]" />
                <span class="min-w-0 flex-1 truncate">{{ normalizedEndpoint }}</span>
              </div>
              <p v-if="endpointWarning" class="mt-2 rounded-2xl bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700">
                {{ endpointWarning }}
              </p>
              <div class="mt-4 grid grid-cols-2 gap-2">
                <button class="btn-secondary justify-center py-2 text-xs" @click="copyText('endpoint', normalizedEndpoint)">
                  {{ copiedKey === 'endpoint' ? '已复制' : '复制 Endpoint' }}
                </button>
                <button class="btn-primary justify-center py-2 text-xs" :disabled="testing || Boolean(endpointWarning)" @click="testToolsList">
                  <span v-if="testing" class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                  {{ testing ? '测试中…' : '握手测试' }}
                </button>
              </div>
            </div>
          </div>
        </section>

        <div class="grid gap-5 xl:grid-cols-[0.85fr_1.15fr]">
          <section class="glass-card p-5 md:p-6">
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-xs font-semibold uppercase tracking-[0.22em] text-stone-400">Step 1</p>
                <h2 class="mt-1 text-lg font-semibold text-stone-800">选择环境</h2>
              </div>
              <span class="rounded-full bg-stone-100 px-3 py-1 text-xs text-stone-500">无需 API Key</span>
            </div>

            <label class="mt-5 block text-xs font-semibold uppercase tracking-[0.16em] text-stone-400">MCP URL</label>
            <input v-model.trim="endpointUrl" class="input mt-2 font-mono text-xs" placeholder="https://your-domain.com/api/mcp" />

            <div class="mt-6">
              <p class="text-sm font-semibold text-stone-700">终端类型</p>
              <div class="shell-selector mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-1 2xl:grid-cols-3">
                <button
                  v-for="shell in shellOptions"
                  :key="shell.id"
                  type="button"
                  class="shell-option rounded-[18px] border px-3 py-3 text-left transition-colors duration-150"
                  :class="selectedShell === shell.id ? 'border-stone-700 bg-stone-800 text-white shadow-sm' : 'border-stone-200/80 bg-white/70 text-stone-600 hover:bg-white'"
                  @click="selectedShell = shell.id"
                >
                  <span class="block text-sm font-semibold">{{ shell.label }}</span>
                  <span class="mt-1 block text-2xs leading-4" :class="selectedShell === shell.id ? 'text-stone-200' : 'text-stone-400'">{{ shell.hint }}</span>
                </button>
              </div>
            </div>

            <div class="mt-6">
              <p class="text-sm font-semibold text-stone-700">MCP 客户端</p>
              <div class="mt-3 grid gap-2 sm:grid-cols-2">
                <button
                  v-for="client in clientOptions"
                  :key="client.id"
                  type="button"
                  class="client-option rounded-[18px] border px-3 py-3 text-left transition-all duration-150"
                  :class="selectedClient === client.id ? 'border-cyan-300 bg-cyan-50/90 shadow-sm' : 'border-stone-200/80 bg-white/70 hover:bg-white'"
                  @click="selectedClient = client.id"
                >
                  <span class="flex items-center justify-between gap-2">
                    <span class="text-sm font-semibold text-stone-800">{{ client.label }}</span>
                    <span class="rounded-full bg-white/80 px-2 py-0.5 text-2xs font-medium text-stone-500">{{ client.badge }}</span>
                  </span>
                  <span class="mt-1 block text-2xs leading-4 text-stone-400">{{ client.description }}</span>
                </button>
              </div>
            </div>
          </section>

          <section class="glass-card command-panel flex min-h-[590px] min-w-0 flex-col p-5 md:p-6">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <p class="text-xs font-semibold uppercase tracking-[0.22em] text-stone-400">Step 2</p>
                <h2 class="mt-1 text-lg font-semibold text-stone-800">{{ generatedTitle }}</h2>
                <p class="mt-1 text-xs text-stone-400">复制后直接粘贴到 {{ selectedShellOption.label }} 执行 · 目标位置：{{ selectedClientOption.configPath }}</p>
              </div>
              <button class="btn-primary py-2 text-xs" @click="copyText('snippet', generatedSnippet)">
                {{ copiedKey === 'snippet' ? '已复制' : '复制生成内容' }}
              </button>
            </div>

            <div class="command-code-shell mt-4 rounded-[24px] border border-stone-800/80 bg-stone-950 p-4 shadow-inner">
              <div class="mb-3 flex items-center justify-between gap-3 text-2xs uppercase tracking-[0.18em] text-stone-400">
                <span>{{ outputLanguage }}</span>
                <span>{{ selectedClientOption.badge }}</span>
              </div>
              <pre class="mcp-code"><code>{{ generatedSnippet }}</code></pre>
            </div>

            <div v-if="selectedClientOption.caveat" class="mt-3 rounded-2xl border border-amber-200/70 bg-amber-50/80 px-4 py-3 text-xs leading-5 text-amber-800">
              {{ selectedClientOption.caveat }}
            </div>

            <div class="mt-4 rounded-2xl border border-stone-200/70 bg-white/70 p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold text-stone-700">通用文件命令 fallback</p>
                  <p class="mt-1 text-xs text-stone-400">如果客户端专属命令不可用，复制这条命令生成标准 mcpServers 文件再导入。</p>
                </div>
                <button class="btn-secondary py-2 text-xs" @click="copyText('generic', genericCommand)">
                  {{ copiedKey === 'generic' ? '已复制' : '复制命令' }}
                </button>
              </div>
              <pre class="fallback-code mt-3 max-h-48 overflow-auto rounded-2xl bg-stone-100/80 p-3 text-xs leading-5 text-stone-700"><code>{{ genericCommand }}</code></pre>
            </div>

            <div class="mt-auto pt-4">
              <div class="rounded-[24px] border border-stone-200/70 bg-stone-50/70 p-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p class="text-sm font-semibold text-stone-700">连接自检</p>
                    <p class="mt-1 text-xs text-stone-400">完整执行 initialize / initialized / tools/list，并顺手检查 resources 与 prompts。</p>
                  </div>
                  <span v-if="testSummary" class="rounded-full bg-emerald-50 px-3 py-1 font-mono text-2xs text-emerald-700">{{ testSummary }}</span>
                </div>

                <div class="mt-4 grid gap-2 md:grid-cols-5">
                  <div
                    v-for="phase in testPhases"
                    :key="phase.id"
                    class="rounded-2xl border px-3 py-3 transition-all"
                    :class="phaseTone(phase.status)"
                  >
                    <div class="flex items-center gap-2">
                      <span class="h-2 w-2 rounded-full" :class="phaseDot(phase.status)" />
                      <span class="font-mono text-2xs font-semibold">{{ phase.label }}</span>
                    </div>
                    <p class="mt-1 text-2xs leading-4 opacity-80">{{ phase.detail || phase.description }}</p>
                  </div>
                </div>

                <p
                  v-if="testMessage"
                  class="mt-3 rounded-2xl px-4 py-3 text-xs leading-5"
                  :class="testStatus === 'success' ? 'bg-emerald-50 text-emerald-700' : testStatus === 'error' ? 'bg-red-50 text-red-700' : 'bg-white/80 text-stone-500'"
                >
                  {{ testMessage }}
                </p>
              </div>
            </div>
          </section>
        </div>

        <section class="grid gap-5 lg:grid-cols-[1.05fr_0.95fr_0.85fr]">
          <div class="glass-card p-5">
            <div class="flex items-center justify-between gap-3">
              <p class="text-sm font-semibold text-stone-800">可调用工具</p>
              <span class="rounded-full bg-stone-100 px-3 py-1 font-mono text-2xs text-stone-500">{{ displayTools.length }}</span>
            </div>
            <div class="mt-3 grid gap-2">
              <div v-for="tool in displayTools" :key="tool.name" class="rounded-2xl border border-stone-200 bg-white/70 px-3 py-2">
                <p class="font-mono text-2xs font-semibold text-stone-700">{{ tool.name }}</p>
                <p class="mt-1 text-2xs leading-4 text-stone-400">{{ tool.description || '公开只读 MCP 工具。' }}</p>
              </div>
            </div>
          </div>

          <div class="glass-card p-5">
            <p class="text-sm font-semibold text-stone-800">可读取资源</p>
            <div class="mt-3 space-y-2">
              <div v-for="resource in resources" :key="resource" class="rounded-2xl bg-white/70 px-3 py-2 font-mono text-2xs leading-5 text-stone-600">
                {{ resource }}
              </div>
            </div>
            <p class="mt-4 text-sm font-semibold text-stone-800">适合这样问</p>
            <ul class="mt-2 space-y-2 text-xs leading-5 text-stone-500">
              <li v-for="question in exampleQuestions" :key="question">“{{ question }}”</li>
            </ul>
          </div>

          <div class="glass-card p-5">
            <p class="text-sm font-semibold text-stone-800">Agent 使用建议</p>
            <ul class="mt-3 space-y-2 text-xs leading-5 text-stone-500">
              <li v-for="note in localFirstNotes" :key="note">{{ note }}</li>
            </ul>
            <p class="mt-4 text-sm font-semibold text-stone-800">安全边界</p>
            <p class="mt-3 text-xs leading-6 text-stone-500">
              当前 MCP Server 不暴露用户收藏、登录会话、邮件订阅、API Key、外部 MCP Token、后台接口、任意 SQL / URL / 文件访问，也没有删除、采集、调度、缓存清理等写操作。
            </p>
            <div class="mt-4 rounded-2xl border border-cyan-100 bg-cyan-50/70 px-4 py-3">
              <p class="text-2xs font-semibold uppercase tracking-[0.18em] text-cyan-700">Local-first read-only contract</p>
              <p class="mt-2 text-xs leading-5 text-cyan-800/80">项目推荐先查 AIGC_NEWS 本地项目库；仅本地 0 条时做限量 GitHub 只读 fallback，不写库也不暴露 Token。</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mcp-connect-page {
  position: relative;
}

.mcp-connect-page::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 12% 8%, rgba(6, 182, 212, 0.08), transparent 26%),
    radial-gradient(circle at 88% 14%, rgba(120, 113, 108, 0.08), transparent 24%);
}

.mcp-hero {
  isolation: isolate;
}

.mcp-grid-overlay {
  position: absolute;
  inset: 0;
  opacity: 0.32;
  background-image:
    linear-gradient(rgba(68, 64, 60, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(68, 64, 60, 0.06) 1px, transparent 1px);
  background-size: 34px 34px;
  mask-image: radial-gradient(circle at 30% 30%, black, transparent 72%);
  pointer-events: none;
}

.endpoint-card {
  box-shadow:
    0 16px 50px rgba(68, 64, 60, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.86);
}

.shell-selector {
  grid-auto-rows: minmax(76px, auto);
}

.shell-option {
  min-width: 0;
  min-height: 76px;
  overflow: hidden;
}

.shell-option span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.client-option:hover {
  transform: translateY(-1px);
}

.command-panel {
  overflow: hidden;
}

.command-code-shell {
  min-width: 0;
  overflow: hidden;
}

.mcp-code,
.fallback-code {
  width: 100%;
  min-width: 0;
  overflow: auto;
  white-space: pre;
  word-break: normal;
  overflow-wrap: normal;
  font-size: 12px;
  line-height: 1.7;
  tab-size: 2;
}

.mcp-code {
  min-height: 148px;
  max-height: 260px;
  color: #f8fafc;
}

.fallback-code {
  min-height: 72px;
}

.mcp-code code,
.fallback-code code {
  display: block;
  min-width: max-content;
}

.text-2xs {
  font-size: 0.68rem;
}
</style>
