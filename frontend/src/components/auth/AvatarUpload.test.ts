import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import AvatarUpload from './AvatarUpload.vue'
import UserAvatar from './UserAvatar.vue'
import { DEFAULT_AVATARS } from '@/features/auth/defaultAvatar'

const defaultAvatarFile = vi.hoisted(() => vi.fn())
vi.mock('@/features/auth/defaultAvatarFile', () => ({ defaultAvatarFile }))

const auth = vi.hoisted(() => ({
  user: { username: 'Reader', avatar_url: '/old.png' },
  updateAvatar: vi.fn(),
}))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => auth }))

beforeEach(() => {
  auth.updateAvatar.mockReset().mockResolvedValue(undefined)
  defaultAvatarFile.mockReset().mockResolvedValue(new File(['png'], 'avatar-fox.png', { type: 'image/png' }))
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
})

const choose = async (wrapper: ReturnType<typeof mount>, file: File) => {
  const input = wrapper.find('input').element as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await wrapper.find('input').trigger('change')
}

describe('avatar upload', () => {
  it('previews and cancels a preset, then persists only the confirmed selection', async () => {
    const wrapper = mount(AvatarUpload, { global: { plugins: [i18n] } })
    await wrapper.get('[aria-controls="account-avatar-presets"]').trigger('click')
    expect(wrapper.findAll('.avatar-upload__option')).toHaveLength(6)
    const fox = wrapper.findAll('.avatar-upload__option')[4]!
    await fox.trigger('click')
    expect(fox.attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('.avatar-upload__preview img').attributes('src')).toBe(DEFAULT_AVATARS[4].src)
    expect(auth.updateAvatar).not.toHaveBeenCalled()
    await wrapper.get('button.btn-primary + button').trigger('click')
    expect(wrapper.get('.avatar-upload__preview img').attributes('src')).toBe('/old.png')
    expect(wrapper.find('button.btn-primary').exists()).toBe(false)
    await fox.trigger('click')
    await wrapper.get('button.btn-primary').trigger('click')
    await flushPromises()
    expect(defaultAvatarFile).toHaveBeenCalledWith(DEFAULT_AVATARS[4])
    expect(auth.updateAvatar).toHaveBeenCalledWith(await defaultAvatarFile.mock.results[0]!.value)
    expect(wrapper.text()).toContain('头像已更新')
    expect(wrapper.find('#account-avatar-presets').exists()).toBe(false)
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('releases an uploaded preview when choosing a preset and keeps the preset ready for retry', async () => {
    const wrapper = mount(AvatarUpload, { global: { plugins: [i18n] } })
    await choose(wrapper, new File(['png'], 'avatar.png', { type: 'image/png' }))
    await wrapper.get('[aria-controls="account-avatar-presets"]').trigger('click')
    await wrapper.get('.avatar-upload__option').trigger('click')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')
    defaultAvatarFile.mockRejectedValueOnce(new Error())
    await wrapper.get('button.btn-primary').trigger('click')
    await flushPromises()
    expect(auth.updateAvatar).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('头像上传失败')
    expect(wrapper.get('.avatar-upload__preview img').attributes('src')).toBe(DEFAULT_AVATARS[0].src)
    await wrapper.get('button.btn-primary').trigger('click')
    await flushPromises()
    expect(auth.updateAvatar).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

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

  it('keeps the account default on image error and name changes, then retries a new image', async () => {
    const wrapper = mount(UserAvatar, { props: { name: ' 李开新', seed: 42 } })
    const fallback = wrapper.find('img.user-avatar__default').attributes('src')
    expect(fallback).toBeTruthy()
    expect(wrapper.text()).toBe('')
    await wrapper.setProps({ src: '/missing.png' })
    expect(wrapper.find('img').attributes('src')).toBe('/missing.png')
    await wrapper.find('img').trigger('error')
    expect(wrapper.find('img.user-avatar__default').attributes('src')).toBe(fallback)
    await wrapper.setProps({ name: '新的名字' })
    expect(wrapper.find('img.user-avatar__default').attributes('src')).toBe(fallback)
    await wrapper.setProps({ src: '/new.png' })
    expect(wrapper.find('img').attributes('src')).toBe('/new.png')
    expect(wrapper.find('.user-avatar__default').exists()).toBe(false)
    await wrapper.setProps({ src: null })
    expect(wrapper.find('img.user-avatar__default').attributes('src')).toBe(fallback)
    wrapper.unmount()
  })
})
