import { computed, ref } from 'vue'
import { DSH_PLUGIN_INSTALL_METHODS, type DshPluginInstallMethodId } from '@/features/mcp/dshPlugin'
import { createMcpToken as defaultCreateMcpToken } from '@/services/mcp/mcpTokenApi'

export type DshIdentity = 'guest' | 'user' | 'vip'
export interface DshSetupOptions { createMcpToken?: typeof defaultCreateMcpToken }

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

export const useDshSetupController = (options: DshSetupOptions = {}) => {
  const createMcpToken = options.createMcpToken ?? defaultCreateMcpToken
  const identity = ref<DshIdentity>('guest')
  const selectedMethod = ref<DshPluginInstallMethodId>('npm')
  const step = ref(0)
  const creating = ref(false)
  const token = ref('')
  const error = ref('')
  const command = computed(() => DSH_PLUGIN_INSTALL_METHODS.find((m) => m.id === selectedMethod.value)?.command ?? DSH_PLUGIN_INSTALL_METHODS[0]!.command)
  // 一条命令完成安装与 Token 落盘：安装插件后把 mcpToken 补丁写进 profile 补丁层。
  // cordis.patch.yml 默认只有注释与空数组，追加会破坏 YAML 结构，因此整文件覆盖。
  const installLine = computed(() => {
    if (!token.value) return command.value
    const args = patchLines(token.value).map(shellDoubleQuote).join(' ')
    return `${command.value} && printf '%s\\n' ${args} > ${DSH_PATCH_PATH}`
  })

  const generate = async () => {
    if (identity.value === 'guest' || token.value || creating.value) return true
    creating.value = true
    error.value = ''
    try {
      const result = await createMcpToken({ client_type: 'other', client_label: 'dsh-aigc-radar' })
      token.value = result.token
      return true
    } catch {
      error.value = 'mcp.tokenCreateFailed'
      return false
    } finally { creating.value = false }
  }
  const next = async (isLoggedIn: boolean, isMember: boolean) => {
    if (step.value === 0) {
      if (identity.value !== 'guest' && !isLoggedIn) return 'login'
      if (identity.value === 'vip' && !isMember) return 'vip'
    }
    step.value = Math.min(2, step.value + 1)
    if (step.value === 2) await generate()
    return 'ok'
  }
  const previous = () => { step.value = Math.max(0, step.value - 1) }
  // VIP 会员免选身份，直接进入安装方式步骤；每次向导会话只自动跳一次，
  // 用户手动返回身份步骤后不再强行前推。
  // 普通登录用户仍停留在身份步骤，但默认身份从 guest 归一化为 user（Free），
  // 避免以隐藏的游客身份误入免 token 路径。
  let vipFastPathUsed = false
  const syncAuth = (isLoggedIn: boolean, isMember: boolean) => {
    if (!isLoggedIn) return
    if (!isMember) {
      if (step.value === 0 && identity.value === 'guest') identity.value = 'user'
      return
    }
    if (vipFastPathUsed || step.value !== 0) return
    vipFastPathUsed = true
    identity.value = 'vip'
    step.value = 1
  }
  const reset = () => { step.value = 0; token.value = ''; error.value = '' }
  return { identity, selectedMethod, step, creating, token, error, command, installLine, next, previous, generate, syncAuth, reset }
}
