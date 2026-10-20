import type { LocationQuery } from 'vue-router'
import type { ReportLoadState } from '@/composables/useReportController'
import { parseReportDateQuery, parseReportTypeQuery } from '@/features/report/reportViewModel'
import type { PageHeadOverride } from './pageHead'
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false })

/** Use the visible introduction, preserving link text but dropping Markdown and heading tags. */
export function reportSearchText(content: string): { heading: string; description: string } {
  const tokens = markdown.parse(content.slice(0, 3000).replace(/\\n\\n/g, '\n\n').replace(/`#[^`\n]+`/g, ''), {})
  let heading = ''
  let description = ''
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index]!
    const inline = tokens[index + 1]
    if (inline?.type !== 'inline') continue
    const text = (inline.children ?? [])
      .filter(child => ['text', 'code_inline', 'softbreak', 'hardbreak'].includes(child.type))
      .map(child => (child.type === 'text' ? child.content.replace(/\*\*/g, '') : child.content) || ' ')
      .join('').replace(/\s+/g, ' ').trim()
    if (!heading && token.type === 'heading_open' && token.tag === 'h1') heading = text
    if (!description && token.type === 'paragraph_open' && text.length >= 40 && !/^(?:生成日期|榜单日期|Generated|Prepared|Date:)/i.test(text)) description = text
  }
  return { heading: [...heading].slice(0, 80).join(''), description }
}

/** 已确认不存在的期号不收录；加载中、未发布和临时故障不等同于不存在。 */
export function reportPageHead(query: LocationQuery, state: ReportLoadState, title: string, content = ''): PageHeadOverride | null {
  const date = parseReportDateQuery(query.date)
  if (!date) return null
  const type = parseReportTypeQuery(query.type)
  const summary = state === 'ready' ? reportSearchText(content) : { heading: '', description: '' }
  return {
    title: `${summary.heading || title} ${date}`,
    ...(summary.description ? { description: summary.description } : {}),
    noindex: state === 'missing',
    canonicalQuery: { date, type: type === 'all' ? null : type },
  }
}
