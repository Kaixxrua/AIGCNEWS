import { describe, expect, it } from 'vitest'
import { BANGERS_EM, CORNER, PEEL, buildShout, letteringEm, shoutTier, type Lettering, type Pt } from './comicTear'

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

// Where `transform="rotate(a cx cy)"` puts a point.
const rotated = (p: Pt, angle: number, cx: number, cy: number): Pt => {
  const a = (angle * Math.PI) / 180
  return { x: cx + (p.x - cx) * Math.cos(a) - (p.y - cy) * Math.sin(a), y: cy + (p.x - cx) * Math.sin(a) + (p.y - cy) * Math.cos(a) }
}

const rectCorners = ({ x, y, width, height }: { x: number; y: number; width: number; height: number }, dx = 0, dy = 0): Pt[] =>
  [{ x, y }, { x: x + width, y }, { x: x + width, y: y + height }, { x, y: y + height }].map(p => ({ x: p.x + dx, y: p.y + dy }))

const inPolygon = (p: Pt, polygon: Pt[]) => {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i]!
    const b = polygon[j]!
    if ((a.y > p.y) !== (b.y > p.y) && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside
  }
  return inside
}

describe('fixed stickers', () => {
  // The masthead's ink rule runs at y ≈ 100–104 under the corner: nothing may reach it.
  const RULE_CLEARANCE = 98

  it('keeps the masthead corner off the rule and inside its box', () => {
    const ribbon = points(CORNER.ribbon.body).flatMap(p => [p, { x: p.x + 2.5, y: p.y + 2.5 }]).map(p => rotated(p, -4, 93, 82))
    const art = [CORNER.fiber, CORNER.edge, CORNER.seam, CORNER.bolt, ...CORNER.impact, ...CORNER.scraps].flatMap(points)
    for (const p of [...art, ...ribbon, ...points(CORNER.bolt).map(p => ({ x: p.x + 3, y: p.y + 3 }))]) {
      expect(p.x).toBeLessThanOrEqual(CORNER.width)
      expect(p.y).toBeLessThanOrEqual(RULE_CLEARANCE)
    }
    expect(CORNER.ribbon.transform).toBe('rotate(-4 93 82)')
  })

  it('tears the corners from edge to edge, so no frame line is left dangling', () => {
    // The tear starts and ends past the box, and the hole closes through the box's own corner.
    const corner = points(CORNER.edge)
    expect(Math.min(...corner.map(p => p.y))).toBeLessThan(0)
    expect(Math.min(...corner.map(p => p.x))).toBeLessThan(0)
    const peel = points(PEEL.edge)
    expect(Math.max(...peel.map(p => p.x))).toBeGreaterThan(PEEL.width)
    expect(Math.max(...peel.map(p => p.y))).toBeGreaterThan(PEEL.height)
    expect(inPolygon({ x: 1, y: 1 }, points(CORNER.hole))).toBe(true)
    expect(inPolygon({ x: PEEL.width - 1, y: PEEL.height - 1 }, points(PEEL.hole))).toBe(true)
  })

  it('keeps the footer caption and robot inside the torn hole', () => {
    const hole = points(PEEL.hole)
    const { rect } = PEEL.caption
    expect(PEEL.caption.transform).toBe('rotate(-7 251 71)')
    for (const p of [...rectCorners(rect), ...rectCorners(rect, 3, 3)].map(p => rotated(p, -7, 251, 71))) {
      expect(inPolygon(p, hole)).toBe(true)
      expect(p.x).toBeLessThanOrEqual(PEEL.width)
    }
    for (const d of PEEL.scraps) for (const p of points(d)) expect(inPolygon(p, hole)).toBe(true)
    const { robot } = PEEL
    expect(robot.x + robot.width).toBeLessThanOrEqual(PEEL.width)
    expect(robot.y + robot.height).toBeLessThanOrEqual(PEEL.height)
  })

  it('fits each fixed slogan inside its frame', () => {
    const inner = PEEL.caption.rect.width - 8
    for (const line of PEEL.lines) expect(line.length).toBeLessThanOrEqual(inner)
    expect(PEEL.small.length).toBeLessThanOrEqual(inner)
    // The ribbon's notched ends take 6 units each.
    expect(CORNER.ribbon.text.length).toBeLessThanOrEqual(157 - 29 - 2 * 6 - 4)
    expect(Object.keys(BANGERS_EM)).toEqual(expect.arrayContaining(['AI!', 'BRIGHTER TOMORROW!', ...PEEL.lines.map(l => l.text), PEEL.small.text]))
  })
})
