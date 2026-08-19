import { computed, ref } from 'vue'
import { DSH_PLUGIN_INSTALL_METHODS, type DshPluginInstallMethodId } from '@/features/mcp/dshPlugin'
import { createMcpToken as defaultCreateMcpToken } from '@/services/mcp/mcpTokenApi'

export type DshIdentity = 'guest' | 'user' | 'vip'
export interface DshSetupOptions { createMcpToken?: typeof defaultCreateMcpToken }

const yamlQuote = (value: string) => `'${value.replace(/'/g, "''")}'`

export const useDshSetupController = (options: DshSetupOptions = {}) => {
  const createMcpToken = options.createMcpToken ?? defaultCreateMcpToken
  const identity = ref<DshIdentity>('guest')
  const selectedMethod = ref<DshPluginInstallMethodId>('npm')
  const step = ref(0)
  const creating = ref(false)
  const token = ref('')
  const error = ref('')
  const command = computed(() => DSH_PLUGIN_INSTALL_METHODS.find((m) => m.id === selectedMethod.value)?.command ?? DSH_PLUGIN_INSTALL_METHODS[0]!.command)
  const patch = computed(() => token.value
    ? `- replace:\n    - id: aigc-radar\n      name: dsh-aigc-radar\n      config:\n        mcpToken: ${yamlQuote(token.value)}`
    : '')

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
  const reset = () => { step.value = 0; token.value = ''; error.value = '' }
  return { identity, selectedMethod, step, creating, token, error, command, patch, next, previous, generate, reset }
}
