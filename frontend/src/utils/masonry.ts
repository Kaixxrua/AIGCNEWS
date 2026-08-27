/**
 * 瀑布流通用工具：估高贪心分列 + 文本折行估算。
 * 由 xboard（推文墙）与 projects（项目库）两个瀑布流视图共用；
 * 各视图只需提供自己卡片结构的估高器。
 */

/**
 * 估高贪心分列：每条放入当前累计估高最矮的列（同高先比卡数、再取最左）。
 * 推文卡高度差可达 5–10 倍（纯文字 ~200px vs 多图/长文 >1000px），旧的
 * 纯轮询（i % n）完全不管高度，列高严重失衡——短列尾部会留下大片空白
 * （实测某页列高 2372/628/274/1296，空洞 2098px）。
 * 列内部仍保持传入顺序（时间降序），左上角依旧是最新一条；跨列横读
 * 连续性本就被高度差破坏，不再作为契约。
 * 缺省估高器时退化为轮询（等高假设下的旧行为）。
 */
export const distributeColumns = <T>(items: T[], columnCount: number, estimateHeight?: (item: T) => number): T[][] => {
  const count = Math.max(1, Math.floor(columnCount) || 1)
  const columns: T[][] = Array.from({ length: count }, () => [])
  if (!estimateHeight) {
    items.forEach((item, index) => columns[index % count]?.push(item))
    return columns
  }
  const heights: number[] = new Array<number>(count).fill(0)
  for (const item of items) {
    let target = 0
    for (let i = 1; i < count; i += 1) {
      const h = heights[i] ?? 0
      const best = heights[target] ?? 0
      // 同高取卡数更少者（估高全 0 的退化场景仍能摊匀），再同取最左
      if (h < best || (h === best && (columns[i]?.length ?? 0) < (columns[target]?.length ?? 0))) target = i
    }
    columns[target]?.push(item)
    heights[target] = (heights[target] ?? 0) + Math.max(0, estimateHeight(item) || 0)
  }
  return columns
}

/** CJK/全角字符按 1em 计宽，其余（拉丁/数字/空格）按 Inter 均值 ~0.52em */
const WIDE_CHAR_RE = /[\u2E80-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/

export const textAdvancePx = (text: string, fontSize: number): number => {
  let units = 0
  for (const ch of text) units += WIDE_CHAR_RE.test(ch) ? 1 : 0.52
  return units * fontSize
}

/** 折行估算：whitespace-pre-line 下显式换行各自独立成行（空段也占一行） */
export const estimateTextLines = (text: string, widthPx: number, fontSize: number): number => {
  if (!text || widthPx <= 0) return 0
  return text
    .split('\n')
    .reduce((lines, seg) => lines + Math.max(1, Math.ceil(textAdvancePx(seg, fontSize) / widthPx)), 0)
}
