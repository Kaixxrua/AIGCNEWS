import { ref } from 'vue'

const COPY_NOTICE_MS = 1800

export interface CopyNoticeOptions {
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  cancelSchedule?: (timer: ReturnType<typeof setTimeout>) => void
  /** 写剪贴板失败（没给权限、不是安全上下文）时调用，一般是弹一条提示。 */
  onError?: () => void
}

/**
 * 复制按钮的「已复制」反馈：copiedKey 记着刚复制成功的那颗按钮，1.8 秒后收回。
 * 怎么写剪贴板由调用方给：带 Token 的内容只走 copySensitiveToClipboard，不会退回把明文写进 DOM 的 textarea。
 */
export const useCopyNotice = (options: CopyNoticeOptions = {}) => {
  const schedule = options.schedule ?? setTimeout
  const cancelSchedule = options.cancelSchedule ?? clearTimeout
  const copiedKey = ref('')
  let timer: ReturnType<typeof setTimeout> | undefined
  let active = true

  /** 返回是否复制成功；卸载后迟到的结果不再改界面。 */
  const copy = async (key: string, write: () => Promise<void>): Promise<boolean> => {
    try {
      await write()
    } catch {
      if (active) options.onError?.()
      return false
    }
    if (!active) return false
    copiedKey.value = key
    if (timer !== undefined) cancelSchedule(timer)
    timer = schedule(() => {
      timer = undefined
      if (active && copiedKey.value === key) copiedKey.value = ''
    }, COPY_NOTICE_MS)
    return true
  }

  const dispose = () => {
    if (!active) return
    active = false
    copiedKey.value = ''
    if (timer !== undefined) cancelSchedule(timer)
    timer = undefined
  }

  return { copiedKey, copy, dispose }
}
