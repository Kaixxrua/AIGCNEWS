import { effectScope, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useFollowViewport } from './useFollowViewport'

describe('responsive reading viewport', () => {
  it('moves follow and wheel handling to the new scroll container and cleans up', async () => {
    const desktop = document.createElement('div')
    const phone = document.createElement('div')
    Object.defineProperty(desktop, 'scrollHeight', { value: 600 })
    Object.defineProperty(phone, 'scrollHeight', { value: 1200 })
    const viewport = ref<HTMLElement | null>(desktop)
    const scope = effectScope()
    const follow = scope.run(() => useFollowViewport(viewport))!

    await follow.scrollToBottom()
    expect(desktop.scrollTop).toBe(600)
    viewport.value = phone
    await nextTick()
    desktop.dispatchEvent(new WheelEvent('wheel', { deltaY: -10 }))
    expect(follow.autoScroll.value).toBe(true)
    phone.dispatchEvent(new WheelEvent('wheel', { deltaY: -10 }))
    expect(follow.autoScroll.value).toBe(false)
    follow.resumeAutoScroll()
    await nextTick()
    expect(phone.scrollTop).toBe(1200)

    scope.stop()
    phone.dispatchEvent(new WheelEvent('wheel', { deltaY: -10 }))
    expect(follow.autoScroll.value).toBe(true)
  })
})

