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
})
