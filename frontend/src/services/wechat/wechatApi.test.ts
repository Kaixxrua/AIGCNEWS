import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { wechatApi } from '@/services/wechat/wechatApi'
import { api } from '@/services/http/apiClient'

vi.mock('@/services/http/apiClient', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}))

describe('wechatApi', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset()
    vi.mocked(api.post).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('creates object URL from blob and revokes it', () => {
    const blob = new Blob(['qr'], { type: 'image/png' })
    const url = URL.createObjectURL(blob)
    expect(typeof url).toBe('string')
    URL.revokeObjectURL(url)
  })

  it('builds QR code URL with encoded attempt id', () => {
    const url = wechatApi.fetchQrCodeUrl('abc/123')
    expect(url).toBe('/api/ops/wechat/login-sessions/abc%2F123/qrcode')
  })

  it('normalizes search result defaults', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: {} })
    const result = await wechatApi.searchAccounts('openai')
    expect(api.get).toHaveBeenCalledWith('/ops/wechat/accounts/search', {
      params: { q: 'openai', begin: 0, size: 5 },
    })
    expect(result.items).toEqual([])
    expect(result.total).toBe(0)
  })
})
