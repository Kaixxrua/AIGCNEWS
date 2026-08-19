import { baseCompile } from '@intlify/message-compiler'
import { beforeEach, describe, expect, it } from 'vitest'
import { i18n, messages } from './index'
import {
  LOCALE_STORAGE_KEY,
  persistAppLocale,
  resolveAppLocale,
  updateDocumentLocale,
} from './locale'

const catalogLeaves = (value: unknown, prefix = ''): Record<string, string> => {
  if (!value || typeof value !== 'object') return {}
  return Object.fromEntries(Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return child && typeof child === 'object'
      ? Object.entries(catalogLeaves(child, path))
      : [[path, String(child)]]
  }))
}

const catalogShape = (value: unknown): unknown => {
  if (!value || typeof value !== 'object') return typeof value
  return Object.fromEntries(
    Object.entries(value).map(([key, child]) => [key, catalogShape(child)]),
  )
}

describe('application locale contract', () => {
  beforeEach(() => localStorage.clear())

  it('prefers a valid persisted locale', () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, 'en-US')
    expect(resolveAppLocale({ storage: localStorage, browserLanguages: ['zh-CN'] })).toBe('en-US')
  })

  it('uses browser Chinese versus non-Chinese preference', () => {
    expect(resolveAppLocale({ storage: localStorage, browserLanguages: ['zh-TW'] })).toBe('zh-CN')
    expect(resolveAppLocale({ storage: localStorage, browserLanguages: ['fr-FR'] })).toBe('en-US')
  })

  it('falls back to Chinese when browser information is unavailable', () => {
    expect(resolveAppLocale({ storage: null, browserLanguages: null })).toBe('zh-CN')
    persistAppLocale('en-US', localStorage)
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en-US')
  })

  it('updates the document language', () => {
    updateDocumentLocale('en-US', document.documentElement)
    expect(document.documentElement.lang).toBe('en-US')
  })

  it('keeps every catalog leaf structurally aligned', () => {
    expect(catalogShape(messages['zh-CN'])).toEqual(catalogShape(messages['en-US']))
  })

  it('compiles every catalog message without syntax errors', () => {
    const failures: string[] = []

    for (const [locale, catalog] of Object.entries(messages)) {
      for (const [key, message] of Object.entries(catalogLeaves(catalog))) {
        baseCompile(message, {
          onError: error => failures.push(`${locale}:${key} [${error.code}] ${error.message}`),
        })
      }
    }

    expect(failures).toEqual([])
  })

  it.each(['zh-CN', 'en-US'] as const)('renders literal email addresses in %s', (locale) => {
    i18n.global.locale.value = locale
    expect(i18n.global.t('auth.emailPlaceholder')).toBe('you@example.com')
    expect(i18n.global.t('legal.disclaimer.upstream')).toContain('kaixxrua@gmail.com')
  })

  it.each(['zh-CN', 'en-US'] as const)(
    'pins the marketing price literals to the backend plan amounts in %s',
    (locale) => {
      i18n.global.locale.value = locale
      // 营销卡价格字面量与后端 plans.py 常量同口径（member_monthly ¥19 /
      // member_yearly ¥129）；收银台金额只渲染 plans API，字面量漂移必须红在这里。
      expect(i18n.global.t('membership.member.priceMonthly')).toBe('¥19')
      expect(i18n.global.t('membership.member.priceYearlyAmount')).toBe('¥129')
    },
  )

  it('keeps the yearly anchor line locale-specific but amount-pinned', () => {
    i18n.global.locale.value = 'zh-CN'
    expect(i18n.global.t('membership.member.priceYearly')).toBe('¥129 / 年')
    expect(i18n.global.t('membership.member.yearlySavings')).toBe('年付省 ¥99')
    i18n.global.locale.value = 'en-US'
    expect(i18n.global.t('membership.member.priceYearly')).toBe('¥129 / year')
    expect(i18n.global.t('membership.member.yearlySavings')).toBe('Save ¥99 with annual billing')
  })

  it('provides an explicit Chinese value for every business catalog leaf', () => {
    const zhLeaves = catalogLeaves(messages['zh-CN'])
    const enLeaves = catalogLeaves(messages['en-US'])
    const intentionallyShared = /(?:appName|chinese|english|github|hn|hackernews|producthunt|emailPlaceholder|recommendedBadge|stars|sortStars|forks|rag|arxivDesc|githubDesc|producthuntDesc|hackernewsDesc|\.x|authToken|ct0|priceMonthly|priceYearlyAmount|yearlyDiscount|free\.name|member\.name)$/
    const inherited = Object.keys(zhLeaves).filter(
      key => zhLeaves[key] === enLeaves[key] && !intentionallyShared.test(key),
    )
    expect(inherited).toEqual([])
  })
})
