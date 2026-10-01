import { KeepAlive, defineComponent, h, ref, type Ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import FolioTools from './FolioTools.vue'
import { FOLIO_TOOLS_AVAILABLE, FOLIO_TOOLS_TARGET_ID } from '@/features/navigation/folioTools'

/* jsdom 不排版：量宽的替身按所挂的档位报宽度，报眉空位按 room 报宽度。 */
const WIDTHS: Record<string, number> = { full: 400, compact: 300 }
let room = 500

const offsetWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')!
const clientWidth = Object.getOwnPropertyDescriptor(Element.prototype, 'clientWidth')!

const Page = defineComponent({
  name: 'ToolsPage',
  setup: () => () => h('div', { class: 'page' }, [
    h(FolioTools, null, {
      default: ({ level }: { level: string | null }) => h('button', { class: 'tool', 'data-level': level ?? 'none' }, 'tool'),
    }),
  ]),
})

const Other = defineComponent({ name: 'OtherPage', setup: () => () => h('div', { class: 'other' }) })

let target: HTMLElement
let host: HTMLElement
let wrapper: VueWrapper | undefined

const tools = () => document.querySelector<HTMLElement>('.folio-tools')
const inFolio = () => target.contains(tools())
const level = () => document.querySelector('.tool')?.getAttribute('data-level')

function mountPage(available?: Ref<boolean>) {
  wrapper = mount(Page, {
    attachTo: host,
    global: available ? { provide: { [FOLIO_TOOLS_AVAILABLE as symbol]: available } } : {},
  })
}

describe('FolioTools', () => {
  beforeEach(() => {
    room = 500
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
      configurable: true,
      get(this: HTMLElement) {
        return this.hasAttribute('data-folio-probe') ? WIDTHS[this.dataset.folio ?? ''] ?? 0 : 0
      },
    })
    Object.defineProperty(Element.prototype, 'clientWidth', {
      configurable: true,
      get(this: Element) {
        return this.id === FOLIO_TOOLS_TARGET_ID ? room : 0
      },
    })
    target = document.createElement('div')
    target.id = FOLIO_TOOLS_TARGET_ID
    host = document.createElement('div')
    document.body.append(target, host)
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    target.remove()
    host.remove()
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', offsetWidth)
    Object.defineProperty(Element.prototype, 'clientWidth', clientWidth)
  })

  it('没有报眉时工具留在页面里', async () => {
    mountPage()
    await flushPromises()

    expect(host.querySelector('.page .folio-tools')).not.toBeNull()
    expect(inFolio()).toBe(false)
    expect(tools()?.hasAttribute('data-folio')).toBe(false)
    expect(level()).toBe('none')
  })

  it('报眉放得下时传送进报眉，量宽的替身当场摘掉', async () => {
    mountPage(ref(true))
    await flushPromises()

    expect(inFolio()).toBe(true)
    expect(tools()?.dataset.folio).toBe('full')
    expect(level()).toBe('full')
    expect(document.querySelector('[data-folio-probe]')).toBeNull()
  })

  it('完整的一组放不下时换紧凑档', async () => {
    room = 350
    mountPage(ref(true))
    await flushPromises()

    expect(inFolio()).toBe(true)
    expect(tools()?.dataset.folio).toBe('compact')
    expect(level()).toBe('compact')
  })

  it('两档都放不下时留在页面里', async () => {
    room = 200
    mountPage(ref(true))
    await flushPromises()

    expect(inFolio()).toBe(false)
    expect(host.querySelector('.page .folio-tools')).not.toBeNull()
    expect(level()).toBe('none')
  })

  it('报眉没了就搬回页面，回来再搬上去', async () => {
    const available = ref(true)
    mountPage(available)
    await flushPromises()
    expect(inFolio()).toBe(true)

    available.value = false
    await flushPromises()
    expect(inFolio()).toBe(false)
    expect(host.querySelector('.page .folio-tools')).not.toBeNull()
    expect(tools()?.hasAttribute('data-folio')).toBe(false)

    available.value = true
    await flushPromises()
    expect(inFolio()).toBe(true)
  })

  it('页面卸载时报眉里不留工具', async () => {
    mountPage(ref(true))
    await flushPromises()
    expect(inFolio()).toBe(true)

    wrapper?.unmount()
    wrapper = undefined
    await flushPromises()
    expect(target.querySelector('.folio-tools')).toBeNull()
  })

  it('KeepAlive 缓存的页面切走时从报眉撤下，切回来再放上去', async () => {
    const Shell = defineComponent({
      props: { show: { type: String, required: true } },
      setup: (props) => () => h(KeepAlive, null, { default: () => h(props.show === 'page' ? Page : Other) }),
    })
    wrapper = mount(Shell, {
      props: { show: 'page' },
      attachTo: host,
      global: { provide: { [FOLIO_TOOLS_AVAILABLE as symbol]: ref(true) } },
    })
    await flushPromises()
    expect(inFolio()).toBe(true)

    await wrapper.setProps({ show: 'other' })
    await flushPromises()
    expect(target.querySelector('.folio-tools')).toBeNull()

    await wrapper.setProps({ show: 'page' })
    await flushPromises()
    expect(inFolio()).toBe(true)
  })
})
