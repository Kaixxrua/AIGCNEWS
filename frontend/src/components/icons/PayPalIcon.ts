import { h, type FunctionalComponent } from 'vue'

/**
 * PayPal 品牌标志（Simple Icons，CC0，2022 版双影 P 字标）。
 * lucide 已移除品牌图标，自行维护；品牌色锁定官方 #003087——
 * 支付渠道识别的刻意用色，不进主题 token。
 * 用法与 lucide 组件一致：<component :is="PayPalIcon" class="h-4 w-4" />，
 * class 等 attrs 会透传到 svg 根节点。
 */
export const PayPalIcon: FunctionalComponent = (_props, { attrs }) => h(
  'svg',
  { ...attrs, viewBox: '0 0 24 24', fill: '#003087', 'aria-hidden': 'true' },
  [h('path', {
    d: 'M15.607 4.653H8.941L6.645 19.251H1.82L4.862 0h7.995c3.754 0 6.375 2.294 6.473 5.513-.648-.478-2.105-.86-3.722-.86m6.57 5.546c0 3.41-3.01 6.853-6.958 6.853h-2.493L11.595 24H6.74l1.845-11.538h3.592c4.208 0 7.346-3.634 7.153-6.949a5.24 5.24 0 0 1 2.848 4.686M9.653 5.546h6.408c.907 0 1.942.222 2.363.541-.195 2.741-2.655 5.483-6.441 5.483H8.714Z',
  })],
)
