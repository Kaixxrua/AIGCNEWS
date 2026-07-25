<script setup lang="ts">
import axios from 'axios'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useClipboard } from '../composables/useClipboard'
import {
  displayedPublicTools as resolveDisplayedPublicTools,
  isActivePublicToolDiscovery,
  normalizePublicTools,
  type PublicToolDiscoveryState,
} from '../features/mcp/publicToolsModel'
import { useAuthStore } from '../stores/authStore'
import {
  mcpClientOptions,
  type McpClientId,
  type McpShellId,
} from '../features/mcp/mcpClientCatalog'
import { generateMcpClientCommand } from '../features/mcp/mcpCommandGenerator'
import {
  performPublicMcpHandshake,
  type McpHandshakePhase,
  type McpHandshakePhaseStatus,
} from '../features/mcp/mcpHandshake'
import {
  createMcpToken,
  deleteMcpToken,
  fetchMcpTokens,
  type McpTokenMetadata,
} from '../services/mcp/mcpTokenApi'

type TestPhaseStatus = 'idle' | 'running' | 'success' | 'error'

interface TestPhase { label: McpHandshakePhase; description: string; status: TestPhaseStatus; detail: string }

const router = useRouter()
const authStore = useAuthStore()
const { copy } = useClipboard()
const SCOPE = 'projects:favorites:read'
const MCP_FIRST_HOST_INSTRUCTION = `当用户明确要求寻找、搜索、推荐、比较或复用项目、仓库、开源实现、SDK、框架、组件、模板、示例或教程时，即使没有明确说 GitHub 或开源，也必须先调用一个最匹配的 AIGC_NEWS MCP 搜索工具。在实现重大模块、完整能力或独立子系统之前，即使用户没有要求搜索，也先做一次开源复用检查；重大能力指具有自身架构、集成或长期维护边界的完整能力，而不是单纯改动行数多。用户要求提升 AI 开发效率、加速 AI 应用交付或减少 AI 工程重复工作时，先调用 search_github_ai_projects。AI、Agent、MCP、RAG、LLM 工程产物使用 search_github_ai_projects；非 AI 软件产物使用 search_github_projects；主要交付物明确是论文、文献、引用、实验或学术评测时使用 search_papers。文案或样式、重命名、明确局部 Bug、测试/日志/类型、validation 或字段调整、简单 CRUD、孤立函数/组件/endpoint 修改不主动搜索。混合请求按主要交付物只选择一个初始路由，每个未变化需求最多一次初始搜索。不要把首次 MCP 搜索与 WebSearch、WebFetch 或 Bash 放在同一批次；等待并检查 MCP 结果后，只有在 MCP 失败、没有可用或相关结果，或缺少某个具体外部事实时，才针对该缺口使用 Web 工具。所有公开项目候选最低要求 500 GitHub Stars；原生 WebSearch 找到的项目必须核验当前 Stars 不低于 500，无法核验或低于门槛的候选不得展示、推荐或比较。500 Stars 只是准入门槛，不代表项目适用。找到候选不等于可以自动采用；如果复用会改变架构、部署、数据归属、许可证或长期维护，列出“直接复用、仅借鉴设计后自研、完全自研”等选项并等待用户确认。`
const defaultEndpoint = typeof window !== 'undefined' ? new URL('/api/mcp', window.location.origin).href : 'https://your-domain.com/api/mcp'

const endpointUrl = ref(defaultEndpoint)
const selectedShell = ref<McpShellId>('powershell')
const selectedClient = ref<McpClientId>('claude-code')
const clientLabel = ref('')
const tokens = ref<McpTokenMetadata[]>([])
const loadingTokens = ref(false)
const creating = ref(false)
const deletingId = ref<number | null>(null)
const setupError = ref('')
const setupNotice = ref('')
const transientCommand = ref('')
const copiedKey = ref('')
const testMessage = ref('')
let discoveryRunId = 0
let copyTimer: ReturnType<typeof setTimeout> | undefined

const shellOptions = [
  { id: 'powershell' as const, label: 'PowerShell' },
  { id: 'cmd' as const, label: 'Command Prompt' },
  { id: 'bash' as const, label: 'Bash / zsh' },
]
const clientOptions = mcpClientOptions
const testPhases = ref<TestPhase[]>(createTestPhases())

const normalizedEndpoint = computed(() => endpointUrl.value.trim() || defaultEndpoint)
const discoveryState = ref<PublicToolDiscoveryState>({ status: 'idle', endpoint: normalizedEndpoint.value })
const testing = computed(() => discoveryState.value.status === 'running')
const clientOption = computed(() => clientOptions.find((item) => item.id === selectedClient.value)!)
const displayedPublicTools = computed(() => resolveDisplayedPublicTools(normalizedEndpoint.value, discoveryState.value))
const setupScopeLabels = {
  user: '用户级',
  'conditional-user': '用户级 · 执行时检测',
  'user-with-session-secret': '用户配置 · 当前终端密钥',
  'import-file': '独立导入文件',
} as const
const setupScopeLabel = computed(() => setupScopeLabels[clientOption.value.setupScope])
const setupTargetDescription = computed(() => {
  if (clientOption.value.id === 'claude-code') return '执行后写入 Claude Code 用户级 MCP 配置，可在该用户的其他项目中使用。'
  if (clientOption.value.id === 'continue') return `执行后创建 ${clientOption.value.configPath}；若文件已存在会安全退出，不会覆盖。`
  if (clientOption.value.id === 'vscode') return '执行时先检查 code --add-mcp；支持时注册到 VS Code 默认用户 Profile，同名服务器会先请求确认；不支持则不修改配置。'
  if (clientOption.value.id === 'codex') return selectedShell.value === 'bash'
    ? 'MCP 注册写入 Codex 用户配置；Token 仅在当前 Bash / zsh 及其子进程中有效。'
    : 'MCP 注册写入 Codex 用户配置；Token 同时保存为当前 Windows 用户环境变量。'
  return `仅创建 ${clientOption.value.configPath}，不会自动修改客户端的用户级配置。`
})
const setupResultDescription = computed(() => {
  if (clientOption.value.id === 'claude-code') return '执行后可运行 claude mcp get aigc-news 或 claude mcp list 验证。'
  if (clientOption.value.id === 'continue') return 'Continue 将从用户级独立文件读取配置；若文件已存在，请先检查原文件，不要直接覆盖。'
  if (clientOption.value.id === 'vscode') return 'CLI 不支持时命令会安全失败；可升级 VS Code，或在 MCP: Add Server 中选择用户级配置。已有同名服务器时请确认是否替换。'
  if (clientOption.value.id === 'codex') return '请从已设置 AIGC_NEWS_MCP_TOKEN 的终端启动 Codex；新 Bash / zsh 终端需要重新设置 Token。'
  return `命令只生成 ${clientOption.value.configPath}，仍需在对应客户端中手动导入或合并。`
})
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
watch([selectedClient, selectedShell, endpointUrl, clientLabel], clearTransientCommand)
watch(normalizedEndpoint, (endpoint) => {
  discoveryRunId += 1
  discoveryState.value = { status: 'idle', endpoint }
  testMessage.value = ''
  testPhases.value = createTestPhases()
})

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
  creating.value = true
  try {
    const result = await createMcpToken({
      client_type: clientOption.value.apiType,
      client_label: clientLabel.value.trim()
        ? `${clientOption.value.label} · ${clientLabel.value.trim()}`
        : clientOption.value.label,
      scopes: [SCOPE],
    })
    transientCommand.value = generateAuthenticatedCommand(result.token)
    setupNotice.value = 'Token 已创建，可与其他 Token 同时使用。请立即复制，离开后无法再次查看。'
    await loadTokens()
  } catch (error) { setupError.value = apiError(error, '创建 MCP Token 失败。') }
  finally { creating.value = false }
}
async function copyText(value: string, key: string) {
  try {
    await copy(value)
    copiedKey.value = key
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copiedKey.value = '' }, 1800)
  } catch { setupError.value = '复制失败，请检查浏览器剪贴板权限。' }
}
async function copyGeneratedCommand() {
  if (!transientCommand.value) return
  await copyText(transientCommand.value, 'command')
}
async function copyHostInstruction() {
  await copyText(MCP_FIRST_HOST_INSTRUCTION, 'host-instruction')
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

async function testPublicHandshake() {
  if (testing.value || endpointWarning.value) return
  const endpoint = normalizedEndpoint.value
  const runId = ++discoveryRunId
  const isActive = () => isActivePublicToolDiscovery(endpoint, runId, discoveryState.value)
  discoveryState.value = { status: 'running', endpoint, runId }
  testMessage.value = '正在测试公开握手…'
  testPhases.value = createTestPhases()
  try {
    const tools = normalizePublicTools(await performPublicMcpHandshake(endpoint, {
      onPhase(phase: McpHandshakePhase, status: McpHandshakePhaseStatus) {
        if (!isActive()) return
        const item = testPhases.value.find((candidate) => candidate.label === phase)
        if (item) item.status = status
      },
    }))
    if (!isActive()) return
    const toolsPhase = testPhases.value.find((phase) => phase.label === 'tools/list')
    if (toolsPhase) toolsPhase.detail = `${tools.length} tools`
    testMessage.value = '公开 MCP 握手成功。'
    discoveryState.value = { status: 'success', endpoint, runId, tools }
  } catch (error) {
    if (!isActive()) return
    const running = testPhases.value.find((phase) => phase.status === 'running')
    if (running) running.status = 'error'
    testMessage.value = apiError(error, '握手失败。')
    discoveryState.value = { status: 'error', endpoint, runId }
  }
}

onMounted(loadTokens)
onBeforeUnmount(() => { discoveryRunId += 1; clearTransientCommand(); if (copyTimer) clearTimeout(copyTimer) })
</script>

<template>
  <div class="mcp-connect-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-8">
      <div class="mx-auto flex max-w-7xl flex-col gap-5 pb-24">
      <section class="glass-card relative overflow-hidden p-4 md:p-5">
        <div class="mcp-grid-overlay" />
        <div class="relative z-10 grid gap-4 xl:grid-cols-[1.05fr_0.95fr] xl:items-center">
          <div>
            <div class="mb-3 flex flex-wrap gap-2">
              <span v-for="pill in ['Streamable HTTP', 'Public tools', 'Private favorites']" :key="pill" class="rounded-full border border-cyan-200/60 bg-cyan-50/75 px-2.5 py-1 text-2xs font-semibold uppercase tracking-[0.12em] text-cyan-700">{{ pill }}</span>
            </div>
            <p class="text-2xs font-semibold uppercase tracking-[0.28em] text-stone-400">AIGC_NEWS MCP Server</p>
            <h1 class="mt-2 max-w-3xl font-serif text-2xl font-semibold leading-tight text-stone-900 md:text-3xl">连接公开情报，安全读取个人收藏</h1>
            <p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">公开工具无需授权；登录后可为不同客户端分别创建只读收藏 Token。</p>
          </div>
          <div class="rounded-[20px] border border-white/90 bg-white/75 p-4 shadow-sm">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">Public endpoint</p>
            <div class="mt-2 rounded-2xl border border-stone-200 bg-stone-50/80 px-3 py-2 font-mono text-xs text-stone-700">{{ normalizedEndpoint }}</div>
            <div class="mt-2 flex flex-col gap-2 sm:flex-row"><input v-model.trim="endpointUrl" class="input min-w-0 flex-1 font-mono text-xs" aria-label="MCP endpoint" /><button class="btn-secondary justify-center text-xs" :disabled="testing || Boolean(endpointWarning)" @click="testPublicHandshake">{{ testing ? '测试中…' : '公开握手' }}</button></div>
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
            <div class="mt-4 grid gap-2 sm:grid-cols-2"><button v-for="client in clientOptions" :key="client.id" class="mcp-choice rounded-[18px] border p-3 text-left" :class="selectedClient === client.id ? 'mcp-choice--active' : 'border-stone-200 bg-white'" @click="selectedClient = client.id"><span class="flex flex-wrap items-center gap-2"><span class="text-sm font-semibold text-stone-800">{{ client.label }}</span><span class="rounded-full bg-stone-100 px-2 py-0.5 text-2xs font-semibold text-stone-500">{{ setupScopeLabels[client.setupScope] }}</span></span><span class="mt-1 block text-2xs leading-4 text-stone-400">{{ client.description }}</span></button></div>
            <p class="mt-5 text-sm font-semibold text-stone-700">执行命令的终端</p>
            <div class="mt-2 flex flex-wrap gap-2"><button v-for="shell in shellOptions" :key="shell.id" class="mcp-choice rounded-full border px-3 py-2 text-xs" :class="selectedShell === shell.id ? 'mcp-choice--active' : 'border-stone-200 bg-white text-stone-600'" @click="selectedShell = shell.id">{{ shell.label }}</button></div>
            <label class="mt-5 block text-xs font-semibold text-stone-600">设备备注（可选）</label><input v-model="clientLabel" maxlength="128" class="input mt-2" placeholder="例如：工作电脑" />
          </div>

          <div class="rounded-[24px] border border-stone-200/80 bg-stone-50/70 p-5">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-stone-400">Step 2 · 确认</p>
            <div class="mt-4 rounded-2xl border border-cyan-100 bg-cyan-50/70 p-4"><p class="text-sm font-semibold text-cyan-900">权限：读取我的项目收藏</p><p class="mt-1 font-mono text-2xs text-cyan-700">{{ SCOPE }}</p><p class="mt-2 text-xs leading-5 text-cyan-800/80">生成的客户端请求均携带 Authorization: Bearer &lt;token&gt;。Token 明文仅在本组件内存中保留到选择变化、删除或离开页面。</p></div>
            <div class="mt-4 rounded-2xl border border-stone-200 bg-white/75 p-4"><div class="flex flex-wrap items-center gap-2"><span class="rounded-full bg-stone-100 px-2.5 py-1 text-2xs font-semibold text-stone-600">{{ setupScopeLabel }}</span><span class="text-xs font-semibold text-stone-700">{{ clientOption.configPath }}</span></div><p class="mt-2 text-xs leading-5 text-stone-500">{{ setupTargetDescription }}</p></div>
            <p class="mt-3 text-xs leading-5 text-stone-500">可为不同设备分别创建 Token，所有未删除的 Token 均可同时使用。</p>
            <button class="btn-primary mt-3 w-full justify-center" :disabled="creating" @click="startSetup">{{ creating ? '正在创建…' : clientOption.setupScope === 'import-file' ? '生成安全导入文件' : '生成用户级配置命令' }}</button>
            <div v-if="transientCommand" class="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4"><p class="text-sm font-semibold text-amber-900">警告：复制内容包含 Bearer Token</p><p class="mt-1 text-xs font-semibold leading-5 text-amber-800">粘贴并执行后可能进入 Shell 历史记录。请将其视为密码，避免共享终端、录屏或日志；使用后按需清理历史记录。</p><p class="mt-2 text-xs leading-5 text-amber-700">配置内容保持隐藏且不会在页面渲染。{{ setupResultDescription }} 若命令失败或不再需要，可在下方 Token 管理中删除刚创建的 Token。</p><button class="btn-primary mt-3 text-xs" @click="copyGeneratedCommand">{{ copiedKey === 'command' ? '已复制到剪贴板' : '复制一次性配置' }}</button></div>
            <p v-if="setupNotice" class="mt-3 rounded-2xl bg-emerald-50 px-4 py-3 text-xs text-emerald-700">{{ setupNotice }}</p>
            <p v-if="setupError" class="mt-3 rounded-2xl bg-rose-50 px-4 py-3 text-xs text-rose-700">{{ setupError }}</p>
          </div>
        </div>
        <div v-else class="mt-6 rounded-[24px] border border-dashed border-stone-300 bg-white/60 p-7 text-center"><p class="text-base font-semibold text-stone-700">登录后才能授权个人收藏</p><p class="mt-2 text-sm text-stone-500">公开 MCP Endpoint、握手文档、工具与资源清单仍可在本页查看和测试。</p></div>
      </section>

      <section v-if="authStore.isLoggedIn" class="glass-card p-5 md:p-6">
        <div class="flex items-center justify-between gap-3"><div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">Token management</p><h2 class="mt-1 text-lg font-semibold text-stone-800">已创建的 MCP Token</h2></div><button class="btn-secondary text-xs" :disabled="loadingTokens" @click="loadTokens">{{ loadingTokens ? '刷新中…' : '刷新' }}</button></div>
        <div v-if="tokens.length" class="mcp-token-list mt-4 grid gap-3 pr-1"><div v-for="item in tokens" :key="item.id" class="grid gap-3 rounded-[20px] border border-stone-200 bg-white/70 p-4 md:grid-cols-[1fr_auto] md:items-center"><div><div class="flex flex-wrap items-center gap-2"><span class="font-semibold text-stone-800">{{ item.client_label || item.client_type }}</span><span class="rounded-full px-2 py-0.5 text-2xs" :class="tokenStatus(item) === '有效' ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'">{{ tokenStatus(item) }}</span></div><p class="mt-2 font-mono text-xs text-stone-500">{{ item.token_hint }}</p><p class="mt-1 text-2xs text-stone-400">创建：{{ formatDate(item.created_at) }} · 最近使用：{{ formatDate(item.last_used_at) }}</p></div><button class="btn-secondary text-xs text-rose-700" :disabled="deletingId === item.id" @click="removeToken(item)">{{ deletingId === item.id ? '删除中…' : '删除' }}</button></div></div>
        <p v-else-if="!loadingTokens" class="mt-4 rounded-2xl bg-stone-50 p-5 text-sm text-stone-500">还没有 MCP Token。</p>
      </section>

      <section class="glass-card p-5 md:p-6">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div><p class="text-xs font-semibold uppercase tracking-[0.2em] text-stone-400">MCP-first routing</p><h2 class="mt-1 text-lg font-semibold text-stone-800">先发现、先复用，再实现重大能力</h2><p class="mt-2 max-w-3xl text-sm leading-6 text-stone-500">明确寻找项目时必搜；实现重大模块或独立子系统前先做一次开源复用检查；提升 AI 开发效率时优先搜索 AI 项目。样式、重命名、局部 Bug、简单 CRUD 等局部改动不主动搜索。</p></div>
          <button class="btn-secondary text-xs" @click="copyHostInstruction">{{ copiedKey === 'host-instruction' ? '已复制' : '复制 Host 指令' }}</button>
        </div>
        <div class="mt-4 grid gap-3 md:grid-cols-3">
          <div class="rounded-2xl border border-cyan-100 bg-cyan-50/60 p-4"><p class="font-mono text-2xs font-semibold text-cyan-800">AI / Agent / MCP / RAG</p><p class="mt-2 text-xs leading-5 text-cyan-900">search_github_ai_projects</p></div>
          <div class="rounded-2xl border border-stone-200 bg-white/70 p-4"><p class="font-mono text-2xs font-semibold text-stone-600">非 AI 软件与组件</p><p class="mt-2 text-xs leading-5 text-stone-800">search_github_projects</p></div>
          <div class="rounded-2xl border border-violet-100 bg-violet-50/60 p-4"><p class="font-mono text-2xs font-semibold text-violet-700">论文 / 引用 / 实验</p><p class="mt-2 text-xs leading-5 text-violet-900">search_papers</p></div>
        </div>
        <div class="mt-4 rounded-2xl border border-amber-200 bg-amber-50/70 p-4"><p class="text-xs font-semibold text-amber-900">连接配置无法强制宿主工具优先级</p><p class="mt-1 text-xs leading-5 text-amber-800">生成的命令只注册 endpoint 和 Token，无法跨客户端覆盖原生 Web Search。请把上方可复制指令加入宿主的全局或项目指令；首次 MCP 结果失败、无相关结果或缺少具体事实时，再顺序回退 Web。</p></div>
      </section>

      <section class="glass-card p-5">
        <div class="flex flex-wrap items-center justify-between gap-2"><div><p class="text-sm font-semibold text-stone-800">公开工具</p><p class="mt-1 text-xs text-stone-500">无需 Token，可直接读取公开数据。</p></div><span class="rounded-full bg-stone-100 px-3 py-1 text-2xs text-stone-500">{{ displayedPublicTools.length }} tools</span></div>
        <div class="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3"><div v-for="tool in displayedPublicTools" :key="tool.name" class="rounded-2xl border border-stone-200 bg-white/70 px-3 py-2"><p class="font-mono text-2xs font-semibold text-stone-700">{{ tool.name }}</p><p class="mt-1 text-2xs leading-4 text-stone-400">{{ tool.description }}</p></div></div>
      </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mcp-connect-page {
  --paper: #f3f0e6;
  --paper-light: #fffdf5;
  --ink: #11110f;
  --muted: #68655d;
  --acid: #c7f432;
  --acid-soft: #f1f8d2;
  position: relative;
  color: var(--ink);
  background: var(--paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.mcp-connect-page::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(17, 17, 15, .035) 1px, transparent 1px);
  background-size: 100% 32px;
}

.mcp-grid-overlay {
  position: absolute;
  inset: 0;
  opacity: .32;
  background-image: linear-gradient(rgba(17,17,15,.08) 1px, transparent 1px), linear-gradient(90deg, rgba(17,17,15,.08) 1px, transparent 1px);
  background-size: 34px 34px;
  pointer-events: none;
}

.mcp-token-list {
  max-height: min(28rem, 55vh);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.mcp-connect-page :deep(.glass-card) {
  border: 1px solid var(--ink);
  border-radius: 6px;
  background: rgba(255, 253, 245, .94);
  box-shadow: 4px 4px 0 var(--ink);
  backdrop-filter: none;
}

.mcp-connect-page :deep(.font-serif) { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.mcp-connect-page :deep(h1),
.mcp-connect-page :deep(h2) { color: var(--ink); font-weight: 850; letter-spacing: -.045em; }
.mcp-connect-page :deep(.text-stone-400),
.mcp-connect-page :deep(.text-stone-500) { color: var(--muted); }

.mcp-connect-page :deep(.rounded-full),
.mcp-connect-page :deep(.rounded-2xl),
.mcp-connect-page :deep(.rounded-xl),
.mcp-connect-page :deep([class*="rounded-["]) { border-radius: 4px; }

.mcp-connect-page :deep(.border-cyan-200\/60),
.mcp-connect-page :deep(.border-cyan-300),
.mcp-connect-page :deep(.border-cyan-100) { border-color: var(--ink); }
.mcp-connect-page :deep(.bg-cyan-50),
.mcp-connect-page :deep(.bg-cyan-50\/70),
.mcp-connect-page :deep(.bg-cyan-50\/75) { background: var(--acid); }
.mcp-connect-page :deep(.text-cyan-700),
.mcp-connect-page :deep(.text-cyan-800\/80),
.mcp-connect-page :deep(.text-cyan-900) { color: var(--ink); }

.mcp-connect-page :deep(button),
.mcp-connect-page :deep(.btn-primary),
.mcp-connect-page :deep(.btn-secondary) {
  border-radius: 4px;
  font-weight: 800;
  box-shadow: none;
}
.mcp-connect-page :deep(.btn-primary) { border: 1px solid var(--ink); color: var(--acid); background: var(--ink); }
.mcp-connect-page :deep(.btn-primary:not(:disabled):hover) { border-color: var(--ink); color: var(--ink); background: var(--acid); transform: none; }
.mcp-connect-page :deep(.btn-secondary) { border: 1px solid var(--ink); color: var(--ink); background: var(--paper-light); }
.mcp-connect-page :deep(.btn-secondary:not(:disabled):hover),
.mcp-connect-page :deep(.mcp-choice:hover) { border-color: var(--ink); color: var(--ink); background: var(--acid-soft); transform: none; }
.mcp-connect-page :deep(.mcp-choice--active),
.mcp-connect-page :deep(.mcp-choice--active:hover) { border-color: var(--ink); color: var(--ink); background: var(--acid); }
.mcp-connect-page :deep(input),
.mcp-connect-page :deep(.input) { border-color: var(--ink); border-radius: 4px; background: var(--paper-light); box-shadow: none; }
.mcp-connect-page :deep(input:focus),
.mcp-connect-page :deep(.input:focus) { border-color: var(--ink); box-shadow: 0 0 0 3px var(--acid); }

.text-2xs { font-size: .68rem; }
</style>
