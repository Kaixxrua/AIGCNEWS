import { computed, ref } from 'vue'
import axios from 'axios'
import { DSH_PLUGIN_INSTALL_METHODS, type DshPluginInstallMethodId } from '@/features/mcp/dshPlugin'
import {
  ensureDshMcpToken as defaultEnsureDshMcpToken,
  isDshTokenRecoveryRequired,
  rotateDshMcpToken as defaultRotateDshMcpToken,
  type DshMcpTokenResponse,
} from '@/services/mcp/mcpTokenApi'

/**
 * DSH 接入向导控制器。
 *
 * /dsh 已对游客开放为获客入口（路由无 requiresAuth），但 ensure 只会由
 * 向导在已登录状态下触发：挂载时已是登录态、或页面停留期间完成登录。
 * 没有 guest/Free/VIP 身份选择——配额由服务端按 token 属主实时会员档位
 * 计算。Token 只保存在本控制器的内存 ref 中——不写入
 * localStorage/sessionStorage/URL/日志；认证丢失或组件卸载立即清空，
 * 且迟到响应（generation/disposed 守卫）不得回填凭证。
 */
export type DshTokenPhase = 'idle' | 'loading' | 'ready' | 'error' | 'recovery'

export interface DshSetupOptions {
  ensureDshMcpToken?: typeof defaultEnsureDshMcpToken
  rotateDshMcpToken?: typeof defaultRotateDshMcpToken
}

const DSH_PATCH_PATH = '~/.dsh/profiles/web/cordis.patch.yml'

const yamlQuote = (value: string) => `'${value.replace(/'/g, "''")}'`

// 后端签发的 token 是 urlsafe 字符集（[A-Za-z0-9_-] 加 aigc_mcp_ 前缀），
// 不含双引号、$、反引号或反斜杠，因此可以安全地置于 shell 双引号内；
// YAML 侧的单引号由 yamlQuote 负责折转。
const shellDoubleQuote = (value: string) => `"${value}"`

const patchLines = (token: string) => [
  '- replace:',
  '    - id: aigc-radar',
  '      name: dsh-aigc-radar',
  '      config:',
  `        mcpToken: ${yamlQuote(token)}`,
]

const toErrorKey = (cause: unknown) =>
  axios.isAxiosError(cause) && cause.response?.status === 503
    ? 'dsh.wizard.tokenUnavailable'
    : 'mcp.tokenCreateFailed'

export const useDshSetupController = (options: DshSetupOptions = {}) => {
  const ensureTokenApi = options.ensureDshMcpToken ?? defaultEnsureDshMcpToken
  const rotateTokenApi = options.rotateDshMcpToken ?? defaultRotateDshMcpToken
  const selectedMethod = ref<DshPluginInstallMethodId>('npm')
  // 两步：0 = 安装方式，1 = 接入命令
  const step = ref(0)
  const phase = ref<DshTokenPhase>('idle')
  const token = ref('')
  const tokenReused = ref(false)
  const error = ref('')
  let generation = 0
  let inflight: Promise<boolean> | null = null
  let disposed = false

  const command = computed(() => DSH_PLUGIN_INSTALL_METHODS.find((m) => m.id === selectedMethod.value)?.command ?? DSH_PLUGIN_INSTALL_METHODS[0]!.command)
  // 一条命令完成安装与 Token 落盘：安装插件后把 mcpToken 补丁写进 profile 补丁层。
  // cordis.patch.yml 默认只有注释与空数组，追加会破坏 YAML 结构，因此整文件覆盖。
  // 没有 ready token 时绝不渲染命令（凭证不得出现在半成品 UI/复制板里）。
  const installLine = computed(() => {
    if (!token.value) return ''
    const args = patchLines(token.value).map(shellDoubleQuote).join(' ')
    return `${command.value} && printf '%s\\n' ${args} > ${DSH_PATCH_PATH}`
  })

  const applyToken = (result: DshMcpTokenResponse) => {
    token.value = result.token
    tokenReused.value = result.reused
    phase.value = 'ready'
    error.value = ''
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
  // 让迟到响应无法回填；在途 promise 自行结束并释放 inflight 槽位）
  const clearToken = () => {
    generation += 1
    token.value = ''
    tokenReused.value = false
    error.value = ''
    phase.value = 'idle'
  }

  const dispose = () => {
    disposed = true
    generation += 1
    token.value = ''
    tokenReused.value = false
  }

  const next = () => { step.value = Math.min(1, step.value + 1) }
  const previous = () => { step.value = Math.max(0, step.value - 1) }

  return {
    selectedMethod,
    step,
    phase,
    token,
    tokenReused,
    error,
    command,
    installLine,
    ensure,
    rotate,
    clearToken,
    dispose,
    next,
    previous,
  }
}
