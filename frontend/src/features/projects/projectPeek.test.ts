import { describe, expect, it } from 'vitest'
import type { GitHubProjectTrendPoint } from '@/services/projects/projectApi'
import { PEEK_CURVE_H, PEEK_GAP, PEEK_MIN_HEIGHT, PEEK_ROOM, peekCurve, peekPlacement, shortSha } from './projectPeek'

const day = (date: string, stars: number): GitHubProjectTrendPoint => ({ date, stars, gain: null })

describe('peekPlacement', () => {
  const view = { top: 100, bottom: 900 }

  it('drops the card below the row while there is room there, measured from the frame', () => {
    expect(peekPlacement({ top: 200, bottom: 260 }, view, 50)).toEqual({
      top: 260 + PEEK_GAP - 50,
      above: false,
      maxHeight: 900 - 260 - PEEK_GAP,
    })
  })

  it('lifts it over the row when below is short and above is roomier, its bottom edge on the row', () => {
    expect(peekPlacement({ top: 700, bottom: 760 }, view, 50)).toEqual({
      top: 700 - PEEK_GAP - 50,
      above: true,
      maxHeight: 700 - 100 - PEEK_GAP,
    })
  })

  it('keeps below while it has the room a card usually needs, however much more there is above', () => {
    const view = { top: 0, bottom: 1000 }
    const row = (bottom: number) => ({ top: bottom - 60, bottom })
    expect(peekPlacement(row(1000 - PEEK_GAP - PEEK_ROOM), view, 0)).toMatchObject({ above: false, maxHeight: PEEK_ROOM })
    expect(peekPlacement(row(1000 - PEEK_GAP - PEEK_ROOM + 1), view, 0)).toMatchObject({ above: true })
  })

  it('rises over rows only, leaving the page header and the column titles in view while the rows have the room', () => {
    // 榜单第一行从 300 起，上面是页头、搜索框和表头
    expect(peekPlacement({ top: 700, bottom: 760 }, { top: 0, bottom: 1000 }, 0, 300)).toEqual({
      top: 700 - PEEK_GAP,
      above: true,
      maxHeight: 700 - 300 - PEEK_GAP,
    })
    // 榜单往上滚出去了：第一行的上沿不再管事
    expect(peekPlacement({ top: 700, bottom: 760 }, { top: 100, bottom: 1000 }, 0, -2000)).toMatchObject({ maxHeight: 700 - 100 - PEEK_GAP })
  })

  it('reaches over the page header only when neither the rows above nor the room below can take a card', () => {
    const view = { top: 0, bottom: 800 }
    // 上面的行只剩 194、下面只剩 234：往上盖过页头，有 494
    expect(peekPlacement({ top: 500, bottom: 560 }, view, 0, 300)).toEqual({ top: 500 - PEEK_GAP, above: true, maxHeight: 500 - PEEK_GAP })
    // 下面放得下就不去盖页头
    expect(peekPlacement({ top: 400, bottom: 460 }, view, 0, 300)).toMatchObject({ above: false, maxHeight: 800 - 460 - PEEK_GAP })
  })

  it('stays below when both sides are short but below is still the roomier', () => {
    expect(peekPlacement({ top: 300, bottom: 340 }, { top: 100, bottom: 600 }, 0)).toEqual({
      top: 340 + PEEK_GAP,
      above: false,
      maxHeight: 600 - 340 - PEEK_GAP,
    })
  })

  it('never gets shorter than the minimum, and lands on whole pixels', () => {
    expect(peekPlacement({ top: 120, bottom: 880 }, view, 0)).toMatchObject({ maxHeight: PEEK_MIN_HEIGHT })
    expect(peekPlacement({ top: 200.4, bottom: 260.6 }, { top: 100, bottom: 900.9 }, 10.2)).toEqual({
      top: Math.round(260.6 + PEEK_GAP - 10.2),
      above: false,
      maxHeight: Math.floor(900.9 - 260.6 - PEEK_GAP),
    })
  })
})

describe('peekCurve', () => {
  it('needs two counted days inside the window to draw', () => {
    expect(peekCurve([], '2026-10-02', 30)).toEqual({
      from: '2026-09-03', to: '2026-10-02', counted: 0, first: null, last: null, delta: 0, lines: [], area: '', bridges: [], end: null,
    })
    expect(peekCurve([], '', 30)).toMatchObject({ from: '', to: '' })
    expect(peekCurve([day('2026-10-02', 5)], '2026-10-02', 30)).toMatchObject({ counted: 1, first: null, lines: [] })
    expect(peekCurve([day('2026-08-01', 5), day('2026-10-02', 6)], '2026-10-02', 30)).toMatchObject({ counted: 1, first: null })
    expect(peekCurve([day('2026-10-01', 5), day('2026-10-02', 6)], '', 30)).toMatchObject({ counted: 0, first: null })
  })

  it("spreads the window across the box and the repository's own low to high across its height", () => {
    const curve = peekCurve([day('2026-09-30', 100), day('2026-10-01', 150), day('2026-10-02', 200)], '2026-10-02', 3)
    expect(curve).toMatchObject({
      counted: 3,
      first: { date: '2026-09-30', stars: 100 },
      last: { date: '2026-10-02', stars: 200 },
      delta: 100,
      bridges: [],
    })
    expect(curve.lines).toEqual(['M4 52L150 28L296 4'])
    expect(curve.area).toBe(`M4 ${PEEK_CURVE_H}L4 52L150 28L296 4L296 ${PEEK_CURVE_H}Z`)
    // 最后一点在框里的百分比位置，圆点按它摆
    expect(curve.end).toEqual({ x: 98.67, y: 7.14 })
  })

  it('breaks the line where days are missing, joins the pieces with a dashed bridge, keeps a lone day visible and fills on under the gap', () => {
    // 五天的窗口：前两天有数，第三天缺，第四天有数，最后一天缺
    const curve = peekCurve(
      [day('2026-09-28', 10), day('2026-09-29', 20), day('2026-10-01', 30)],
      '2026-10-02',
      5,
    )
    expect(curve.lines).toEqual(['M4 52L77 28', 'M221.5 4h3'])
    expect(curve.area).toBe(`M4 ${PEEK_CURVE_H}L4 52L77 28L223 4L223 ${PEEK_CURVE_H}Z`)
    expect(curve.bridges).toEqual(['M77 28L223 4'])
    expect(curve).toMatchObject({ counted: 3, delta: 20, last: { date: '2026-10-01', stars: 30 }, end: { x: 74.33, y: 7.14 } })
    // 框的两端是窗口的头尾，不是有数的头尾天
    expect(curve).toMatchObject({ from: '2026-09-28', to: '2026-10-02' })
  })

  it('draws a level line through the middle when nothing moved, and a negative change when stars were taken back', () => {
    const flat = peekCurve([day('2026-10-01', 42), day('2026-10-02', 42)], '2026-10-02', 2)
    expect(flat).toMatchObject({ delta: 0, lines: ['M4 28L296 28'], end: { x: 98.67, y: 50 } })

    const down = peekCurve([day('2026-10-01', 50), day('2026-10-02', 40)], '2026-10-02', 2)
    expect(down).toMatchObject({ delta: -10, lines: ['M4 4L296 52'] })
  })
})

describe('shortSha', () => {
  it('keeps the first seven characters, as GitHub shows them', () => {
    expect(shortSha('abcdef1234567890')).toBe('abcdef1')
    expect(shortSha('f00')).toBe('f00')
  })
})
