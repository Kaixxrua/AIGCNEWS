import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import i18n from '@/i18n'
import GithubUnprocessableProjectsPanel from './GithubUnprocessableProjectsPanel.vue'

const projects = [{
  repo_id: 'repo-1',
  full_name: 'amadeusprotocol/node',
  url: 'https://github.com/amadeusprotocol/node',
  stars: 1234,
  reason: 'missing_description' as const,
}]

const mountPanel = (props: Record<string, unknown> = {}) => mount(GithubUnprocessableProjectsPanel, {
  global: { plugins: [i18n] },
  props,
})

describe('GithubUnprocessableProjectsPanel', () => {
  it('renders unprocessable projects with a safe external link', () => {
    const wrapper = mountPanel({ items: projects, total: 1 })

    expect(wrapper.text()).toContain('amadeusprotocol/node')
    expect(wrapper.text()).toContain('1,234')
    expect(wrapper.text()).toContain('缺少 GitHub 项目简介')
    expect(wrapper.find('a').attributes()).toMatchObject({
      href: projects[0].url,
      target: '_blank',
      rel: 'noopener noreferrer',
    })
  })

  it('does not render when there are no unprocessable projects', () => {
    expect(mountPanel({ items: [], total: 0 }).find('section').exists()).toBe(false)
  })
})
