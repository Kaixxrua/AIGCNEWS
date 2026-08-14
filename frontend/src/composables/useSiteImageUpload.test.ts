import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  uploadSiteImage: vi.fn(),
  showToast: vi.fn(),
}))
vi.mock('@/services/monitor/monitorApi', () => ({
  monitorApi: { uploadSiteImage: mocks.uploadSiteImage },
}))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))
vi.mock('@/i18n', () => ({ i18n: { global: { t: (key: string) => key } } }))

import { useSiteImageUpload } from './useSiteImageUpload'

describe('useSiteImageUpload', () => {
  beforeEach(() => {
    mocks.uploadSiteImage.mockReset()
    mocks.showToast.mockReset()
  })

  it('uploads an allowed image and returns its site URL', async () => {
    mocks.uploadSiteImage.mockResolvedValueOnce({
      url: '/api/media/site/abc123.png',
      filename: 'qr.png',
      size_bytes: 8,
      mime_type: 'image/png',
    })
    const { uploadImage, uploading } = useSiteImageUpload()
    const file = new File([new Uint8Array(8)], 'qr.png', { type: 'image/png' })

    await expect(uploadImage(file)).resolves.toBe('/api/media/site/abc123.png')

    expect(mocks.uploadSiteImage).toHaveBeenCalledWith(file)
    expect(uploading.value).toBe(false)
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it('rejects unsupported image types client-side without calling the API', async () => {
    const { uploadImage } = useSiteImageUpload()
    const file = new File([new Uint8Array(8)], 'icon.svg', { type: 'image/svg+xml' })

    await expect(uploadImage(file)).resolves.toBeNull()

    expect(mocks.uploadSiteImage).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('monitor.contactPageConfig.unsupportedImageType')
  })

  it('rejects oversize images client-side without calling the API', async () => {
    const { uploadImage } = useSiteImageUpload()
    const file = new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' })

    await expect(uploadImage(file)).resolves.toBeNull()

    expect(mocks.uploadSiteImage).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('monitor.contactPageConfig.imageTooLarge')
  })

  it('toasts and returns null when the API call fails', async () => {
    mocks.uploadSiteImage.mockRejectedValueOnce(new Error('boom'))
    const { uploadImage, uploading } = useSiteImageUpload()
    const file = new File([new Uint8Array(8)], 'qr.png', { type: 'image/png' })

    await expect(uploadImage(file)).resolves.toBeNull()

    expect(uploading.value).toBe(false)
    expect(mocks.showToast).toHaveBeenCalledWith('monitor.contactPageConfig.uploadFailed')
  })
})
