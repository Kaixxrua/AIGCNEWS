import { describe, expect, it } from 'vitest'
import { messages } from '@/i18n'
import { COMPARE_ROWS, COMPARE_TIERS, compareColumn, sameAcrossTiers, type CompareRow, type CompareTier } from './membershipCompare'

const TIERS: readonly CompareTier[] = ['guest', 'free', 'member']
const LOCALES = ['zh-CN', 'en-US'] as const

type Copy = { readonly [key: string]: string | Copy }
const membershipCopy = (locale: (typeof LOCALES)[number]) => messages[locale].membership as unknown as Copy
const copyAt = (copy: Copy, path: string): string => {
  const value = path.split('.').reduce<string | Copy | undefined>((node, key) => (typeof node === 'object' ? node[key] : undefined), copy)
  if (typeof value !== 'string') throw new Error(`no copy at membership.${path}`)
  return value
}
const keysAt = (copy: Copy, path: string): string[] => {
  const value = path.split('.').reduce<string | Copy | undefined>((node, key) => (typeof node === 'object' ? node[key] : undefined), copy)
  if (!value || typeof value !== 'object') throw new Error(`no copy at membership.${path}`)
  return Object.keys(value)
}

describe('compareColumn', () => {
  it('gives each plan one cell per row, in the table order', () => {
    expect(compareColumn('guest')).toEqual([
      { row: 'browse', included: true, lines: [], upgrade: false, same: true },
      { row: 'tracking', included: false, lines: [], upgrade: false, same: false },
      { row: 'digest', included: false, lines: [], upgrade: false, same: false },
      { row: 'website', included: false, lines: [], upgrade: false, same: false },
      { row: 'uiCopy', included: false, lines: [], upgrade: false, same: false },
      { row: 'quota', included: true, lines: ['quotaGuestDay', 'quotaGuestScope'], upgrade: false, same: false },
      { row: 'briefing', included: false, lines: [], upgrade: false, same: false },
      { row: 'rss', included: false, lines: [], upgrade: false, same: false },
    ])
    expect(compareColumn('member').map(({ included, lines }) => [included, lines])).toEqual([
      [true, []],
      [true, ['trackingMember', 'trackingMcp']],
      [true, ['digestMember']],
      [true, ['websiteMember']],
      [true, ['uiCopyMember']],
      [true, ['quotaMemberDay', 'quotaMemberMonth']],
      [true, ['briefingAll']],
      [true, ['rssAll']],
    ])
    for (const tier of TIERS) expect(compareColumn(tier).map((entry) => entry.row)).toEqual(COMPARE_ROWS.map((row) => row.key))
  })

  it('never takes a benefit away from a higher plan', () => {
    const [guest, free, member] = TIERS.map((tier) => compareColumn(tier))
    COMPARE_ROWS.forEach(({ key }, index) => {
      if (guest?.[index]?.included) expect(free?.[index]?.included, key).toBe(true)
      if (free?.[index]?.included) expect(member?.[index]?.included, key).toBe(true)
    })
  })

  it('marks what each plan gives more of than the plan to its left, and the one row all three have alike', () => {
    const upgraded = (tier: CompareTier) => compareColumn(tier).filter((entry) => entry.upgrade).map((entry) => entry.row)
    expect(TIERS).toEqual(COMPARE_TIERS)
    expect(upgraded('guest')).toEqual([])
    expect(upgraded('free')).toEqual(['quota'])
    expect(upgraded('member')).toEqual(['tracking', 'digest', 'website', 'uiCopy', 'quota'])
    expect(COMPARE_ROWS.filter(sameAcrossTiers).map((row) => row.key)).toEqual(['browse'])
    for (const tier of TIERS) {
      expect(compareColumn(tier).filter((entry) => entry.same).map((entry) => entry.row)).toEqual(['browse'])
      // 划荧光笔的格子都有说明文字可划
      for (const entry of compareColumn(tier)) if (entry.upgrade) expect(entry.lines.length, `${tier}.${entry.row}`).toBeGreaterThan(0)
    }
  })

  it('leaves a ✗ to ✓ step unmarked and compares what the cells say, line by line', () => {
    const rows: CompareRow[] = [
      { key: 'browse', cells: { guest: false, free: 'a', member: 'a' } },
      { key: 'tracking', cells: { guest: true, free: true, member: 'b' } },
      { key: 'quota', cells: { guest: ['x', 'y'], free: ['x', 'y'], member: ['x', 'z'] } },
      { key: 'website', cells: { guest: ['x'], free: ['x', 'y'], member: ['x', 'y'] } },
      { key: 'rss', cells: { guest: false, free: false, member: false } },
    ]
    const marks = (tier: CompareTier) => compareColumn(tier, rows).map((entry) => entry.upgrade)
    expect(marks('guest')).toEqual([false, false, false, false, false])
    expect(marks('free')).toEqual([false, false, false, true, false])
    expect(marks('member')).toEqual([false, true, true, false, false])
    expect(rows.map(sameAcrossTiers)).toEqual([false, false, false, false, true])
  })
})

describe('membership.compare copy', () => {
  it.each(LOCALES)('names every row and words every cell in %s, with nothing left over', (locale) => {
    const copy = membershipCopy(locale)
    expect(keysAt(copy, 'compare.rows')).toEqual(COMPARE_ROWS.map((row) => row.key))
    for (const row of COMPARE_ROWS) expect(copyAt(copy, `compare.rows.${row.key}`)).not.toBe('')
    const used = new Set(TIERS.flatMap((tier) => compareColumn(tier).flatMap((entry) => entry.lines)))
    for (const line of used) expect(copyAt(copy, `compare.cells.${line}`)).not.toBe('')
    expect(keysAt(copy, 'compare.cells').sort()).toEqual([...used].sort())
  })

  // 对比表里的次数、条数、天数和卡片原文是同一件事；卡片上的数字改了，这里提醒对比表一起改。
  const SAME_NUMBERS: ReadonlyArray<readonly [card: string, cells: readonly string[]]> = [
    ['guest.features.mcpAnonymous', ['quotaGuestDay', 'quotaGuestScope']],
    ['free.features.tracking', ['trackingFree']],
    ['free.features.mcpFree', ['quotaFreeDay', 'quotaFreeMonth']],
    ['free.features.websiteFree', ['websiteFree']],
    ['free.features.uiCopyFree', ['uiCopyFree']],
    ['free.features.briefingFree', ['briefingAll']],
    ['member.features.tracking', ['trackingMember']],
    ['member.features.mcpMember', ['quotaMemberDay', 'quotaMemberMonth']],
  ]
  const numbersIn = (text: string) => (text.match(/\d[\d,]*/g) ?? []).map((digits) => Number(digits.replace(/,/g, '')))

  it.each(LOCALES)('gives the same counts as the plan cards in %s', (locale) => {
    const copy = membershipCopy(locale)
    for (const [card, cells] of SAME_NUMBERS) {
      const expected = numbersIn(copyAt(copy, card))
      expect(expected.length, card).toBeGreaterThan(0)
      expect(numbersIn(cells.map((cell) => copyAt(copy, `compare.cells.${cell}`)).join(' ')), card).toEqual(expected)
    }
  })
})
