import { describe, expect, it } from 'vitest'
import {
  formatReportIssueDate,
  groupReportSections,
  parseReportDateQuery,
  parseReportTypeQuery,
  shiftReportDate,
  todayInReportTimeZone,
} from './reportViewModel'

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

describe('parseReportTypeQuery', () => {
  it('accepts a known briefing type from the quick search link', () => {
    expect(parseReportTypeQuery('arxiv')).toBe('arxiv')
    expect(parseReportTypeQuery('all')).toBe('all')
  })

  it('falls back to all types for missing, repeated or unknown values', () => {
    expect(parseReportTypeQuery(undefined)).toBeNull()
    expect(parseReportTypeQuery(['arxiv', 'news'])).toBeNull()
    expect(parseReportTypeQuery('ARXIV')).toBeNull()
    expect(parseReportTypeQuery('saved')).toBeNull()
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

describe('shiftReportDate', () => {
  it('steps across month and year boundaries on the calendar', () => {
    expect(shiftReportDate('2026-10-01', -1)).toBe('2026-09-30')
    expect(shiftReportDate('2026-01-01', -1)).toBe('2025-12-31')
    expect(shiftReportDate('2028-02-28', 1)).toBe('2028-02-29')
    expect(shiftReportDate('2026-10-04', -7)).toBe('2026-09-27')
  })
})

describe('formatReportIssueDate', () => {
  it('writes the day in the interface language', () => {
    expect(formatReportIssueDate('2026-10-03', 'zh-CN', '2026-10-04')).toBe('10月3日')
    expect(formatReportIssueDate('2026-10-03', 'en-US', '2026-10-04')).toBe('October 3')
  })

  it('adds the year for a day outside the current year', () => {
    expect(formatReportIssueDate('2025-12-30', 'zh-CN', '2026-01-02')).toBe('2025年12月30日')
    expect(formatReportIssueDate('2025-12-30', 'en-US', '2026-01-02')).toBe('December 30, 2025')
  })

  it('returns anything unreadable as it is', () => {
    expect(formatReportIssueDate('', 'zh-CN', '2026-10-04')).toBe('')
    expect(formatReportIssueDate('not-a-date', 'en-US', '2026-10-04')).toBe('not-a-date')
  })
})

describe('groupReportSections', () => {
  it('wraps each top-level h2 with the blocks that follow it', () => {
    const html = '<h1>简报</h1>\n<p>导语</p>\n<h2>技术亮点 <code>LLM</code></h2>\n<ol><li>一</li></ol>\n<h2>行业资讯</h2>\n<p>二</p>\n'
    const grouped = groupReportSections(html)
    const root = document.createElement('div')
    root.innerHTML = grouped

    const masthead = root.querySelector('.report-masthead')
    expect(masthead?.parentElement).toBe(root)
    expect(masthead?.textContent).toBe('简报')
    const sections = root.querySelectorAll(':scope > section.report-section')
    expect(sections).toHaveLength(2)
    expect(sections[0]!.querySelector('h2')?.textContent).toBe('技术亮点 LLM')
    expect(sections[0]!.querySelector('ol li')?.textContent).toBe('一')
    expect(sections[1]!.textContent).toContain('二')
    expect(root.textContent).toBe(new DOMParser().parseFromString(html, 'text/html').body.textContent)
  })

  it('marks the closing dateline so the comic layout can set it small in the corner', () => {
    const html = '<h2>今日判断</h2>\n<p>正文</p>\n<p><strong>生成日期：</strong> 2026-09-29</p>\n'
    const root = document.createElement('div')
    root.innerHTML = groupReportSections(html)

    const paragraphs = root.querySelectorAll('section.report-section > p')
    expect(paragraphs[0]!.classList.contains('report-dateline')).toBe(false)
    expect(paragraphs[1]!.classList.contains('report-dateline')).toBe(true)
    expect(root.textContent).toBe(new DOMParser().parseFromString(html, 'text/html').body.textContent)
    expect(groupReportSections('<h2>一</h2>\n<p>生成日期在句中</p>\n<p>结尾</p>')).not.toContain('report-dateline')
  })

  it('sets the opening h1 as a second-level masthead so the page keeps a single h1', () => {
    const html = '<h1 id="top">AIGC 日报 <code>#news</code></h1>\n<p>导语</p>\n<blockquote><h1>引文标题</h1></blockquote>'
    const root = document.createElement('div')
    root.innerHTML = groupReportSections(html)

    expect(root.querySelectorAll(':scope > h1')).toHaveLength(0)
    const masthead = root.querySelector(':scope > .report-masthead')!
    expect(masthead.tagName).toBe('DIV')
    expect(masthead.getAttribute('role')).toBe('heading')
    expect(masthead.getAttribute('aria-level')).toBe('2')
    expect(masthead.id).toBe('top')
    expect(masthead.innerHTML).toBe('AIGC 日报 <code>#news</code>')
    // 只换顶层报名；嵌在别的块里的标题原样保留
    expect(root.querySelector('blockquote > h1')?.textContent).toBe('引文标题')
    expect(root.textContent).toBe(new DOMParser().parseFromString(html, 'text/html').body.textContent)
  })

  it('leaves nested h2 and h2-free html untouched', () => {
    expect(groupReportSections('<p>无分节</p>')).toBe('<p>无分节</p>')
    const nested = '<ul><li><h2>列表内标题</h2></li></ul>'
    expect(groupReportSections(nested)).toBe(nested)
  })
})
