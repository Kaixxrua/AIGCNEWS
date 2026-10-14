import { consumeStyleParam, type AppStyle } from './appStyle'

/**
 * 分享链接里的 ?style=，在路由模块求值之前就从地址里读走。createWebHistory() 一创建就记下当时的地址，首次导航
 * 按记下的地址写回地址栏；晚一步读，参数就又回到地址里，刷新时还会把访客已经切回去的那一版再换掉。所以本模块
 * 是 main.ts 的第一条 import，App 和路由都排在它后面求值；读到的值交给 installAppStyle()。
 */
export const styleFromLink: AppStyle | null = typeof window === 'undefined' ? null : consumeStyleParam()
