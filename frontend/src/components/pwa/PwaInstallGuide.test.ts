import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import i18n, { setAppLocale } from '@/i18n'
import PwaInstallLink from '@/components/PwaInstallLink.vue'
import PwaInstallGuide from './PwaInstallGuide.vue'
import { __resetInstallPromptForTests, initializeInstallPrompt } from '@/pwa/installPrompt'

const originalUA = navigator.userAgent
const InstallUI = defineComponent({
  components: { PwaInstallLink, PwaInstallGuide },
  template: '<PwaInstallLink /><PwaInstallGuide />',
})
let wrapper: ReturnType<typeof mount> | undefined

beforeEach(() => {
  __resetInstallPromptForTests()
  setAppLocale('zh-CN')
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  __resetInstallPromptForTests()
  Object.defineProperty(navigator, 'userAgent', { value: originalUA, configurable: true })
  setAppLocale('zh-CN')
})

const openGuide = async () => {
  initializeInstallPrompt()
  wrapper = mount(InstallUI, { attachTo: document.body, global: { plugins: [i18n] } })
  const install = wrapper.get<HTMLButtonElement>('.pwa-install-link')
  install.element.focus()
  await install.trigger('click')
  await nextTick()
  return { install, guide: wrapper.get('[role="dialog"]') }
}

describe('manual installation guide', () => {
  it('opens from the install button, updates its language, and restores focus on Escape', async () => {
    const { install, guide } = await openGuide()
    expect(guide.text()).toContain('使用 Chrome 或 Edge 浏览器打开本站')
    expect(document.activeElement).toBe(guide.get('button').element)

    setAppLocale('en-US')
    await nextTick()
    expect(guide.attributes('aria-label')).toBe('Install AIGCNEWS')
    expect(guide.text()).toContain('Add to Home Screen')

    await guide.get('button').trigger('keydown', { key: 'Escape' })
    expect(wrapper?.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(install.element)
  })

  it('shows the iPhone share steps and can reopen after dismissal', async () => {
    Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', configurable: true })
    const { install, guide } = await openGuide()
    expect(guide.attributes('aria-label')).toBe('添加到主屏幕')
    expect(guide.text()).toContain('在 Safari 工具栏中点击「分享」按钮')
    expect(guide.text()).not.toContain('Chrome')
    await guide.get('button').trigger('click')
    expect(wrapper?.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(install.element)
    await install.trigger('click')
    expect(wrapper?.find('[role="dialog"]').exists()).toBe(true)
  })
})
