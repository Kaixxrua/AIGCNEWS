import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { DEFAULT_CONTACT_PAGE, fetchContactPage } from './contactPageApi'

describe('Contact page API contract', () => {
  beforeEach(() => {
    transport.get.mockReset()
  })

  it('maps wire snake_case content to camelCase', async () => {
    const signal = new AbortController().signal
    transport.get.mockResolvedValueOnce({
      data: {
        enabled: true,
        nav_label: '合作',
        title: '联系合作',
        subtitle: '外包 · 商务合作',
        service_cards: [{ title: '外包开发', description: 'AI 应用定制', icon: 'code' }],
        contact_entries: [
          { label: 'QQ 群', value: '123456', href: 'https://qm.qq.com/x', qr_image_url: '/qr.png' },
        ],
        body_markdown: '# 欢迎',
        updated_at: '2026-08-13T10:00:00+00:00',
      },
    })

    await expect(fetchContactPage(signal)).resolves.toEqual({
      enabled: true,
      navLabel: '合作',
      title: '联系合作',
      subtitle: '外包 · 商务合作',
      serviceCards: [{ title: '外包开发', description: 'AI 应用定制', icon: 'code' }],
      contactEntries: [
        { label: 'QQ 群', value: '123456', href: 'https://qm.qq.com/x', qrImageUrl: '/qr.png' },
      ],
      bodyMarkdown: '# 欢迎',
      updatedAt: '2026-08-13T10:00:00+00:00',
    })
    expect(transport.get).toHaveBeenLastCalledWith('/site/contact-page', { signal })
  })

  it('fails closed when the page is disabled or fields are missing', async () => {
    // 后端对未启用页面只返回 {"enabled": false}
    transport.get.mockResolvedValueOnce({ data: { enabled: false } })
    await expect(fetchContactPage()).resolves.toEqual(DEFAULT_CONTACT_PAGE)

    transport.get.mockResolvedValueOnce({ data: {} })
    await expect(fetchContactPage()).resolves.toEqual(DEFAULT_CONTACT_PAGE)

    transport.get.mockResolvedValueOnce({ data: null })
    await expect(fetchContactPage()).resolves.toEqual(DEFAULT_CONTACT_PAGE)
  })

  it('tolerates non-array cards/entries payloads', async () => {
    transport.get.mockResolvedValueOnce({
      data: { enabled: true, service_cards: 'oops', contact_entries: null },
    })

    const page = await fetchContactPage()
    expect(page.enabled).toBe(true)
    expect(page.serviceCards).toEqual([])
    expect(page.contactEntries).toEqual([])
  })
})
