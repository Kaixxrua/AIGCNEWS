import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SiteContactPageConfigPanel from './SiteContactPageConfigPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import { createSiteContactPageForm, type SiteContactPageForm } from '@/features/monitor/monitorModel'

const mocks = vi.hoisted(() => ({ uploadImage: vi.fn() }))
vi.mock('@/composables/useSiteImageUpload', async () => {
  const { ref } = await import('vue')
  return {
    useSiteImageUpload: () => ({ uploading: ref(false), uploadImage: mocks.uploadImage }),
  }
})

const mountPanel = (form: SiteContactPageForm) =>
  mount(SiteContactPageConfigPanel, {
    global: { plugins: [i18n] },
    props: { config: null, form, loading: false, saving: false },
  })

const chooseFile = async (wrapper: ReturnType<typeof mountPanel>, file: File) => {
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

describe('SiteContactPageConfigPanel image upload', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
    mocks.uploadImage.mockReset()
  })

  it('fills the row qr_image_url after a successful QR upload', async () => {
    const form = createSiteContactPageForm(null)
    form.contact_entries.push({ label: 'QQ 群', value: '', href: '', qr_image_url: '' })
    mocks.uploadImage.mockResolvedValueOnce('/api/media/site/abc123.png')
    const wrapper = mountPanel(form)

    await wrapper.find('button[title="上传图片"]').trigger('click')
    const file = new File([new Uint8Array([1])], 'qr.png', { type: 'image/png' })
    await chooseFile(wrapper, file)

    expect(mocks.uploadImage).toHaveBeenCalledWith(file)
    expect(form.contact_entries[0]!.qr_image_url).toBe('/api/media/site/abc123.png')
  })

  it('keeps the QR URL text input editable for manual entry', async () => {
    const form = createSiteContactPageForm(null)
    form.contact_entries.push({ label: '', value: '', href: '', qr_image_url: '' })
    const wrapper = mountPanel(form)

    const input = wrapper.find('input[placeholder="https://... 或 /qr.png"]')
    await input.setValue('https://cdn.example.com/qr.png')

    expect(form.contact_entries[0]!.qr_image_url).toBe('https://cdn.example.com/qr.png')
  })

  it('renders a QR thumbnail preview when qr_image_url is set', () => {
    const form = createSiteContactPageForm(null)
    form.contact_entries.push({ label: 'QQ 群', value: '', href: '', qr_image_url: '/api/media/site/abc123.png' })
    const wrapper = mountPanel(form)

    const preview = wrapper.find('img[src="/api/media/site/abc123.png"]')
    expect(preview.exists()).toBe(true)
  })

  it('inserts the uploaded image markdown at the textarea cursor', async () => {
    const form = createSiteContactPageForm(null)
    form.body_markdown = '前面后面'
    mocks.uploadImage.mockResolvedValueOnce('/api/media/site/pic.png')
    const wrapper = mountPanel(form)

    const textarea = wrapper.find('textarea')
    const el = textarea.element as HTMLTextAreaElement
    el.selectionStart = el.selectionEnd = 2

    const insertButton = wrapper.findAll('button').find(button => button.text().includes('插入图片'))
    expect(insertButton).toBeDefined()
    await insertButton!.trigger('click')
    const file = new File([new Uint8Array([1])], 'pic.png', { type: 'image/png' })
    await chooseFile(wrapper, file)

    expect(form.body_markdown).toBe('前面![pic.png](/api/media/site/pic.png)后面')
  })

  it('does not write anything when the upload is rejected or fails', async () => {
    const form = createSiteContactPageForm(null)
    form.contact_entries.push({ label: '', value: '', href: '', qr_image_url: '' })
    mocks.uploadImage.mockResolvedValueOnce(null)
    const wrapper = mountPanel(form)

    await wrapper.find('button[title="上传图片"]').trigger('click')
    const file = new File([new Uint8Array([1])], 'big.png', { type: 'image/png' })
    await chooseFile(wrapper, file)

    expect(form.contact_entries[0]!.qr_image_url).toBe('')
  })
})
