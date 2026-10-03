import { describe, expect, it } from 'vitest'
import type { QuickSearchResult } from '@/services/search/searchApi'
import type { UiTemplate } from '@/features/ui-library/catalog'
import {
  buildSections,
  highlight,
  highlightTerms,
  matchTemplates,
  parseRecentQueries,
  pushRecentQuery,
  recentSection,
  RECENT_QUERIES_MAX,
  searchableQuery,
  slimTemplate,
  type QuickSearchSection,
  type QuickSearchTemplate,
} from './quickSearch'

const t = (key: string, named?: Record<string, unknown>) => (named ? `${key}${JSON.stringify(named)}` : key)

const result = (overrides: Partial<QuickSearchResult> = {}): QuickSearchResult => ({
  q: 'agent',
  projects: null,
  papers: null,
  briefings: null,
  tweets: null,
  failed: [],
  ...overrides,
})

const template = (id: string, name: string, extra: Partial<QuickSearchTemplate> = {}): QuickSearchTemplate => ({
  id,
  name: { zh: `${name}（中）`, en: name },
  description: { zh: `${name} 中文简介`, en: `${name} description` },
  provider: 'Uiverse',
  aliases: [],
  frameworks: ['html'],
  category: 'buttons',
  ...extra,
})

/** 第 group 组的第 index 行；没有这一行时为 undefined，交给断言失败。 */
const rowAt = (sections: readonly QuickSearchSection[], group: number, index = 0) => sections[group]?.rows[index]
const lastRow = (section: QuickSearchSection | undefined) => section?.rows[section.rows.length - 1]

describe('searchableQuery', () => {
  it('normalizes width and whitespace and needs two characters or one Han character', () => {
    expect(searchableQuery('  ｍagpie　 agent ')).toBe('magpie agent')
    expect(searchableQuery('a')).toBe('')
    expect(searchableQuery('  ')).toBe('')
    expect(searchableQuery('ai')).toBe('ai')
    expect(searchableQuery('图')).toBe('图')
  })

  it('stops at the backend limit of 120 characters', () => {
    expect(searchableQuery('x'.repeat(200))).toHaveLength(120)
  })
})

describe('buildSections', () => {
  it('orders the groups projects, papers, briefings, tweets, templates and skips empty ones', () => {
    const sections = buildSections({
      q: 'agent',
      result: result({
        projects: { total: 1, items: [{ fullName: 'acme/agent', url: '', description: 'raw', descriptionZh: '中文简介', descriptionEn: 'English', stars: 12_345, language: 'Python' }] },
        papers: { total: 0, items: [] },
        briefings: { total: 1, items: [{ date: '2026-09-30', type: 'github', title: 'GitHub 简报', lead: 'acme/agent', snippet: '…agent…' }] },
        tweets: { total: 1, items: [{ id: 't1', text: 'agents!', url: 'https://x.com/ada/status/1', author: 'ada', date: '2026-09-30' }] },
      }),
      templates: { total: 1, items: [template('btn-1', 'Agent button')] },
      failed: [],
    }, 'zh-CN', t)

    expect(sections.map(section => section.kind)).toEqual(['projects', 'briefings', 'tweets', 'templates'])
    expect(rowAt(sections, 0)).toEqual({
      kind: 'projects',
      key: 'projects:acme/agent',
      title: 'acme/agent',
      detail: '中文简介',
      meta: ['★ 1.2万', 'Python'],
      target: { type: 'route', to: { name: 'github-projects', query: { q: 'acme/agent' } } },
      more: false,
    })
    expect(rowAt(sections, 1)).toMatchObject({
      title: 'acme/agent',
      detail: '…agent…',
      meta: ['saved.issue{"date":"2026-09-30","name":"report.type.githubLabel"}'],
      target: { type: 'route', to: { name: 'report', query: { date: '2026-09-30', type: 'github' } } },
    })
    expect(rowAt(sections, 2)).toMatchObject({ title: '@ada', detail: 'agents!', target: { type: 'external', href: 'https://x.com/ada/status/1' } })
    expect(rowAt(sections, 3)).toMatchObject({
      title: 'Agent button（中）',
      detail: 'Agent button 中文简介',
      meta: ['Uiverse'],
      target: { type: 'route', to: { name: 'ui-library', params: { id: 'btn-1' }, query: { q: 'agent' } } },
    })
  })

  it('adds a see-all row only where a list page can show the rest', () => {
    const sections = buildSections({
      q: 'agent',
      result: result({
        projects: { total: 42, items: [{ fullName: 'a/b', url: '', description: '', descriptionZh: '', descriptionEn: '', stars: 0, language: '' }] },
        papers: { total: 9, items: [{ id: 'p1', title: 'Paper', summary: '', date: '2026-09-30', authors: [], authorCount: 0 }] },
      }),
      templates: { total: 30, items: [template('btn-1', 'Agent button')] },
      failed: [],
    }, 'en-US', t)

    const [projects, papers, templates] = sections
    expect(projects?.total).toBe(42)
    expect(lastRow(projects)).toEqual({
      kind: 'projects',
      key: 'projects::more',
      title: 'quickSearch.more.projects{"count":42}',
      detail: '',
      meta: [],
      target: { type: 'route', to: { name: 'github-projects', query: { q: 'agent' } } },
      more: true,
    })
    expect(projects?.rows[0]?.meta).toEqual([])
    // 论文没有列表页可去：只列出前几篇。
    expect(papers?.rows.map(item => item.more)).toEqual([false])
    expect(papers?.rows[0]?.target).toEqual({ type: 'route', to: { name: 'paper-read', params: { id: 'p1' } } })
    expect(lastRow(templates)?.target).toEqual({ type: 'route', to: { name: 'ui-library', query: { q: 'agent' } } })
    expect(templates?.rows[0]?.title).toBe('Agent button')
  })

  it('names the first author and says how many there are in all', () => {
    const [papers] = buildSections({
      q: 'agent',
      result: result({ papers: { total: 4, items: [
        { id: 'p1', title: 'Many hands', summary: 's', date: '2026-09-30', authors: ['Ada', 'Bo', 'Cy'], authorCount: 12 },
        { id: 'p2', title: '', summary: '', date: '', authors: ['Ada'], authorCount: 1 },
        { id: 'p3', title: 'Pair', summary: '', date: '', authors: ['Ada', 'Bo'], authorCount: 0 },
        { id: 'p4', title: 'Nobody', summary: '', date: '2026-09-30', authors: [], authorCount: 3 },
      ] } }),
      templates: null,
      failed: [],
    }, 'zh-CN', t)

    expect(papers?.rows[0]?.meta).toEqual(['quickSearch.authors{"name":"Ada","count":12}', '2026-09-30'])
    expect(papers?.rows[1]).toMatchObject({ title: 'p2', meta: ['Ada'] })
    expect(papers?.rows[2]?.meta).toEqual(['quickSearch.authors{"name":"Ada","count":2}'])
    expect(papers?.rows[3]?.meta).toEqual(['2026-09-30'])
  })

  it('keeps a header for a group that failed and drops rows that cannot be opened', () => {
    const sections = buildSections({
      q: 'agent',
      result: result({
        briefings: { total: 2, items: [{ date: '2026-09-30', type: 'retired', title: '', lead: '', snippet: '' }, { date: '2026-09-29', type: 'all', title: '', lead: '', snippet: 'x' }] },
        tweets: { total: 1, items: [{ id: 't1', text: 'no link', url: '', author: '', date: '' }] },
      }),
      templates: null,
      failed: ['projects', 'templates'],
    }, 'zh-CN', t)

    expect(sections.map(section => [section.kind, section.failed, section.rows.length])).toEqual([
      ['projects', true, 0],
      ['briefings', false, 1],
      ['templates', true, 0],
    ])
    expect(rowAt(sections, 1)?.title).toBe('report.type.allLabel')
  })

  it('shows nothing before any result arrives', () => {
    expect(buildSections({ q: 'agent', result: null, templates: null, failed: [] }, 'zh-CN', t)).toEqual([])
  })
})

describe('matchTemplates', () => {
  const items = [
    template('glow', 'Glow button', { aliases: ['发光'] }),
    template('card', 'Agent card'),
    template('glow-2', 'Glow input', { category: 'inputs' }),
  ]

  it('searches like the library page and caps the rows', () => {
    expect(matchTemplates(items, 'glow', 1)).toEqual({ total: 2, items: [items[0]] })
    expect(matchTemplates(items, '发光', 5).items.map(item => item.id)).toEqual(['glow'])
  })

  it('finds nothing for an empty or stop-word-only query instead of the whole catalog', () => {
    expect(matchTemplates(items, '', 5)).toEqual({ total: 0, items: [] })
    expect(matchTemplates(items, 'the', 5)).toEqual({ total: 0, items: [] })
  })

  it('keeps only the fields search needs', () => {
    const full = { ...template('glow', 'Glow'), files: [{ name: 'a', path: 'b', sha256: 'c' }], notes: { zh: '', en: '' } } as unknown as UiTemplate
    expect(Object.keys(slimTemplate(full)).sort()).toEqual(['aliases', 'category', 'description', 'frameworks', 'id', 'name', 'provider'])
  })
})

describe('recent queries', () => {
  it('fills the empty box with the last few queries', () => {
    expect(recentSection([])).toEqual([])
    expect(recentSection(['agent'])).toEqual([{
      kind: 'recent',
      total: 1,
      failed: false,
      rows: [{ kind: 'recent', key: 'recent:agent', title: 'agent', detail: '', meta: [], target: { type: 'query', q: 'agent' }, more: false }],
    }])
  })

  it('reads only well-formed lists', () => {
    expect(parseRecentQueries(null)).toEqual([])
    expect(parseRecentQueries('{')).toEqual([])
    expect(parseRecentQueries('{"q":1}')).toEqual([])
    expect(parseRecentQueries('["agent", 3, "a", " rag "]')).toEqual(['agent'])
  })

  it('moves a repeated query to the front once and keeps the newest few', () => {
    expect(pushRecentQuery(['RAG', 'agent'], 'rag')).toEqual(['rag', 'agent'])
    const many = Array.from({ length: RECENT_QUERIES_MAX }, (_, index) => `q${index}`)
    expect(pushRecentQuery(many, 'new')).toEqual(['new', ...many.slice(0, RECENT_QUERIES_MAX - 1)])
  })
})

describe('highlight', () => {
  it('marks every term without caring about case, longest first', () => {
    const terms = highlightTerms('agent  Agents ｒag')
    expect(terms).toEqual(['agents', 'agent', 'rag'])
    expect(highlight('Agents use RAG; an agent too', terms)).toEqual([
      { text: 'Agents', hit: true },
      { text: ' use ', hit: false },
      { text: 'RAG', hit: true },
      { text: '; an ', hit: false },
      { text: 'agent', hit: true },
      { text: ' too', hit: false },
    ])
  })

  it('treats regex characters in the query as plain text', () => {
    expect(highlight('C++ (beta)', highlightTerms('c++ (beta'))).toEqual([
      { text: 'C++', hit: true },
      { text: ' ', hit: false },
      { text: '(beta', hit: true },
      { text: ')', hit: false },
    ])
  })

  it('leaves text without terms whole and empty text empty', () => {
    expect(highlight('plain', [])).toEqual([{ text: 'plain', hit: false }])
    expect(highlight('', ['a'])).toEqual([])
  })
})
