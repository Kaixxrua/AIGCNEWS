import { i18n } from './index'
import type { AppLocale } from './locale'

const localeFor = (locale?: AppLocale) => locale ?? i18n.global.locale.value

/** Parse database timestamps as UTC when the API omits an explicit offset. */
export function parseImplicitUtc(value: string | Date): Date {
  if (value instanceof Date) return value
  return new Date(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`)
}

export function formatLocaleDate(
  value: string | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit' },
  locale?: AppLocale,
): string {
  if (!value) return '—'
  const date = parseImplicitUtc(value)
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(localeFor(locale), options).format(date)
}

export function formatLocaleNumber(value: number | null | undefined, locale?: AppLocale): string {
  const numeric = Number(value ?? 0)
  return Number.isFinite(numeric) ? new Intl.NumberFormat(localeFor(locale)).format(numeric) : '0'
}

export function formatLocaleCompactNumber(value: number | null | undefined, locale?: AppLocale): string {
  const numeric = Number(value ?? 0)
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat(localeFor(locale), { notation: 'compact', maximumFractionDigits: 1 }).format(numeric)
    : '0'
}

export function compareLocaleStrings(left: string, right: string, locale?: AppLocale): number {
  return new Intl.Collator(localeFor(locale)).compare(left, right)
}
