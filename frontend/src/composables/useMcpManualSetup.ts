import { computed, ref } from 'vue'
import axios from 'axios'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import { MANUAL_MCP_TOKEN_LABEL, buildManualMcpConfig } from '@/features/mcp/manualMcpConfig'
import {
  createMcpToken as defaultCreateMcpToken,
  fetchMcpTokens as defaultFetchMcpTokens,
} from '@/services/mcp/mcpTokenApi'
import { copySensitiveToClipboard } from '@/composables/useClipboard'
import { useCopyNotice, type CopyNoticeOptions } from '@/composables/useCopyNotice'
import { useTokenConnectionWatch, type TokenConnectionWatchOptions } from '@/composables/useTokenConnectionWatch'

/**
 * /mcp 折叠起来的「手动配置」：给不支持浏览器授权的客户端，也用来排障。
 * 用户点「生成配置」才签一枚 Token（每点一次是新的一枚），明文只留在这个组合函数的内存里、只进安全剪贴板，
 * 页面预览一律用 COMMAND_TOKEN_SLOT；登出、卸载即丢弃，迟到的响应不回填。签好后盯着这枚令牌等第一次连接。
 */
export type ManualSetupPhase = 'idle' | 'creating' | 'ready' | 'error'

export interface McpManualSetupOptions {
  /** 当前入口的 MCP 地址（manualMcpEndpoint(location.origin)）。 */
  endpoint: () => string
  createMcpToken?: typeof defaultCreateMcpToken
  fetchMcpTokens?: typeof defaultFetchMcpTokens
  write?: (text: string) => Promise<void>
  connectionWatch?: Omit<TokenConnectionWatchOptions, 'fetchTokens'>
  copyNotice?: CopyNoticeOptions
}

const toErrorKey = (cause: unknown) =>
  axios.isAxiosError(cause) && cause.response?.status === 401 ? 'mcp.loginExpired' : 'mcp.tokenCreateFailed'

export const useMcpManualSetup = (options: McpManualSetupOptions) => {
  const createTokenApi = options.createMcpToken ?? defaultCreateMcpToken
  const fetchTokensApi = options.fetchMcpTokens ?? defaultFetchMcpTokens
  const write = options.write ?? copySensitiveToClipboard
  const connection = useTokenConnectionWatch({ ...options.connectionWatch, fetchTokens: () => fetchTokensApi() })
  const notice = useCopyNotice(options.copyNotice)
  const phase = ref<ManualSetupPhase>('idle')
  const error = ref('')
  const token = ref('')
  let generation = 0
  let disposed = false

  const preview = computed(() => buildManualMcpConfig(options.endpoint(), COMMAND_TOKEN_SLOT))
  // 没有 Token 时不拼配置，半成品不进剪贴板。
  const config = computed(() => (token.value ? buildManualMcpConfig(options.endpoint(), token.value) : ''))

  const generate = async (): Promise<boolean> => {
    if (disposed || phase.value === 'creating') return false
    const current = ++generation
    phase.value = 'creating'
    error.value = ''
    token.value = ''
    connection.stop()
    try {
      // 不传 scopes：由后端签发默认集合，前后端发布先后不会 422。
      const result = await createTokenApi({ client_type: 'other', client_label: MANUAL_MCP_TOKEN_LABEL })
      if (disposed || current !== generation) return false
      token.value = result.token
      phase.value = 'ready'
      connection.start(result.token_metadata)
      return true
    } catch (cause) {
      if (disposed || current !== generation) return false
      phase.value = 'error'
      error.value = toErrorKey(cause)
      return false
    }
  }

  /** 复制带 Token 的配置；复制后几分钟最可能连上，让检测重新勤快地查。 */
  const copyConfig = async (): Promise<boolean> => {
    if (!config.value) return false
    const copied = await notice.copy('manual-config', () => write(config.value))
    if (copied) connection.nudge()
    return copied
  }

  /** 登出或会话失效：丢掉明文，作废在途请求。 */
  const clear = () => {
    generation += 1
    token.value = ''
    error.value = ''
    phase.value = 'idle'
    connection.stop()
  }

  const dispose = () => {
    clear()
    disposed = true
    notice.dispose()
    connection.dispose()
  }

  return { phase, error, preview, config, copiedKey: notice.copiedKey, connection, generate, copyConfig, clear, dispose }
}
