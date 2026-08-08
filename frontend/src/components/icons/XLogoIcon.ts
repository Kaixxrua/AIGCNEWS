import { h, type FunctionalComponent } from 'vue'

/**
 * 最新 X（原 Twitter）品牌标志。lucide 已移除品牌图标，自行维护；
 * 用法与 lucide 组件一致：<component :is="XLogoIcon" class="h-4 w-4" />，
 * class 等 attrs 会透传到 svg 根节点。
 */
export const XLogoIcon: FunctionalComponent = (_props, { attrs }) => h(
  'svg',
  { ...attrs, viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': 'true' },
  [h('path', {
    d: 'M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z',
  })],
)
