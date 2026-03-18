/**
 * useClipboard — 公共剪贴板 composable
 *
 * 统一剪贴板操作，兼容非 HTTPS 环境（fallback textarea + execCommand）。
 * 消除 ChatView / PaperReadView 中的重复实现。
 */

/** 复制文本到剪贴板（兼容非 HTTPS） */
export function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text)
  }
  // fallback：textarea + execCommand
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
  return Promise.resolve()
}

/**
 * useClipboard composable — 返回 copy 函数与可选的 UI 反馈辅助
 */
export function useClipboard() {
  const copy = copyToClipboard

  return { copy }
}
