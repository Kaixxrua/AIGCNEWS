import { describe, expect, it } from 'vitest'
import { groupReportSections, parseReportDateQuery, todayInReportTimeZone } from './reportViewModel'

describe('parseReportDateQuery', () => {
  it('accepts a past or current calendar date from the RSS briefing link', () => {
    expect(parseReportDateQuery('2026-09-27', '2026-09-29')).toBe('2026-09-27')
    expect(parseReportDateQuery('2026-09-29', '2026-09-29')).toBe('2026-09-29')
  })

  it('falls back to the default date for missing, repeated, malformed or future values', () => {
    expect(parseReportDateQuery(undefined, '2026-09-29')).toBeNull()
    expect(parseReportDateQuery(['2026-09-27', '2026-09-28'], '2026-09-29')).toBeNull()
    expect(parseReportDateQuery('2026-9-27', '2026-09-29')).toBeNull()
    expect(parseReportDateQuery('2026-02-30', '2026-09-29')).toBeNull()
    expect(parseReportDateQuery('2026-09-30', '2026-09-29')).toBeNull()
  })
})

describe('todayInReportTimeZone', () => {
  it('returns the CST calendar date even when UTC is still on the previous day', () => {
    // UTC 17:00 = 次日 01:00 CST；简报缓存键按 CST 日期生成。
    expect(todayInReportTimeZone(new Date('2026-08-08T17:00:00Z'))).toBe('2026-08-09')
  })

  it('stays on the same date before the CST midnight boundary', () => {
    // UTC 15:59:59 = 当天 23:59:59 CST。
    expect(todayInReportTimeZone(new Date('2026-08-08T15:59:59Z'))).toBe('2026-08-08')
  })

  it('zero-pads month and day for single-digit values', () => {
    // UTC 2026-01-02 20:00 = CST 2026-01-03 04:00。
    expect(todayInReportTimeZone(new Date('2026-01-02T20:00:00Z'))).toBe('2026-01-03')
  })
})

describe('groupReportSections', () => {
  it('wraps each top-level h2 with the blocks that follow it', () => {
    const html = '<h1>简报</h1>\n<p>导语</p>\n<h2>技术亮点 <code>LLM</code></h2>\n<ol><li>一</li></ol>\n<h2>行业资讯</h2>\n<p>二</p>\n'
    const grouped = groupReportSections(html)
    const root = document.createElement('div')
    root.innerHTML = grouped

    expect(root.querySelector('h1')?.parentElement).toBe(root)
    const sections = root.querySelectorAll(':scope > section.report-section')
    expect(sections).toHaveLength(2)
    expect(sections[0]!.querySelector('h2')?.textContent).toBe('技术亮点 LLM')
    expect(sections[0]!.querySelector('ol li')?.textContent).toBe('一')
    expect(sections[1]!.textContent).toContain('二')
    expect(root.textContent).toBe(new DOMParser().parseFromString(html, 'text/html').body.textContent)
  })

  it('leaves nested h2 and h2-free html untouched', () => {
    expect(groupReportSections('<p>无分节</p>')).toBe('<p>无分节</p>')
    const nested = '<ul><li><h2>列表内标题</h2></li></ul>'
    expect(groupReportSections(nested)).toBe(nested)
  })
})
