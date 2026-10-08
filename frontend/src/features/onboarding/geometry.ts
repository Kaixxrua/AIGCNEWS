export interface Box { left: number; top: number; width: number; height: number }
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(n, Math.max(min, max)))

export function spotlightBox(rect: Box, width: number, height: number): Box | null {
  const left = clamp(rect.left - 6, 4, width - 4)
  const top = clamp(rect.top - 6, 4, height - 4)
  const right = clamp(rect.left + rect.width + 6, 4, width - 4)
  const bottom = clamp(rect.top + rect.height + 6, 4, height - 4)
  return right > left && bottom > top ? { left, top, width: right - left, height: bottom - top } : null
}
export function placeCard(target: Box | null, card: { width: number; height: number }, width: number, height: number): Box {
  const gap = 20
  const w = Math.min(card.width, width - 32)
  const h = Math.min(card.height, height - 32)
  const centered = { left: (width - w) / 2, top: (height - h) / 2, width: w, height: h }
  if (!target) return centered
  const candidates = [
    { left: target.left + target.width + gap, top: target.top },
    { left: target.left - w - gap, top: target.top },
    { left: target.left + (target.width - w) / 2, top: target.top + target.height + gap },
    { left: target.left + (target.width - w) / 2, top: target.top - h - gap },
  ]
  const boxes = candidates.map(point => ({
    left: clamp(point.left, 16, width - w - 16),
    top: clamp(point.top, 16, height - h - 16), width: w, height: h,
  }))
  const overlap = (box: Box) => Math.max(0, Math.min(box.left + w, target.left + target.width) - Math.max(box.left, target.left))
    * Math.max(0, Math.min(box.top + h, target.top + target.height) - Math.max(box.top, target.top))
  return boxes.reduce((best, box) => overlap(box) < overlap(best) ? box : best, boxes[0]!)
}
