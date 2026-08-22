/**
 * 支付页跳转封装：收银台拿到 redirect_url 指令后在新标签页打开渠道收银台，
 * 原标签页保留轮询与倒计时，支付结果在两边都能看到。
 * 抽成模块便于测试 vi.mock 替换（jsdom 无法 spy window.open/location.assign）。
 */
export const openPaymentPageInNewTab = (url: string): void => {
  // 被浏览器弹窗拦截时返回 null：兜底交给收银台的手动链接（提示语已覆盖）
  window.open(url, '_blank', 'noopener')
}
