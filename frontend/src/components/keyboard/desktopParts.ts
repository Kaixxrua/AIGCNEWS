import { lazyComponent } from '@/utils/lazyComponent'

/**
 * 列表键盘流的快捷键表只在桌面出现，单独成包，手机不下载。
 * 放在模块顶层：换页回来、页面重新挂载，都用同一份已经取回来的包。
 */
export const listKeysSheet = lazyComponent(() => import('./ListKeysSheet.vue'))
