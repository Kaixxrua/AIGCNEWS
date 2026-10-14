import { mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GodotContactScene from './GodotContactScene.vue'

const SESSION = 'a'.repeat(32)
const i18n = createI18n({ legacy: false, locale: 'zh-CN' })

const mountScene = (options: { attachTo?: HTMLElement } = {}) =>
  mount(GodotContactScene, { ...options, global: { plugins: [i18n] } })

function postFromFrame(wrapper: VueWrapper, data: Record<string, unknown>) {
  const iframe = wrapper.find('iframe').element as HTMLIFrameElement
  window.dispatchEvent(new MessageEvent('message', {
    data: { protocol: 'meadow-camp-presentation', version: 1, session: SESSION, ...data },
    origin: window.location.origin,
    source: iframe.contentWindow,
  }))
}

/** 模拟场景外壳往 #loading-message 写进度（jsdom 不加载 iframe，里面是空文档）。 */
function writeShellProgress(wrapper: VueWrapper, text: string) {
  const shell = (wrapper.find('iframe').element as HTMLIFrameElement).contentDocument!
  const root = shell.documentElement ?? shell.appendChild(shell.createElement('html'))
  const line = shell.getElementById('loading-message') ?? root.appendChild(shell.createElement('p'))
  line.id = 'loading-message'
  line.textContent = text
}

async function enterScene(wrapper: VueWrapper, quality?: 'lite' | 'balanced' | 'original') {
  await wrapper.find('.scene-launch').trigger('click')
  if (quality) await wrapper.find(`input[value="${quality}"]`).setValue(true)
  await wrapper.find('form.scene-chooser-panel').trigger('submit')
}

describe('GodotContactScene', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    window.localStorage.clear()
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
  })

  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
    i18n.global.locale.value = 'zh-CN'
  })

  it('shows only the static poster until the visitor opts in', () => {
    const wrapper = mountScene()

    expect(wrapper.find('iframe').exists()).toBe(false)
    const poster = wrapper.find('img.scene-poster-image')
    expect(poster.attributes('src')).toMatch(/^\/camp-scene\/contact-poster-1600\.webp\?v=\w+$/)
    expect(poster.attributes('srcset')).toMatch(/\/camp-scene\/contact-poster-2400\.webp\?v=\w+ 2400w/)
    expect(wrapper.find('.scene-launch').text()).toBe('选择画质')
    expect(wrapper.find('.scene-chooser').exists()).toBe(false)
  })

  it('never auto-starts even when a quality was remembered, but preselects it', async () => {
    window.localStorage.setItem('meadow-texture-quality-v1', 'original')
    const wrapper = mountScene()

    expect(wrapper.find('iframe').exists()).toBe(false)
    await wrapper.find('.scene-launch').trigger('click')

    const checked = wrapper.findAll('input[type="radio"]').filter((radio) => (radio.element as HTMLInputElement).checked)
    expect(checked.map((radio) => radio.attributes('value'))).toEqual(['original'])
    expect(wrapper.emitted('overlay')?.slice(-1)[0]).toEqual([true])
  })

  it('offers three qualities inline and cancels back to the poster', async () => {
    const wrapper = mountScene()
    await wrapper.find('.scene-launch').trigger('click')

    expect(wrapper.findAll('.scene-option')).toHaveLength(3)
    expect(wrapper.find('input[value="lite"]').element).toHaveProperty('checked', true)

    await wrapper.find('.scene-chooser-cancel').trigger('click')
    expect(wrapper.find('.scene-chooser').exists()).toBe(false)
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.emitted('overlay')?.slice(-1)[0]).toEqual([false])
  })

  it('embeds the scene with the chosen quality only after 开启 and remembers the choice', async () => {
    const wrapper = mountScene({ attachTo: document.body })
    await enterScene(wrapper, 'balanced')

    const src = new URL(wrapper.find('iframe').attributes('src')!)
    expect(src.pathname).toBe('/camp-scene/index.html')
    expect(src.searchParams.get('camp')).toBe('1')
    expect(src.searchParams.get('quality')).toBe('balanced')
    expect(window.localStorage.getItem('meadow-texture-quality-v1')).toBe('balanced')
    // 截图保持覆盖直到原野核心画出
    expect(wrapper.find('.scene-poster').classes()).not.toContain('scene-poster--hidden')
    expect(wrapper.find('.scene-status').text()).toContain('正在载入原野 · 均衡')
    wrapper.unmount()
  })

  it('sends the demo snapshot on bridge_ready and reveals the scene once the core is presented', async () => {
    const wrapper = mountScene({ attachTo: document.body })
    await enterScene(wrapper)
    const iframe = wrapper.find('iframe').element as HTMLIFrameElement
    const post = vi.spyOn(iframe.contentWindow!, 'postMessage')

    postFromFrame(wrapper, { type: 'bridge_ready' })
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0]![0]).toMatchObject({ type: 'snapshot', session: SESSION, sequence: 1, snapshot: { mode: 'demo' } })

    postFromFrame(wrapper, { type: 'presentation_status', status: 'waiting_for_core' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.scene-poster').classes()).not.toContain('scene-poster--hidden')

    postFromFrame(wrapper, { type: 'presentation_status', status: 'waiting_for_state' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.scene-poster').classes()).toContain('scene-poster--hidden')
    const labels = wrapper.findAll('.scene-actions button').map((button) => button.attributes('aria-label'))
    expect(labels).toEqual(['全屏显示原野', '退出实时场景，回到静态预览'])
    wrapper.unmount()
  })

  it('unloads the embedded scene when the visitor exits', async () => {
    const wrapper = mountScene({ attachTo: document.body })
    await enterScene(wrapper)
    postFromFrame(wrapper, { type: 'bridge_ready' })
    postFromFrame(wrapper, { type: 'presentation_status', status: 'ready' })
    await wrapper.vm.$nextTick()

    await wrapper.find('button[aria-label="退出实时场景，回到静态预览"]').trigger('click')
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.find('.scene-poster').classes()).not.toContain('scene-poster--hidden')
    expect(wrapper.find('.scene-launch').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows a truthful retry state when the bridge never connects', async () => {
    const wrapper = mountScene()
    await enterScene(wrapper)
    vi.advanceTimersByTime(30_000)
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.scene-status').text()).toContain('原野暂未连接，可重新载入。')
    expect(wrapper.find('.scene-status').classes()).toContain('scene-status--visible')
    const firstSrc = wrapper.find('iframe').attributes('src')
    vi.setSystemTime(Date.now() + 1000)
    await wrapper.find('.scene-status-retry').trigger('click')
    expect(wrapper.find('iframe').attributes('src')).not.toBe(firstSrc)
    expect(wrapper.find('.scene-status').text()).not.toContain('暂未连接')
  })

  it('passes the scene shell’s own download line through on the Chinese site', async () => {
    const wrapper = mountScene({ attachTo: document.body })
    await enterScene(wrapper)
    writeShellProgress(wrapper, '正在接收引擎与素材 · 12.3 / 113.0 MiB（解压后）')
    vi.advanceTimersByTime(500)
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.scene-status').text()).toBe('正在载入原野 · 极速 · 正在接收引擎与素材 · 12.3 / 113.0 MiB（解压后）')
    wrapper.unmount()
  })

  it('speaks English on the English site and keeps only the figures from the Chinese scene shell', async () => {
    i18n.global.locale.value = 'en-US'
    const wrapper = mountScene({ attachTo: document.body })

    expect(wrapper.find('.godot-contact-scene').attributes('aria-label')).toBe('Windrise Meadow live scene')
    expect(wrapper.find('img.scene-poster-image').attributes('alt')).toMatch(/^Still of Windrise Meadow: /)
    expect(wrapper.find('.scene-poster-badge').text()).toBe('Still preview')
    expect(wrapper.find('.scene-launch').text()).toBe('Choose quality')

    await wrapper.find('.scene-launch').trigger('click')
    expect(wrapper.find('.scene-chooser-title').text()).toBe('Choose quality')
    expect(wrapper.findAll('.scene-option-body strong').map((label) => label.text())).toEqual(['LiteRecommended', 'Balanced', 'Original'])
    expect(wrapper.findAll('.scene-option-size').map((size) => size.text())).toEqual(['~13 MB to start', '~113 MB', '~126 MB'])
    expect(wrapper.find('.scene-chooser-cancel').text()).toBe('Cancel')
    expect(wrapper.find('.scene-chooser-enter').text()).toBe('Start')

    await wrapper.find('form.scene-chooser-panel').trigger('submit')
    expect(wrapper.find('.scene-status').text()).toBe('Loading the meadow · Lite…')
    writeShellProgress(wrapper, '正在接收引擎与素材 · 12.3 / 113.0 MiB（解压后）')
    vi.advanceTimersByTime(500)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.scene-status').text()).toBe('Loading the meadow · Lite · 12.3 / 113.0 MiB unpacked')

    // 外壳其余的中文进度不往英文界面里搬。
    writeShellProgress(wrapper, '下载完成，正在准备场景…')
    vi.advanceTimersByTime(500)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.scene-status').text()).toBe('Loading the meadow · Lite…')

    postFromFrame(wrapper, { type: 'bridge_ready' })
    postFromFrame(wrapper, { type: 'presentation_status', status: 'missing_assets' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.scene-status').text()).toBe('The meadow loaded, but some demo companions are unavailable.')
    expect(wrapper.findAll('.scene-actions button').map((button) => button.attributes('aria-label')))
      .toEqual(['Show the meadow full screen', 'Leave the live scene and go back to the still preview'])

    // 切回中文，文案跟着换。
    i18n.global.locale.value = 'zh-CN'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.scene-status').text()).toBe('原野已载入，部分演示伙伴暂不可用。')
    wrapper.unmount()
  })

  it('ignores a status the presentation protocol does not define', async () => {
    const wrapper = mountScene({ attachTo: document.body })
    await enterScene(wrapper)
    postFromFrame(wrapper, { type: 'bridge_ready' })
    postFromFrame(wrapper, { type: 'presentation_status', status: 'toString' })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.scene-poster').classes()).not.toContain('scene-poster--hidden')
    expect(wrapper.find('.scene-status').text()).toBe('正在载入原野 · 极速…')
    wrapper.unmount()
  })
})
