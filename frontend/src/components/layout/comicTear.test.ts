import { describe, expect, it } from 'vitest'
import { BANGERS_EM, BURST, LABEL, buildShout, letteringEm, shoutTier, type Lettering } from './comicTear'

const SLOGANS = ['让创造更自由！', 'Create freely!'] as const
const [ZH] = SLOGANS
const HEIGHT = 92

const points = (d: string) => {
  const numbers = (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number)
  return Array.from({ length: numbers.length / 2 }, (_, i) => ({ x: numbers[i * 2] ?? NaN, y: numbers[i * 2 + 1] ?? NaN }))
}

const expectInside = (d: string, width: number, height: number) => {
  for (const p of points(d)) {
    expect(p.x).toBeGreaterThanOrEqual(0)
    expect(p.x).toBeLessThanOrEqual(width)
    expect(p.y).toBeGreaterThanOrEqual(0)
    expect(p.y).toBeLessThanOrEqual(height)
  }
}

const letteringCorners = (text: Lettering) => {
  const a = (-text.angle * Math.PI) / 180
  const halfW = text.length / 2
  const halfH = text.size * 0.45
  return ([[-halfW, -halfH], [halfW, -halfH], [halfW, halfH], [-halfW, halfH]] as const).map(([dx, dy]) => ({
    x: text.cx + dx * Math.cos(a) - dy * Math.sin(a),
    y: text.cy + dx * Math.sin(a) + dy * Math.cos(a),
  }))
}

describe('shout tiers', () => {
  it.each([[149, null], [150, 'compact'], [199, 'compact'], [200, 'standard'], [299, 'standard'], [300, 'full'], [440, 'full']] as const)(
    'gives a %ipx slot the %s tier', (width, tier) => {
      expect(shoutTier(width)).toBe(tier)
    })

  it('tears nothing without room or text', () => {
    expect(buildShout(149, HEIGHT, ZH)).toBeNull()
    expect(buildShout(320, 50, ZH)).toBeNull()
    expect(buildShout(320, HEIGHT, '  ')).toBeNull()
  })
})

describe('shout geometry', () => {
  // Every slot width the masthead can produce, for both locales.
  const widths = Array.from({ length: 291 }, (_, i) => 150 + i)

  it.each(SLOGANS)('keeps every stroke of "%s" inside the slot at each width', slogan => {
    for (const width of widths) {
      const art = buildShout(width, HEIGHT, slogan)!
      for (const d of [art.rim, art.hole, art.crack ?? '', ...art.speed, ...art.scraps, ...art.splats]) expectInside(d, width, HEIGHT)
      for (const drop of art.drops) {
        expect(drop.cx - drop.r).toBeGreaterThanOrEqual(0)
        expect(drop.cx + drop.r).toBeLessThanOrEqual(width)
        expect(drop.cy - drop.r).toBeGreaterThanOrEqual(0)
        expect(drop.cy + drop.r).toBeLessThanOrEqual(HEIGHT)
      }
    }
  })

  it.each(SLOGANS)('letters "%s" legibly and within the slot at each width', slogan => {
    for (const width of widths) {
      const { text } = buildShout(width, HEIGHT, slogan)!
      expect(text.size).toBeGreaterThanOrEqual(16)
      expect(text.angle).toBeGreaterThan(0)
      expect(text.angle).toBeLessThanOrEqual(12)
      for (const corner of letteringCorners(text)) {
        expect(corner.x).toBeGreaterThanOrEqual(0)
        expect(corner.x).toBeLessThanOrEqual(width)
        expect(corner.y).toBeGreaterThanOrEqual(0)
        expect(corner.y).toBeLessThanOrEqual(HEIGHT)
      }
    }
  })

  it('tears the same edge for the same box', () => {
    expect(buildShout(320, HEIGHT, ZH)).toEqual(buildShout(320, HEIGHT, ZH))
  })

  it('estimates lettering advances close to the subset fonts', () => {
    // Advances measured from the woff2 subsets with fontTools.
    expect(Math.abs(letteringEm('让创造更自由！') / 5.355 - 1)).toBeLessThan(0.04)
    expect(Math.abs(letteringEm('Create freely!') / 4.946 - 1)).toBeLessThan(0.04)
  })
})

describe('fixed stickers', () => {
  it('keeps the burst inside its viewBox', () => {
    for (const d of [BURST.rim, BURST.hole, BURST.cover, BURST.lipFiber, BURST.lip, ...BURST.flaps.map(f => f.body), ...BURST.scraps, BURST.ribbon.body]) {
      expectInside(d, BURST.width, BURST.height)
    }
    const { robot } = BURST
    expect(robot.x).toBeGreaterThanOrEqual(0)
    expect(robot.x + robot.width).toBeLessThanOrEqual(BURST.width)
    // The robot's flat chest cut must sit under the page cover.
    expect(robot.y + robot.height).toBeLessThanOrEqual(BURST.height)
    const lipLowest = Math.max(...points(BURST.lip).map(p => p.y))
    expect(robot.y + robot.height).toBeGreaterThan(lipLowest)
  })

  it('keeps the footer corner inside its viewBox', () => {
    for (const d of [LABEL.reveal, LABEL.fiber, LABEL.edge, LABEL.seam]) expectInside(d, LABEL.width, LABEL.height)
    expect(LABEL.fist.x + LABEL.fist.width).toBeLessThanOrEqual(LABEL.width)
    // The forearm's cut runs past the bottom edge, which is the bottom of the viewport.
    expect(LABEL.fist.y + LABEL.fist.height).toBeGreaterThanOrEqual(LABEL.height)
  })

  it('fits each fixed slogan inside its frame', () => {
    const inner = LABEL.caption.rect.width - 8
    for (const line of LABEL.lines) expect(line.length).toBeLessThanOrEqual(inner)
    expect(LABEL.small.length).toBeLessThanOrEqual(inner)
    expect(BURST.ribbon.text.length).toBeLessThanOrEqual(124 - 2 * 7 - 4)
    expect(Object.keys(BANGERS_EM)).toEqual(expect.arrayContaining(['AI!', 'BRIGHTER TOMORROW!', ...LABEL.lines.map(l => l.text), LABEL.small.text]))
  })
})
