import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import i18n, { DEFAULT_LOCALE } from '@/i18n'
import type { AssessmentClaim, ProjectAssessment as Assessment } from '@/features/projects/projectAssessment'
import ProjectAssessment from './ProjectAssessment.vue'

const claim: AssessmentClaim = {
  text_zh: '需要自备模型 API Key',
  text_en: 'Bring your own model API key.',
  source: 'readme',
  quote: 'Bring your own model API key. <img src=x onerror=alert(1)>',
}
const review: Assessment = {
  version: 1, decision: 'evaluate', relevance: 'core', relevance_evidence: claim,
  audience: [claim], value: [claim], setup: [claim], limitations: [],
  license_spdx_id: '', assessed_at: '2026-10-14T00:00:00+00:00', readme_sha256: 'abc',
}
const render = (assessment: Assessment | null = review) => mount(ProjectAssessment, {
  props: { assessment, repoId: 'acme/documents' }, global: { plugins: [i18n] },
})

describe('document-backed trial assessment', () => {
  beforeEach(() => { i18n.global.locale.value = 'zh-CN' })
  afterEach(() => { i18n.global.locale.value = DEFAULT_LOCALE })

  it('shows constraints and unknowns alongside the verdict, with inspectable plain-text evidence', () => {
    const wrapper = render()
    expect(wrapper.text()).toContain('可评估试用')
    expect(wrapper.text()).toContain('需要自备模型 API Key')
    expect(wrapper.text()).toContain('现有资料未能确认')
    expect(wrapper.text()).toContain('未识别许可')
    expect(wrapper.text()).toContain('未经实测')
    expect(wrapper.findAll('blockquote')).toHaveLength(1)
    expect(wrapper.get('blockquote').text()).toContain('<img src=x onerror=alert(1)>')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.get('a').attributes('href')).toBe('https://github.com/acme/documents#readme')
    expect(wrapper.get('time').attributes('datetime')).toBe(review.assessed_at)
  })

  it('keeps an unassessed project honest and displays the same facts in English', async () => {
    const empty = render(null)
    expect(empty.text()).toContain('尚未评估')
    expect(empty.find('details').exists()).toBe(false)
    const wrapper = render()
    i18n.global.locale.value = 'en-US'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Bring your own model API key.')
    expect(wrapper.text()).toContain('not a hands-on test')
    expect(wrapper.text()).not.toContain('需要自备')
  })
})
