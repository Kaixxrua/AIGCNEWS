import type { HtmlTagDescriptor, Plugin } from 'vite'

/** 与 src/theme/desktopStyles.ts 的 DESKTOP_STYLES_MEDIA 一致（测试钉住）。 */
export const DESKTOP_STYLES_MEDIA = '(min-width: 1024px)'

/** comic-pages.css 经 ?url 引入后产出的样式表。 */
export const isDesktopStylesAsset = (fileName: string): boolean => /^assets\/comic-pages-[\w-]+\.css$/.test(fileName)

export function desktopStylesPreloadTag(href: string): HtmlTagDescriptor {
  return { tag: 'link', attrs: { rel: 'preload', as: 'style', href, media: DESKTOP_STYLES_MEDIA }, injectTo: 'head' }
}

/**
 * 漫画版内页样式只在桌面宽度挂上（src/theme/desktopStyles.ts），挂载应用前要等它。构建时在 index.html 里给它加一条
 * 同样媒体条件的预加载：桌面上它和入口脚本一起下载，手机不命中就不下载。预加载不带 crossorigin，和运行时插入的
 * 样式表一致，才用得上。找不到这份样式表就让构建失败，免得桌面首屏悄悄多等一轮请求。
 */
export function desktopStylesPreload(): Plugin {
  let base = '/'
  return {
    name: 'desktop-styles-preload',
    apply: 'build',
    configResolved(config) {
      base = config.base
    },
    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        const asset = Object.values(ctx.bundle ?? {}).find(file => file.type === 'asset' && isDesktopStylesAsset(file.fileName))
        if (!asset) throw new Error('desktop-styles-preload: comic-pages.css 没有产出独立样式表，检查 src/theme/desktopStyles.ts 的 ?url 引入')
        return [desktopStylesPreloadTag(`${base}${asset.fileName}`)]
      },
    },
  }
}
