/** Lettering advance in em: the CJK subset averages ~0.77em per glyph, the Latin display face ~0.36em. */
export function letteringEm(text: string): number {
  let em = 0
  for (const ch of text) em += (ch.codePointAt(0) ?? 0) >= 0x2e80 ? 0.77 : 0.36
  return em
}
