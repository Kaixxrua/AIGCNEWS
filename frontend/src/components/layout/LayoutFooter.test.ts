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

const mountFooter = () =>
  mount(LayoutFooter, {
    props: { brandName: 'AIGC NEWS' },
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
