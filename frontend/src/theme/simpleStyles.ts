import simpleThemeHref from '../simple-theme.css?url'

// 开发时改了 simple-theme.css：页面上那张样式表由 Vite 原地换新，这里只用它的地址，接住更新，免得整页刷新。
import.meta.hot?.accept('../simple-theme.css?url', () => {})

/**
 * 简洁版样式（simple-theme.css）只有选了简洁版的人用得上，不进入口样式表：以简洁版打开时挂载前加载，
 * 从漫画版切过来时先加载再换版。规则全部挂在 html[data-style='simple'] 下，切回漫画版不用卸，再切过去也不必重下。
 * 选择器比漫画版的同名规则多两级，挂在哪张样式表前后都压得住，所以直接追加在 head 末尾。
 */
let pending: Promise<void> | null = null

/** 兑现时样式表已可用；加载失败也兑现（照样换版，总比按钮没反应强），失败的那张会被摘掉，下次重试。 */
export function ensureSimpleStyles(href: string = simpleThemeHref, doc: Document = document): Promise<void> {
  if (pending) return pending
  const link = doc.createElement('link')
  link.rel = 'stylesheet'
  link.href = href
  link.dataset.appStyle = 'simple'
  pending = new Promise<void>((resolve) => {
    link.addEventListener('load', () => resolve(), { once: true })
    link.addEventListener('error', () => {
      link.remove()
      pending = null
      resolve()
    }, { once: true })
  })
  doc.head.append(link)
  return pending
}

/** 测试用：忘掉已挂上的样式表。 */
export function resetSimpleStylesForTest(): void {
  pending = null
}
