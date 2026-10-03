import { lazyComponent } from '@/utils/lazyComponent'

/**
 * 项目库榜单上只在桌面出现的部件：速览卡片（≥1024px）与详情栏（≥1600px），单独成包，手机不下载。
 * 放在模块顶层：换页回来、页面重新挂载，都用同一份已经取回来的包，不会每次先空一帧。
 */
export const projectPeekCard = lazyComponent(() => import('./ProjectPeekCard.vue'))
export const projectPane = lazyComponent(() => import('./ProjectPane.vue'))
