import { i18n } from './index'
import type { AppLocale } from './locale'

const localeFor = (locale?: AppLocale) => locale ?? i18n.global.locale.value
const isCalendarDate = (value: string | Date) => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)

/** Parse database timestamps as UTC when the API omits an explicit offset. */
export function parseImplicitUtc(value: string | Date): Date {
  if (value instanceof Date) return value
  if (isCalendarDate(value)) return new Date(`${value}T00:00:00Z`)
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`)
}

export function formatLocaleDate(
  value: string | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit' },
  locale?: AppLocale,
): string {
  if (!value) return '—'
  const date = parseImplicitUtc(value)
  // A publication day is a calendar label, whereas a timestamp is an instant.
  const displayOptions = isCalendarDate(value) ? { ...options, timeZone: 'UTC' } : options
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(localeFor(locale), displayOptions).format(date)
}

export function formatLocaleCompactNumber(value: number | null | undefined, locale?: AppLocale): string {
  const numeric = Number(value ?? 0)
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat(localeFor(locale), { notation: 'compact', maximumFractionDigits: 1 }).format(numeric)
    : '0'
}

/** Whole counts with the locale's digit grouping (48,214). */
export function formatLocaleNumber(value: number | null | undefined, locale?: AppLocale): string {
  const numeric = Number(value ?? 0)
  return Number.isFinite(numeric) ? new Intl.NumberFormat(localeFor(locale)).format(numeric) : '0'
}

const UTC_DAY_MS = 86_400_000

const utcCalendarDay = (date: Date) =>
  Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())

/**
 * Relative calendar-day label ("today" / "昨天" / "3 days ago") computed on UTC
 * day boundaries, so date-only values ('YYYY-MM-DD') and full timestamps for the
 * same day produce identical output. Future dates clamp to today.
 */
export function formatLocaleRelativeDay(
  value: string | Date | null | undefined,
  locale?: AppLocale,
  now: Date = new Date(),
): string {
  if (!value) return ''
  const date = parseImplicitUtc(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const days = Math.max(0, Math.round((utcCalendarDay(now) - utcCalendarDay(date)) / UTC_DAY_MS))
  const rtf = new Intl.RelativeTimeFormat(localeFor(locale), { numeric: 'auto' })
  if (days < 30) return rtf.format(-days, 'day')
  if (days < 365) return rtf.format(-Math.floor(days / 30), 'month')
  return rtf.format(-Math.floor(days / 365), 'year')
}
