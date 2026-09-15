import axios from 'axios'
import { computed, ref, watch } from 'vue'
import {
  mcpClientOptions,
  type McpClientId,
  type McpClientOption,
  type McpShellId,
} from '@/features/mcp/mcpClientCatalog'
import { generateMcpClientCommand } from '@/features/mcp/mcpCommandGenerator'
import {
  feedbackKey,
  feedbackLiteral,
  type McpFeedback,
  type McpFeedbackTranslator,
} from '@/features/mcp/mcpFeedback'
import {
  performPublicMcpHandshake,
  type McpHandshakeOptions,
  type McpHandshakePhase,
  type McpHandshakePhaseStatus,
} from '@/features/mcp/mcpHandshake'
import {
  displayedPublicTools as resolveDisplayedPublicTools,
  isActivePublicToolDiscovery,
  normalizePublicTools,
  type PublicToolDiscoveryState,
} from '@/features/mcp/publicToolsModel'
import {
  createMcpToken,
  deleteMcpToken,
  fetchMcpTokens,
  type CreateMcpTokenPayload,
  type CreateMcpTokenResponse,
  type McpTokenMetadata,
} from '@/services/mcp/mcpTokenApi'

const SCOPE = 'projects:favorites:read'
const COPY_NOTICE_MS = 1800

const defaultApi = { fetchMcpTokens, createMcpToken, deleteMcpToken }

export interface McpConnectApi {
  fetchMcpTokens: () => Promise<McpTokenMetadata[]>
  createMcpToken: (payload: CreateMcpTokenPayload) => Promise<CreateMcpTokenResponse>
  deleteMcpToken: (tokenId: number) => Promise<{ deleted: boolean; id: number }>
}

export type McpConnectHandshake = (
  endpoint: string,
  options?: McpHandshakeOptions,
) => Promise<unknown[]>

export type McpTokenStatus = 'valid' | 'expired' | 'revoked'
export type McpTestPhaseStatus = 'idle' | 'running' | 'success' | 'error'

export interface McpTestPhase {
  label: McpHandshakePhase
  descriptionKey: string
  status: McpTestPhaseStatus
  detail: McpFeedback
}

export interface McpConnectControllerOptions {
  api?: McpConnectApi
  handshake?: McpConnectHandshake
  copy?: (value: string) => Promise<void>
  isLoggedIn?: () => boolean
  navigateToLogin?: () => void | Promise<void>
  confirm?: (message: string) => boolean
  translate?: McpFeedbackTranslator
  defaultEndpoint?: string
  now?: () => Date
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  cancelSchedule?: (timer: ReturnType<typeof setTimeout>) => void
}

const createTestPhases = (): McpTestPhase[] => [
  { label: 'initialize', descriptionKey: 'initialize', status: 'idle', detail: null },
  { label: 'initialized', descriptionKey: 'initialized', status: 'idle', detail: null },
  { label: 'tools/list', descriptionKey: 'tools', status: 'idle', detail: null },
]

const defaultMcpEndpoint = () => (
  typeof window === 'undefined'
    ? 'https://your-domain.com/api/mcp'
    : new URL('/api/mcp', window.location.origin).href
)

export const useMcpConnectController = (options: McpConnectControllerOptions = {}) => {
  const api = options.api ?? defaultApi
  const handshake = options.handshake ?? performPublicMcpHandshake
  const copy = options.copy ?? (async (value: string) => navigator.clipboard.writeText(value))
  const isLoggedIn = options.isLoggedIn ?? (() => false)
  const translate = options.translate ?? ((key) => key)
  const confirmAction = options.confirm ?? ((message) => window.confirm(message))
  const now = options.now ?? (() => new Date())
  const schedule = options.schedule ?? setTimeout
  const cancelSchedule = options.cancelSchedule ?? clearTimeout
  const fallbackEndpoint = options.defaultEndpoint ?? defaultMcpEndpoint()

  const endpointUrl = ref(fallbackEndpoint)
  const selectedShell = ref<McpShellId>('powershell')
  const selectedClient = ref<McpClientId>('claude-code')
  const clientLabel = ref('')
  const tokens = ref<McpTokenMetadata[]>([])
  const loadingTokens = ref(false)
  const creating = ref(false)
  const deletingId = ref<number | null>(null)
  const setupError = ref<McpFeedback>(null)
  const setupNotice = ref<McpFeedback>(null)
  const transientCommand = ref('')
  const copiedKey = ref('')
  const testMessage = ref<McpFeedback>(null)
  const testPhases = ref<McpTestPhase[]>(createTestPhases())
  const isActive = ref(true)

  const normalizedEndpoint = computed(() => endpointUrl.value.trim() || fallbackEndpoint)
  // 游客可进入向导并选择客户端；前进到命令/验证步时由向导按此状态弹登录。
  // 登录态经视图注入的 authStore getter 保持响应式，登录完成后即翻转为 true。
  const isLoggedInState = computed(() => isLoggedIn())
  const requestLogin = async () => { await options.navigateToLogin?.() }
  const endpointWarningKey = computed(() => {
    try {
      return ['http:', 'https:'].includes(new URL(normalizedEndpoint.value).protocol)
        ? ''
        : 'mcp.invalidProtocol'
    } catch {
      return 'mcp.invalidUrl'
    }
  })
  const clientOption = computed(() => mcpClientOptions.find((item) => item.id === selectedClient.value)!)
  const clientDisplayLabel = (option: McpClientOption) => (option.labelKey ? translate(option.labelKey) : option.label)
  const quickCommand = computed(() => (
    endpointWarningKey.value
      ? ''
      : generateMcpClientCommand(clientOption.value, normalizedEndpoint.value, undefined, selectedShell.value)
  ))
  const discoveryState = ref<PublicToolDiscoveryState>({ status: 'idle', endpoint: normalizedEndpoint.value })
  const testing = computed(() => discoveryState.value.status === 'running')
  const displayedPublicTools = computed(() => resolveDisplayedPublicTools(normalizedEndpoint.value, discoveryState.value))

  let lifecycleGeneration = 0
  let setupGeneration = 0
  let tokenLoadGeneration = 0
  let discoveryRunId = 0
  let copyTimer: ReturnType<typeof setTimeout> | undefined
  const deletedTokenIds = new Set<number>()

  const activeLifecycle = (generation: number) => isActive.value && generation === lifecycleGeneration

  const apiFeedback = (error: unknown, fallbackKey: string): McpFeedback => {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') return feedbackLiteral(detail)
      if (error.response?.status === 401) return feedbackKey('mcp.loginExpired')
    }
    return error instanceof Error ? feedbackLiteral(error.message) : feedbackKey(fallbackKey)
  }

  const clearTransientCommand = () => {
    transientCommand.value = ''
    if (copiedKey.value === 'command') copiedKey.value = ''
  }

  const invalidateSetup = () => {
    setupGeneration += 1
    creating.value = false
    clearTransientCommand()
  }

  const resetDiscovery = (endpoint = normalizedEndpoint.value) => {
    discoveryRunId += 1
    discoveryState.value = { status: 'idle', endpoint }
    testMessage.value = null
    testPhases.value = createTestPhases()
  }

  watch([selectedClient, selectedShell, endpointUrl, clientLabel], invalidateSetup)
  watch(normalizedEndpoint, (endpoint) => resetDiscovery(endpoint))

  const loadTokens = async () => {
    if (!isLoggedIn() || !isActive.value) return
    const request = ++tokenLoadGeneration
    const lifecycle = lifecycleGeneration
    loadingTokens.value = true
    setupError.value = null
    try {
      const metadata = await api.fetchMcpTokens()
      if (!activeLifecycle(lifecycle) || request !== tokenLoadGeneration) return
      tokens.value = metadata.filter((token) => !deletedTokenIds.has(token.id))
    } catch (error) {
      if (activeLifecycle(lifecycle) && request === tokenLoadGeneration) {
        setupError.value = apiFeedback(error, 'mcp.tokenLoadFailed')
      }
    } finally {
      if (activeLifecycle(lifecycle) && request === tokenLoadGeneration) loadingTokens.value = false
    }
  }

  /**
   * Drop account-scoped material when the website auth state is no longer verified.
   * The view stays mounted during auth transitions, so hiding the template alone is
   * not enough to prevent stale token metadata or one-time commands from lingering.
   */
  const clearAuthenticatedState = () => {
    tokenLoadGeneration += 1
    setupGeneration += 1
    creating.value = false
    loadingTokens.value = false
    tokens.value = []
    setupError.value = null
    setupNotice.value = null
    clearTransientCommand()
  }

  const startSetup = async () => {
    setupError.value = null
    setupNotice.value = null
    invalidateSetup()
    if (!isLoggedIn()) {
      await options.navigateToLogin?.()
      return
    }
    if (endpointWarningKey.value) {
      setupError.value = feedbackKey(endpointWarningKey.value)
      return
    }

    const generation = setupGeneration
    const lifecycle = lifecycleGeneration
    const selectedOption = clientOption.value
    const shell = selectedShell.value
    const endpoint = normalizedEndpoint.value
    const label = clientLabel.value.trim()
    const displayLabel = clientDisplayLabel(selectedOption)
    creating.value = true
    try {
      const result = await api.createMcpToken({
        client_type: selectedOption.apiType,
        client_label: label ? `${displayLabel} · ${label}` : displayLabel,
        scopes: [SCOPE],
      })
      if (activeLifecycle(lifecycle) && generation === setupGeneration) {
        transientCommand.value = generateMcpClientCommand(selectedOption, endpoint, result.token, shell)
        setupNotice.value = feedbackKey('mcp.tokenCreated')
      }
      if (activeLifecycle(lifecycle)) await loadTokens()
    } catch (error) {
      if (activeLifecycle(lifecycle) && generation === setupGeneration) {
        setupError.value = apiFeedback(error, 'mcp.tokenCreateFailed')
      }
    } finally {
      if (activeLifecycle(lifecycle) && generation === setupGeneration) creating.value = false
    }
  }

  const copyText = async (value: string, key: string) => {
    const lifecycle = lifecycleGeneration
    try {
      await copy(value)
      if (!activeLifecycle(lifecycle)) return
      copiedKey.value = key
      if (copyTimer) cancelSchedule(copyTimer)
      copyTimer = schedule(() => {
        if (activeLifecycle(lifecycle) && copiedKey.value === key) copiedKey.value = ''
      }, COPY_NOTICE_MS)
    } catch {
      if (activeLifecycle(lifecycle)) setupError.value = feedbackKey('mcp.copyFailed')
    }
  }

  const copyGeneratedCommand = async () => {
    if (transientCommand.value) await copyText(transientCommand.value, 'command')
  }

  const copyQuickCommand = async () => {
    if (quickCommand.value) await copyText(quickCommand.value, 'quick-command')
  }

  const copyHostInstruction = async () => copyText(translate('mcp.hostInstruction'), 'host-instruction')

  const removeToken = async (item: McpTokenMetadata) => {
    const label = item.client_label || item.token_hint
    if (!confirmAction(translate('mcp.deleteConfirm', { label }))) return
    const lifecycle = lifecycleGeneration
    clearTransientCommand()
    deletedTokenIds.add(item.id)
    tokenLoadGeneration += 1
    loadingTokens.value = false
    deletingId.value = item.id
    setupError.value = null
    try {
      await api.deleteMcpToken(item.id)
      if (!activeLifecycle(lifecycle)) return
      tokens.value = tokens.value.filter((token) => token.id !== item.id)
      setupNotice.value = feedbackKey('mcp.tokenDeleted')
    } catch (error) {
      deletedTokenIds.delete(item.id)
      if (activeLifecycle(lifecycle)) setupError.value = apiFeedback(error, 'mcp.tokenDeleteFailed')
    } finally {
      if (activeLifecycle(lifecycle) && deletingId.value === item.id) deletingId.value = null
    }
  }

  const tokenStatus = (item: McpTokenMetadata): McpTokenStatus => {
    if (item.revoked_at) return 'revoked'
    if (item.expires_at && new Date(item.expires_at) <= now()) return 'expired'
    return 'valid'
  }

  const testPublicHandshake = async () => {
    if (testing.value || endpointWarningKey.value || !isActive.value) return
    const endpoint = normalizedEndpoint.value
    const runId = ++discoveryRunId
    const lifecycle = lifecycleGeneration
    const runIsActive = () => activeLifecycle(lifecycle)
      && isActivePublicToolDiscovery(endpoint, runId, discoveryState.value)
    discoveryState.value = { status: 'running', endpoint, runId }
    testMessage.value = feedbackKey('mcp.handshakeTesting')
    testPhases.value = createTestPhases()
    try {
      const tools = normalizePublicTools(await handshake(endpoint, {
        onPhase(phase: McpHandshakePhase, status: McpHandshakePhaseStatus) {
          if (!runIsActive()) return
          const item = testPhases.value.find((candidate) => candidate.label === phase)
          if (item) item.status = status
        },
      }))
      if (!runIsActive()) return
      const toolsPhase = testPhases.value.find((phase) => phase.label === 'tools/list')
      if (toolsPhase) toolsPhase.detail = feedbackKey('mcp.toolCount', { count: tools.length })
      testMessage.value = feedbackKey('mcp.handshakeSuccess')
      discoveryState.value = { status: 'success', endpoint, runId, tools }
    } catch (error) {
      if (!runIsActive()) return
      const running = testPhases.value.find((phase) => phase.status === 'running')
      if (running) running.status = 'error'
      testMessage.value = apiFeedback(error, 'mcp.handshakeFailed')
      discoveryState.value = { status: 'error', endpoint, runId }
    }
  }

  const dispose = () => {
    if (!isActive.value) return
    isActive.value = false
    lifecycleGeneration += 1
    setupGeneration += 1
    tokenLoadGeneration += 1
    discoveryRunId += 1
    loadingTokens.value = false
    creating.value = false
    deletingId.value = null
    clearTransientCommand()
    copiedKey.value = ''
    if (copyTimer) cancelSchedule(copyTimer)
    copyTimer = undefined
  }

  return {
    clientDisplayLabel,
    clientLabel,
    clientOption,
    clearAuthenticatedState,
    clearTransientCommand,
    copiedKey,
    copyGeneratedCommand,
    copyHostInstruction,
    copyQuickCommand,
    creating,
    deletingId,
    discoveryState,
    displayedPublicTools,
    dispose,
    endpointUrl,
    endpointWarningKey,
    isActive,
    isLoggedIn: isLoggedInState,
    loadTokens,
    loadingTokens,
    normalizedEndpoint,
    quickCommand,
    removeToken,
    requestLogin,
    resetDiscovery,
    selectedClient,
    selectedShell,
    setupError,
    setupNotice,
    startSetup,
    testing,
    testMessage,
    testPhases,
    testPublicHandshake,
    tokenStatus,
    tokens,
    transientCommand,
  }
}

export type McpConnectController = ReturnType<typeof useMcpConnectController>
