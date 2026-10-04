import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TrackingResults from './TrackingResults.vue'
import { i18n } from '@/i18n'
import type { TrackingItem } from '@/features/tracking/trackingModel'

const item = (overrides: Partial<TrackingItem>): TrackingItem => ({
  key: 'item', title: 'Title', url: 'https://example.com', summary: 'Summary', source: 'news',
  observed_at: '2026-10-04T00:00:00Z', matched_rules: ['RAG'], ...overrides,
})

describe('TrackingResults', () => {
  it('shows paper titles and summaries without LaTeX, leaving other sources as written', () => {
    const wrapper = mount(TrackingResults, {
      props: { items: [
        item({ key: 'paper', source: 'arxiv', title: String.raw`\textbf{Aphanta}: Steering--Free`, summary: String.raw`The \emph{Harness} at 2\%.` }),
        item({ key: 'news', title: String.raw`C:\path--odd`, summary: 'x--y' }),
      ] },
      global: { plugins: [i18n] },
    })

    const [paper, news] = wrapper.findAll('li')
    expect(paper?.get('a').text()).toBe('Aphanta: Steering–Free')
    expect(paper?.get('.tracking-result-summary').text()).toBe('The Harness at 2%.')
    expect(news?.get('a').text()).toBe(String.raw`C:\path--odd`)
    expect(news?.get('.tracking-result-summary').text()).toBe('x--y')
  })
})
