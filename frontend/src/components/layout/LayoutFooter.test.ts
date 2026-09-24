import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref, type Ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import LayoutFooter from './LayoutFooter.vue'
import { useDockSuppression } from '@/composables/useDockSuppression'
import i18n from '@/i18n'

/* 浮层开关宿主：在 setup 上下文调用 useDockSuppression，用 ref 直控计数。 */
const mountOverlayHost = (open: Ref<boolean>) =>
  mount(
    defineComponent({
      setup() {
        useDockSuppression(() => open.value)
        return () => h('div')
      },
    }),
  )

const mountFooter = (props: { editorial?: boolean; embedded?: boolean } = {}) =>
  mount(LayoutFooter, {
    props: { brandName: 'AIGC NEWS', ...props },
    global: { plugins: [i18n] },
    attachTo: document.body,
  })

describe('LayoutFooter', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders the compliance line with the ICP filing number', () => {
    const footer = mountFooter()

    expect((footer.find('.dock-footer').element as HTMLElement).style.display).not.toBe('none')
    expect(footer.text()).toContain('蜀ICP备2026011291号')
    footer.unmount()
  })

  it('renders the editorial footer groups while preserving legal and contact access', () => {
    const footer = mountFooter({ editorial: true })
    expect(footer.find('.footer-brand').text()).toContain('AIGC NEWS')
    expect(footer.find('.footer-copyright').text()).toContain(String(new Date().getFullYear()))
    expect(footer.find('.footer-copyright').text()).toContain('蜀ICP备2026011291号')
    expect(footer.find('.footer-nav a[href="mailto:kaixxrua@gmail.com"]').exists()).toBe(true)
    expect(footer.find('dialog[aria-labelledby="footer-about-title"]').exists()).toBe(true)
    expect(footer.text()).not.toContain('footer.createMore')
    expect(footer.text()).not.toContain('footer.aboutDescription')
    footer.unmount()
  })

  it('keeps the full compliance footer when embedded even on the homepage', () => {
    const footer = mountFooter({ editorial: true, embedded: true })
    expect(footer.find('.footer-brand').exists()).toBe(false)
    expect(footer.find('dialog').exists()).toBe(false)
    expect(footer.text()).toContain('kaixxrua@gmail.com')
    footer.unmount()
  })

  it('hides while a fullscreen overlay suppresses the dock and returns after it closes', async () => {
    const open = ref(false)
    const host = mountOverlayHost(open)
    const footer = mountFooter()

    open.value = true
    await nextTick()
    expect((footer.find('.dock-footer').element as HTMLElement).style.display).toBe('none')

    open.value = false
    await nextTick()
    expect((footer.find('.dock-footer').element as HTMLElement).style.display).not.toBe('none')

    footer.unmount()
    host.unmount()
  })
})
