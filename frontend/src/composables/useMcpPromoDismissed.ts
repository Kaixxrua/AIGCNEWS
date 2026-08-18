/**
 * useMcpPromoDismissed — 项目页 MCP 推广卡的关闭状态
 *
 * 两档关闭语义：
 * - dismiss()：仅本次会话隐藏（内存态），刷新后重新显示；
 * - dismissForWeek()：localStorage 写入 7 天后的过期时间戳，到期自动恢复显示。
 *
 * 存储值为过期时刻的 epoch 毫秒字符串；历史上写入的永久标记 '1' 无法解析为
 * 未来时间戳，会被视为未关闭（卡片默认显示）。读写均 try/catch，隐私模式/
 * 存储不可用时不抛错、只退化为本次会话内隐藏。
 */
import { ref, type Ref } from 'vue'
import { MCP_PROMO_DISMISSED_STORAGE_KEY } from '@/features/mcp/mcpExamplePrompts'

export const MCP_PROMO_DISMISS_WEEK_MS = 7 * 24 * 60 * 60 * 1000

function readDismissed(): boolean {
  try {
    const raw = window.localStorage.getItem(MCP_PROMO_DISMISSED_STORAGE_KEY)
    if (!raw) return false
    const expiresAt = Number(raw)
    return Number.isFinite(expiresAt) && expiresAt > Date.now()
  } catch {
    return false
  }
}

export function useMcpPromoDismissed(): {
  dismissed: Ref<boolean>
  dismiss: () => void
  dismissForWeek: () => void
} {
  const dismissed = ref(readDismissed())

  const dismiss = () => {
    dismissed.value = true
  }

  const dismissForWeek = () => {
    dismissed.value = true
    try {
      window.localStorage.setItem(MCP_PROMO_DISMISSED_STORAGE_KEY, String(Date.now() + MCP_PROMO_DISMISS_WEEK_MS))
    } catch {
      // 存储不可用时仅保留内存态
    }
  }

  return { dismissed, dismiss, dismissForWeek }
}
