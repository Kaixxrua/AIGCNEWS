import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import { BANGERS_EM } from './comicTear'

// The lettering faces are subsets: a character outside their unicode-range falls back to a plain
// system face in the middle of the comic art. Every string a sticker can print must be covered.
const fontsCss = readFileSync(`${process.cwd()}/src/fonts.css`, 'utf-8')
const ranges = [...fontsCss.matchAll(/@font-face\s*{([^}]*)}/g)]
  .map(match => match[1] ?? '')
  .filter(block => block.includes("'AIGC Comic Lettering'"))
  .flatMap(block => (block.match(/unicode-range:\s*([^;]+);/)?.[1] ?? '').split(','))
  .map(part => part.trim().replace(/^U\+/i, '').split('-').map(hex => parseInt(hex, 16)))
  .map(([from = NaN, to = from]) => [from, to] as const)

const uncovered = (text: string) => [...text].filter(ch => {
  const code = ch.codePointAt(0) ?? 0
  return !ranges.some(([from, to]) => code >= from && code <= to)
})

describe('comic lettering subsets', () => {
  it('declares both subsets', () => {
    expect(ranges.length).toBeGreaterThanOrEqual(2)
  })

  it.each(['zh-CN', 'en-US'] as const)('cover the %s creation slogan', locale => {
    const slogan = i18n.global.t('dashboard.editorial.creationMark', {}, { locale })
    expect(slogan).toBeTruthy()
    expect(uncovered(slogan)).toEqual([])
  })

  it('cover the fixed sticker slogans', () => {
    expect(uncovered(Object.keys(BANGERS_EM).join(''))).toEqual([])
  })
})
