/**
 * 整页跳转封装：收银台拿到 redirect_url 指令后自动跳渠道收银台。
 * jsdom 无法 spy window.location.assign，抽成模块便于测试 vi.mock 替换。
 */
export const redirectToUrl = (url: string): void => {
  window.location.assign(url)
}
