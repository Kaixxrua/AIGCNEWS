<script setup lang="ts">
import axios from 'axios'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useClipboard } from '../composables/useClipboard'
import { useAuthStore } from '../stores/authStore'
import {
  createMcpToken,
  deleteMcpToken,
  fetchMcpTokens,
  type McpTokenMetadata,
} from '../services/api'
import {
  generateMcpClientCommand,
  mcpClientOptions,
  type McpClientId,
  type McpShellId,
} from '../utils/mcpClientConfig'

type TestPhaseStatus = 'idle' | 'running' | 'success' | 'error'

interface PublicTool { name: string; description: string }
interface TestPhase { label: string; description: string; status: TestPhaseStatus; detail: string }
interface JsonRpcData { jsonrpc?: string; id?: string | number | null; result?: any; error?: { message?: string } | string }

const router = useRouter()
const authStore = useAuthStore()
const { copy } = useClipboard()
const MCP_PROTOCOL_VERSION = '2025-06-18'
const MCP_TEST_TIMEOUT_MS = 15_000
const SCOPE = 'projects:favorites:read'
const defaultEndpoint = typeof window !== 'undefined' ? new URL('/api/mcp', window.location.origin).href : 'https://your-domain.com/api/mcp'

const endpointUrl = ref(defaultEndpoint)
const selectedShell = ref<McpShellId>('powershell')
const selectedClient = ref<McpClientId>('claude-code')
const clientLabel = ref('')
const multiOpen = ref(false)
const tokens = ref<McpTokenMetadata[]>([])
const loadingTokens = ref(false)
const creating = ref(false)
const deletingId = ref<number | null>(null)
const setupError = ref('')
const setupNotice = ref('')
const transientCommand = ref('')
const copiedKey = ref('')
const testing = ref(false)
const testMessage = ref('')
const detectedTools = ref<PublicTool[]>([])
let copyTimer: ReturnType<typeof setTimeout> | undefined

const shellOptions = [
  { id: 'powershell' as const, label: 'PowerShell' },
  { id: 'cmd' as const, label: 'Command Prompt' },
  { id: 'bash' as const, label: 'Bash / zsh' },
]
const clientOptions = mcpClientOptions
const publicTools: PublicTool[] = [
  { name: 'search_papers', description: '检索公开论文、AI 新闻与索引文档。' },
  { name: 'get_top_items', description: '读取 daily / weekly / monthly 排行。' },
  { name: 'search_github_projects', description: '搜索 GitHub 开源软件。' },
  { name: 'get_project_categories', description: '读取项目分类与计数。' },
]
const resources = ['aigc-news://dashboard/summary', 'aigc-news://projects/categories', 'aigc-news://report/latest']
const testPhases = ref<TestPhase[]>(createTestPhases())

const normalizedEndpoint = computed(() => endpointUrl.value.trim() || defaultEndpoint)
const clientOption = computed(() => clientOptions.find((item) => item.id === selectedClient.value)!)
const activeTokens = computed(() => tokens.value.filter((item) => !item.revoked_at && (!item.expires_at || new Date(item.expires_at) > new Date())))
const endpointWarning = computed(() => {
  try { return ['http:', 'https:'].includes(new URL(normalizedEndpoint.value).protocol) ? '' : 'MCP URL 只支持 http 或 https。' }
  catch { return '请输入有效的 MCP Server URL。' }
})

function createTestPhases(): TestPhase[] {
  return [
    { label: 'initialize', description: '协商协议版本', status: 'idle', detail: '' },
    { label: 'initialized', description: '确认初始化', status: 'idle', detail: '' },
    { label: 'tools/list', description: '读取公开工具', status: 'idle', detail: '' },
  ]
}

function clearTransientCommand() {
  transientCommand.value = ''
  if (copiedKey.value === 'command') copiedKey.value = ''
}
watch([selectedClient, selectedShell, endpointUrl, clientLabel, multiOpen], clearTransientCommand)

function generateAuthenticatedCommand(token: string) {
  return generateMcpClientCommand(
    clientOption.value,
    normalizedEndpoint.value,
    token,
    selectedShell.value,
  )
}

function apiError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (error.response?.status === 401) return '登录已过期，请重新登录。'
  }
  return error instanceof Error ? error.message : fallback
}
async function loadTokens() {
  if (!authStore.isLoggedIn) return
  loadingTokens.value = true
  setupError.value = ''
  try { tokens.value = await fetchMcpTokens() }
  catch (error) { setupError.value = apiError(error, '无法读取 MCP Token。') }
  finally { loadingTokens.value = false }
}
async function startSetup() {
  setupError.value = ''
  setupNotice.value = ''
  clearTransientCommand()
  if (!authStore.isLoggedIn) { await router.push('/login'); return }
  if (endpointWarning.value) { setupError.value = endpointWarning.value; return }
  if (!multiOpen.value && activeTokens.value.length > 0 && !window.confirm(`默认模式会撤销 ${activeTokens.value.length} 个现有有效 Token。确认继续替换？`)) return
  creating.value = true
  try {
    const result = await createMcpToken({
      client_type: clientOption.value.apiType,
      client_label: clientLabel.value.trim()
        ? `${clientOption.value.label} · ${clientLabel.value.trim()}`
        : clientOption.value.label,
      scopes: [SCOPE],
      multi_open: multiOpen.value,
    })
    transientCommand.value = generateAuthenticatedCommand(result.token)
    setupNotice.value = result.replaced_count > 0 ? `已创建并替换 ${result.replaced_count} 个旧 Token。请立即复制，离开后无法再次查看。` : 'Token 已创建。请立即复制，离开后无法再次查看。'
    await loadTokens()
  } catch (error) { setupError.value = apiError(error, '创建 MCP Token 失败。') }
  finally { creating.value = false }
}
async function copyGeneratedCommand() {
  if (!transientCommand.value) return
  try {
    await copy(transientCommand.value)
    copiedKey.value = 'command'
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copiedKey.value = '' }, 1800)
  } catch { setupError.value = '复制失败，请检查浏览器剪贴板权限。' }
}
async function removeToken(item: McpTokenMetadata) {
  if (!window.confirm(`删除 ${item.client_label || item.token_hint}？使用该 Token 的客户端将立即失去收藏访问权限。`)) return
  clearTransientCommand()
  deletingId.value = item.id
  setupError.value = ''
  try {
    await deleteMcpToken(item.id)
    tokens.value = tokens.value.filter((token) => token.id !== item.id)
    setupNotice.value = 'Token 已删除。'
  } catch (error) { setupError.value = apiError(error, '删除 MCP Token 失败。') }
  finally { deletingId.value = null }
}
function tokenStatus(item: McpTokenMetadata) {
  if (item.revoked_at) return '已撤销'
  if (item.expires_at && new Date(item.expires_at) <= new Date()) return '已过期'
  return '有效'
}
function formatDate(value?: string | null) { return value ? new Date(value).toLocaleString() : '从未' }

function protocolHeaders() { return { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': MCP_PROTOCOL_VERSION } }
async function postMcp(method: string, params: Record<string, unknown> | undefined, id: number | undefined) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), MCP_TEST_TIMEOUT_MS)
  try {
    const response = await fetch(normalizedEndpoint.value, { method: 'POST', headers: protocolHeaders(), body: JSON.stringify({ jsonrpc: '2.0', method, ...(id === undefined ? {} : { id }), ...(params ? { params } : {}) }), signal: controller.signal })
    const text = await response.text()
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const match = text.match(/data:\s*(\{.*\})/)
    const data = JSON.parse(match?.[1] || text || '{}') as JsonRpcData
    if (data.error) throw new Error(typeof data.error === 'string' ? data.error : data.error.message)
    return data
  } finally { window.clearTimeout(timeout) }
}
async function testPublicHandshake() {
  if (testing.value || endpointWarning.value) return
  testing.value = true
  testMessage.value = '正在测试公开握手…'
  testPhases.value = createTestPhases()
  try {
    testPhases.value[0]!.status = 'running'
    await postMcp('initialize', { protocolVersion: MCP_PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'aigc-news-connect-page', version: '1.0.0' } }, 1)
    testPhases.value[0]!.status = 'success'
    testPhases.value[1]!.status = 'running'
    await postMcp('notifications/initialized', undefined, undefined)
    testPhases.value[1]!.status = 'success'
    testPhases.value[2]!.status = 'running'
    const data = await postMcp('tools/list', {}, 2)
    detectedTools.value = Array.isArray(data.result?.tools) ? data.result.tools : []
    testPhases.value[2]!.status = 'success'
    testPhases.value[2]!.detail = `${detectedTools.value.length} tools`
    testMessage.value = '公开 MCP 握手成功。'
  } catch (error) {
    const running = testPhases.value.find((phase) => phase.status === 'running')
    if (running) running.status = 'error'
    testMessage.value = apiError(error, '握手失败。')
  } finally { testing.value = false }
}

onMounted(loadTokens)
onBeforeUnmount(() => { clearTransientCommand(); if (copyTimer) clearTimeout(copyTimer) })
</script>

<template>
  <div class="mcp-connect-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-8">
      <div class="mx-auto flex max-w-7xl flex-col gap-5 pb-24">
      <section class="glass-card relative overflow-hidden p-6 md:p-8">
        <div class="mcp-grid-overlay" />
        <div class="relative z-10 grid gap-6 xl:grid-cols-[1.15fr_0.85fr] xl:items-end">
          <div>
            <div class="mb-5 flex flex-wrap gap-2">
              <span v-for="pill in ['Streamable HTTP', 'Public Docs', 'Authenticated Favorites', 'Tools', 'Resources', 'Prompts']" :key="pill" class="rounded-full border border-cyan-200/60 bg-cyan-50/75 px-3 py-1 text-2xs font-semibold uppercase tracking-[0.14em] text-cyan-700">{{ pill }}</span>
            </div>
            <p class="text-xs font-semibold uppercase tracking-[0.32em] text-stone-400">AIGC_NEWS MCP Server</p>
            <h1 class="mt-3 max-w-4xl font-serif text-3xl font-semibold leading-tight text-stone-900 md:text-5xl">公开情报直接连接，个人收藏安全授权</h1>
            <p class="mt-4 max-w-3xl text-sm leading-7 text-stone-500 md:text-base">公开文档、工具发现与握手始终可用。登录后可创建仅含“读取收藏”权限的独立 MCP Token，并为客户端生成带 Authorization 的配置。</p>
          </div>
          <div class="rounded-[28px] border border-white/90 bg-white/75 p-5 shadow-sm">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">Public endpoint</p>
            <div class="mt-3 rounded-2xl border border-stone-200 bg-stone-50/80 px-3 py-3 font-mono text-xs text-stone-700">{{ normalizedEndpoint }}</div>
            <div class="mt-3 flex flex-col gap-2 sm:flex-row"><input v-model.trim="endpointUrl" class="input min-w-0 flex-1 font-mono text-xs" aria-label="MCP endpoint" /><button class="btn-secondary justify-center text-xs" :disabled="testing || Boolean(endpointWarning)" @click="testPublicHandshake">{{ testing ? '测试中…' : '公开握手' }}</button></div>
            <p v-if="endpointWarning" class="mt-2 text-xs text-rose-700">{{ endpointWarning }}</p>
            <p v-if="testMessage" class="mt-3 text-xs text-stone-500">{{ testMessage }}</p>
            <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3"><div v-for="phase in testPhases" :key="phase.label" class="rounded-xl border border-stone-200 bg-white p-2"><p class="font-mono text-2xs text-stone-700">{{ phase.label }}</p><p class="mt-1 text-2xs" :class="phase.status === 'success' ? 'text-emerald-600' : phase.status === 'error' ? 'text-rose-600' : 'text-stone-400'">{{ phase.detail || phase.status }}</p></div></div>
          </div>
        </div>
      </section>

      <section class="glass-card p-5 md:p-6">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div><p class="text-xs font-semibold uppercase tracking-[0.22em] text-stone-400">Authenticated setup</p><h2 class="mt-1 text-xl font-semibold text-stone-800">两步接入个人收藏</h2><p class="mt-2 text-sm text-stone-500">第一步选择客户端；第二步确认后创建 Token 并复制一次性命令。命令不会显示在页面，也不会持久化。</p></div>
          <button v-if="!authStore.isLoggedIn" class="btn-primary" @click="router.push('/login')">登录后配置</button>
          <span v-else class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">已登录</span>
        </div>

        <div v-if="authStore.isLoggedIn" class="mt-6 grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
          <div class="rounded-[24px] border border-stone-200/80 bg-white/65 p-5">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">Step 1 · 选择</p>
            <div class="mt-4 grid gap-2 sm:grid-cols-2"><button v-for="client in clientOptions" :key="client.id" class="rounded-[18px] border p-3 text-left" :class="selectedClient === client.id ? 'border-cyan-300 bg-cyan-50' : 'border-stone-200 bg-white'" @click="selectedClient = client.id"><span class="text-sm font-semibold text-stone-800">{{ client.label }}</span><span class="mt-1 block text-2xs leading-4 text-stone-400">{{ client.description }}</span></button></div>
            <p class="mt-5 text-sm font-semibold text-stone-700">终端</p>
            <div class="mt-2 flex flex-wrap gap-2"><button v-for="shell in shellOptions" :key="shell.id" class="rounded-full border px-3 py-2 text-xs" :class="selectedShell === shell.id ? 'border-stone-800 bg-stone-800 text-white' : 'border-stone-200 bg-white text-stone-600'" @click="selectedShell = shell.id">{{ shell.label }}</button></div>
            <label class="mt-5 block text-xs font-semibold text-stone-600">设备备注（可选）</label><input v-model="clientLabel" maxlength="128" class="input mt-2" placeholder="例如：工作电脑" />
          </div>

          <div class="rounded-[24px] border border-stone-200/80 bg-stone-50/70 p-5">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">Step 2 · 确认</p>
            <div class="mt-4 rounded-2xl border border-cyan-100 bg-cyan-50/70 p-4"><p class="text-sm font-semibold text-cyan-900">权限：读取我的项目收藏</p><p class="mt-1 font-mono text-2xs text-cyan-700">{{ SCOPE }}</p><p class="mt-2 text-xs leading-5 text-cyan-800/80">生成的客户端请求均携带 Authorization: Bearer &lt;token&gt;。Token 明文仅在本组件内存中保留到选择变化、删除或离开页面。</p></div>
            <label class="mt-4 flex cursor-pointer items-start gap-3 rounded-2xl border border-stone-200 bg-white p-4"><input v-model="multiOpen" type="checkbox" class="mt-0.5" /><span><span class="block text-sm font-semibold text-stone-700">允许多个 Token 同时有效</span><span class="mt-1 block text-xs leading-5 text-stone-400">默认关闭；关闭时会先确认，并由后端撤销现有有效 Token。</span></span></label>
            <button class="btn-primary mt-4 w-full justify-center" :disabled="creating" @click="startSetup">{{ creating ? '正在创建…' : activeTokens.length && !multiOpen ? `确认替换并生成配置（${activeTokens.length}）` : '生成安全配置' }}</button>
            <div v-if="transientCommand" class="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4"><p class="text-sm font-semibold text-amber-900">警告：复制内容包含 Bearer Token</p><p class="mt-1 text-xs font-semibold leading-5 text-amber-800">粘贴并执行后可能进入 Shell 历史记录。请将其视为密码，避免共享终端、录屏或日志；使用后按需清理历史记录。</p><p class="mt-2 text-xs leading-5 text-amber-700">配置内容保持隐藏且不会在页面渲染。请立即复制并粘贴到 {{ clientOption.configPath }} 对应环境。Claude Code 可执行后运行 <span class="font-mono">claude mcp get aigc-news</span> 或 <span class="font-mono">claude mcp list</span> 验证；Codex 需要从已设置 AIGC_NEWS_MCP_TOKEN 的终端启动。</p><button class="btn-primary mt-3 text-xs" @click="copyGeneratedCommand">{{ copiedKey === 'command' ? '已复制到剪贴板' : '复制一次性配置' }}</button></div>
            <p v-if="setupNotice" class="mt-3 rounded-2xl bg-emerald-50 px-4 py-3 text-xs text-emerald-700">{{ setupNotice }}</p>
            <p v-if="setupError" class="mt-3 rounded-2xl bg-rose-50 px-4 py-3 text-xs text-rose-700">{{ setupError }}</p>
          </div>
        </div>
        <div v-else class="mt-6 rounded-[24px] border border-dashed border-stone-300 bg-white/60 p-7 text-center"><p class="text-base font-semibold text-stone-700">登录后才能授权个人收藏</p><p class="mt-2 text-sm text-stone-500">公开 MCP Endpoint、握手文档、工具与资源清单仍可在本页查看和测试。</p></div>
      </section>

      <section v-if="authStore.isLoggedIn" class="glass-card p-5 md:p-6">
        <div class="flex items-center justify-between gap-3"><div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">Token management</p><h2 class="mt-1 text-lg font-semibold text-stone-800">已创建的 MCP Token</h2></div><button class="btn-secondary text-xs" :disabled="loadingTokens" @click="loadTokens">{{ loadingTokens ? '刷新中…' : '刷新' }}</button></div>
        <div v-if="tokens.length" class="mt-4 grid gap-3"><div v-for="item in tokens" :key="item.id" class="grid gap-3 rounded-[20px] border border-stone-200 bg-white/70 p-4 md:grid-cols-[1fr_auto] md:items-center"><div><div class="flex flex-wrap items-center gap-2"><span class="font-semibold text-stone-800">{{ item.client_label || item.client_type }}</span><span class="rounded-full px-2 py-0.5 text-2xs" :class="tokenStatus(item) === '有效' ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'">{{ tokenStatus(item) }}</span></div><p class="mt-2 font-mono text-xs text-stone-500">{{ item.token_hint }}</p><p class="mt-1 text-2xs text-stone-400">创建：{{ formatDate(item.created_at) }} · 最近使用：{{ formatDate(item.last_used_at) }}</p></div><button class="btn-secondary text-xs text-rose-700" :disabled="deletingId === item.id" @click="removeToken(item)">{{ deletingId === item.id ? '删除中…' : '删除' }}</button></div></div>
        <p v-else-if="!loadingTokens" class="mt-4 rounded-2xl bg-stone-50 p-5 text-sm text-stone-500">还没有 MCP Token。</p>
      </section>

      <section class="grid gap-5 lg:grid-cols-2">
        <div class="glass-card p-5"><div class="flex items-center justify-between"><p class="text-sm font-semibold text-stone-800">公开工具</p><span class="rounded-full bg-stone-100 px-3 py-1 text-2xs text-stone-500">{{ (detectedTools.length || publicTools.length) }} tools</span></div><div class="mt-3 grid gap-2"><div v-for="tool in (detectedTools.length ? detectedTools : publicTools)" :key="tool.name" class="rounded-2xl border border-stone-200 bg-white/70 px-3 py-2"><p class="font-mono text-2xs font-semibold text-stone-700">{{ tool.name }}</p><p class="mt-1 text-2xs text-stone-400">{{ tool.description }}</p></div></div></div>
        <div class="glass-card p-5"><p class="text-sm font-semibold text-stone-800">公开资源与安全边界</p><div class="mt-3 space-y-2"><div v-for="resource in resources" :key="resource" class="rounded-2xl bg-white/70 px-3 py-2 font-mono text-2xs text-stone-600">{{ resource }}</div></div><p class="mt-4 text-xs leading-6 text-stone-500">公开工具保持只读。个人收藏仅在携带用户创建的 Bearer Token 时可读；页面不保存 Token 明文，管理列表只返回脱敏提示。</p></div>
      </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mcp-connect-page { position: relative; }
.mcp-connect-page::before { content: ''; position: fixed; inset: 0; pointer-events: none; background: radial-gradient(circle at 12% 8%, rgba(6,182,212,.08), transparent 26%), radial-gradient(circle at 88% 14%, rgba(120,113,108,.08), transparent 24%); }
.mcp-grid-overlay { position: absolute; inset: 0; opacity: .28; background-image: linear-gradient(rgba(68,64,60,.06) 1px, transparent 1px), linear-gradient(90deg, rgba(68,64,60,.06) 1px, transparent 1px); background-size: 34px 34px; mask-image: radial-gradient(circle at 30% 30%, black, transparent 72%); pointer-events: none; }
.text-2xs { font-size: .68rem; }
</style>
