import i18n from '@/i18n'

/**
 * 「页面不存在」页的文案独立成文件，沿用 pwa.ts 的注入方式：主 locale 表由其他
 * 工作流维护，这里在页面初始化时经 mergeLocaleMessage 注入 notFound.*。
 * 栏目入口的名字沿用报眉版名 masthead.sections.*，不另写。
 */

type NotFoundMessages = {
  notFound: {
    title: string
    lead: string
    home: string
    back: string
    sections: string
  }
}

const enUS: NotFoundMessages = {
  notFound: {
    title: 'Page not found',
    lead: 'There is no page at this address on AIGCNEWS. The link may be mistyped, or the page has been taken down.',
    home: 'Back to home',
    back: 'Go back',
    sections: 'Or head to a section',
  },
}

const zhCN: NotFoundMessages = {
  notFound: {
    title: '页面不存在',
    lead: '本站没有这个地址：可能是链接写错了，也可能这一页已经下线。',
    home: '回到首页',
    back: '返回上一页',
    sections: '也可以去这些栏目看看',
  },
}

let installed = false

export function installNotFoundMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
