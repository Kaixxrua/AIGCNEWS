/**
 * useClipboard — 公共剪贴板 composable
 *
 * 统一剪贴板操作，兼容非 HTTPS 环境（fallback textarea + execCommand）。
 * 各页面共用，避免重复实现。
 */

/** 复制文本到剪贴板（兼容非 HTTPS） */
export function copyToClipboard(text: string): Promise<void> {
  if (typeof navigator === 'undefined' || typeof document === 'undefined') {
    return Promise.reject(new Error('Clipboard unavailable'))
  }
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text)
  }
  // fallback：textarea + execCommand
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  try {
    ta.select()
    if (!document.execCommand('copy')) {
      throw new Error('Clipboard copy failed')
    }
  } finally {
    ta.remove()
  }
  return Promise.resolve()
}

/** 复制敏感文本（例如会员 RSS token），禁止退回会将文本写入 DOM 的 textarea。 */
export function copySensitiveToClipboard(text: string): Promise<void> {
  if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
    return Promise.reject(new Error('Secure clipboard unavailable'))
  }
  return navigator.clipboard.writeText(text)
}

/**
 * useClipboard composable — 返回 copy 函数与可选的 UI 反馈辅助
 */
export function useClipboard() {
  const copy = copyToClipboard

  return { copy }
}
