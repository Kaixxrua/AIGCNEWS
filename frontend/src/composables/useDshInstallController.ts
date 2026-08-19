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

  const copyValue = async (key: string, value: string) => {
    try {
      await copy(value)
      if (!active) return
      copiedKey.value = key
      if (timer) cancelSchedule(timer)
      timer = schedule(() => {
        if (active && copiedKey.value === key) copiedKey.value = ''
      }, COPY_NOTICE_MS)
    } catch {
      if (active) options.onCopyError?.()
    }
  }

  const copyDshInstallCommand = async (methodId: DshPluginInstallMethodId = 'npm') => {
    const method = DSH_PLUGIN_INSTALL_METHODS.find((candidate) => candidate.id === methodId)
      ?? DSH_PLUGIN_INSTALL_METHODS[0]
    if (!method) return
    await copyValue(`dsh-install-${method.id}`, method.command)
  }

  const dispose = () => {
    if (!active) return
    active = false
    copiedKey.value = ''
    if (timer) cancelSchedule(timer)
    timer = undefined
  }

  return { copiedKey, copyValue, copyDshInstallCommand, dispose }
}
