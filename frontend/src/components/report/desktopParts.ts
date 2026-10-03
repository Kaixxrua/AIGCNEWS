import { lazyComponent } from '@/utils/lazyComponent'

/**
 * 简报只在桌面出现的部件：大报版式、收藏（≥1024px）与论文详情栏（≥1600px），单独成包，手机不下载。
 * 放在模块顶层：换页回来、面板重新挂载，都用同一份已经取回来的包，不会每次先空一帧。
 */
export const reportBroadsheet = lazyComponent(() => import('./ReportBroadsheet.vue'))
export const reportSavedPanel = lazyComponent(() => import('./ReportSavedPanel.vue'))
export const reportPaperPeek = lazyComponent(() => import('./ReportPaperPeek.vue'))
