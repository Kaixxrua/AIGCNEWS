import { computed, ref } from 'vue'
import axios from 'axios'
import { DSH_PLUGIN_INSTALL_METHODS, buildDshInstallLine, type DshPluginInstallMethodId } from '@/features/mcp/dshPlugin'
import {
  ensureDshMcpToken as defaultEnsureDshMcpToken,
  fetchMcpTokens as defaultFetchMcpTokens,
  isDshTokenRecoveryRequired,
  rotateDshMcpToken as defaultRotateDshMcpToken,
  type DshMcpTokenResponse,
} from '@/services/mcp/mcpTokenApi'
import { useTokenConnectionWatch, type TokenConnectionWatchOptions } from '@/composables/useTokenConnectionWatch'

/**
 * DSH 接入向导控制器。
 *
 * /dsh 已对游客开放为获客入口（路由无 requiresAuth），但 ensure 只会由
 * 向导在已登录状态下触发：挂载时已是登录态、或页面停留期间完成登录。
 * 没有 guest/Free/VIP 身份选择——配额由服务端按 token 属主实时会员档位
 * 计算。Token 只保存在本控制器的内存 ref 中——不写入
 * localStorage/sessionStorage/URL/日志；认证丢失或组件卸载立即清空，
 * 且迟到响应（generation/disposed 守卫）不得回填凭证。
 * 拿到 Token 后由 connection 盯着它（只按 id 对令牌列表，不碰明文）：新 Token 等第一次连接，
 * 以前连过的复用 Token 显示上次使用时间，用户复制命令后才接着查。
 */
export type DshTokenPhase = 'idle' | 'loading' | 'ready' | 'error' | 'recovery'

export interface DshSetupOptions {
  ensureDshMcpToken?: typeof defaultEnsureDshMcpToken
  rotateDshMcpToken?: typeof defaultRotateDshMcpToken
  fetchMcpTokens?: typeof defaultFetchMcpTokens
  /** 测试注入时钟、定时器与页面可见性。 */
  connectionWatch?: Omit<TokenConnectionWatchOptions, 'fetchTokens'>
}

const toErrorKey = (cause: unknown) =>
  axios.isAxiosError(cause) && cause.response?.status === 503
    ? 'dsh.wizard.tokenUnavailable'
    : 'mcp.tokenCreateFailed'

export const useDshSetupController = (options: DshSetupOptions = {}) => {
  const ensureTokenApi = options.ensureDshMcpToken ?? defaultEnsureDshMcpToken
  const rotateTokenApi = options.rotateDshMcpToken ?? defaultRotateDshMcpToken
  const fetchTokensApi = options.fetchMcpTokens ?? defaultFetchMcpTokens
  const connection = useTokenConnectionWatch({ ...options.connectionWatch, fetchTokens: () => fetchTokensApi() })
  const selectedMethod = ref<DshPluginInstallMethodId>('npm')
  const phase = ref<DshTokenPhase>('idle')
  const token = ref('')
  const tokenReused = ref(false)
  const error = ref('')
  let generation = 0
  let inflight: Promise<boolean> | null = null
  let disposed = false

  const command = computed(() => DSH_PLUGIN_INSTALL_METHODS.find((m) => m.id === selectedMethod.value)?.command ?? DSH_PLUGIN_INSTALL_METHODS[0]!.command)
  // 没有 ready token 时绝不渲染命令（凭证不得出现在半成品 UI/复制板里）。
  const installLine = computed(() => (token.value ? buildDshInstallLine(command.value, token.value) : ''))

  const applyToken = (result: DshMcpTokenResponse) => {
    token.value = result.token
    tokenReused.value = result.reused
    phase.value = 'ready'
    error.value = ''
    connection.start(result.token_metadata)
  }

  const ensure = async (): Promise<boolean> => {
    if (disposed) return false
    // 同一控制器实例只并发一次 ensure；已有 ready token 时直接命中
    if (phase.value === 'ready' && token.value) return true
    if (inflight) return inflight
    const current = ++generation
    phase.value = 'loading'
    error.value = ''
    let task: Promise<boolean> | null = null
    task = (async () => {
      try {
        const result = await ensureTokenApi()
        if (disposed || current !== generation) return false
        applyToken(result)
        return true
      } catch (cause) {
        if (disposed || current !== generation) return false
        token.value = ''
        connection.stop()
        if (isDshTokenRecoveryRequired(cause)) {
          // 旧版 hash-only token 无法回显明文：引导用户显式重新生成
          phase.value = 'recovery'
          return false
        }
        phase.value = 'error'
        error.value = toErrorKey(cause)
        return false
      } finally {
        if (inflight === task) inflight = null
      }
    })()
    inflight = task
    return task
  }

  const rotate = async (): Promise<boolean> => {
    if (disposed) return false
    const current = ++generation
    phase.value = 'loading'
    error.value = ''
    token.value = ''
    connection.stop()
    try {
      const result = await rotateTokenApi()
      if (disposed || current !== generation) return false
      applyToken(result)
      return true
    } catch (cause) {
      if (disposed || current !== generation) return false
      phase.value = 'error'
      error.value = toErrorKey(cause)
      return false
    }
  }

  // 认证丢失/登出：立即丢弃内存 token 并使在途请求失效（generation 守卫
  // 让迟到响应无法回填）。在途 promise 自行结束，但槽位当场让出：
  // 登出后马上又登录，新的 ensure 要发新请求，不能等来旧请求作废后的 false。
  const clearToken = () => {
    generation += 1
    inflight = null
    token.value = ''
    tokenReused.value = false
    error.value = ''
    phase.value = 'idle'
    connection.stop()
  }

  const dispose = () => {
    disposed = true
    generation += 1
    token.value = ''
    tokenReused.value = false
    connection.dispose()
  }

  return {
    selectedMethod,
    phase,
    token,
    tokenReused,
    error,
    command,
    installLine,
    connection,
    ensure,
    rotate,
    clearToken,
    dispose,
  }
}

/** /dsh 页面持有一个控制器，主卡（复制给 Agent）与「手动安装」共用同一枚 Token 和同一个连接检测。 */
export type DshSetupController = ReturnType<typeof useDshSetupController>
