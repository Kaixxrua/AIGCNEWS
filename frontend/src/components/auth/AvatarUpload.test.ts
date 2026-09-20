import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import AvatarUpload from './AvatarUpload.vue'
import UserAvatar from './UserAvatar.vue'

const auth = vi.hoisted(() => ({
  user: { username: 'Reader', avatar_url: '/old.png' },
  updateAvatar: vi.fn(),
}))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => auth }))

beforeEach(() => {
  auth.updateAvatar.mockReset().mockResolvedValue(undefined)
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
})

const choose = async (wrapper: ReturnType<typeof mount>, file: File) => {
  const input = wrapper.find('input').element as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await wrapper.find('input').trigger('change')
}

describe('avatar upload', () => {
  it('previews a file before upload and releases the preview after saving', async () => {
    const wrapper = mount(AvatarUpload, { global: { plugins: [i18n] } })
    const file = new File(['png'], 'avatar.png', { type: 'image/png' })
    await choose(wrapper, file)
    expect(wrapper.find('img').attributes('src')).toBe('blob:preview')
    expect(auth.updateAvatar).not.toHaveBeenCalled()
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()
    expect(auth.updateAvatar).toHaveBeenCalledWith(file)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')
    expect(wrapper.text()).toContain('头像已更新')
    wrapper.unmount()
  })

  it('rejects SVG and oversized files without previewing or uploading', async () => {
    const wrapper = mount(AvatarUpload, { global: { plugins: [i18n] } })
    await choose(wrapper, new File(['<svg/>'], 'avatar.svg', { type: 'image/svg+xml' }))
    expect(wrapper.text()).toContain('请选择 PNG')
    await choose(wrapper, new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'large.png', { type: 'image/png' }))
    expect(wrapper.text()).toContain('不超过 2 MB')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(auth.updateAvatar).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps preview and allows retry when upload fails', async () => {
    auth.updateAvatar.mockRejectedValue(new Error('offline'))
    const wrapper = mount(AvatarUpload, { global: { plugins: [i18n] } })
    await choose(wrapper, new File(['png'], 'avatar.png', { type: 'image/png' }))
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.find('img').attributes('src')).toBe('blob:preview')
    expect(wrapper.find('button.btn-primary').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('offline')
    wrapper.unmount()
  })

  it('falls back to the first Unicode character on image error and retries a new image', async () => {
    const wrapper = mount(UserAvatar, { props: { name: ' 李开新', src: '/missing.png' } })
    await wrapper.find('img').trigger('error')
    expect(wrapper.text()).toBe('李')
    await wrapper.setProps({ src: '/new.png' })
    expect(wrapper.find('img').attributes('src')).toBe('/new.png')
    wrapper.unmount()
  })
})
