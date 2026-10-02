// 本机收藏的推文：收下时整条原样存下（配图、引用、链接卡都在，配图上墙时照常走同源代理），看收藏时照推文墙原样排。
// 存在本机的内容拿出来上墙前把一道关：推文、引用与链接卡的地址只认 http(s)，被改过的本机存储塞不进别的协议。
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'

const isWebUrl = (value: unknown): value is string => typeof value === 'string' && /^https?:\/\//i.test(value)

/** 卡片里的地址缺了不碍事（不渲染），有就得是网页地址。 */
const linksOk = (part: unknown): boolean =>
  part == null || (typeof part === 'object' && isWebUrl((part as { url?: unknown }).url))

export function isSavedTweet(data: unknown): data is TopDoc {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return false
  const { url, quote, link_card: card } = data as TopDoc
  return isWebUrl(url) && linksOk(quote) && linksOk(card)
}
