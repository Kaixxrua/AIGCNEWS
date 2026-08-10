import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startRouteProgress, stopRouteProgress, useRouteProgress } from './useRouteProgress'

describe('useRouteProgress', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('导航开始后延迟显示，避免快速切换闪烁', () => {
    const { isRouteLoading } = useRouteProgress()
    startRouteProgress()
    expect(isRouteLoading.value).toBe(false)
    vi.advanceTimersByTime(149)
    expect(isRouteLoading.value).toBe(false)
    vi.advanceTimersByTime(1)
    expect(isRouteLoading.value).toBe(true)
    stopRouteProgress()
  })

  it('延迟窗口内完成的导航不显示进度条', () => {
    const { isRouteLoading } = useRouteProgress()
    startRouteProgress()
    vi.advanceTimersByTime(50)
    stopRouteProgress()
    vi.advanceTimersByTime(500)
    expect(isRouteLoading.value).toBe(false)
  })

  it('并发导航（重定向/快速连点）需全部结束才隐藏', () => {
    const { isRouteLoading } = useRouteProgress()
    startRouteProgress()
    startRouteProgress()
    vi.advanceTimersByTime(200)
    expect(isRouteLoading.value).toBe(true)
    stopRouteProgress()
    expect(isRouteLoading.value).toBe(true)
    stopRouteProgress()
    expect(isRouteLoading.value).toBe(false)
  })

  it('stop 多于 start 时计数不为负', () => {
    const { isRouteLoading } = useRouteProgress()
    stopRouteProgress()
    startRouteProgress()
    vi.advanceTimersByTime(200)
    expect(isRouteLoading.value).toBe(true)
    stopRouteProgress()
    expect(isRouteLoading.value).toBe(false)
  })
})
