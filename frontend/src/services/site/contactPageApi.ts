import { api } from '@/services/http/apiClient'
import type {
  ContactPageEntryWire,
  ContactPageServiceCardWire,
  ContactPageWireResponse,
} from './contactPageContracts'

export interface SiteContactServiceCard {
  title: string
  description: string
  icon: string
}

export interface SiteContactEntry {
  label: string
  value: string
  href: string
  qrImageUrl: string
}

export interface SiteContactPage {
  enabled: boolean
  navLabel: string
  title: string
  subtitle: string
  serviceCards: SiteContactServiceCard[]
  contactEntries: SiteContactEntry[]
  bodyMarkdown: string
  updatedAt: string | null
}

/**
 * 缺省 fail-closed：与特性开关相反。开源部署默认不启用该页，
 * 端点不可达时宁可暂时隐藏入口，也不给未配置的站点闪一个空页面。
 */
export const DEFAULT_CONTACT_PAGE: SiteContactPage = {
  enabled: false,
  navLabel: '',
  title: '',
  subtitle: '',
  serviceCards: [],
  contactEntries: [],
  bodyMarkdown: '',
  updatedAt: null,
}

const mapServiceCard = (card: ContactPageServiceCardWire): SiteContactServiceCard => ({
  title: card.title ?? '',
  description: card.description ?? '',
  icon: card.icon ?? '',
})

const mapEntry = (entry: ContactPageEntryWire): SiteContactEntry => ({
  label: entry.label ?? '',
  value: entry.value ?? '',
  href: entry.href ?? '',
  qrImageUrl: entry.qr_image_url ?? '',
})

export const fetchContactPage = async (signal?: AbortSignal): Promise<SiteContactPage> => {
  const response = await api.get<ContactPageWireResponse>('/site/contact-page', { signal })
  const data = response.data
  if (!data?.enabled) {
    // 后端对未启用页面只返回 {"enabled": false}，草稿内容不下发
    return { ...DEFAULT_CONTACT_PAGE }
  }
  return {
    enabled: true,
    navLabel: data.nav_label ?? '',
    title: data.title ?? '',
    subtitle: data.subtitle ?? '',
    serviceCards: Array.isArray(data.service_cards) ? data.service_cards.map(mapServiceCard) : [],
    contactEntries: Array.isArray(data.contact_entries)
      ? data.contact_entries.map(mapEntry)
      : [],
    bodyMarkdown: data.body_markdown ?? '',
    updatedAt: data.updated_at ?? null,
  }
}
