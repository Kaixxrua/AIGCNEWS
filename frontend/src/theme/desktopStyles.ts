import comicPagesHref from '../comic-pages.css?url'

// 开发时改了 comic-pages.css：页面上那张样式表由 Vite 原地换新，这里只用它的地址，接住更新，免得整页刷新。
import.meta.hot?.accept('../comic-pages.css?url', () => {})

/**
 * 漫画版内页样式（comic-pages.css）整份包在 (min-width: 1024px) 里，手机用不上，打进入口样式表却占了六成（gzip 约 46 KB），
 * 每一页都得先下完才能出画面。所以它不进入口，只在桌面宽度挂上：一打开就是桌面宽度的，等它加载完再挂载应用，
 * 免得先按没有漫画样式的版面排一遍再跳；从窄屏拉宽到桌面时再挂。构建时 index.html 带一条同样媒体条件的预加载
 * （build/desktopStylesPreload.ts），桌面上它和入口脚本一起下载，挂载前通常不用再等。
 */
export const DESKTOP_STYLES_MEDIA = '(min-width: 1024px)'

/**
 * 返回的 Promise 在可以挂载应用时兑现：桌面宽度等样式表加载完（失败也放行），其余宽度立即兑现。
 * 要在路由开始加载页面之前调用：此刻最后一张样式表就是入口的，漫画版样式表不管什么时候挂上都插在它后面。
 */
export function installDesktopStyles(href: string = comicPagesHref, win: Window = window): Promise<void> {
  const doc = win.document
  const entry = lastStyleSheet(doc)
  const query = win.matchMedia(DESKTOP_STYLES_MEDIA)
  if (query.matches) return attach(href, doc, entry)
  const onChange = (event: MediaQueryListEvent) => {
    if (!event.matches) return
    query.removeEventListener('change', onChange)
    void attach(href, doc, entry)
  }
  query.addEventListener('change', onChange)
  return Promise.resolve()
}

/** 文档里最后一张样式表（开发时入口的样式是 <style>）。 */
function lastStyleSheet(doc: Document): Element | null {
  const sheets = doc.head.querySelectorAll('link[rel="stylesheet"], style')
  return sheets[sheets.length - 1] ?? null
}

/**
 * 插在入口样式表后面、各页按需加载的样式表之前，层叠先后才和原来打进入口时一样（项目库的 projectCatalog.css 有
 * 同样以 #app 开头、权重相同的规则，靠排在后面胜出）。从窄屏拉宽时这一页的样式表已经在了，所以按入口样式表定位，
 * 不是插到最后。加载失败也放行：没有漫画样式总比整页空白好。
 */
function attach(href: string, doc: Document, entry: Element | null): Promise<void> {
  const link = doc.createElement('link')
  link.rel = 'stylesheet'
  link.href = href
  const settled = new Promise<void>((resolve) => {
    link.addEventListener('load', () => resolve(), { once: true })
    link.addEventListener('error', () => resolve(), { once: true })
  })
  const first = doc.head.querySelector('link[rel="stylesheet"], style')
  if (entry?.isConnected) entry.after(link)
  else if (first) first.before(link)
  else doc.head.append(link)
  return settled
}
