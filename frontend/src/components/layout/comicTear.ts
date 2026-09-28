// Torn-paper geometry for ComicSticker.vue.
// Coordinates are CSS pixels of the sticker's box (shout) or of a fixed viewBox (burst, label), so
// ink lines, halftone dots and lettering never stretch: only the tear adapts to the room it has.

export interface Pt { x: number; y: number }
type Rand = () => number
type Curve = (t: number) => Pt

/** mulberry32: a fixed seed tears the same edge on every render, so nothing flickers on resize. */
export function seeded(seed: number): Rand {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const fmt = (n: number) => String(Math.round(n * 10) / 10)
const lerp = (a: Pt, b: Pt, t: number): Pt => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t })
const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n))
const shift = (points: Pt[], dx: number, dy: number) => points.map(p => ({ x: p.x + dx, y: p.y + dy }))
/** A quadratic Bézier from `a` to `b` pulled towards `c`. */
const quad = (a: Pt, c: Pt, b: Pt): Curve => t => ({
  x: (1 - t) ** 2 * a.x + 2 * t * (1 - t) * c.x + t ** 2 * b.x,
  y: (1 - t) ** 2 * a.y + 2 * t * (1 - t) * c.y + t ** 2 * b.y,
})
/** Moves a curve sideways by `d`: positive is to the left of its direction of travel (y points down). */
const offset = (curve: Curve, d: number): Curve => t => {
  const p = curve(t)
  const a = curve(Math.max(0, t - 0.004))
  const b = curve(Math.min(1, t + 0.004))
  const len = Math.hypot(b.x - a.x, b.y - a.y) || 1
  return { x: p.x - ((b.y - a.y) / len) * d, y: p.y + ((b.x - a.x) / len) * d }
}

export function toPath(points: Pt[], close = true): string {
  return points.map((p, i) => `${i ? 'L' : 'M'}${fmt(p.x)} ${fmt(p.y)}`).join('') + (close ? 'Z' : '')
}

/**
 * Tears along a curve: walks it in uneven steps and pushes each sample alternately to either side
 * by an uneven depth, which reads as paper fibres. Both ends stay on the curve so tears join cleanly.
 */
export function tear(curve: Curve, rand: Rand, depth: number, step: readonly [number, number] = [4, 9]): Pt[] {
  const samples = Array.from({ length: 33 }, (_, i) => curve(i / 32))
  // run[i]: arc length from the start to samples[i].
  let length = 0
  const run = samples.map((p, i) => {
    const prev = samples[i - 1]
    if (prev) length += Math.hypot(p.x - prev.x, p.y - prev.y)
    return length
  })
  const paramAt = (s: number) => {
    let i = 1
    while (i < run.length - 1 && (run[i] ?? length) < s) i++
    const from = run[i - 1] ?? 0
    const to = run[i] ?? length
    return (i - 1 + (s - from) / (to - from || 1)) / 32
  }
  const points = [curve(0)]
  const next = () => step[0] + rand() * (step[1] - step[0])
  let side = 1
  for (let s = next(); s < length - step[0] * 0.7; s += next()) {
    const t = paramAt(s)
    const p = curve(t)
    const a = curve(Math.max(0, t - 0.004))
    const b = curve(Math.min(1, t + 0.004))
    const d = Math.hypot(b.x - a.x, b.y - a.y) || 1
    const offset = side * depth * (0.3 + 0.7 * rand())
    points.push({ x: p.x - ((b.y - a.y) / d) * offset, y: p.y + ((b.x - a.x) / d) * offset })
    side = -side
  }
  points.push(curve(1))
  return points
}

/** A soft ink blob: uneven lobes joined by quadratic curves. It stays within 1.22 × r of its centre. */
function blob(cx: number, cy: number, r: number, rand: Rand, lobes = 9): string {
  const points = Array.from({ length: lobes }, (_, i) => {
    const angle = (i / lobes) * Math.PI * 2 + rand() * 0.3
    const radius = r * (0.72 + rand() * 0.5)
    return { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius }
  })
  const mids = points.map((p, i) => lerp(p, points[(i + 1) % lobes] ?? p, 0.5))
  const start = mids[lobes - 1] ?? { x: cx, y: cy }
  let d = `M${fmt(start.x)} ${fmt(start.y)}`
  points.forEach((p, i) => {
    const m = mids[i] ?? p
    d += `Q${fmt(p.x)} ${fmt(p.y)} ${fmt(m.x)} ${fmt(m.y)}`
  })
  return `${d}Z`
}

/** A small flying paper scrap: a jittered quadrilateral rotated by `angle` degrees. */
function scrap(cx: number, cy: number, size: number, angle: number, rand: Rand): string {
  const a = (angle * Math.PI) / 180
  const corners: [number, number][] = [[-1, -0.7], [1, -0.9], [0.8, 0.8], [-0.9, 0.6]]
  return toPath(corners.map(([x, y]) => {
    const px = x * size * (0.8 + 0.4 * rand())
    const py = y * size * (0.8 + 0.4 * rand())
    return { x: cx + px * Math.cos(a) - py * Math.sin(a), y: cy + px * Math.sin(a) + py * Math.cos(a) }
  }))
}

/** Lettering advance in em: the CJK subset averages ~0.77em per glyph, the Latin display face ~0.36em. */
export function letteringEm(text: string): number {
  let em = 0
  for (const ch of text) em += (ch.codePointAt(0) ?? 0) >= 0x2e80 ? 0.77 : 0.36
  return em
}

/** Advances (em) of the fixed slogans, measured from the Latin subset; textLength pins them to these. */
export const BANGERS_EM = {
  'AI!': 0.896,
  'BRIGHTER TOMORROW!': 7.567,
  MORE: 1.897,
  'CREATORS!': 3.624,
  'A BRIGHTER WORLD': 6.264,
} as const

export interface Lettering { x: number; y: number; size: number; length: number; angle: number; cx: number; cy: number }

// ── Shout: the diagonal rip beside the account menu ────────────────────────────────────────────

export type ShoutTier = 'compact' | 'standard' | 'full'

const SHOUT_TIERS: Record<ShoutTier, { min: number; thick: number; rim: number; left: number; font: number }> = {
  compact: { min: 150, thick: 40, rim: 3.5, left: 8, font: 22 },
  standard: { min: 200, thick: 48, rim: 4, left: 24, font: 28 },
  full: { min: 300, thick: 54, rim: 4.5, left: 48, font: 34 },
}
const RAMP = 0.24 // share of the rip spent widening from its tip
const TEXT_FROM = 0.22
const TEXT_TO = 0.97

export function shoutTier(width: number): ShoutTier | null {
  if (width >= SHOUT_TIERS.full.min) return 'full'
  if (width >= SHOUT_TIERS.standard.min) return 'standard'
  if (width >= SHOUT_TIERS.compact.min) return 'compact'
  return null
}

export interface ShoutArt {
  tier: ShoutTier
  width: number
  height: number
  rim: string
  hole: string
  shade: string
  crack: string | null
  splats: string[]
  drops: { cx: number; cy: number; r: number }[]
  speed: string[]
  scraps: string[]
  text: Lettering
}

/** Tears a rip rising to the right across a `width` × `height` box, or null when there is too little room. */
export function buildShout(width: number, height: number, text: string): ShoutArt | null {
  const tier = shoutTier(width)
  if (!tier || height < 64 || !text.trim()) return null
  const { thick, rim, left, font } = SHOUT_TIERS[tier]
  const rand = seeded(0x5a17)
  const depth = rim * 0.5
  const clearance = rim + depth + 1.5
  const x0 = left
  const len = width - clearance - 3 - x0
  // The lowest point is where the rip reaches full thickness, so the tilt is bounded by the box height.
  const drop = Math.min(len * Math.tan((12 * Math.PI) / 180), (height - thick - 2 * clearance) / (1 - RAMP))
  const yRight = (height - ((1 - RAMP) * drop + thick)) / 2 + thick / 2

  const centre = (u: number): Pt => ({ x: x0 + u * len, y: yRight + drop * (1 - u) })
  const girth = (u: number) => u < RAMP ? thick * (0.08 + 0.92 * (1 - (1 - u / RAMP) ** 2)) : thick * (1 - 0.06 * ((u - RAMP) / (1 - RAMP)))
  const edge = (u: number, side: -1 | 1, out = 0): Pt => {
    const c = centre(u)
    return { x: c.x, y: c.y + side * (girth(u) / 2 + out) }
  }
  const rightEnd = (out: number) => (t: number): Pt => {
    const p = lerp(edge(1, -1, out), edge(1, 1, out), t)
    return { x: p.x + out + 3 * Math.sin(Math.PI * t), y: p.y }
  }

  const holePoints = [
    ...tear(u => edge(u, -1), rand, depth * 0.8, [4, 8]),
    ...tear(rightEnd(0), rand, depth * 0.8, [4, 7]).slice(1),
    ...tear(t => edge(1 - t, 1), rand, depth * 0.8, [4, 8]).slice(1),
  ]
  const rimPoints = [
    { x: x0 - rim * 1.4, y: centre(0).y },
    ...tear(u => edge(u, -1, rim), rand, depth, [3.5, 7.5]),
    ...tear(rightEnd(rim), rand, depth, [3.5, 6.5]).slice(1),
    ...tear(t => edge(1 - t, 1, rim), rand, depth, [3.5, 7.5]).slice(1),
  ]

  const inside = (p: Pt, pad: number): Pt => ({ x: clamp(p.x, pad, width - pad), y: clamp(p.y, pad, height - pad) })
  const tip = centre(0)
  const slope = drop / len

  let crack: string | null = null
  if (tier !== 'compact') {
    const end = { x: Math.max(3, x0 - (tier === 'full' ? 30 : 16)), y: 0 }
    end.y = tip.y + slope * (x0 - end.x)
    crack = toPath(tear(t => lerp(tip, end, t), rand, 2, [3, 6]), false)
  }

  const speed: string[] = []
  if (tier === 'full') {
    const lanes: [number, number, number][] = [[-13, 10, 20], [-6, 2, 30], [7, 5, 26], [14, 14, 16]]
    for (const [dy, start, length] of lanes) {
      const xs = 4 + start
      const xe = Math.min(x0 - 4, xs + length)
      if (xe - xs < 8) continue
      const at = (x: number) => clamp(tip.y + dy + slope * (x0 - x), 2, height - 2)
      speed.push(toPath([{ x: xs, y: at(xs) }, { x: xe, y: at(xe) }], false))
    }
  }

  const splats: string[] = []
  const drops: { cx: number; cy: number; r: number }[] = []
  if (tier !== 'compact') {
    const r = tier === 'full' ? 7 : 5.5
    const below = edge(0.5, 1, rim)
    const a = inside({ x: below.x - 6, y: below.y + r * 0.55 }, r * 1.22 + 1)
    splats.push(blob(a.x, a.y, r, rand))
    for (const [dx, dy, dr] of [[-1.7, 0.9, 0.32], [-2.5, 1.5, 0.22], [-3.2, 1.9, 0.15]] as const) {
      const p = inside({ x: a.x + dx * r, y: a.y + dy * r }, dr * r + 1)
      drops.push({ cx: p.x, cy: p.y, r: dr * r })
    }
    if (tier === 'full') {
      const above = edge(0.18, -1, rim)
      const b = inside({ x: above.x, y: above.y - 2.5 }, 5 * 1.22 + 1)
      splats.push(blob(b.x, b.y, 5, rand))
      for (const [dx, dy, dr] of [[-8, -4, 1.8], [-13, -7, 1.1]] as const) {
        const p = inside({ x: b.x + dx, y: b.y + dy }, dr + 1)
        drops.push({ cx: p.x, cy: p.y, r: dr })
      }
    }
  }

  const scraps: string[] = []
  if (tier === 'full') {
    const s1 = inside({ x: centre(0.42).x, y: edge(0.42, -1, rim).y - 7 }, 5)
    const s2 = inside({ x: centre(0.72).x, y: edge(0.72, 1, rim).y + 8 }, 5)
    scraps.push(scrap(s1.x, s1.y, 3.5, 25, rand), scrap(s2.x, s2.y, 3, -30, rand))
  }

  const em = letteringEm(text)
  const size = Math.min(font, thick * 0.62, ((TEXT_TO - TEXT_FROM) * len - thick * 0.2) / em)
  const mid = centre((TEXT_FROM + TEXT_TO) / 2)
  return {
    tier,
    width,
    height,
    rim: toPath(rimPoints),
    hole: toPath(holePoints),
    shade: toPath(shift(holePoints, 2.5, 3.5)),
    crack,
    splats,
    drops,
    speed,
    scraps,
    text: {
      x: mid.x,
      y: mid.y + size * 0.35,
      size,
      length: em * size,
      angle: (Math.atan2(drop, len) * 180) / Math.PI,
      cx: mid.x,
      cy: mid.y,
    },
  }
}

// ── Torn corners ─────────────────────────────────────────────────────────────────────────────
// A corner of the page is ripped off along `edge`, showing the lime layer underneath. The paper's
// torn core (white fibres) is drawn *inside* the hole, so frame lines printed on the page run right
// up to the ink edge instead of being cut by a white band.

interface Tear { hole: string; fiber: string; edge: string; seam: string }

/** `corner` is a point beyond the box on the hole's side; `inward` is ±1: the side of `edge` the hole lies on. */
function tornCorner(edge: Curve, corner: Pt[], inward: 1 | -1, rand: Rand): Tear {
  const outer = tear(edge, rand, 2.4, [4, 8])
  const inner = tear(offset(edge, 4.5 * inward), rand, 1.5, [4, 8])
  return {
    hole: toPath([...outer, ...corner]),
    fiber: toPath([...outer, ...[...inner].reverse()]),
    edge: toPath(outer, false),
    seam: toPath(inner, false),
  }
}

/** Straight focus lines from `from`, fanned between two angles (degrees, y down). */
function rays(from: Pt, count: number, fromDeg: number, toDeg: number, length: number): string {
  return Array.from({ length: count }, (_, i) => {
    const a = ((fromDeg + (i / (count - 1)) * (toDeg - fromDeg)) * Math.PI) / 180
    return toPath([from, { x: from.x + Math.cos(a) * length, y: from.y + Math.sin(a) * length }], false)
  }).join('')
}

// ── Corner: the masthead's top-left corner, torn open behind the date line ─────────────────────
// Everything stays above y = 98: the masthead's ink rule runs at y ≈ 100–104 below it.

export const CORNER = (() => {
  const rand = seeded(0xc0a1)
  const width = 244
  const height = 100
  const edge = quad({ x: 236, y: -3 }, { x: 214, y: 78 }, { x: -3, y: 92 })
  const bolt = [[0.62, 0], [0.12, 0.58], [0.46, 0.55], [0.22, 1], [0.94, 0.36], [0.56, 0.4], [0.9, 0]] as const
  const boltAt = (x: number, y: number, w: number, h: number) => toPath(bolt.map(([u, v]) => ({ x: x + u * w, y: y + v * h })))
  return {
    width,
    height,
    ...tornCorner(edge, [{ x: -8, y: -8 }], 1, rand),
    focus: rays({ x: 62, y: 40 }, 16, -120, 70, 190),
    bolt: boltAt(116, 5, 42, 62),
    impact: [toPath([{ x: 164, y: 12 }, { x: 176, y: 6 }], false), toPath([{ x: 166, y: 24 }, { x: 181, y: 23 }], false), toPath([{ x: 163, y: 36 }, { x: 174, y: 41 }], false)],
    scraps: [scrap(204, 14, 3, 25, rand)],
    shout: { x: 62, y: 69, size: 76, length: 88, angle: -6, cx: 62, cy: 42 },
    ribbon: {
      body: toPath([{ x: 29, y: 73.5 }, { x: 157, y: 73.5 }, { x: 151, y: 82 }, { x: 157, y: 90.5 }, { x: 29, y: 90.5 }, { x: 35, y: 82 }]),
      transform: 'rotate(-4 93 82)',
      text: { x: 93, y: 86.9, size: 14, length: BANGERS_EM['BRIGHTER TOMORROW!'] * 14 },
    },
  }
})()

// ── Peel: the page's bottom-right corner torn off over the UI card, a robot climbing out ─────────
// Drawn for a 300 × 250 box whose bottom-right is the viewport corner; the theme scales the box.
// The caption stays inside the hole so it never lands on a card frame at any scale.

export const PEEL = (() => {
  const rand = seeded(0x9ee1)
  const width = 300
  const height = 250
  const edge = quad({ x: 303, y: -3 }, { x: 150, y: 10 }, { x: 146, y: 253 })
  return {
    width,
    height,
    ...tornCorner(edge, [{ x: 308, y: 258 }], -1, rand),
    focus: rays({ x: 300, y: 250 }, 14, 180, 270, 330),
    robot: { x: 166, y: 120, width: 134, height: 130 },
    scraps: [scrap(250, 18, 3.2, 20, rand), scrap(172, 138, 2.8, -35, rand)],
    caption: { rect: { x: 209, y: 44, width: 84, height: 54 }, transform: 'rotate(-7 251 71)' },
    lines: (['MORE', 'CREATORS!'] as const).map((text, i) => ({ text, y: 64 + i * 17, size: 18, length: BANGERS_EM[text] * 18 })),
    small: { text: 'A BRIGHTER WORLD', y: 93, size: 7.6, length: BANGERS_EM['A BRIGHTER WORLD'] * 7.6 },
  }
})()
