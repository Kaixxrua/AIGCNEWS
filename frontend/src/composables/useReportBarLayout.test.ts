import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { useReportBarLayout } from './useReportBarLayout'

type Part = 'tabs' | 'dateline' | 'actions'

// jsdom 不排版：三段只在控制条处于测量态（各按内容宽度排开）时报出自己的宽度，其余时候报 0。
const buildBar = (widths: Record<Part, number>, clientWidth: number) => {
  const bar = document.createElement('div')
  bar.style.padding = '10px 12px 11px'
  bar.style.columnGap = '16px'
  bar.innerHTML = [
    '<div class="report-controls__head">',
    '<div><span class="report-controls__meta">2026-10-01</span></div>',
    '<div class="report-controls__actions"><button>订阅</button></div>',
    '</div>',
    '<div class="report-controls__tabs"></div>',
  ].join('')
  const parts: Record<Part, Element> = {
    tabs: bar.querySelector('.report-controls__tabs')!,
    dateline: bar.querySelector('.report-controls__head > :first-child')!,
    actions: bar.querySelector('.report-controls__actions')!,
  }
  for (const [part, el] of Object.entries(parts) as [Part, Element][]) {
    Object.defineProperty(el, 'offsetWidth', { get: () => (bar.classList.contains('is-measuring-row') ? widths[part] : 0) })
  }
  Object.defineProperty(bar, 'clientWidth', { get: () => clientWidth })
  document.body.append(bar)
  return { bar, actions: parts.actions }
}

const layoutOf = (widths: Record<Part, number>, clientWidth: number) => {
  const { bar } = buildBar(widths, clientWidth)
  const scope = effectScope()
  const layout = scope.run(() => useReportBarLayout(ref(bar), ref(true)))!.value
  scope.stop()
  expect(bar.classList.contains('is-measuring-row')).toBe(false)
  return layout
}

afterEach(() => {
  document.body.replaceChildren()
})

describe('useReportBarLayout', () => {
  it('puts the three parts on one row only when their own widths fit beside each other', () => {
    // 内容区 = 宽度 - 24（左右内边距）；三段合计 1593，加两道 16px 间距与 2px 余量要 1627。
    const guest = { tabs: 832, dateline: 603, actions: 158 }
    expect(layoutOf(guest, 1651)).toBe('one-row')
    expect(layoutOf(guest, 1650)).toBe('actions-up')
  })

  it('moves the buttons beside the dateline when they no longer fit beside the tabs, and wraps when neither fits', () => {
    // 登录后按钮多：标签 + 按钮 = 832 + 16 + 560 + 2 = 1410，日期行 + 按钮 = 603 + 16 + 560 + 2 = 1181。
    const signedIn = { tabs: 832, dateline: 603, actions: 560 }
    expect(layoutOf(signedIn, 1434)).toBe('actions-up')
    expect(layoutOf(signedIn, 1433)).toBe('actions-down')
    expect(layoutOf(signedIn, 1205)).toBe('actions-down')
    expect(layoutOf(signedIn, 1204)).toBe('actions-up')
  })

  it('measures again when the bar content changes, and stops when switched off or unmounted', async () => {
    const widths = { tabs: 832, dateline: 603, actions: 158 }
    const { bar, actions } = buildBar(widths, 1900)
    const enabled = ref(true)
    const scope = effectScope()
    const layout = scope.run(() => useReportBarLayout(ref(bar), enabled))!
    expect(layout.value).toBe('one-row')

    // 登录后多出订阅状态、发送到邮箱等按钮
    widths.actions = 520
    actions.append(document.createElement('button'))
    await Promise.resolve()
    expect(layout.value).toBe('actions-up')

    widths.actions = 158
    enabled.value = false
    await nextTick()
    expect(layout.value).toBeNull()
    actions.lastElementChild!.remove()
    await Promise.resolve()
    expect(layout.value).toBeNull()

    enabled.value = true
    await nextTick()
    expect(layout.value).toBe('one-row')

    scope.stop()
    widths.actions = 520
    actions.append(document.createElement('button'))
    await Promise.resolve()
    expect(layout.value).toBe('one-row')
  })
})
