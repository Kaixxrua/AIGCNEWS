import { readonly, ref } from 'vue'
import {
  DEFAULT_CONTACT_PAGE,
  fetchContactPage,
  type SiteContactPage,
} from '@/services/site/contactPageApi'

const contactPageConfig = ref<SiteContactPage>({ ...DEFAULT_CONTACT_PAGE })
let inflight: Promise<SiteContactPage> | null = null

/** 拉取一次联系合作页配置（进程内缓存共享）；请求失败保持 fail-closed 默认值。 */
export const ensureContactPageConfig = (): Promise<SiteContactPage> => {
  if (!inflight) {
    inflight = fetchContactPage()
      .then((fetched) => {
        contactPageConfig.value = fetched
        return fetched
      })
      .catch(() => contactPageConfig.value)
  }
  return inflight
}

/** 强制重取配置（monitor 保存成功后调用，使 Dock 入口当会话更新）。 */
export const refreshContactPageConfig = (): Promise<SiteContactPage> => {
  inflight = null
  return ensureContactPageConfig()
}

export const useContactPageConfig = () => ({
  contactPageConfig: readonly(contactPageConfig),
  ensureContactPageConfig,
  refreshContactPageConfig,
})

/** 测试缝：复位缓存与状态。 */
export const __resetContactPageConfigForTest = (): void => {
  contactPageConfig.value = { ...DEFAULT_CONTACT_PAGE }
  inflight = null
}
