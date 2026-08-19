import { ref } from 'vue'
import { DSH_PLUGIN_INSTALL_METHODS, type DshPluginInstallMethodId } from '@/features/mcp/dshPlugin'

const COPY_NOTICE_MS = 1800

export interface DshInstallControllerOptions {
  copy?: (value: string) => Promise<void>
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  cancelSchedule?: (timer: ReturnType<typeof setTimeout>) => void
  onCopyError?: () => void
}

export const useDshInstallController = (options: DshInstallControllerOptions = {}) => {
  const copy = options.copy ?? ((value: string) => navigator.clipboard.writeText(value))
  const schedule = options.schedule ?? setTimeout
  const cancelSchedule = options.cancelSchedule ?? clearTimeout
  const copiedKey = ref('')
  let timer: ReturnType<typeof setTimeout> | undefined
  let active = true

  const copyDshInstallCommand = async (methodId: DshPluginInstallMethodId = 'npm') => {
    const method = DSH_PLUGIN_INSTALL_METHODS.find((candidate) => candidate.id === methodId)
      ?? DSH_PLUGIN_INSTALL_METHODS[0]
    if (!method) return
    try {
      await copy(method.command)
      if (!active) return
      const key = `dsh-install-${method.id}`
      copiedKey.value = key
      if (timer) cancelSchedule(timer)
      timer = schedule(() => {
        if (active && copiedKey.value === key) copiedKey.value = ''
      }, COPY_NOTICE_MS)
    } catch {
      if (active) options.onCopyError?.()
    }
  }

  const dispose = () => {
    if (!active) return
    active = false
    copiedKey.value = ''
    if (timer) cancelSchedule(timer)
    timer = undefined
  }

  return { copiedKey, copyDshInstallCommand, dispose }
}
