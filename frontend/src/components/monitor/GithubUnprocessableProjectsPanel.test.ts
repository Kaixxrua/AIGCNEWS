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

const retainedProjects = [
  {
    repo_id: 'repo-gone',
    full_name: 'QAI-brain/awesome-QAI-Papers-QDiffusion',
    url: 'https://github.com/QAI-brain/awesome-QAI-Papers-QDiffusion',
    stars: 900,
    reason: 'not_found' as const,
  },
  {
    repo_id: 'repo-dropped',
    full_name: 'acme/lost-stars',
    url: 'https://github.com/acme/lost-stars',
    stars: 450,
    reason: 'snapshot_below_threshold' as const,
  },
  {
    repo_id: 'repo-lost',
    full_name: 'acme/desc-deleted',
    url: 'https://github.com/acme/desc-deleted',
    stars: 850,
    reason: 'lost_input' as const,
  },
  {
    repo_id: 'repo-tomb',
    full_name: 'acme/before-rename',
    url: 'https://github.com/acme/before-rename',
    stars: 950,
    reason: 'tombstone' as const,
  },
]

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
      href: projects[0]!.url,
      target: '_blank',
      rel: 'noopener noreferrer',
    })
  })

  it('does not render when there are no unprocessable projects', () => {
    expect(mountPanel({ items: [], total: 0 }).find('section').exists()).toBe(false)
  })

  it('renders retained projects with per-project traceable reasons', () => {
    const wrapper = mountPanel({
      items: [], total: 0,
      retainedItems: retainedProjects, retainedTotal: 4,
    })

    expect(wrapper.text()).toContain('保留在库但不再处理的项目')
    expect(wrapper.text()).toContain('保留 4 个')
    expect(wrapper.text()).toContain('QAI-brain/awesome-QAI-Papers-QDiffusion')
    expect(wrapper.text()).toContain('源仓库已下架（404）')
    expect(wrapper.text()).toContain('acme/lost-stars')
    expect(wrapper.text()).toContain('最新快照星数回落至门槛以下')
    expect(wrapper.text()).toContain('acme/desc-deleted')
    expect(wrapper.text()).toContain('简介被作者删除且无有效 README')
    expect(wrapper.text()).toContain('acme/before-rename')
    expect(wrapper.text()).toContain('改名前的旧仓库行（成果已归一到新名）')
    // retained 行的外链同样要求安全属性
    const links = wrapper.findAll('a')
    expect(links).toHaveLength(4)
    for (const link of links) {
      expect(link.attributes()).toMatchObject({ target: '_blank', rel: 'noopener noreferrer' })
    }
  })

  it('renders retained section alone when unprocessable is empty', () => {
    const wrapper = mountPanel({
      items: [], total: 0,
      retainedItems: [retainedProjects[0]], retainedTotal: 1,
    })

    expect(wrapper.text()).not.toContain('缺少 GitHub 项目简介')
    expect(wrapper.text()).toContain('保留 1 个')
  })

  it('renders both sections when both kinds exist', () => {
    const wrapper = mountPanel({
      items: projects, total: 1,
      retainedItems: [retainedProjects[0]], retainedTotal: 1,
    })

    expect(wrapper.text()).toContain('无法处理 1 个')
    expect(wrapper.text()).toContain('保留 1 个')
  })

  it('does not render when both unprocessable and retained are empty', () => {
    expect(
      mountPanel({ items: [], total: 0, retainedItems: [], retainedTotal: 0 }).find('section').exists(),
    ).toBe(false)
  })
})
