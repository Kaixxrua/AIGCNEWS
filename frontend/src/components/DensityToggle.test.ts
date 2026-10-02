import { createApp, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import DensityToggle from './DensityToggle.vue'
import i18n, { setAppLocale } from '@/i18n'
import { APP_DENSITY_KEY, setAppDensity, useAppDensity } from '@/composables/useAppDensity'

let unmount: (() => void) | undefined

function mount() {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(DensityToggle)
  app.use(i18n)
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return host.querySelector('button') as HTMLButtonElement
}

describe('DensityToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('zh-CN')
    setAppDensity('compact')
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('switches between the compact and comfortable layouts and remembers the choice', async () => {
    const button = mount()
    const { comfortable } = useAppDensity()
    expect(button.getAttribute('aria-label')).toBe('换成舒适版面（宽松的卡片）')
    expect(button.getAttribute('title')).toBe('换成舒适版面（宽松的卡片）')
    expect(button.querySelector('svg')).not.toBeNull()

    button.click()
    await nextTick()
    expect(comfortable.value).toBe(true)
    expect(localStorage.getItem(APP_DENSITY_KEY)).toBe('comfortable')
    expect(button.getAttribute('aria-label')).toBe('换成紧凑版面（一屏看更多）')

    button.click()
    await nextTick()
    expect(comfortable.value).toBe(false)
    expect(localStorage.getItem(APP_DENSITY_KEY)).toBe('compact')
    expect(button.getAttribute('aria-label')).toBe('换成舒适版面（宽松的卡片）')
  })

  it('follows a choice made elsewhere and the active language', async () => {
    const button = mount()
    setAppDensity('comfortable')
    await nextTick()
    expect(button.getAttribute('aria-label')).toBe('换成紧凑版面（一屏看更多）')
    setAppLocale('en-US')
    await nextTick()
    expect(button.getAttribute('aria-label')).toBe('Switch to the compact layout (more on screen)')
  })
})
