import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PaperDocumentPanel from './PaperDocumentPanel.vue'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

describe('Paper summary after PDF reader retirement', () => {
  it('shows the summary and original link without a PDF canvas or download control', () => {
    const wrapper = mount(PaperDocumentPanel, { props: {
      paper: { id: 'paper', title: 'A paper', summary: 'A useful abstract', url: 'https://arxiv.org/abs/2403.12345' },
      paperLoading: false, paperError: '', renderMarkdown: (text) => text,
    } })
    expect(wrapper.get('h1').text()).toBe('A paper')
    expect(wrapper.get('article').text()).toContain('A useful abstract')
    expect(wrapper.get('a').attributes('href')).toBe('https://arxiv.org/abs/2403.12345')
    expect(wrapper.find('canvas, iframe').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('keeps loading, empty summary and error states readable', async () => {
    const wrapper = mount(PaperDocumentPanel, { props: {
      paper: null, paperLoading: true, paperError: '', renderMarkdown: (text) => text,
    } })
    expect(wrapper.attributes('aria-busy')).toBe('true')
    await wrapper.setProps({ paperLoading: false, paperError: 'Unavailable' })
    expect(wrapper.get('[role="alert"]').text()).toBe('Unavailable')
    await wrapper.setProps({ paper: { id: 'paper', title: 'Title' } })
    expect(wrapper.get('article').text()).toContain('paper.summaryUnavailable')
  })

  it('adds the desktop facts line only when detailed, skipping facts the paper lacks', async () => {
    const paper = { id: 'paper', title: 'A paper', authors: '["Ada", "Grace", "Alan", "Edsger"]', published_date: '2026-10-01T02:42:45' }
    const plain = mount(PaperDocumentPanel, { props: { paper, paperLoading: false, paperError: '', renderMarkdown: (text) => text } })
    expect(plain.find('.paper-authors').exists()).toBe(false)

    const detailed = mount(PaperDocumentPanel, { props: { paper, paperLoading: false, paperError: '', renderMarkdown: (text) => text, detailed: true } })
    expect(detailed.get('.paper-authors').text()).toContain('Ada, Grace, Alan, Edsger')
    expect(detailed.find('.paper-authors-toggle').exists()).toBe(false)
    expect(detailed.findAll('.paper-fact').map((fact) => fact.text())).toEqual(['2026-10-01'])
    expect(detailed.findAll('time')).toHaveLength(1)
    expect(detailed.get('time').attributes('datetime')).toBe('2026-10-01')
  })

  it('folds long author lists and folds them again for the next paper', async () => {
    const paper = (id: string) => ({ id, title: id, authors: ['A', 'B', 'C', 'D', 'E'], arxiv_id: '2609.1', source_channel: 'huggingface_weekly_html', rank_in_period: 3, raw_score: 12 })
    const wrapper = mount(PaperDocumentPanel, { props: { paper: paper('one'), paperLoading: false, paperError: '', renderMarkdown: (text) => text, detailed: true } })
    expect(wrapper.findAll('.paper-fact').map((fact) => fact.text())).toEqual(['paper.head.arxiv', 'paper.head.upvotes', 'paper.head.board.weekly'])
    expect(wrapper.find('time').exists()).toBe(false)
    await wrapper.get('.paper-authors-toggle').trigger('click')
    expect(wrapper.get('.paper-authors').text()).toContain('D, E')
    await wrapper.setProps({ paper: paper('two') })
    expect(wrapper.get('.paper-authors-toggle').attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('.paper-authors').text()).not.toContain('D, E')
  })
})
