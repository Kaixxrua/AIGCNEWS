import { mount, RouterLinkStub } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReportPaperPeek from './ReportPaperPeek.vue'
import { i18n } from '@/i18n'
import { renderMarkdown } from '@/composables/useLatexRenderer'
import type { PeekPaper, PeekTarget } from '@/composables/useReportPeek'
import type { PaperLink } from '@/features/report/reportPaperLinks'
import type { PaperItem } from '@/services/papers/paperApi'

const PAPERS: PaperLink[] = [
  { arxivId: '2609.33439', href: 'https://hf-mirror.com/papers/2609.33439', label: 'Raven' },
  { arxivId: '2609.31847', href: 'https://hf-mirror.com/papers/2609.31847', label: '' },
]
const RAVEN: PaperItem = {
  id: 'doc-raven',
  source: 'arxiv',
  source_channel: 'huggingface_daily_html',
  title: 'Raven: Agents That Split Their Work',
  url: 'https://huggingface.co/papers/2609.33439',
  summary: 'We split **tasks** before acting.',
  published_date: '2026-09-30T00:00:00Z',
  raw_score: 128,
  rank_in_period: 3,
  authors: '["Hao Li", "MeiJia Chen", "Ana Ruiz", "Tom Ito", "Lu Wan"]',
  arxiv_id: '2609.33439',
}

const mountPeek = (state: PeekPaper, props: { target?: PeekTarget; papers?: PaperLink[]; index?: number; total?: number } = {}) => mount(ReportPaperPeek, {
  props: {
    target: { key: '0-0-0', arxivId: '2609.33439' },
    state,
    papers: PAPERS,
    index: 0,
    total: 3,
    direction: 0,
    withinItem: false,
    renderMarkdown,
    ...props,
  },
  global: { plugins: [i18n], stubs: { RouterLink: RouterLinkStub } },
})

describe('ReportPaperPeek', () => {
  it('shows the paper with its authors folded after three, its day, id, upvotes and board, the abstract and three ways on', async () => {
    const wrapper = mountPeek({ status: 'ready', paper: RAVEN })

    expect(wrapper.get('.report-peek__title').text()).toBe('Raven: Agents That Split Their Work')
    const authors = wrapper.get('.report-peek__authors')
    expect(authors.text()).toContain('Hao Li, MeiJia Chen, Ana Ruiz')
    expect(authors.text()).not.toContain('Tom Ito')
    await authors.get('.report-peek__more').trigger('click')
    expect(authors.text()).toContain('Tom Ito, Lu Wan')
    expect(wrapper.findAll('.report-peek__facts > *').map((fact) => fact.text())).toEqual(['2026-09-30', 'arXiv 2609.33439', 'HF 点赞 128', '日榜第 3'])
    expect(wrapper.get('.report-peek__abstract').html()).toContain('<strong>tasks</strong>')

    const read = wrapper.getComponent(RouterLinkStub)
    expect(read.props('to')).toEqual({ name: 'paper-read', params: { id: 'doc-raven' } })
    expect(read.classes()).toContain('is-primary')
    const away = wrapper.findAll('a.report-peek__action').filter((link) => link.attributes('target') === '_blank')
    expect(away.map((link) => [link.attributes('href'), link.attributes('rel')])).toEqual([
      ['https://huggingface.co/papers/2609.33439', 'noopener noreferrer'],
      ['https://arxiv.org/abs/2609.33439', 'noopener noreferrer'],
    ])
  })

  it('typesets LaTeX written into the title and abstract', () => {
    const wrapper = mountPeek({ status: 'ready', paper: { ...RAVEN, title: String.raw`\textbf{Raven}: Agents--Split`, summary: String.raw`We split \emph{tasks} at 2\% cost~\cite{x}.` } })

    expect(wrapper.get('.report-peek__title').text()).toBe('Raven: Agents–Split')
    const abstract = wrapper.get('.report-peek__abstract')
    expect(abstract.html()).toContain('<em>tasks</em>')
    expect(abstract.text()).toContain('at 2% cost.')
  })

  it('lists the papers of an item that cites several, counts its place among the items, and steps or closes', async () => {
    const wrapper = mountPeek({ status: 'ready', paper: RAVEN })

    const papers = wrapper.findAll('.report-peek__paper')
    expect(papers.map((paper) => [paper.text(), paper.attributes('aria-pressed')])).toEqual([['Raven', 'true'], ['2', 'false']])
    await papers[1]!.trigger('click')
    expect(wrapper.emitted('pick')).toEqual([['2609.31847']])

    expect(wrapper.get('.report-peek__count').attributes('aria-label')).toBe('第 1 条，共 3 条')
    const [prev, next, close] = wrapper.findAll('.report-peek__btn')
    expect(prev!.attributes('disabled')).toBeDefined()
    await next!.trigger('click')
    await close!.trigger('click')
    expect(wrapper.emitted('step')).toEqual([[1]])
    expect(wrapper.emitted('close')).toHaveLength(1)

    await wrapper.setProps({ index: 2 })
    expect(prev!.attributes('disabled')).toBeUndefined()
    expect(next!.attributes('disabled')).toBeDefined()
    await prev!.trigger('click')
    expect(wrapper.emitted('step')).toEqual([[1], [-1]])

    // 只讲一篇时不列
    await wrapper.setProps({ papers: PAPERS.slice(0, 1) })
    expect(wrapper.find('.report-peek__papers').exists()).toBe(false)
  })

  it('holds a skeleton while loading, points to the paper pages when the site lacks the paper, and offers a retry when the request failed', async () => {
    const wrapper = mountPeek({ status: 'loading' })
    expect(wrapper.findAll('.report-peek__skeleton').length).toBeGreaterThan(2)
    expect(wrapper.get('.report-peek__body').attributes('aria-busy')).toBe('true')
    expect(wrapper.find('.report-peek__title').exists()).toBe(false)

    // 站里没有：标题用链接文字，没有站内阅读
    await wrapper.setProps({ state: { status: 'missing' } })
    expect(wrapper.get('.report-peek__title').text()).toBe('Raven')
    expect(wrapper.get('.report-peek__note').text()).toBe('站里还没收录这篇论文，可以先去论文页看。')
    expect(wrapper.findComponent(RouterLinkStub).exists()).toBe(false)
    expect(wrapper.findAll('a.report-peek__action').map((link) => link.attributes('href'))).toEqual([
      'https://hf-mirror.com/papers/2609.33439',
      'https://arxiv.org/abs/2609.33439',
    ])

    // 没取到：链接文字是泛称时标题用编号
    await wrapper.setProps({ state: { status: 'error' }, target: { key: '0-0-0', arxivId: '2609.31847' } })
    expect(wrapper.get('.report-peek__title').text()).toBe('arXiv:2609.31847')
    const alert = wrapper.get('[role="alert"]')
    expect(alert.text()).toContain('这篇论文的详情没取到。')
    await alert.get('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})
